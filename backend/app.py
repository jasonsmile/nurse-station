#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CVOnto 护士工作站后端 API 服务
纯内网环境运行，无需外网依赖
"""

from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS
from datetime import datetime
import logging
import os
import sys

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 配置日志
if os.name == 'nt':
    log_dir = os.path.join(current_dir, 'logs')
else:
    log_dir = '/opt/nurse-station/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__)
# 配置session
app.secret_key = os.urandom(24)  # 用于session加密
app.config['SESSION_COOKIE_NAME'] = 'nurse_station_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# 纯内网环境，允许所有来源（或指定内网IP段）
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# 配置
app.config['JSON_AS_ASCII'] = False
app.config['JSON_SORT_KEYS'] = False

# 导入并注册路由
from routes_g0078_g0080 import api_bp
from auth import auth_bp
from routes_patient_query import patient_query_bp
from routes_admin import admin_bp
app.register_blueprint(api_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(patient_query_bp)
app.register_blueprint(admin_bp)

# 定时同步调度器（已移除，改用其他同步方式）
# 原因：在gunicorn环境下无法正常导入scheduler模块
# 替代方案：使用独立的定时任务进程或系统crontab

# def init_scheduler():
#     """初始化定时同步调度器"""
#     global _scheduler_initialized
#     if _scheduler_initialized:
#         return
#     
#     try:
#         from scheduler import start_scheduler
#         start_scheduler()
#         _scheduler_initialized = True
#         logger.info("定时同步调度器初始化成功")
#     except Exception as e:
#         logger.error(f"定时同步调度器初始化失败: {e}")
#         import traceback
#         logger.error(traceback.format_exc())

# 在应用上下文中初始化调度器
# with app.app_context():
#     init_scheduler()

# ============ 健康检查 ============
@app.route('/api/v1/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({
        "success": True,
        "code": "SUCCESS",
        "message": "服务正常运行",
        "data": {
            "status": "running",
            "service": "CVOnto Nurse Station API",
            "version": "1.0.0",
            "environment": "intranet",
            "timestamp": datetime.now().isoformat()
        },
        "timestamp": datetime.now().isoformat()
    })

# ============ 静态文件服务 ============
@app.route('/')
def index():
    """首页"""
    return send_from_directory('/opt/nurse-station/frontend', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    """静态文件"""
    return send_from_directory('/opt/nurse-station/frontend', path)

# ============ 手动同步接口 ============
@app.route('/api/v1/sync/trigger', methods=['POST'])
def trigger_sync():
    """手动触发一次全量同步"""
    try:
        from his_webapi_adapter import get_his_webapi_adapter
        from config import HIS_WEBAPI_CONFIG, DB_CONFIG
        import pymysql
        
        # 检查HIS配置
        if not HIS_WEBAPI_CONFIG.get('enabled'):
            return jsonify({
                "success": False,
                "code": "HIS_DISABLED",
                "message": "HIS WebAPI未启用",
                "data": None,
                "timestamp": datetime.now().isoformat()
            }), 503
        
        base_url = HIS_WEBAPI_CONFIG.get('base_url')
        meskey = HIS_WEBAPI_CONFIG.get('meskey')
        
        if not base_url or not meskey:
            return jsonify({
                "success": False,
                "code": "HIS_CONFIG_ERROR",
                "message": "HIS WebAPI配置不完整",
                "data": None,
                "timestamp": datetime.now().isoformat()
            }), 503
        
        # 创建HIS适配器实例
        adapter = get_his_webapi_adapter(
            base_url, 
            meskey, 
            HIS_WEBAPI_CONFIG.get('timeout', 30)
        )
        
        use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
        sync_date = datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"开始手动同步 {sync_date} 的数据")
        
        # 连接数据库
        conn = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )
        
        try:
            # 1. 同步号别排班
            schedules_result = adapter.get_all_clinic_schedules(
                clinic_date=sync_date,
                use_encryption=use_encryption
            )
            
            schedules_count = 0
            if schedules_result.get('success'):
                sync_result = adapter.sync_clinic_schedules_to_db(conn, sync_date)
                if sync_result.get('success'):
                    schedules_count = sync_result.get('added', 0) + sync_result.get('updated', 0)
            
            # 2. 同步患者挂号数据
            registrations_count = 0
            schedules = schedules_result.get('schedules', [])
            
            for schedule in schedules:
                clinic_label = schedule.get('CLINIC_LABEL')
                time_desc = schedule.get('TIME_DESC')
                
                if not clinic_label or not time_desc:
                    continue
                
                try:
                    reg_result = adapter.get_patient_registrations(
                        visit_date=sync_date,
                        clinic_label=clinic_label,
                        visit_time_desc=time_desc,
                        use_cache=False,
                        use_encryption=use_encryption
                    )
                    
                    if reg_result.get('success'):
                        registrations = reg_result.get('registrations', [])
                        if registrations:
                            sync_result = adapter.sync_patient_registrations_to_db(
                                conn, sync_date, clinic_label, time_desc
                            )
                            if sync_result.get('success'):
                                registrations_count += len(registrations)
                except Exception as e:
                    logger.warning(f"同步 {clinic_label} {time_desc} 挂号数据失败: {e}")
            
            # 3. 同步患者开单数据
            orders_count = 0
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT DISTINCT visit_no FROM patient_registrations 
                    WHERE visit_date = %s
                """, (sync_date,))
                visit_nos = [row['visit_no'] for row in cursor.fetchall()]
            
            for visit_no in visit_nos:
                try:
                    order_result = adapter.get_patient_orders(
                        visit_date=sync_date,
                        visit_no=visit_no,
                        use_cache=False,
                        use_encryption=use_encryption
                    )
                    
                    if order_result.get('success'):
                        orders = order_result.get('orders', [])
                        if orders:
                            sync_result = adapter.sync_patient_orders_to_db(conn, sync_date, visit_no)
                            if sync_result.get('success'):
                                orders_count += len(orders)
                except Exception as e:
                    pass
            
            conn.commit()
            
            logger.info(f"手动同步完成: 排班{schedules_count}条, 挂号{registrations_count}条, 医嘱{orders_count}条")
            
            return jsonify({
                "success": True,
                "code": "SUCCESS",
                "message": f"同步完成: 排班{schedules_count}条, 挂号{registrations_count}条, 医嘱{orders_count}条",
                "data": {
                    "schedules_count": schedules_count,
                    "registrations_count": registrations_count,
                    "orders_count": orders_count
                },
                "timestamp": datetime.now().isoformat()
            })
            
        finally:
            conn.close()
        
    except Exception as e:
        logger.error(f"手动同步失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({
            "success": False,
            "code": "SYNC_ERROR",
            "message": f"同步失败: {str(e)}",
            "data": None,
            "timestamp": datetime.now().isoformat()
        }), 500

# ============ 错误处理 ============
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "code": "NOT_FOUND",
        "message": "接口不存在",
        "data": None,
        "timestamp": datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({
        "success": False,
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "data": None,
        "timestamp": datetime.now().isoformat()
    }), 500

if __name__ == '__main__':
    # 开发环境直接启动
    app.run(host='0.0.0.0', port=5000, debug=False)
