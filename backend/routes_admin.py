#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
软件名称：北京医院门诊护士工作站
文件名称：routes_admin.py
功能描述：护士账号、角色权限及科室关联配置的管理 API 路由
开发单位：北京医院
开发日期：2026年8月
版本号：V1.0
================================================================================
"""

from flask import Blueprint, request, jsonify, session
from datetime import datetime
import logging
import uuid
import hashlib
from db import db
from auth import require_login, require_permission, is_admin

logger = logging.getLogger(__name__)
admin_bp = Blueprint('admin', __name__, url_prefix='/api/v1/admin')

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

def md5_hash(text):
    """MD5加密"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

# ============ 护士管理 ============

@admin_bp.route('/nurses', methods=['GET'])
@require_login
@require_permission('manage_nurse')
def get_nurses():
    """
    获取护士列表
    
    请求参数：
    - status: 状态筛选（可选）
    - dept_code: 科室筛选（可选）
    - keyword: 关键词搜索（工号/姓名，可选）
    """
    try:
        status = request.args.get('status', '')
        dept_code = request.args.get('dept_code', '')
        keyword = request.args.get('keyword', '')
        
        with db.get_cursor() as cursor:
            sql = """
                SELECT 
                    n.*,
                    GROUP_CONCAT(DISTINCT r.role_name) as role_names,
                    GROUP_CONCAT(DISTINCT ndr.dept_name) as dept_names
                FROM nurses n
                LEFT JOIN nurse_roles nr ON n.nurse_id = nr.nurse_id
                LEFT JOIN roles r ON nr.role_id = r.role_id
                LEFT JOIN nurse_dept_relations ndr ON n.nurse_id = ndr.nurse_id AND ndr.status = 1
                WHERE 1=1
            """
            params = []
            
            if status:
                sql += " AND n.status = %s"
                params.append(status)
            
            if dept_code:
                sql += " AND n.dept_code = %s"
                params.append(dept_code)
            
            if keyword:
                sql += " AND (n.nurse_code LIKE %s OR n.name LIKE %s)"
                params.extend([f"%{keyword}%", f"%{keyword}%"])
            
            sql += " GROUP BY n.nurse_id ORDER BY n.created_at DESC"
            
            cursor.execute(sql, params)
            nurses = cursor.fetchall()
        
        return success_response({
            "nurses": nurses,
            "total_count": len(nurses)
        })
        
    except Exception as e:
        logger.error(f"获取护士列表失败: {e}")
        return error_response("获取护士列表失败", "ERROR", 500)

@admin_bp.route('/nurses', methods=['POST'])
@require_login
@require_permission('manage_nurse')
def create_nurse():
    """
    创建护士账号
    
    请求参数：
    {
        "nurse_code": "nurse007",
        "name": "赵护士",
        "password": "123456",
        "title": "护师",
        "dept_code": "XK",
        "dept_name": "心内科",
        "floor": "门诊六层",
        "phone": "13800138000",
        "email": "nurse007@hospital.com",
        "role_ids": ["R003"],
        "dept_codes": ["XK", "NFMK"]
    }
    """
    try:
        data = request.json or {}
        
        # 必填字段验证
        required_fields = ['nurse_code', 'name', 'password', 'dept_code', 'dept_name']
        for field in required_fields:
            if not data.get(field):
                return error_response(f"缺少必填字段: {field}", "MISSING_FIELD")
        
        nurse_code = data['nurse_code'].strip()
        
        # 检查工号是否已存在
        with db.get_cursor() as cursor:
            cursor.execute("SELECT nurse_id FROM nurses WHERE nurse_code = %s", (nurse_code,))
            if cursor.fetchone():
                return error_response("工号已存在", "NURSE_CODE_EXISTS")
        
        # 生成护士ID
        nurse_id = f"N{str(uuid.uuid4().int)[:6]}"
        
        # 创建护士
        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO nurses
                (nurse_id, nurse_code, name, password_hash, title, dept_code, dept_name,
                 floor, phone, email, role, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'nurse', 1, %s, %s)
            """, (
                nurse_id, nurse_code, data['name'], md5_hash(data['password']),
                data.get('title'), data['dept_code'], data['dept_name'],
                data.get('floor'), data.get('phone'), data.get('email'),
                datetime.now(), datetime.now()
            ))
        
        # 分配角色
        role_ids = data.get('role_ids', ['R004'])  # 默认基础护士
        with db.get_cursor() as cursor:
            for role_id in role_ids:
                cursor.execute("""
                    INSERT INTO nurse_roles (nurse_id, role_id, created_at)
                    VALUES (%s, %s, %s)
                """, (nurse_id, role_id, datetime.now()))
        
        # 配置科室
        dept_codes = data.get('dept_codes', [data['dept_code']])
        with db.get_cursor() as cursor:
            for i, dept_code in enumerate(dept_codes):
                # 查询科室名称
                cursor.execute("SELECT DISTINCT dept_name FROM clinic_schedules WHERE clinic_dept = %s LIMIT 1", (dept_code,))
                result = cursor.fetchone()
                dept_name = result['dept_name'] if result else dept_code
                
                relation_id = f"NDR_{nurse_id}_{dept_code}"
                cursor.execute("""
                    INSERT INTO nurse_dept_relations
                    (relation_id, nurse_id, dept_code, dept_name, floor, is_primary, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s)
                """, (
                    relation_id, nurse_id, dept_code, dept_name,
                    data.get('floor'), 1 if i == 0 else 0,
                    datetime.now(), datetime.now()
                ))
        
        logger.info(f"创建护士账号成功: {data['name']} ({nurse_code})")
        
        return success_response({
            "nurse_id": nurse_id,
            "nurse_code": nurse_code
        }, "创建护士账号成功")
        
    except Exception as e:
        logger.error(f"创建护士账号失败: {e}")
        return error_response("创建护士账号失败", "ERROR", 500)

@admin_bp.route('/nurses/<nurse_id>', methods=['PUT'])
@require_login
@require_permission('manage_nurse')
def update_nurse(nurse_id):
    """
    更新护士信息
    
    请求参数：
    {
        "name": "赵护士",
        "title": "主管护师",
        "phone": "13800138000",
        "email": "nurse007@hospital.com",
        "status": 1,
        "role_ids": ["R003"],
        "dept_codes": ["XK", "NFMK"]
    }
    """
    try:
        data = request.json or {}
        
        # 检查护士是否存在
        with db.get_cursor() as cursor:
            cursor.execute("SELECT nurse_id FROM nurses WHERE nurse_id = %s", (nurse_id,))
            if not cursor.fetchone():
                return error_response("护士不存在", "NURSE_NOT_FOUND", 404)
        
        # 更新基本信息
        update_fields = []
        params = []
        
        for field in ['name', 'title', 'phone', 'email', 'status', 'floor']:
            if field in data:
                update_fields.append(f"{field} = %s")
                params.append(data[field])
        
        if update_fields:
            params.append(datetime.now())
            params.append(nurse_id)
            
            with db.get_cursor() as cursor:
                sql = f"UPDATE nurses SET {', '.join(update_fields)}, updated_at = %s WHERE nurse_id = %s"
                cursor.execute(sql, params)
        
        # 更新角色
        if 'role_ids' in data:
            with db.get_cursor() as cursor:
                # 删除旧角色
                cursor.execute("DELETE FROM nurse_roles WHERE nurse_id = %s", (nurse_id,))
                # 添加新角色
                for role_id in data['role_ids']:
                    cursor.execute("""
                        INSERT INTO nurse_roles (nurse_id, role_id, created_at)
                        VALUES (%s, %s, %s)
                    """, (nurse_id, role_id, datetime.now()))
        
        # 更新科室配置
        if 'dept_codes' in data:
            with db.get_cursor() as cursor:
                # 删除旧配置
                cursor.execute("DELETE FROM nurse_dept_relations WHERE nurse_id = %s", (nurse_id,))
                # 添加新配置
                for i, dept_code in enumerate(data['dept_codes']):
                    cursor.execute("SELECT DISTINCT dept_name FROM clinic_schedules WHERE clinic_dept = %s LIMIT 1", (dept_code,))
                    result = cursor.fetchone()
                    dept_name = result['dept_name'] if result else dept_code
                    
                    relation_id = f"NDR_{nurse_id}_{dept_code}"
                    cursor.execute("""
                        INSERT INTO nurse_dept_relations
                        (relation_id, nurse_id, dept_code, dept_name, floor, is_primary, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s)
                    """, (
                        relation_id, nurse_id, dept_code, dept_name,
                        data.get('floor'), 1 if i == 0 else 0,
                        datetime.now(), datetime.now()
                    ))
        
        logger.info(f"更新护士信息成功: {nurse_id}")
        
        return success_response(message="更新护士信息成功")
        
    except Exception as e:
        logger.error(f"更新护士信息失败: {e}")
        return error_response("更新护士信息失败", "ERROR", 500)

@admin_bp.route('/nurses/<nurse_id>', methods=['DELETE'])
@require_login
@require_permission('manage_nurse')
def delete_nurse(nurse_id):
    """
    删除护士账号（软删除，设置为停用状态）
    """
    try:
        # 检查护士是否存在
        with db.get_cursor() as cursor:
            cursor.execute("SELECT nurse_id, name FROM nurses WHERE nurse_id = %s", (nurse_id,))
            nurse = cursor.fetchone()
            if not nurse:
                return error_response("护士不存在", "NURSE_NOT_FOUND", 404)
        
        # 软删除（设置为停用状态）
        with db.get_cursor() as cursor:
            cursor.execute("""
                UPDATE nurses SET status = 0, updated_at = %s WHERE nurse_id = %s
            """, (datetime.now(), nurse_id))
        
        logger.info(f"删除护士账号成功: {nurse['name']} ({nurse_id})")
        
        return success_response(message="删除护士账号成功")
        
    except Exception as e:
        logger.error(f"删除护士账号失败: {e}")
        return error_response("删除护士账号失败", "ERROR", 500)

@admin_bp.route('/nurses/<nurse_id>/reset-password', methods=['POST'])
@require_login
@require_permission('manage_nurse')
def reset_nurse_password(nurse_id):
    """
    重置护士密码
    
    请求参数：
    {
        "new_password": "123456"
    }
    """
    try:
        data = request.json or {}
        new_password = data.get('new_password', '123456')
        
        # 检查护士是否存在
        with db.get_cursor() as cursor:
            cursor.execute("SELECT nurse_id, name FROM nurses WHERE nurse_id = %s", (nurse_id,))
            nurse = cursor.fetchone()
            if not nurse:
                return error_response("护士不存在", "NURSE_NOT_FOUND", 404)
        
        # 重置密码
        with db.get_cursor() as cursor:
            cursor.execute("""
                UPDATE nurses SET password_hash = %s, updated_at = %s WHERE nurse_id = %s
            """, (md5_hash(new_password), datetime.now(), nurse_id))
        
        logger.info(f"重置护士密码成功: {nurse['name']} ({nurse_id})")
        
        return success_response(message="重置密码成功")
        
    except Exception as e:
        logger.error(f"重置护士密码失败: {e}")
        return error_response("重置密码失败", "ERROR", 500)

# ============ 角色权限管理 ============

@admin_bp.route('/roles', methods=['GET'])
@require_login
@require_permission('manage_permission')
def get_roles():
    """获取角色列表"""
    try:
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    r.*,
                    GROUP_CONCAT(p.permission_name) as permission_names
                FROM roles r
                LEFT JOIN role_permissions rp ON r.role_id = rp.role_id
                LEFT JOIN permissions p ON rp.permission_id = p.permission_id
                WHERE r.status = 1
                GROUP BY r.role_id
                ORDER BY r.created_at
            """)
            roles = cursor.fetchall()
        
        return success_response({
            "roles": roles,
            "total_count": len(roles)
        })
        
    except Exception as e:
        logger.error(f"获取角色列表失败: {e}")
        return error_response("获取角色列表失败", "ERROR", 500)

@admin_bp.route('/permissions', methods=['GET'])
@require_login
@require_permission('manage_permission')
def get_permissions():
    """获取权限列表"""
    try:
        category = request.args.get('category', '')
        
        with db.get_cursor() as cursor:
            sql = "SELECT * FROM permissions WHERE status = 1"
            params = []
            
            if category:
                sql += " AND category = %s"
                params.append(category)
            
            sql += " ORDER BY category, permission_code"
            
            cursor.execute(sql, params)
            permissions = cursor.fetchall()
        
        return success_response({
            "permissions": permissions,
            "total_count": len(permissions)
        })
        
    except Exception as e:
        logger.error(f"获取权限列表失败: {e}")
        return error_response("获取权限列表失败", "ERROR", 500)

@admin_bp.route('/roles/<role_id>/permissions', methods=['PUT'])
@require_login
@require_permission('manage_permission')
def update_role_permissions(role_id):
    """
    更新角色权限
    
    请求参数：
    {
        "permission_ids": ["P001", "P002", "P003"]
    }
    """
    try:
        data = request.json or {}
        permission_ids = data.get('permission_ids', [])
        
        # 检查角色是否存在
        with db.get_cursor() as cursor:
            cursor.execute("SELECT role_id FROM roles WHERE role_id = %s", (role_id,))
            if not cursor.fetchone():
                return error_response("角色不存在", "ROLE_NOT_FOUND", 404)
        
        # 更新角色权限
        with db.get_cursor() as cursor:
            # 删除旧权限
            cursor.execute("DELETE FROM role_permissions WHERE role_id = %s", (role_id,))
            # 添加新权限
            for permission_id in permission_ids:
                cursor.execute("""
                    INSERT INTO role_permissions (role_id, permission_id, created_at)
                    VALUES (%s, %s, %s)
                """, (role_id, permission_id, datetime.now()))
        
        logger.info(f"更新角色权限成功: {role_id}")
        
        return success_response(message="更新角色权限成功")
        
    except Exception as e:
        logger.error(f"更新角色权限失败: {e}")
        return error_response("更新角色权限失败", "ERROR", 500)

@admin_bp.route('/nurses/<nurse_id>/permissions', methods=['GET'])
@require_login
@require_permission('manage_nurse')
def get_nurse_permissions(nurse_id):
    """获取护士的权限列表"""
    try:
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT
                    p.permission_id,
                    p.permission_code,
                    p.permission_name,
                    p.category
                FROM nurse_roles nr
                JOIN role_permissions rp ON nr.role_id = rp.role_id
                JOIN permissions p ON rp.permission_id = p.permission_id
                WHERE nr.nurse_id = %s AND p.status = 1
                ORDER BY p.category, p.permission_code
            """, (nurse_id,))
            permissions = cursor.fetchall()
        
        return success_response({
            "permissions": permissions,
            "total_count": len(permissions)
        })
        
    except Exception as e:
        logger.error(f"获取护士权限失败: {e}")
        return error_response("获取护士权限失败", "ERROR", 500)
