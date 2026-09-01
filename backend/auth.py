#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
护士登录认证模块
"""

from flask import Blueprint, request, jsonify, session
from datetime import datetime
import logging
import hashlib
import uuid
from db import db

logger = logging.getLogger(__name__)
auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')

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

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    护士登录
    
    请求参数：
    {
        "nurse_code": "nurse001",
        "password": "123456"
    }
    
    响应：
    {
        "success": true,
        "data": {
            "nurse_id": "N001",
            "nurse_code": "nurse001",
            "name": "李护士",
            "title": "主管护师",
            "dept_code": "XK",
            "dept_name": "心内科",
            "role": "nurse",
            "token": "session_id"
        }
    }
    """
    try:
        data = request.json or {}
        nurse_code = data.get('nurse_code', '').strip()
        password = data.get('password', '').strip()
        
        if not nurse_code:
            return error_response("请输入护士工号", "MISSING_NURSE_CODE")
        
        if not password:
            return error_response("请输入密码", "MISSING_PASSWORD")
        
        # 查询护士信息
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT nurse_id, nurse_code, name, password_hash, title,
                       dept_code, dept_name, role, status
                FROM nurses
                WHERE nurse_code = %s
            """, (nurse_code,))
            nurse = cursor.fetchone()
        
        if not nurse:
            logger.warning(f"登录失败：护士工号不存在 {nurse_code}")
            return error_response("工号或密码错误", "INVALID_CREDENTIALS", 401)
        
        # 检查状态
        if nurse['status'] != 1:
            logger.warning(f"登录失败：账号已停用 {nurse_code}")
            return error_response("账号已停用，请联系管理员", "ACCOUNT_DISABLED", 403)
        
        # 验证密码
        password_hash = md5_hash(password)
        if password_hash != nurse['password_hash']:
            logger.warning(f"登录失败：密码错误 {nurse_code}")
            return error_response("工号或密码错误", "INVALID_CREDENTIALS", 401)
        
        # 生成会话ID
        session_id = str(uuid.uuid4())
        
        # 更新最后登录时间
        login_time = datetime.now()
        login_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', '')
        
        with db.get_cursor() as cursor:
            # 更新护士表
            cursor.execute("""
                UPDATE nurses
                SET last_login_time = %s, last_login_ip = %s
                WHERE nurse_id = %s
            """, (login_time, login_ip, nurse['nurse_id']))
            
            # 记录登录日志
            log_id = str(uuid.uuid4()).replace('-', '')[:20]
            cursor.execute("""
                INSERT INTO login_logs
                (log_id, nurse_id, nurse_code, nurse_name, dept_code, dept_name,
                 login_time, login_ip, user_agent, login_status, session_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
            """, (
                log_id, nurse['nurse_id'], nurse['nurse_code'], nurse['name'],
                nurse['dept_code'], nurse['dept_name'], login_time, login_ip,
                user_agent, session_id, login_time
            ))
        
        # 保存到session
        session['nurse_id'] = nurse['nurse_id']
        session['nurse_code'] = nurse['nurse_code']
        session['dept_code'] = nurse['dept_code']
        session['role'] = nurse['role']
        session['session_id'] = session_id
        
        logger.info(f"护士登录成功: {nurse['name']} ({nurse_code}) - {nurse['dept_name']}")
        
        return success_response({
            "nurse_id": nurse['nurse_id'],
            "nurse_code": nurse['nurse_code'],
            "name": nurse['name'],
            "title": nurse['title'],
            "dept_code": nurse['dept_code'],
            "dept_name": nurse['dept_name'],
            "role": nurse['role'],
            "token": session_id
        }, "登录成功")
        
    except Exception as e:
        logger.error(f"登录异常: {e}")
        return error_response("登录失败，请重试", "LOGIN_ERROR", 500)

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    护士登出
    """
    try:
        nurse_id = session.get('nurse_id')
        session_id = session.get('session_id')
        
        if nurse_id and session_id:
            # 更新登录日志的登出时间
            with db.get_cursor() as cursor:
                cursor.execute("""
                    UPDATE login_logs
                    SET logout_time = %s
                    WHERE session_id = %s AND logout_time IS NULL
                """, (datetime.now(), session_id))
        
        # 清除session
        session.clear()
        
        return success_response(message="登出成功")
        
    except Exception as e:
        logger.error(f"登出异常: {e}")
        return error_response("登出失败", "LOGOUT_ERROR", 500)

@auth_bp.route('/current', methods=['GET'])
def get_current_nurse():
    """
    获取当前登录护士信息
    """
    try:
        nurse_id = session.get('nurse_id')
        
        if not nurse_id:
            return error_response("未登录", "NOT_LOGGED_IN", 401)
        
        # 查询护士信息
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT nurse_id, nurse_code, name, title,
                       dept_code, dept_name, role, status
                FROM nurses
                WHERE nurse_id = %s
            """, (nurse_id,))
            nurse = cursor.fetchone()
        
        if not nurse:
            return error_response("护士信息不存在", "NURSE_NOT_FOUND", 404)
        
        return success_response({
            "nurse_id": nurse['nurse_id'],
            "nurse_code": nurse['nurse_code'],
            "name": nurse['name'],
            "title": nurse['title'],
            "dept_code": nurse['dept_code'],
            "dept_name": nurse['dept_name'],
            "role": nurse['role']
        })
        
    except Exception as e:
        logger.error(f"获取当前护士信息异常: {e}")
        return error_response("获取信息失败", "ERROR", 500)

@auth_bp.route('/change-password', methods=['POST'])
def change_password():
    """
    修改密码
    
    请求参数：
    {
        "old_password": "123456",
        "new_password": "654321"
    }
    """
    try:
        nurse_id = session.get('nurse_id')
        
        if not nurse_id:
            return error_response("未登录", "NOT_LOGGED_IN", 401)
        
        data = request.json or {}
        old_password = data.get('old_password', '').strip()
        new_password = data.get('new_password', '').strip()
        
        if not old_password or not new_password:
            return error_response("请输入旧密码和新密码", "MISSING_PASSWORD")
        
        if len(new_password) < 6:
            return error_response("新密码长度不能少于6位", "PASSWORD_TOO_SHORT")
        
        # 验证旧密码
        with db.get_cursor() as cursor:
            cursor.execute("""
                SELECT password_hash FROM nurses WHERE nurse_id = %s
            """, (nurse_id,))
            nurse = cursor.fetchone()
        
        if not nurse:
            return error_response("护士信息不存在", "NURSE_NOT_FOUND", 404)
        
        old_password_hash = md5_hash(old_password)
        if old_password_hash != nurse['password_hash']:
            return error_response("旧密码错误", "INVALID_OLD_PASSWORD")
        
        # 更新密码
        new_password_hash = md5_hash(new_password)
        with db.get_cursor() as cursor:
            cursor.execute("""
                UPDATE nurses
                SET password_hash = %s, updated_at = %s
                WHERE nurse_id = %s
            """, (new_password_hash, datetime.now(), nurse_id))
        
        logger.info(f"护士修改密码成功: {nurse_id}")
        
        return success_response(message="密码修改成功")
        
    except Exception as e:
        logger.error(f"修改密码异常: {e}")
        return error_response("修改密码失败", "ERROR", 500)

def require_login(f):
    """登录验证装饰器"""
    from functools import wraps
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        nurse_id = session.get('nurse_id')
        if not nurse_id:
            return error_response("请先登录", "NOT_LOGGED_IN", 401)
        return f(*args, **kwargs)
    
    return decorated_function

def get_current_dept_code():
    """获取当前登录护士的科室编码"""
    return session.get('dept_code')

def is_admin():
    """判断当前用户是否是管理员"""
    return session.get('role') == 'admin'