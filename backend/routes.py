#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 路由定义 - G0078/G0079/G0080 版本
基于HIS新接口的门诊护士站API
"""

from flask import Blueprint, request, jsonify, session
from datetime import datetime
import logging
import uuid
from db import db
from config import SCANNER_CONFIG, HIS_WEBAPI_CONFIG
from his_webapi_adapter import get_his_webapi_adapter, HISAdapterError
from auth import require_login, get_current_dept_code, is_admin

logger = logging.getLogger(__name__)
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

# ============ 工具函数 ============

def success_response(data=None, message="操作成功"):
    """成功响应"""
    return jsonify({
        "success": True,
        "code": "SUCCESS",
        "message": message,
        "data": data,
        "timestamp": datetime.now().isoformat()
    })

def error_response(message, code="ERROR", status_code=400):
    """错误响应"""
    return jsonify({
        "success": False,
        "code": code,
        "message": message,
        "data": None,
        "timestamp": datetime.now().isoformat()
    }), status_code

def get_his_adapter():
    """获取HIS适配器实例"""
    if not HIS_WEBAPI_CONFIG.get('enabled'):
        return None
    
    base_url = HIS_WEBAPI_CONFIG.get('base_url')
    meskey = HIS_WEBAPI_CONFIG.get('meskey')
    
    if not base_url or not meskey:
        return None
    
    return get_his_webapi_adapter(base_url, meskey, HIS_WEBAPI_CONFIG.get('timeout', 30))

# ============ G0078 号别排班接口 ============

@api_bp.route('/clinic-schedules', methods=['GET'])
@require_login
def get_clinic_schedules():
    """
    获取门诊号别排班信息（G0078）
    从HIS获取并同步到本地数据库
    自动根据登录护士的科室过滤
    """
    try:
        clinic_date = request.args.get('clinic_date', datetime.now().strftime('%Y-%m-%d'))
        dept_code = request.args.get('dept_code', '')
        dept_name = request.args.get('dept_name', '')
        time_desc = request.args.get('time_desc', '')  # 新增：午别筛选
        
        # 获取当前登录护士的科室编码
        nurse_dept_code = get_current_dept_code()
        
        # 如果不是管理员，强制使用护士的科室编码
        if not is_admin():
            dept_code = nurse_dept_code
        
        # 尝试从HIS同步数据
        adapter = get_his_adapter()
        if adapter:
            try:
                use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
                his_result = adapter.get_all_clinic_schedules(clinic_date=clinic_date, use_encryption=use_encryption)
                
                if his_result.get('success') and his_result.get('schedules'):
                    # 同步到数据库
                    conn = db.get_connection()
                    try:
                        sync_result = adapter.sync_clinic_schedules_to_db(conn, clinic_date)
                        if sync_result.get('success'):
                            logger.info(f"号别排班数据同步成功: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
                        else:
                            logger.warning(f"号别排班数据同步失败: {sync_result.get('message')}")
                    finally:
                        conn.close()
            except Exception as sync_error:
                logger.warning(f"从HIS同步号别排班失败: {sync_error}，使用本地缓存数据")
        
        # 从本地数据库查询
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    schedule_id, clinic_date, clinic_dept, dept_name,
                    clinic_label, time_desc, registration_limits,
                    registration_num, regist_price, clinic_type,
                    states, pnum
                FROM clinic_schedules 
                WHERE clinic_date = %s AND states = '正常'
            """
            params = [clinic_date]
            
            if dept_code:
                sql += " AND clinic_dept = %s"
                params.append(dept_code)
            elif dept_name:
                sql += " AND dept_name LIKE %s"
                params.append(f"%{dept_name}%")
            
            # 新增：午别筛选
            if time_desc:
                sql += " AND time_desc = %s"
                params.append(time_desc)
            
            sql += " ORDER BY clinic_dept, pnum, clinic_label"
            
            cursor.execute(sql, params)
            schedules = cursor.fetchall()
        
        # 按科室分组
        dept_groups = {}
        for schedule in schedules:
            dept = schedule['dept_name']
            if dept not in dept_groups:
                dept_groups[dept] = {
                    'dept_code': schedule['clinic_dept'],
                    'dept_name': dept,
                    'schedules': []
                }
            dept_groups[dept]['schedules'].append(schedule)
        
        return success_response({
            "clinic_date": clinic_date,
            "schedules": schedules,
            "dept_groups": list(dept_groups.values()),
            "total_count": len(schedules),
            "nurse_dept_code": nurse_dept_code,
            "is_admin": is_admin()
        })
        
    except Exception as e:
        logger.error(f"Get clinic schedules error: {e}")
        return error_response("获取号别排班失败", "DB_ERROR", 500)

@api_bp.route('/clinic-schedules/sync', methods=['POST'])
def sync_clinic_schedules():
    """
    从HIS同步号别排班数据
    """
    try:
        data = request.json or {}
        clinic_date = data.get('clinic_date', datetime.now().strftime('%Y-%m-%d'))
        
        adapter = get_his_adapter()
        if not adapter:
            return error_response("HIS WebAPI未启用或配置不完整", "HIS_DISABLED", 503)
        
        conn = db.get_connection()
        try:
            result = adapter.sync_clinic_schedules_to_db(conn, clinic_date)
            if result.get('success'):
                return success_response(result, "号别排班数据同步成功")
            else:
                return error_response(result.get('message', '同步失败'), "SYNC_ERROR", 500)
        finally:
            conn.close()
            
    except HISAdapterError as e:
        logger.error(f"HIS同步失败: {e}")
        return error_response(f"HIS同步失败: {str(e)}", "HIS_ERROR", 502)
    except Exception as e:
        logger.error(f"同步号别排班数据失败: {e}")
        return error_response("同步号别排班数据失败", "ERROR", 500)

# ============ G0079 患者挂号接口 ============

@api_bp.route('/patient-registrations', methods=['GET'])
@require_login
def get_patient_registrations():
    """
    获取患者挂号信息（G0079）
    根据号别查询患者列表
    """
    try:
        visit_date = request.args.get('visit_date', datetime.now().strftime('%Y-%m-%d'))
        clinic_label = request.args.get('clinic_label', '')
        visit_time_desc = request.args.get('visit_time_desc', '')
        
        if not clinic_label:
            return error_response("缺少clinic_label参数", "INVALID_PARAMS")
        
        if not visit_time_desc:
            return error_response("缺少visit_time_desc参数", "INVALID_PARAMS")
        
        # 尝试从HIS同步数据
        adapter = get_his_adapter()
        if adapter:
            try:
                use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
                his_result = adapter.get_patient_registrations(
                    visit_date=visit_date,
                    clinic_label=clinic_label,
                    visit_time_desc=visit_time_desc,
                    use_encryption=use_encryption
                )
                
                if his_result.get('success') and his_result.get('registrations'):
                    # 同步到数据库
                    conn = db.get_connection()
                    try:
                        sync_result = adapter.sync_patient_registrations_to_db(
                            conn, visit_date, clinic_label, visit_time_desc
                        )
                        if sync_result.get('success'):
                            logger.info(f"患者挂号数据同步成功: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
                        else:
                            logger.warning(f"患者挂号数据同步失败: {sync_result.get('message')}")
                    finally:
                        conn.close()
            except Exception as sync_error:
                logger.warning(f"从HIS同步患者挂号失败: {sync_error}，使用本地缓存数据")
        
        # 从本地数据库查询
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    registration_id, visit_date, visit_no, visit_time_desc,
                    clinic_label, patient_id, card_id, name, sex, age,
                    charge_type, serial_no, pnum
                FROM patient_registrations 
                WHERE visit_date = %s AND clinic_label = %s AND visit_time_desc = %s
                ORDER BY serial_no, pnum
            """
            
            cursor.execute(sql, (visit_date, clinic_label, visit_time_desc))
            registrations = cursor.fetchall()
        
        return success_response({
            "visit_date": visit_date,
            "clinic_label": clinic_label,
            "visit_time_desc": visit_time_desc,
            "registrations": registrations,
            "total_count": len(registrations)
        })
        
    except Exception as e:
        logger.error(f"Get patient registrations error: {e}")
        return error_response("获取患者挂号信息失败", "DB_ERROR", 500)

@api_bp.route('/patient-registrations/sync', methods=['POST'])
def sync_patient_registrations():
    """
    从HIS同步患者挂号数据
    """
    try:
        data = request.json or {}
        visit_date = data.get('visit_date', datetime.now().strftime('%Y-%m-%d'))
        clinic_label = data.get('clinic_label', '')
        visit_time_desc = data.get('visit_time_desc', '')
        
        if not clinic_label or not visit_time_desc:
            return error_response("缺少必要参数", "INVALID_PARAMS")
        
        adapter = get_his_adapter()
        if not adapter:
            return error_response("HIS WebAPI未启用或配置不完整", "HIS_DISABLED", 503)
        
        conn = db.get_connection()
        try:
            result = adapter.sync_patient_registrations_to_db(conn, visit_date, clinic_label, visit_time_desc)
            if result.get('success'):
                return success_response(result, "患者挂号数据同步成功")
            else:
                return error_response(result.get('message', '同步失败'), "SYNC_ERROR", 500)
        finally:
            conn.close()
            
    except HISAdapterError as e:
        logger.error(f"HIS同步失败: {e}")
        return error_response(f"HIS同步失败: {str(e)}", "HIS_ERROR", 502)
    except Exception as e:
        logger.error(f"同步患者挂号数据失败: {e}")
        return error_response("同步患者挂号数据失败", "ERROR", 500)

# ============ G0080 患者开单接口 ============

@api_bp.route('/patient-orders', methods=['GET'])
@require_login
def get_patient_orders():
    """
    获取患者开单信息（G0080）
    根据就诊号查询处方、检查申请单、检验申请单等
    """
    try:
        visit_date = request.args.get('visit_date', datetime.now().strftime('%Y-%m-%d'))
        visit_no = request.args.get('visit_no', '')
        
        if not visit_no:
            return error_response("缺少visit_no参数", "INVALID_PARAMS")
        
        # 尝试从HIS同步数据
        adapter = get_his_adapter()
        if adapter:
            try:
                use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
                his_result = adapter.get_patient_orders(
                    visit_date=visit_date,
                    visit_no=visit_no,
                    use_encryption=use_encryption
                )
                
                if his_result.get('success') and his_result.get('orders'):
                    # 同步到数据库
                    conn = db.get_connection()
                    try:
                        sync_result = adapter.sync_patient_orders_to_db(conn, visit_date, visit_no)
                        if sync_result.get('success'):
                            logger.info(f"患者开单数据同步成功: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
                        else:
                            logger.warning(f"患者开单数据同步失败: {sync_result.get('message')}")
                    finally:
                        conn.close()
            except Exception as sync_error:
                logger.warning(f"从HIS同步患者开单失败: {sync_error}，使用本地缓存数据")
        
        # 从本地数据库查询
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    order_id, visit_date, visit_no, patient_id, card_id,
                    presc_attr, states, test_no, template_name, presc_date,
                    presc_no, item_no, diagnoses, class_name, item_code,
                    item_name, package_spec, package_units, firm_id,
                    administration, frequency, quantity, price, pnum
                FROM patient_orders 
                WHERE visit_date = %s AND visit_no = %s
                ORDER BY presc_no, item_no, pnum
            """
            
            cursor.execute(sql, (visit_date, visit_no))
            orders = cursor.fetchall()
        
        # 按项目类别分组
        class_groups = {}
        for order in orders:
            class_name = order['class_name'] or '其他'
            if class_name not in class_groups:
                class_groups[class_name] = []
            class_groups[class_name].append(order)
        
        return success_response({
            "visit_date": visit_date,
            "visit_no": visit_no,
            "orders": orders,
            "class_groups": class_groups,
            "total_count": len(orders)
        })
        
    except Exception as e:
        logger.error(f"Get patient orders error: {e}")
        return error_response("获取患者开单信息失败", "DB_ERROR", 500)

@api_bp.route('/patient-orders/sync', methods=['POST'])
def sync_patient_orders():
    """
    从HIS同步患者开单数据
    """
    try:
        data = request.json or {}
        visit_date = data.get('visit_date', datetime.now().strftime('%Y-%m-%d'))
        visit_no = data.get('visit_no', '')
        
        if not visit_no:
            return error_response("缺少visit_no参数", "INVALID_PARAMS")
        
        adapter = get_his_adapter()
        if not adapter:
            return error_response("HIS WebAPI未启用或配置不完整", "HIS_DISABLED", 503)
        
        conn = db.get_connection()
        try:
            result = adapter.sync_patient_orders_to_db(conn, visit_date, visit_no)
            if result.get('success'):
                return success_response(result, "患者开单数据同步成功")
            else:
                return error_response(result.get('message', '同步失败'), "SYNC_ERROR", 500)
        finally:
            conn.close()
            
    except HISAdapterError as e:
        logger.error(f"HIS同步失败: {e}")
        return error_response(f"HIS同步失败: {str(e)}", "HIS_ERROR", 502)
    except Exception as e:
        logger.error(f"同步患者开单数据失败: {e}")
        return error_response("同步患者开单数据失败", "ERROR", 500)

# ============ 综合查询接口 ============

@api_bp.route('/nurse-station/dashboard', methods=['GET'])
def get_nurse_station_dashboard():
    """
    获取护士站工作台数据
    整合号别排班、患者挂号、患者开单信息
    """
    try:
        clinic_date = request.args.get('clinic_date', datetime.now().strftime('%Y-%m-%d'))
        dept_name = request.args.get('dept_name', '')
        clinic_label = request.args.get('clinic_label', '')
        visit_time_desc = request.args.get('visit_time_desc', '')
        visit_no = request.args.get('visit_no', '')
        
        result = {
            "clinic_date": clinic_date,
            "dept_name": dept_name,
            "clinic_label": clinic_label,
            "visit_time_desc": visit_time_desc,
            "visit_no": visit_no
        }
        
        # 1. 获取号别排班（左侧医生栏）
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    clinic_dept, dept_name, clinic_label, time_desc,
                    registration_limits, registration_num, regist_price
                FROM clinic_schedules 
                WHERE clinic_date = %s AND states = '正常'
            """
            params = [clinic_date]
            
            if dept_name:
                sql += " AND dept_name LIKE %s"
                params.append(f"%{dept_name}%")
            
            sql += " ORDER BY clinic_dept, clinic_label"
            
            cursor.execute(sql, params)
            schedules = cursor.fetchall()
            
            # 按科室分组
            dept_groups = {}
            for schedule in schedules:
                dept = schedule['dept_name']
                if dept not in dept_groups:
                    dept_groups[dept] = {
                        'dept_code': schedule['clinic_dept'],
                        'dept_name': dept,
                        'schedules': []
                    }
                dept_groups[dept]['schedules'].append(schedule)
            
            result['dept_groups'] = list(dept_groups.values())
        
        # 2. 如果指定了号别，获取患者列表
        if clinic_label and visit_time_desc:
            with db.get_cursor() as cursor:
                sql = """
                    SELECT 
                        registration_id, visit_no, patient_id, card_id,
                        name, sex, age, charge_type, serial_no
                    FROM patient_registrations 
                    WHERE visit_date = %s AND clinic_label = %s AND visit_time_desc = %s
                    ORDER BY serial_no
                """
                
                cursor.execute(sql, (clinic_date, clinic_label, visit_time_desc))
                patients = cursor.fetchall()
                result['patients'] = patients
        
        # 3. 如果指定了就诊号，获取患者开单信息
        if visit_no:
            with db.get_cursor() as cursor:
                # 获取患者基本信息
                sql = """
                    SELECT 
                        patient_id, card_id, name, sex, age, charge_type
                    FROM patient_registrations 
                    WHERE visit_date = %s AND visit_no = %s
                    LIMIT 1
                """
                
                cursor.execute(sql, (clinic_date, visit_no))
                patient_info = cursor.fetchone()
                result['patient_info'] = patient_info
                
                # 获取开单信息
                sql = """
                    SELECT 
                        order_id, presc_attr, states, presc_no, item_no,
                        diagnoses, class_name, item_code, item_name,
                        package_spec, package_units, administration,
                        frequency, quantity, price
                    FROM patient_orders 
                    WHERE visit_date = %s AND visit_no = %s
                    ORDER BY presc_no, item_no
                """
                
                cursor.execute(sql, (clinic_date, visit_no))
                orders = cursor.fetchall()
                
                # 按项目类别分组
                class_groups = {}
                for order in orders:
                    class_name = order['class_name'] or '其他'
                    if class_name not in class_groups:
                        class_groups[class_name] = []
                    class_groups[class_name].append(order)
                
                result['orders'] = orders
                result['order_groups'] = class_groups
        
        return success_response(result)
        
    except Exception as e:
        logger.error(f"Get nurse station dashboard error: {e}")
        return error_response("获取护士站数据失败", "DB_ERROR", 500)

# ============ 健康检查 ============

@api_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return success_response({
        "status": "running",
        "service": "CVOnto Nurse Station API (G0078/G0079/G0080)",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat()
    })

@api_bp.route('/his/health', methods=['GET'])
def his_health_check():
    """HIS接口健康检查"""
    try:
        adapter = get_his_adapter()
        if not adapter:
            return success_response({
                "enabled": False,
                "status": "disabled",
                "message": "HIS WebAPI未启用"
            })
        
        result = adapter.health_check()
        result['enabled'] = True
        result['configured'] = True
        
        if result.get('success'):
            return success_response(result)
        else:
            return error_response(result.get('message', 'HIS接口异常'), "HIS_ERROR", 502)
            
    except Exception as e:
        logger.error(f"HIS健康检查失败: {e}")
        return error_response(f"HIS健康检查失败: {str(e)}", "ERROR", 500)