#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件
纯内网环境配置
"""

import os

# ============ MySQL 配置 ============
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'nurse'),
    'password': os.getenv('DB_PASSWORD', 'NursePass123!'),
    'database': os.getenv('DB_NAME', 'cvonto_nurse_station'),
    'charset': 'utf8mb4',
    'cursorclass': 'DictCursor'
}

# ============ Redis 配置（可选） ============
REDIS_CONFIG = {
    'host': os.getenv('REDIS_HOST', 'localhost'),
    'port': int(os.getenv('REDIS_PORT', 6379)),
    'db': int(os.getenv('REDIS_DB', 0)),
    'password': os.getenv('REDIS_PASSWORD', None),
    'enabled': os.getenv('REDIS_ENABLED', 'false').lower() == 'true'
}

# ============ HIS 接口配置 ============
HIS_CONFIG = {
    'base_url': os.getenv('HIS_BASE_URL', 'http://his-server/api/v1'),
    'timeout': int(os.getenv('HIS_TIMEOUT', 30)),
    'token': os.getenv('HIS_TOKEN', ''),
    'enabled': os.getenv('HIS_ENABLED', 'false').lower() == 'true'
}

# ============ HIS WebAPI 配置 (G0076等接口) ============
HIS_WEBAPI_CONFIG = {
    'base_url': os.getenv('HIS_WEBAPI_BASE_URL', ''),  # 如: http://IP:端口号
    'meskey': os.getenv('HIS_WEBAPI_MESKEY', ''),  # HIS提供的用户唯一ID
    'timeout': int(os.getenv('HIS_WEBAPI_TIMEOUT', 30)),
    'enabled': os.getenv('HIS_WEBAPI_ENABLED', 'false').lower() == 'true',
    'use_encryption': os.getenv('HIS_WEBAPI_USE_ENCRYPTION', 'false').lower() == 'true'  # 是否使用BASE64加密
}

# ============ 叫号系统配置 ============
QUEUE_CONFIG = {
    'callback_secret': os.getenv('QUEUE_CALLBACK_SECRET', 'your-secret-key'),
    'sign_verify': os.getenv('QUEUE_SIGN_VERIFY', 'false').lower() == 'true'
}

# ============ 应用配置 ============
APP_CONFIG = {
    'debug': os.getenv('APP_DEBUG', 'false').lower() == 'true',
    'port': int(os.getenv('APP_PORT', 5000)),
    'host': os.getenv('APP_HOST', '0.0.0.0'),
    'secret_key': os.getenv('SECRET_KEY', 'intranet-secret-key'),
    'intranet_mode': True  # 纯内网模式标志
}

# ============ 扫码设备配置 ============
SCANNER_CONFIG = {
    # 条码扫描枪配置
    'barcode_prefix': os.getenv('BARCODE_PREFIX', ''),  # 条码前缀过滤
    'barcode_length': int(os.getenv('BARCODE_LENGTH', 0)),  # 条码长度验证，0表示不验证
    'auto_submit': os.getenv('SCANNER_AUTO_SUBMIT', 'true').lower() == 'true',  # 扫描后自动提交
}
