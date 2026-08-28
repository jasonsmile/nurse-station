#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
初始化同步脚本
启动时从HIS同步医生数据到本地数据库
"""

import os
import sys
import logging
from datetime import datetime

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from his_webapi_adapter import get_his_webapi_adapter, HISAdapterError
from config import HIS_WEBAPI_CONFIG, DB_CONFIG
import pymysql


def init_database_connection():
    """初始化数据库连接"""
    try:
        conn = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn
    except Exception as e:
        logger.error(f"数据库连接失败: {e}")
        return None


def sync_doctors():
    """同步医生数据"""
    print("=" * 60)
    print("CVOnto 护士站 - HIS医生数据初始化同步")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 检查HIS配置
    if not HIS_WEBAPI_CONFIG.get('enabled'):
        print("✗ HIS WebAPI未启用，跳过同步")
        print("  如需启用，请设置 HIS_WEBAPI_ENABLED=true")
        return False
    
    base_url = HIS_WEBAPI_CONFIG.get('base_url')
    meskey = HIS_WEBAPI_CONFIG.get('meskey')
    
    if not base_url or not meskey:
        print("✗ HIS WebAPI配置不完整")
        print(f"  BASE_URL: {'已配置' if base_url else '未配置'}")
        print(f"  MESKEY: {'已配置' if meskey else '未配置'}")
        return False
    
    use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
    
    print(f"HIS配置:")
    print(f"  BASE_URL: {base_url}")
    print(f"  MESKEY: {meskey[:10]}...")
    print(f"  USE_ENCRYPTION: {use_encryption}")
    print()
    
    # 连接数据库
    print("连接数据库...")
    conn = init_database_connection()
    if not conn:
        print("✗ 数据库连接失败")
        return False
    print("✓ 数据库连接成功")
    print()
    
    try:
        # 初始化适配器
        print("初始化HIS适配器...")
        adapter = get_his_webapi_adapter(
            base_url, 
            meskey, 
            HIS_WEBAPI_CONFIG.get('timeout', 30)
        )
        print("✓ HIS适配器初始化成功")
        print()
        
        # 健康检查
        print("检查HIS接口连通性...")
        health = adapter.health_check()
        if not health.get('success'):
            print(f"✗ HIS接口连接失败: {health.get('message')}")
            return False
        print(f"✓ HIS接口连接正常")
        print()
        
        # 获取医生数据
        print("从HIS获取医生数据...")
        his_result = adapter.get_all_doctors(use_encryption=use_encryption)
        
        if not his_result.get('success'):
            print(f"✗ 获取医生数据失败: {his_result.get('message')}")
            return False
        
        doctors = his_result.get('doctors', [])
        print(f"✓ 获取成功，共 {len(doctors)} 条医生记录")
        print()
        
        # 同步到数据库
        print("同步数据到本地数据库...")
        sync_result = adapter.sync_doctors_to_db(conn)
        
        if not sync_result.get('success'):
            print(f"✗ 同步失败: {sync_result.get('message')}")
            return False
        
        print("✓ 同步成功!")
        print()
        print("同步统计:")
        print(f"  新增: {sync_result.get('added', 0)} 条")
        print(f"  更新: {sync_result.get('updated', 0)} 条")
        print(f"  删除: {sync_result.get('deleted', 0)} 条")
        print(f"  总计: {sync_result.get('total', 0)} 条")
        print()
        
        # 显示部分医生信息
        if doctors:
            print("医生列表预览 (前5条):")
            print("-" * 60)
            for i, doc in enumerate(doctors[:5], 1):
                print(f"{i}. {doc.get('NAME', 'N/A')} ({doc.get('TITLE', 'N/A')}) - {doc.get('DEPT_NAME', 'N/A')}")
        
        return True
        
    except HISAdapterError as e:
        print(f"✗ HIS接口错误: {e}")
        return False
    except Exception as e:
        print(f"✗ 同步过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()
        print()
        print("=" * 60)


def main():
    """主函数"""
    success = sync_doctors()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
