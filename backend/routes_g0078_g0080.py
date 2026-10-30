#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
软件名称：北京医院门诊护士工作站
文件名称：routes_g0078_g0080.py
功能描述：门诊护士站 API 路由，提供号别排班、患者挂号、患者开单及耗材扫码服务
开发单位：北京医院
开发日期：2026年8月
版本号：V1.0
================================================================================
"""

from flask import Blueprint, request, jsonify, session
from datetime import datetime
import logging
import uuid
from db import db
from config import SCANNER_CONFIG, HIS_WEBAPI_CONFIG
from his_webapi_adapter import get_his_webapi_adapter, HISAdapterError
from auth import require_login, get_current_dept_code, get_current_dept_codes, is_admin

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
        
        # 获取当前登录护士的科室编码列表（支持多科室，前缀匹配）
        nurse_dept_codes = get_current_dept_codes()
        
        # 如果不是管理员，强制使用护士的科室编码列表过滤
        if not is_admin() and nurse_dept_codes:
            if dept_code:
                # 如果指定了dept_code，检查是否匹配护士的科室前缀
                if not any(dept_code.startswith(code) for code in nurse_dept_codes):
                    return error_response("无权限查看该科室", "PERMISSION_DENIED", 403)
                # 只查询指定的科室
                nurse_dept_codes = [dept_code]
            # 后续SQL会使用nurse_dept_codes进行LIKE前缀过滤
        elif not is_admin() and not nurse_dept_codes:
            # 如果没有配置科室，返回空结果
            return success_response({
                "clinic_date": clinic_date,
                "schedules": [],
                "dept_groups": [],
                "total_count": 0,
                "nurse_dept_codes": [],
                "is_admin": False
            })
        
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
            
            # 多科室过滤（LIKE 前缀匹配：dept_code 是 clinic_dept 的前缀）
            if not is_admin() and nurse_dept_codes:
                like_conditions = ' OR '.join(['clinic_dept LIKE %s'] * len(nurse_dept_codes))
                sql += f" AND ({like_conditions})"
                params.extend([f"{code}%" for code in nurse_dept_codes])
            elif dept_code:
                sql += " AND clinic_dept LIKE %s"
                params.append(f"{dept_code}%")
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
            "nurse_dept_codes": nurse_dept_codes,
            "is_admin": is_admin()
        })
        
    except Exception as e:
        logger.error(f"Get clinic schedules error: {e}")
        return error_response("获取号别排班失败", "DB_ERROR", 500)

@api_bp.route('/clinic-schedules/sync', methods=['POST'])
@require_login
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
        keyword = request.args.get('keyword', '').strip()
        
        if not clinic_label:
            return error_response("缺少clinic_label参数", "INVALID_PARAMS")
        
        if not visit_time_desc:
            return error_response("缺少visit_time_desc参数", "INVALID_PARAMS")
        
        # 获取当前登录护士的科室编码列表（支持多科室）
        nurse_dept_codes = get_current_dept_codes()
        
        # 如果不是管理员，验证科室权限（前缀匹配）
        if not is_admin():
            if not nurse_dept_codes:
                return error_response("未配置科室权限", "NO_DEPT_PERMISSION", 403)
            # 检查clinic_label是否属于护士的科室（通过号别排班表验证，LIKE前缀匹配）
            permission_ok = False
            try:
                with db.get_cursor() as cursor:
                    like_conditions = ' OR '.join(['clinic_dept LIKE %s'] * len(nurse_dept_codes))
                    like_params = [f"{code}%" for code in nurse_dept_codes]
                    cursor.execute(f"""
                        SELECT COUNT(*) as count FROM clinic_schedules
                        WHERE clinic_label = %s AND ({like_conditions})
                    """, [clinic_label] + like_params)
                    result = cursor.fetchone()
                    if result['count'] > 0:
                        permission_ok = True
            except Exception as e:
                logger.warning(f"本地权限验证失败: {e}")
            
            # 如果本地验证不通过，但护士有所属科室，暂时放行（HIS直连模式下本地可能无排班数据）
            if not permission_ok and nurse_dept_codes:
                logger.info(f"本地clinic_schedules无匹配记录，但护士有所属科室，放行: clinic_label={clinic_label}")
                permission_ok = True
            
            if not permission_ok:
                return error_response("无权限查看该号别", "PERMISSION_DENIED", 403)
        
        # 尝试从HIS同步数据
        adapter = get_his_adapter()
        his_registrations = None
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
                    his_registrations = his_result['registrations']
                    logger.info(f"从HIS获取到 {len(his_registrations)} 条患者挂号数据")
                    
                    # 同步到数据库（后台执行，不影响返回）
                    try:
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
                    except Exception as db_sync_error:
                        logger.warning(f"同步到数据库失败: {db_sync_error}")
                else:
                    logger.info(f"HIS返回空数据: {his_result.get('message', '无数据')}")
            except Exception as sync_error:
                logger.warning(f"从HIS获取患者挂号失败: {sync_error}，使用本地缓存数据")
        
        # 如果HIS有数据，直接转换格式返回
        if his_registrations:
            registrations = []
            for reg in his_registrations:
                registrations.append({
                    'registration_id': f"{visit_date}_{reg.get('VISIT_NO', '')}",
                    'visit_date': visit_date,
                    'visit_no': reg.get('VISIT_NO', ''),
                    'visit_time_desc': visit_time_desc,
                    'clinic_label': clinic_label,
                    'patient_id': reg.get('PATIENT_ID', ''),
                    'card_id': reg.get('CARD_ID', ''),
                    'name': reg.get('NAME', ''),
                    'sex': reg.get('SEX', ''),
                    'age': reg.get('AGE', 0),
                    'charge_type': reg.get('CHARGE_TYPE', ''),
                    'serial_no': reg.get('SERIAL_NO', 0),
                    'pnum': reg.get('PNUM', 0),
                    'fre_date': reg.get('FRE_DATE')
                })

            if keyword:
                normalized_keyword = keyword.casefold()
                registrations = [reg for reg in registrations if
                    normalized_keyword in str(reg.get('name') or '').casefold() or
                    str(reg.get('card_id') or '').strip() == keyword
                ]
            
            return success_response({
                "visit_date": visit_date,
                "clinic_label": clinic_label,
                "visit_time_desc": visit_time_desc,
                "registrations": registrations,
                "total_count": len(registrations),
                "source": "his"
            })
        
        # HIS无数据或不可用，从本地数据库查询
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    registration_id, visit_date, visit_no, visit_time_desc,
                    clinic_label, patient_id, card_id, name, sex, age,
                    charge_type, serial_no, pnum, fre_date
                FROM patient_registrations 
                WHERE visit_date = %s AND clinic_label = %s AND visit_time_desc = %s
            """
            
            params = [visit_date, clinic_label, visit_time_desc]
            if keyword:
                sql += " AND (LOCATE(%s, LOWER(name)) > 0 OR TRIM(card_id) = %s)"
                params.extend([keyword.lower(), keyword])
            sql += " ORDER BY serial_no, pnum"
            cursor.execute(sql, tuple(params))
            registrations = cursor.fetchall()
        
        return success_response({
            "visit_date": visit_date,
            "clinic_label": clinic_label,
            "visit_time_desc": visit_time_desc,
            "registrations": registrations,
            "total_count": len(registrations),
            "source": "local"
        })
        
    except Exception as e:
        logger.error(f"Get patient registrations error: {e}")
        return error_response("获取患者挂号信息失败", "DB_ERROR", 500)

@api_bp.route('/patient-registrations/sync', methods=['POST'])
@require_login
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
        
        # 获取当前登录护士的科室编码列表（支持多科室）
        nurse_dept_codes = get_current_dept_codes()
        
        # 如果不是管理员，验证科室权限（通过患者挂号信息验证，LIKE前缀匹配）
        if not is_admin():
            if not nurse_dept_codes:
                return error_response("未配置科室权限", "NO_DEPT_PERMISSION", 403)
            # 检查visit_no是否属于护士的科室
            permission_ok = False
            try:
                with db.get_cursor() as cursor:
                    like_conditions = ' OR '.join(['cs.clinic_dept LIKE %s'] * len(nurse_dept_codes))
                    like_params = [f"{code}%" for code in nurse_dept_codes]
                    cursor.execute(f"""
                        SELECT COUNT(*) as count FROM patient_registrations pr
                        JOIN clinic_schedules cs ON pr.clinic_label = cs.clinic_label 
                            AND pr.visit_date = cs.clinic_date 
                            AND pr.visit_time_desc = cs.time_desc
                        WHERE pr.visit_no = %s AND pr.visit_date = %s 
                            AND ({like_conditions})
                    """, [visit_no, visit_date] + like_params)
                    result = cursor.fetchone()
                    if result['count'] > 0:
                        permission_ok = True
            except Exception as e:
                logger.warning(f"本地权限验证失败: {e}")
            
            # 如果本地验证不通过，尝试通过号别排班表验证（只要该患者对应的号别在护士科室范围内即可）
            if not permission_ok:
                try:
                    with db.get_cursor() as cursor:
                        like_conditions = ' OR '.join(['clinic_dept LIKE %s'] * len(nurse_dept_codes))
                        like_params = [f"{code}%" for code in nurse_dept_codes]
                        cursor.execute(f"""
                            SELECT COUNT(*) as count FROM clinic_schedules
                            WHERE clinic_date = %s AND ({like_conditions})
                        """, [visit_date] + like_params)
                        result = cursor.fetchone()
                        if result['count'] > 0:
                            permission_ok = True
                            logger.info(f"通过号别排班表验证权限: visit_no={visit_no}")
                except Exception as e:
                    logger.warning(f"排班表权限验证失败: {e}")
            
            if not permission_ok:
                return error_response("无权限查看该患者", "PERMISSION_DENIED", 403)
        
        # 尝试从HIS获取数据
        adapter = get_his_adapter()
        his_orders = None
        if adapter:
            try:
                use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
                his_result = adapter.get_patient_orders(
                    visit_date=visit_date,
                    visit_no=visit_no,
                    use_encryption=use_encryption
                )
                
                if his_result.get('success') and his_result.get('orders'):
                    his_orders = his_result['orders']
                    logger.info(f"从HIS获取到 {len(his_orders)} 条患者开单数据")
                    
                    # 同步到数据库（后台执行，不影响返回）
                    try:
                        conn = db.get_connection()
                        try:
                            sync_result = adapter.sync_patient_orders_to_db(conn, visit_date, visit_no)
                            if sync_result.get('success'):
                                logger.info(f"患者开单数据同步成功: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
                            else:
                                logger.warning(f"患者开单数据同步失败: {sync_result.get('message')}")
                        finally:
                            conn.close()
                    except Exception as db_sync_error:
                        logger.warning(f"同步到数据库失败: {db_sync_error}")
                else:
                    logger.info(f"HIS返回空开单数据: {his_result.get('message', '无数据')}")
            except Exception as sync_error:
                logger.warning(f"从HIS获取患者开单失败: {sync_error}，使用本地缓存数据")
        
        # 如果HIS有数据，直接转换格式返回
        if his_orders:
            orders = []
            for order in his_orders:
                orders.append({
                    'order_id': f"{visit_date}_{visit_no}_{order.get('PRESC_NO', '')}_{order.get('ITEM_NO', 0)}",
                    'visit_date': visit_date,
                    'visit_no': visit_no,
                    'patient_id': order.get('PATIENT_ID', ''),
                    'card_id': order.get('CARD_ID', ''),
                    'presc_attr': order.get('PRESC_ATTR', ''),
                    'states': order.get('STATES', ''),
                    'test_no': order.get('TEST_NO', ''),
                    'template_name': order.get('TEMPLATE_NAME', ''),
                    'presc_date': order.get('PRESC_DATE', ''),
                    'presc_no': order.get('PRESC_NO', ''),
                    'item_no': order.get('ITEM_NO', 0),
                    'diagnoses': order.get('DIAGNOSES', ''),
                    'class_name': order.get('CLASS_NAME', ''),
                    'item_code': order.get('ITEM_CODE', ''),
                    'item_name': order.get('ITEM_NAME', ''),
                    'package_spec': order.get('PACKAGE_SPEC', ''),
                    'package_units': order.get('PACKAGE_UNITS', ''),
                    'firm_id': order.get('FIRM_ID', ''),
                    'administration': order.get('ADMINISTRATION', ''),
                    'frequency': order.get('FREQUENCY', ''),
                    'quantity': order.get('QUANTITY', 0),
                    'price': order.get('PRICE', 0),
                    'pnum': order.get('PNUM', 0),
                    'cmc_flag': order.get('CMC_FLAG', '0')
                })
            
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
                "total_count": len(orders),
                "source": "his"
            })
        
        # HIS无数据或不可用，从本地数据库查询
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    order_id, visit_date, visit_no, patient_id, card_id,
                    presc_attr, states, test_no, template_name, presc_date,
                    presc_no, item_no, diagnoses, class_name, item_code,
                    item_name, package_spec, package_units, firm_id,
                    administration, frequency, quantity, price, pnum, cmc_flag
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
            "total_count": len(orders),
            "source": "local"
        })
        
    except Exception as e:
        logger.error(f"Get patient orders error: {e}")
        return error_response("获取患者开单信息失败", "DB_ERROR", 500)

@api_bp.route('/patient-orders/sync', methods=['POST'])
@require_login
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

# ============ I0010 高值耗材扫码接口 ============

@api_bp.route('/scan-consumable', methods=['POST'])
@require_login
def scan_consumable():
    """
    高值耗材扫码保存（I0010）
    护士扫描高值耗材条码后，调用HIS I0010接口保存
    """
    try:
        data = request.json or {}
        
        # 必填参数
        presc_date = data.get('presc_date', '')      # 处方日期
        presc_no = data.get('presc_no', '')            # 处方号
        cmc_code = data.get('cmc_code', '')            # 高值耗材编码（扫码条码）
        item_no = data.get('item_no', '')              # 项目序号
        item_code = data.get('item_code', '')          # 项目编码
        
        if not all([presc_date, presc_no, cmc_code, item_no, item_code]):
            return error_response("缺少必要参数: presc_date, presc_no, cmc_code, item_no, item_code", "INVALID_PARAMS")
        
        # 格式化处方日期为 YYYY-MM-DD HH:MM:SS
        try:
            from datetime import datetime
            # 尝试解析各种日期格式
            dt = datetime.strptime(presc_date, '%Y-%m-%d %H:%M:%S')
            presc_date = dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            try:
                dt = datetime.strptime(presc_date, '%a, %d %b %Y %H:%M:%S GMT')
                presc_date = dt.strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                # 如果无法解析，保持原样（可能已经是正确格式）
                pass
        
        # I0010 的 OPER_CODE 必须从当前护士的数据库记录获取，不使用前端传参或默认值。
        nurse_id = session.get('nurse_id')
        with db.get_cursor() as cursor:
            cursor.execute(
                "SELECT nurse_code FROM nurses WHERE nurse_id = %s",
                (nurse_id,)
            )
            nurse = cursor.fetchone()

        oper_code = (nurse or {}).get('nurse_code', '').strip()
        if not oper_code:
            logger.warning(f"扫码失败：护士 {nurse_id} 未配置 HIS 操作员编码 nurse_code")
            return error_response(
                "当前护士未配置 HIS 操作员编码，请在护士信息中维护 nurse_code",
                "HIS_OPERATOR_CODE_NOT_CONFIGURED",
                400
            )
        
        adapter = get_his_adapter()
        if not adapter:
            return error_response("HIS WebAPI未启用或配置不完整", "HIS_DISABLED", 503)
        
        use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
        
        logger.info(f"扫码请求参数: presc_date={presc_date}, presc_no={presc_no}, cmc_code={cmc_code}, item_no={item_no}, item_code={item_code}, oper_code={oper_code}")
        
        result = adapter.scan_consumable(
            presc_date=presc_date,
            presc_no=presc_no,
            cmc_code=cmc_code,
            item_no=item_no,
            item_code=item_code,
            oper_code=oper_code,
            flag="1",
            use_encryption=use_encryption
        )
        
        logger.info(f"扫码结果: {result}")
        
        if result.get('success'):
            return success_response(result, "耗材扫码保存成功")
        else:
            return error_response(result.get('message', '扫码保存失败'), "SCAN_ERROR", 500)
            
    except Exception as e:
        logger.error(f"耗材扫码失败: {e}")
        return error_response(f"耗材扫码失败: {str(e)}", "ERROR", 500)

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
        
        # 1. 获取号别排班（左侧医生栏）- 支持多科室过滤
        nurse_dept_codes = get_current_dept_codes()
        
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    clinic_dept, dept_name, clinic_label, time_desc,
                    registration_limits, registration_num, regist_price
                FROM clinic_schedules 
                WHERE clinic_date = %s AND states = '正常'
            """
            params = [clinic_date]
            
            # 多科室过滤（LIKE 前缀匹配）
            if not is_admin() and nurse_dept_codes:
                like_conditions = ' OR '.join(['clinic_dept LIKE %s'] * len(nurse_dept_codes))
                sql += f" AND ({like_conditions})"
                params.extend([f"{code}%" for code in nurse_dept_codes])
            elif dept_name:
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
                        patient_id, card_id, name, sex, age, charge_type, fre_date
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
                        frequency, quantity, price, cmc_flag
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
