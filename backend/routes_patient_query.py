#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
患者查询API路由
支持通过病历号或卡号查询患者就诊记录和处方记录
"""

from flask import Blueprint, request, jsonify, session
from datetime import datetime
import logging
import uuid
from db import db
from auth import require_login, require_permission, has_permission

logger = logging.getLogger(__name__)
patient_query_bp = Blueprint('patient_query', __name__, url_prefix='/api/v1/patient-query')


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


@patient_query_bp.route('/search', methods=['GET'])
@require_login
@require_permission('query_patient')
def search_patient():
    """
    查询患者就诊记录
    
    请求参数：
    - query_type: 查询类型（patient_id-病历号 card_id-卡号）
    - query_value: 查询值
    - start_date: 开始日期（可选，默认今天）
    - end_date: 结束日期（可选，默认今天）
    
    响应：
    {
        "success": true,
        "data": {
            "patient_info": {...},
            "visits": [...],
            "total_count": 10
        }
    }
    """
    try:
        query_type = request.args.get('query_type', 'patient_id')
        query_value = request.args.get('query_value', '').strip()
        start_date = request.args.get('start_date', datetime.now().strftime('%Y-%m-%d'))
        end_date = request.args.get('end_date', datetime.now().strftime('%Y-%m-%d'))

        if not query_value:
            return error_response("请输入查询值", "MISSING_QUERY_VALUE")

        if query_type not in ['patient_id', 'card_id']:
            return error_response("查询类型必须是 patient_id 或 card_id", "INVALID_QUERY_TYPE")

        # 构建查询条件
        if query_type == 'patient_id':
            where_clause = "pr.patient_id = %s"
        else:
            where_clause = "pr.card_id = %s"

        # 查询患者就诊记录
        with db.get_cursor() as cursor:
            sql = f"""
                SELECT 
                    pr.registration_id,
                    pr.visit_date,
                    pr.visit_no,
                    pr.visit_time_desc,
                    pr.clinic_label,
                    pr.patient_id,
                    pr.card_id,
                    pr.name as patient_name,
                    pr.sex,
                    pr.age,
                    pr.charge_type,
                    pr.serial_no,
                    pr.fre_date,
                    cs.dept_name,
                    cs.clinic_dept
                FROM patient_registrations pr
                LEFT JOIN clinic_schedules cs ON pr.clinic_label = cs.clinic_label 
                    AND pr.visit_date = cs.clinic_date 
                    AND pr.visit_time_desc = cs.time_desc
                WHERE {where_clause}
                    AND pr.visit_date BETWEEN %s AND %s
                ORDER BY pr.visit_date DESC, pr.visit_time_desc, pr.serial_no
            """

            cursor.execute(sql, (query_value, start_date, end_date))
            visits = cursor.fetchall()

        # 如果没有找到记录
        if not visits:
            # 记录查询日志
            log_query(query_type, query_value, start_date, end_date, None, None, 0)
            return success_response({
                "patient_info": None,
                "visits": [],
                "total_count": 0
            }, "未找到患者就诊记录")

        # 提取患者基本信息（从第一条记录）
        first_visit = visits[0]
        patient_info = {
            "patient_id": first_visit['patient_id'],
            "card_id": first_visit['card_id'],
            "name": first_visit['patient_name'],
            "sex": first_visit['sex'],
            "age": first_visit['age'],
            "charge_type": first_visit['charge_type']
        }

        # 如果有处方查询权限，查询处方记录
        can_query_prescription = has_permission('query_prescription')

        for visit in visits:
            visit['orders'] = []
            visit['order_count'] = 0
            visit['cmc_count'] = 0

            if can_query_prescription:
                with db.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            order_id,
                            presc_no,
                            presc_date,
                            item_no,
                            class_name,
                            item_code,
                            item_name,
                            package_spec,
                            administration,
                            frequency,
                            quantity,
                            price,
                            states,
                            cmc_flag
                        FROM patient_orders
                        WHERE visit_date = %s AND visit_no = %s
                        ORDER BY presc_no, item_no
                    """, (visit['visit_date'], visit['visit_no']))

                    orders = cursor.fetchall()
                    visit['orders'] = orders
                    visit['order_count'] = len(orders)
                    visit['cmc_count'] = sum(1 for o in orders if o.get('cmc_flag') == '1')

        # 记录查询日志
        log_query(query_type, query_value, start_date, end_date,
                  patient_info['patient_id'], patient_info['name'], len(visits))

        return success_response({
            "patient_info": patient_info,
            "visits": visits,
            "total_count": len(visits),
            "can_query_prescription": can_query_prescription
        }, f"查询成功，共找到{len(visits)}条就诊记录")

    except Exception as e:
        logger.error(f"查询患者就诊记录失败: {e}")
        return error_response("查询失败，请重试", "QUERY_ERROR", 500)


@patient_query_bp.route('/visit-detail', methods=['GET'])
@require_login
@require_permission('query_patient')
def get_visit_detail():
    """
    获取就诊详情
    
    请求参数：
    - visit_date: 就诊日期
    - visit_no: 就诊号
    """
    try:
        visit_date = request.args.get('visit_date', '')
        visit_no = request.args.get('visit_no', '')

        if not visit_date or not visit_no:
            return error_response("缺少必要参数", "MISSING_PARAMS")

        # 查询就诊信息
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    pr.*,
                    cs.dept_name,
                    cs.clinic_dept
                FROM patient_registrations pr
                LEFT JOIN clinic_schedules cs ON pr.clinic_label = cs.clinic_label 
                    AND pr.visit_date = cs.clinic_date 
                    AND pr.visit_time_desc = cs.time_desc
                WHERE pr.visit_date = %s AND pr.visit_no = %s
            """, (visit_date, visit_no))

            visit = cursor.fetchone()

        if not visit:
            return error_response("就诊记录不存在", "VISIT_NOT_FOUND", 404)

        # 查询处方记录（如果有权限）
        orders = []
        if has_permission('query_prescription'):
            with db.get_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM patient_orders
                    WHERE visit_date = %s AND visit_no = %s
                    ORDER BY presc_no, item_no
                """, (visit_date, visit_no))
                orders = cursor.fetchall()

        return success_response({
            "visit": visit,
            "orders": orders,
            "can_query_prescription": has_permission('query_prescription')
        })

    except Exception as e:
        logger.error(f"获取就诊详情失败: {e}")
        return error_response("获取详情失败", "ERROR", 500)


@patient_query_bp.route('/query-logs', methods=['GET'])
@require_login
def get_query_logs():
    """
    获取查询日志（仅管理员和护士长）
    """
    try:
        # 检查权限
        if not (has_permission('manage_nurse') or session.get('role') == 'admin'):
            return error_response("无权限查看查询日志", "PERMISSION_DENIED", 403)

        nurse_id = request.args.get('nurse_id', '')
        query_date = request.args.get('query_date', datetime.now().strftime('%Y-%m-%d'))
        limit = int(request.args.get('limit', 100))

        with db.get_cursor() as cursor:
            sql = """
                SELECT * FROM patient_query_logs
                WHERE query_date = %s
            """
            params = [query_date]

            if nurse_id:
                sql += " AND nurse_id = %s"
                params.append(nurse_id)

            sql += " ORDER BY query_time DESC LIMIT %s"
            params.append(limit)

            cursor.execute(sql, params)
            logs = cursor.fetchall()

        return success_response({
            "logs": logs,
            "total_count": len(logs)
        })

    except Exception as e:
        logger.error(f"获取查询日志失败: {e}")
        return error_response("获取日志失败", "ERROR", 500)


def log_query(query_type, query_value, start_date, end_date, patient_id, patient_name, result_count):
    """记录查询日志"""
    try:
        nurse_id = session.get('nurse_id')
        nurse_code = session.get('nurse_code')
        nurse_name = session.get('name', '')

        if not nurse_id:
            return

        query_id = str(uuid.uuid4()).replace('-', '')[:20]

        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO patient_query_logs
                (query_id, nurse_id, nurse_code, nurse_name, query_type, query_value,
                 query_date, patient_id, patient_name, result_count, query_time, query_ip, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                query_id, nurse_id, nurse_code, nurse_name, query_type, query_value,
                start_date, patient_id, patient_name, result_count,
                datetime.now(), request.remote_addr, datetime.now()
            ))
    except Exception as e:
        logger.error(f"记录查询日志失败: {e}")
