#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
立即同步数据脚本
用于手动触发全量数据同步
"""

import sys
import os

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """主函数"""
    print("=" * 60)
    print("CVOnto 护士站 - 手动数据同步")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        from his_webapi_adapter import get_his_webapi_adapter
        from config import HIS_WEBAPI_CONFIG, DB_CONFIG
        import pymysql
        
        # 检查HIS配置
        if not HIS_WEBAPI_CONFIG.get('enabled'):
            print("✗ HIS WebAPI未启用")
            print("  请设置环境变量 HIS_WEBAPI_ENABLED=true")
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
        conn = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset'],
            cursorclass=pymysql.cursors.DictCursor
        )
        print("✓ 数据库连接成功")
        print()
        
        # 创建HIS适配器
        print("初始化HIS适配器...")
        adapter = get_his_webapi_adapter(
            base_url, 
            meskey, 
            HIS_WEBAPI_CONFIG.get('timeout', 30)
        )
        print("✓ HIS适配器初始化成功")
        print()
        
        sync_date = datetime.now().strftime('%Y-%m-%d')
        
        # 1. 同步号别排班
        print(f"同步 {sync_date} 号别排班数据...")
        schedules_result = adapter.get_all_clinic_schedules(
            clinic_date=sync_date,
            use_encryption=use_encryption
        )
        
        if not schedules_result.get('success'):
            print(f"✗ 获取号别排班失败: {schedules_result.get('message')}")
            return False
        
        schedules = schedules_result.get('schedules', [])
        print(f"✓ 获取到 {len(schedules)} 条号别排班记录")
        
        sync_result = adapter.sync_clinic_schedules_to_db(conn, sync_date)
        if sync_result.get('success'):
            print(f"✓ 号别排班同步完成: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
        else:
            print(f"✗ 号别排班同步失败: {sync_result.get('message')}")
        print()
        
        # 2. 同步患者挂号数据
        print("同步患者挂号数据...")
        total_registrations = 0
        
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
                            total_registrations += len(registrations)
                            print(f"  {clinic_label} {time_desc}: {len(registrations)}条")
            except Exception as e:
                print(f"  {clinic_label} {time_desc} 同步失败: {e}")
        
        print(f"✓ 患者挂号数据同步完成，共 {total_registrations} 条")
        print()
        
        # 3. 同步患者开单数据
        print("同步患者开单数据...")
        total_orders = 0
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT visit_no FROM patient_registrations 
                WHERE visit_date = %s
            """, (sync_date,))
            visit_nos = [row['visit_no'] for row in cursor.fetchall()]
        
        print(f"  共 {len(visit_nos)} 个就诊号需要同步")
        
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
                            total_orders += len(orders)
            except Exception as e:
                pass  # 静默处理，避免输出过多
        
        print(f"✓ 患者开单数据同步完成，共 {total_orders} 条")
        print()
        
        conn.commit()
        conn.close()
        
        print("=" * 60)
        print("同步完成!")
        print(f"  号别排班: {len(schedules)} 条")
        print(f"  患者挂号: {total_registrations} 条")
        print(f"  患者开单: {total_orders} 条")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"✗ 同步失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    input("\n按回车键退出...")
    sys.exit(0 if success else 1)
