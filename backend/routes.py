#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 路由定义
纯内网环境，支持耗材扫码功能
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import logging
import uuid
from db import db
from config import SCANNER_CONFIG, HIS_WEBAPI_CONFIG
from his_webapi_adapter import get_his_webapi_adapter, HISAdapterError

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

def validate_barcode(barcode):
    """验证条码格式"""
    if not barcode:
        return False, "条码不能为空"
    
    # 检查前缀
    prefix = SCANNER_CONFIG.get('barcode_prefix', '')
    if prefix and not barcode.startswith(prefix):
        return False, f"条码前缀不匹配，应以 {prefix} 开头"
    
    # 检查长度
    length = SCANNER_CONFIG.get('barcode_length', 0)
    if length > 0 and len(barcode) != length:
        return False, f"条码长度不正确，应为 {length} 位"
    
    return True, None

# ============ 医生接口 ============

@api_bp.route('/doctors', methods=['GET'])
def get_doctors():
    """
    获取医生列表
    如果HIS WebAPI已启用，自动从HIS同步数据到本地数据库后返回
    """
    try:
        dept_code = request.args.get('dept_code', '')
        dept_name = request.args.get('dept_name', '心内科')
        
        # 如果HIS WebAPI已启用，先尝试同步数据
        if HIS_WEBAPI_CONFIG.get('enabled'):
            base_url = HIS_WEBAPI_CONFIG.get('base_url')
            meskey = HIS_WEBAPI_CONFIG.get('meskey')
            
            if base_url and meskey:
                try:
                    adapter = get_his_webapi_adapter(base_url, meskey, HIS_WEBAPI_CONFIG.get('timeout', 30))
                    
                    # 获取HIS数据（根据配置决定是否加密）
                    use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
                    his_result = adapter.get_all_doctors(use_encryption=use_encryption)
                    
                    if his_result.get('success') and his_result.get('doctors'):
                        # 同步到数据库
                        conn = db.get_connection()
                        try:
                            sync_result = adapter.sync_doctors_to_db(conn)
                            if sync_result.get('success'):
                                logger.info(f"医生数据自动同步成功: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
                            else:
                                logger.warning(f"医生数据自动同步失败: {sync_result.get('message')}")
                        finally:
                            conn.close()
                except Exception as sync_error:
                    logger.warning(f"自动同步HIS医生数据失败: {sync_error}，将使用本地缓存数据")
        
        # 从本地数据库查询
        with db.get_cursor() as cursor:
            sql = """
                SELECT doctor_id, doctor_code, name, title, title_code, 
                       specialty, dept_code, dept_name, room, room_code, 
                       work_status, phone
                FROM doctors 
                WHERE status = 1
            """
            params = []
            if dept_code:
                sql += " AND dept_code = %s"
                params.append(dept_code)
            elif dept_name:
                sql += " AND dept_name = %s"
                params.append(dept_name)
            
            sql += " ORDER BY sort_order, doctor_id"
            cursor.execute(sql, params)
            doctors = cursor.fetchall()
        
        return success_response({"doctors": doctors, "total_count": len(doctors)})
    except Exception as e:
        logger.error(f"Get doctors error: {e}")
        return error_response("获取医生列表失败", "DB_ERROR", 500)


@api_bp.route('/doctors/his', methods=['GET'])
def get_doctors_from_his():
    """
    从HIS系统获取医生列表（G0076接口）
    正式运行时通过此接口获取实时医生数据
    """
    try:
        # 检查HIS WebAPI是否启用
        if not HIS_WEBAPI_CONFIG.get('enabled'):
            return error_response("HIS WebAPI未启用，请在.env中配置HIS_WEBAPI_ENABLED=true", "HIS_DISABLED", 503)
        
        # 检查配置
        base_url = HIS_WEBAPI_CONFIG.get('base_url')
        meskey = HIS_WEBAPI_CONFIG.get('meskey')
        
        if not base_url or not meskey:
            return error_response("HIS WebAPI配置不完整，请检查HIS_WEBAPI_BASE_URL和HIS_WEBAPI_MESKEY", "HIS_CONFIG_ERROR", 503)
        
        # 获取分页参数
        ono = int(request.args.get('ono', 1))
        eno = int(request.args.get('eno', 50))
        dept_code = request.args.get('dept_code', '')
        dept_name = request.args.get('dept_name', '')
        
        # 获取适配器
        adapter = get_his_webapi_adapter(base_url, meskey, HIS_WEBAPI_CONFIG.get('timeout', 30))
        
        # 是否使用加密
        use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
        
        # 调用HIS接口
        if dept_code or dept_name:
            result = adapter.get_doctors_by_dept(dept_code=dept_code, dept_name=dept_name, use_encryption=use_encryption)
        else:
            result = adapter.get_doctors(ono=ono, eno=eno, use_encryption=use_encryption)
        
        if result.get('success'):
            return success_response({
                "doctors": result.get('doctors', []),
                "total_count": result.get('total_count', 0),
                "source": "HIS"
            })
        else:
            return error_response(result.get('message', '获取医生信息失败'), "HIS_ERROR", 502)
            
    except ValueError as e:
        return error_response(f"参数错误: {str(e)}", "PARAM_ERROR", 400)
    except HISAdapterError as e:
        logger.error(f"HIS接口调用失败: {e}")
        return error_response(f"HIS接口调用失败: {str(e)}", "HIS_ERROR", 502)
    except Exception as e:
        logger.error(f"从HIS获取医生列表失败: {e}")
        return error_response("从HIS获取医生列表失败", "ERROR", 500)


@api_bp.route('/doctors/sync', methods=['POST'])
def sync_doctors_from_his():
    """
    从HIS同步医生数据到本地数据库
    用于初始化或定期同步医生信息
    """
    try:
        # 检查HIS WebAPI是否启用
        if not HIS_WEBAPI_CONFIG.get('enabled'):
            return error_response("HIS WebAPI未启用", "HIS_DISABLED", 503)
        
        base_url = HIS_WEBAPI_CONFIG.get('base_url')
        meskey = HIS_WEBAPI_CONFIG.get('meskey')
        
        if not base_url or not meskey:
            return error_response("HIS WebAPI配置不完整", "HIS_CONFIG_ERROR", 503)
        
        # 获取适配器
        adapter = get_his_webapi_adapter(base_url, meskey, HIS_WEBAPI_CONFIG.get('timeout', 30))
        
        # 获取数据库连接
        conn = db.get_connection()
        try:
            result = adapter.sync_doctors_to_db(conn)
            if result.get('success'):
                return success_response(result, "医生数据同步成功")
            else:
                return error_response(result.get('message', '同步失败'), "SYNC_ERROR", 500)
        finally:
            conn.close()
            
    except HISAdapterError as e:
        logger.error(f"HIS同步失败: {e}")
        return error_response(f"HIS同步失败: {str(e)}", "HIS_ERROR", 502)
    except Exception as e:
        logger.error(f"同步医生数据失败: {e}")
        return error_response("同步医生数据失败", "ERROR", 500)


@api_bp.route('/his/health', methods=['GET'])
def his_health_check():
    """
    HIS接口健康检查
    测试G0076接口连通性
    """
    try:
        # 检查HIS WebAPI是否启用
        if not HIS_WEBAPI_CONFIG.get('enabled'):
            return success_response({
                "enabled": False,
                "status": "disabled",
                "message": "HIS WebAPI未启用"
            })
        
        base_url = HIS_WEBAPI_CONFIG.get('base_url')
        meskey = HIS_WEBAPI_CONFIG.get('meskey')
        
        if not base_url or not meskey:
            return success_response({
                "enabled": True,
                "configured": False,
                "status": "not_configured",
                "message": "HIS WebAPI配置不完整"
            })
        
        # 获取适配器
        adapter = get_his_webapi_adapter(base_url, meskey, HIS_WEBAPI_CONFIG.get('timeout', 30))
        
        # 健康检查
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


# ============ 患者接口 ============

@api_bp.route('/patients', methods=['GET'])
def get_patients():
    """获取患者列表"""
    try:
        dept_code = request.args.get('dept_code', '')
        dept_name = request.args.get('dept_name', '心内科')
        doctor_id = request.args.get('doctor_id')
        visit_status = request.args.get('visit_status')
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        keyword = request.args.get('keyword', '')
        page = int(request.args.get('page', 1))
        page_size = min(int(request.args.get('page_size', 20)), 100)  # 最大100条
        
        with db.get_cursor() as cursor:
            # 构建查询条件
            where_clause = "WHERE v.visit_date = %s AND v.status = 1"
            params = [date]
            
            if dept_code:
                where_clause += " AND v.dept_code = %s"
                params.append(dept_code)
            elif dept_name:
                where_clause += " AND v.dept_name = %s"
                params.append(dept_name)
            
            if doctor_id:
                where_clause += " AND v.doctor_id = %s"
                params.append(doctor_id)
            
            if visit_status:
                where_clause += " AND v.visit_status = %s"
                params.append(visit_status)
            
            if keyword:
                where_clause += " AND (p.name LIKE %s OR p.card_no LIKE %s OR v.patient_no LIKE %s)"
                like_keyword = f"%{keyword}%"
                params.extend([like_keyword, like_keyword, like_keyword])
            
            # 查询患者列表
            sql = f"""
                SELECT v.visit_id, v.patient_id, v.patient_no, v.card_no,
                       p.name, p.gender, p.age, v.visit_sequence,
                       v.dept_code, v.dept_name, v.visit_date as admission_date,
                       v.diagnosis, v.diagnosis_code, v.doctor_id, v.doctor_name as attending_doctor,
                       v.visit_status, v.visit_status_name, v.queue_no,
                       v.room, v.room_code, v.is_emergency, v.is_vip,
                       v.register_time, v.arrive_time, v.call_time, v.complete_time
                FROM visits v
                LEFT JOIN patients p ON v.patient_id = p.patient_id
                {where_clause}
                ORDER BY v.visit_sequence, v.queue_no
                LIMIT %s OFFSET %s
            """
            params.extend([page_size, (page - 1) * page_size])
            
            cursor.execute(sql, params)
            patients = cursor.fetchall()
            
            # 查询统计数据
            count_sql = f"""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN v.visit_status = 'not_registered' THEN 1 ELSE 0 END) as not_registered,
                    SUM(CASE WHEN v.visit_status LIKE 'registered%' THEN 1 ELSE 0 END) as registered,
                    SUM(CASE WHEN v.visit_status = 'registered_not_arrived' THEN 1 ELSE 0 END) as registered_not_arrived,
                    SUM(CASE WHEN v.visit_status = 'registered_arrived' THEN 1 ELSE 0 END) as registered_arrived,
                    SUM(CASE WHEN v.visit_status = 'in_treatment' THEN 1 ELSE 0 END) as in_treatment,
                    SUM(CASE WHEN v.visit_status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN v.visit_status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
                FROM visits v
                LEFT JOIN patients p ON v.patient_id = p.patient_id
                {where_clause.split('LIMIT')[0]}
            """
            cursor.execute(count_sql, params[:-2])  # 去掉 limit 参数
            summary = cursor.fetchone()
        
        return success_response({
            "patients": patients,
            "summary": summary,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": summary['total'] or 0,
                "total_pages": ((summary['total'] or 0) + page_size - 1) // page_size
            }
        })
    except Exception as e:
        logger.error(f"Get patients error: {e}")
        return error_response("获取患者列表失败", "DB_ERROR", 500)

@api_bp.route('/patients/<patient_id>', methods=['GET'])
def get_patient_detail(patient_id):
    """获取患者详情"""
    try:
        with db.get_cursor() as cursor:
            # 患者基本信息
            cursor.execute("""
                SELECT v.*, p.name, p.gender, p.age, p.phone, p.address, p.allergy_info
                FROM visits v
                LEFT JOIN patients p ON v.patient_id = p.patient_id
                WHERE v.patient_id = %s AND v.status = 1
                ORDER BY v.visit_date DESC
                LIMIT 1
            """, (patient_id,))
            patient = cursor.fetchone()
            
            if not patient:
                return error_response("患者不存在", "PATIENT_NOT_FOUND", 404)
            
            # 医嘱数量
            cursor.execute("""
                SELECT COUNT(*) as count FROM orders 
                WHERE patient_id = %s AND status IN ('pending', 'scan_pending')
            """, (patient_id,))
            orders_count = cursor.fetchone()['count']
            
            # 申请单数量
            cursor.execute("""
                SELECT COUNT(*) as count FROM applications 
                WHERE patient_id = %s AND status IN ('pending', 'scheduled')
            """, (patient_id,))
            apps_count = cursor.fetchone()['count']
        
        return success_response({
            "patient": patient,
            "orders_count": orders_count,
            "apps_count": apps_count
        })
    except Exception as e:
        logger.error(f"Get patient detail error: {e}")
        return error_response("获取患者详情失败", "DB_ERROR", 500)

# ============ 医嘱接口 ============

@api_bp.route('/orders/patient/<patient_id>', methods=['GET'])
def get_patient_orders(patient_id):
    """获取患者医嘱"""
    try:
        order_type = request.args.get('order_type')
        status = request.args.get('status')
        
        with db.get_cursor() as cursor:
            sql = """
                SELECT o.*, p.name as patient_name
                FROM orders o
                LEFT JOIN patients p ON o.patient_id = p.patient_id
                WHERE o.patient_id = %s AND o.status != 'deleted'
            """
            params = [patient_id]
            
            if order_type:
                sql += " AND o.order_type = %s"
                params.append(order_type)
            
            if status:
                sql += " AND o.status = %s"
                params.append(status)
            
            sql += " ORDER BY o.start_time DESC"
            
            cursor.execute(sql, params)
            orders = cursor.fetchall()
            
            # 获取医嘱项目
            for order in orders:
                cursor.execute("""
                    SELECT item_code, item_name, specification, dosage, 
                           unit, quantity, usage_desc, frequency, price, amount
                    FROM order_items 
                    WHERE order_id = %s ORDER BY sort_order
                """, (order['order_id'],))
                order['items'] = cursor.fetchall()
        
        return success_response({
            "patient": {"patient_id": patient_id, "name": orders[0]['patient_name'] if orders else ""},
            "orders": orders,
            "total_count": len(orders)
        })
    except Exception as e:
        logger.error(f"Get orders error: {e}")
        return error_response("获取医嘱失败", "DB_ERROR", 500)

# ============ 申请单接口 ============

@api_bp.route('/applications/patient/<patient_id>', methods=['GET'])
def get_patient_applications(patient_id):
    """获取患者申请单"""
    try:
        app_type = request.args.get('app_type')
        status = request.args.get('status')
        
        with db.get_cursor() as cursor:
            sql = """
                SELECT a.*, p.name as patient_name
                FROM applications a
                LEFT JOIN patients p ON a.patient_id = p.patient_id
                WHERE a.patient_id = %s AND a.status != 'deleted'
            """
            params = [patient_id]
            
            if app_type:
                sql += " AND a.app_type = %s"
                params.append(app_type)
            
            if status:
                sql += " AND a.status = %s"
                params.append(status)
            
            sql += " ORDER BY a.apply_time DESC"
            
            cursor.execute(sql, params)
            apps = cursor.fetchall()
            
            # 获取申请单项目
            for app in apps:
                cursor.execute("""
                    SELECT item_code, item_name, quantity, price, amount, specimen_type
                    FROM application_items 
                    WHERE app_id = %s ORDER BY sort_order
                """, (app['app_id'],))
                app['items'] = cursor.fetchall()
        
        return success_response({
            "patient": {"patient_id": patient_id, "name": apps[0]['patient_name'] if apps else ""},
            "applications": apps,
            "total_count": len(apps)
        })
    except Exception as e:
        logger.error(f"Get applications error: {e}")
        return error_response("获取申请单失败", "DB_ERROR", 500)

# ============ 耗材扫码接口（核心功能） ============

@api_bp.route('/orders/scan-consumable', methods=['POST'])
def scan_consumable():
    """
    耗材扫码确认
    护士使用条码扫描枪扫描耗材条码进行确认
    """
    try:
        data = request.json or {}
        order_id = data.get('order_id')
        barcode = data.get('barcode', '').strip()
        nurse_id = data.get('nurse_id')
        nurse_name = data.get('nurse_name')
        scan_time = data.get('scan_time', datetime.now().isoformat())
        scan_device = data.get('scan_device', '')  # 扫描设备标识
        
        # 参数验证
        if not order_id:
            return error_response("缺少order_id参数", "INVALID_PARAMS")
        
        if not barcode:
            return error_response("请扫描耗材条码", "MISSING_BARCODE")
        
        if not nurse_id and not nurse_name:
            return error_response("缺少护士信息", "INVALID_PARAMS")
        
        # 条码格式验证
        valid, error_msg = validate_barcode(barcode)
        if not valid:
            return error_response(error_msg, "INVALID_BARCODE")
        
        with db.get_cursor() as cursor:
            # 1. 检查医嘱是否存在且为耗材医嘱
            cursor.execute("""
                SELECT o.*, p.name as patient_name
                FROM orders o
                LEFT JOIN patients p ON o.patient_id = p.patient_id
                WHERE o.order_id = %s AND o.is_consumable = 1
            """, (order_id,))
            order = cursor.fetchone()
            
            if not order:
                return error_response("医嘱不存在或不是耗材医嘱", "ORDER_NOT_FOUND", 404)
            
            # 2. 检查是否已扫码
            if order['consumable_scanned']:
                return error_response(
                    f"该耗材已于 {order['scan_time']} 被 {order['scanner_nurse_name']} 扫码确认",
                    "ALREADY_SCANNED", 
                    400
                )
            
            # 3. 检查交费状态
            if order['payment_status'] != '已交费':
                return error_response(
                    f"该耗材尚未交费，当前状态：{order['payment_status']}",
                    "NOT_PAID",
                    400
                )
            
            # 4. 获取耗材名称
            cursor.execute("""
                SELECT item_name FROM order_items 
                WHERE order_id = %s ORDER BY sort_order LIMIT 1
            """, (order_id,))
            item = cursor.fetchone()
            consumable_name = item['item_name'] if item else '未知耗材'
            
            # 5. 生成扫码记录ID
            scan_id = str(uuid.uuid4()).replace('-', '')[:20]
            
            # 6. 更新医嘱状态
            cursor.execute("""
                UPDATE orders 
                SET consumable_scanned = 1,
                    consumable_barcode = %s,
                    scan_time = %s,
                    scanner_nurse_id = %s,
                    scanner_nurse_name = %s,
                    status = 'scanned',
                    updated_at = NOW()
                WHERE order_id = %s
            """, (barcode, scan_time, nurse_id, nurse_name, order_id))
            
            # 7. 记录扫码日志
            cursor.execute("""
                INSERT INTO consumable_scans 
                (scan_id, order_id, patient_id, barcode, consumable_name, 
                 consumable_code, nurse_id, nurse_name, scan_time, 
                 scan_device, scan_location, verify_status, verify_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s)
            """, (
                scan_id, order_id, order['patient_id'], barcode, 
                consumable_name, order['items'][0]['item_code'] if order.get('items') else '',
                nurse_id, nurse_name, scan_time, 
                scan_device, '护士站', '扫码验证通过'
            ))
            
            # 8. 记录操作日志
            cursor.execute("""
                INSERT INTO operation_logs 
                (log_id, user_id, user_name, user_type, operation_type, 
                 operation_desc, module, request_method, request_params, 
                 ip_address, status, created_at)
                VALUES (UUID(), %s, %s, 'nurse', 'SCAN_CONSUMABLE',
                        %s, 'order', 'POST', %s, %s, 1, NOW())
            """, (
                nurse_id, nurse_name,
                f"扫码确认耗材：{consumable_name}，条码：{barcode}",
                str(data),
                request.remote_addr
            ))
        
        logger.info(f"Consumable scanned: order_id={order_id}, barcode={barcode}, nurse={nurse_name}")
        
        return success_response({
            "scan_id": scan_id,
            "order_id": order_id,
            "order_no": order['order_no'],
            "consumable_name": consumable_name,
            "consumable_scanned": True,
            "consumable_barcode": barcode,
            "scan_time": scan_time,
            "scanner_nurse_id": nurse_id,
            "scanner_nurse_name": nurse_name,
            "status": "scanned",
            "status_name": "已扫码",
            "patient_name": order['patient_name'],
            "auto_submit": SCANNER_CONFIG.get('auto_submit', True)
        }, "耗材扫码确认成功")
        
    except Exception as e:
        logger.error(f"Scan consumable error: {e}")
        return error_response("扫码失败，请重试", "SCAN_ERROR", 500)

@api_bp.route('/orders/scan-consumable/validate', methods=['POST'])
def validate_consumable_barcode():
    """
    预验证耗材条码
    用于扫描时实时验证条码是否有效
    """
    try:
        data = request.json or {}
        barcode = data.get('barcode', '').strip()
        order_id = data.get('order_id')
        
        if not barcode:
            return error_response("条码不能为空", "MISSING_BARCODE")
        
        # 条码格式验证
        valid, error_msg = validate_barcode(barcode)
        if not valid:
            return error_response(error_msg, "INVALID_BARCODE")
        
        with db.get_cursor() as cursor:
            # 检查条码是否已被使用
            cursor.execute("""
                SELECT order_id, scan_time, scanner_nurse_name
                FROM orders 
                WHERE consumable_barcode = %s AND consumable_scanned = 1
            """, (barcode,))
            existing = cursor.fetchone()
            
            if existing:
                return error_response(
                    f"该条码已于 {existing['scan_time']} 被使用",
                    "BARCODE_USED",
                    400
                )
            
            # 如果提供了order_id，检查是否匹配
            if order_id:
                cursor.execute("""
                    SELECT order_id, order_no, is_consumable, consumable_scanned, payment_status
                    FROM orders WHERE order_id = %s
                """, (order_id,))
                order = cursor.fetchone()
                
                if not order:
                    return error_response("医嘱不存在", "ORDER_NOT_FOUND", 404)
                
                if not order['is_consumable']:
                    return error_response("该医嘱不是耗材医嘱", "NOT_CONSUMABLE", 400)
        
        return success_response({
            "barcode": barcode,
            "valid": True,
            "message": "条码验证通过"
        })
        
    except Exception as e:
        logger.error(f"Validate barcode error: {e}")
        return error_response("验证失败", "VALIDATE_ERROR", 500)

@api_bp.route('/orders/<order_id>/scan-info', methods=['GET'])
def get_scan_info(order_id):
    """获取耗材扫码信息"""
    try:
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT scan_id, barcode, consumable_name, nurse_name, 
                       scan_time, scan_device, verify_status, verify_message
                FROM consumable_scans
                WHERE order_id = %s
                ORDER BY scan_time DESC
            """, (order_id,))
            scans = cursor.fetchall()
        
        return success_response({
            "order_id": order_id,
            "scans": scans,
            "total_count": len(scans)
        })
    except Exception as e:
        logger.error(f"Get scan info error: {e}")
        return error_response("获取扫码信息失败", "DB_ERROR", 500)

# ============ 统计接口 ============

@api_bp.route('/summary/visit-status', methods=['GET'])
def get_visit_status_summary():
    """获取就诊状态统计"""
    try:
        dept_code = request.args.get('dept_code', '')
        dept_name = request.args.get('dept_name', '心内科')
        doctor_id = request.args.get('doctor_id')
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    %s as date,
                    dept_code,
                    dept_name,
                    %s as doctor_id,
                    COUNT(*) as total,
                    SUM(CASE WHEN visit_status = 'not_registered' THEN 1 ELSE 0 END) as not_registered,
                    SUM(CASE WHEN visit_status LIKE 'registered%' THEN 1 ELSE 0 END) as registered,
                    SUM(CASE WHEN visit_status = 'registered_not_arrived' THEN 1 ELSE 0 END) as registered_not_arrived,
                    SUM(CASE WHEN visit_status = 'registered_arrived' THEN 1 ELSE 0 END) as registered_arrived,
                    SUM(CASE WHEN visit_status = 'in_treatment' THEN 1 ELSE 0 END) as in_treatment,
                    SUM(CASE WHEN visit_status = 'completed' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN visit_status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
                FROM visits
                WHERE visit_date = %s AND status = 1
            """
            params = [date, doctor_id or '', date]
            
            if dept_code:
                sql += " AND dept_code = %s"
                params.append(dept_code)
            elif dept_name:
                sql += " AND dept_name = %s"
                params.append(dept_name)
            
            if doctor_id:
                sql += " AND doctor_id = %s"
                params.append(doctor_id)
            
            cursor.execute(sql, params)
            summary = cursor.fetchone()
        
        return success_response(summary)
    except Exception as e:
        logger.error(f"Get summary error: {e}")
        return error_response("获取统计失败", "DB_ERROR", 500)

# ============ 叫号系统回调接口 ============

@api_bp.route('/callback/visit-status', methods=['POST'])
def callback_visit_status():
    """
    叫号系统状态推送回调
    叫号系统在患者状态变更时调用此接口
    """
    try:
        data = request.json or {}
        
        # 记录回调日志
        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO queue_callback_logs 
                (log_id, callback_type, patient_id, visit_id, event_type, 
                 event_data, source_ip, sign_verify, process_status, created_at)
                VALUES (UUID(), 'visit_status', %s, %s, %s, %s, %s, 1, 0, NOW())
            """, (
                data.get('patient_id'),
                data.get('visit_id'),
                data.get('event_type'),
                str(data),
                request.remote_addr
            ))
        
        # TODO: 处理状态变更，更新 visits 表
        logger.info(f"Queue callback received: {data}")
        
        return success_response(message="状态更新成功")
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return error_response("回调处理失败", "CALLBACK_ERROR", 500)

@api_bp.route('/callback/patient-arrive', methods=['POST'])
def callback_patient_arrive():
    """
    患者报到回调
    患者报到时叫号系统调用此接口
    """
    try:
        data = request.json or {}
        
        # 记录回调日志
        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO queue_callback_logs 
                (log_id, callback_type, patient_id, visit_id, event_type, 
                 event_data, source_ip, sign_verify, process_status, created_at)
                VALUES (UUID(), 'patient_arrive', %s, %s, 'arrived', %s, %s, 1, 0, NOW())
            """, (
                data.get('patient_id'),
                data.get('visit_id'),
                str(data),
                request.remote_addr
            ))
        
        # TODO: 处理报到，更新 visits 表
        logger.info(f"Arrive callback received: {data}")
        
        return success_response(message="报到处理成功")
    except Exception as e:
        logger.error(f"Arrive callback error: {e}")
        return error_response("报到处理失败", "CALLBACK_ERROR", 500)

# ============ 扫码设备接口 ============

@api_bp.route('/scanner/config', methods=['GET'])
def get_scanner_config():
    """获取扫码设备配置"""
    return success_response({
        "barcode_prefix": SCANNER_CONFIG.get('barcode_prefix', ''),
        "barcode_length": SCANNER_CONFIG.get('barcode_length', 0),
        "auto_submit": SCANNER_CONFIG.get('auto_submit', True)
    })
