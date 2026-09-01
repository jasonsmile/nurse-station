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
from config import APP_CONFIG

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 配置日志
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
app.secret_key = APP_CONFIG['secret_key']
# 纯内网环境，允许所有来源（或指定内网IP段）
CORS(app, resources={r"/api/*": {"origins": "*"}})

# 配置
app.config['JSON_AS_ASCII'] = False
app.config['JSON_SORT_KEYS'] = False

# 导入并注册路由
from routes import api_bp
from auth import auth_bp

app.register_blueprint(api_bp)
app.register_blueprint(auth_bp)


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
    app.run(host='0.0.0.0', port=5000, debug=False)
