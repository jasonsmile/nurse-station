#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立定时同步任务进程
用于替代gunicorn内置的定时任务调度器
"""

import sys
import os
import time
import logging
from datetime import datetime, timedelta

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 配置日志
log_dir = os.path.join(current_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'{log_dir}/scheduler.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def get_db_connection():
    """获取数据库连接"""
    from config import DB_CONFIG
    import pymysql
    return pymysql.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password'],
        database=DB_CONFIG['database'],
        charset=DB_CONFIG['charset'],
        cursorclass=pymysql.cursors.DictCursor
    )


def sync_all_data():
    """执行全量数据同步"""
    try:
        from his_webapi_adapter import get_his_webapi_adapter
        from config import HIS_WEBAPI_CONFIG
        
        # 检查HIS配置
        if not HIS_WEBAPI_CONFIG.get('enabled'):
            logger.warning("HIS WebAPI未启用，跳过同步")
            return False
        
        base_url = HIS_WEBAPI_CONFIG.get('base_url')
        meskey = HIS_WEBAPI_CONFIG.get('meskey')
        
        if not base_url or not meskey:
            logger.error("HIS WebAPI配置不完整")
            return False
        
        # 创建HIS适配器实例
        adapter = get_his_webapi_adapter(
            base_url, 
            meskey, 
            HIS_WEBAPI_CONFIG.get('timeout', 30)
        )
        
        use_encryption = HIS_WEBAPI_CONFIG.get('use_encryption', False)
        sync_date = datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"开始同步 {sync_date} 的数据")
        
        conn = get_db_connection()
        
        try:
            # 1. 同步号别排班 (G0078)
            logger.info("同步号别排班数据...")
            schedules_result = adapter.get_all_clinic_schedules(
                clinic_date=sync_date,
                use_encryption=use_encryption
            )
            
            if schedules_result.get('success'):
                sync_result = adapter.sync_clinic_schedules_to_db(conn, sync_date)
                if sync_result.get('success'):
                    logger.info(f"号别排班同步完成: 新增{sync_result.get('added', 0)}条, 更新{sync_result.get('updated', 0)}条")
                else:
                    logger.warning(f"号别排班同步失败: {sync_result.get('message')}")
            else:
                logger.warning(f"获取号别排班失败: {schedules_result.get('message')}")
            
            # 2. 同步患者挂号数据 (G0079) - 按号别循环同步
            logger.info("同步患者挂号数据...")
            schedules = schedules_result.get('schedules', [])
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
                                logger.info(f"  {clinic_label} {time_desc}: {len(registrations)}条")
                            else:
                                logger.warning(f"  {clinic_label} {time_desc} 同步失败: {sync_result.get('message')}")
                except Exception as e:
                    logger.error(f"  同步 {clinic_label} {time_desc} 挂号数据失败: {e}")
            
            logger.info(f"患者挂号数据同步完成，共 {total_registrations} 条")
            
            # 3. 同步患者开单数据 (G0080) - 按就诊号循环同步
            logger.info("同步患者开单数据...")
            total_orders = 0
            
            # 从数据库获取今天的所有就诊号
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
                                total_orders += len(orders)
                except Exception as e:
                    logger.error(f"  同步就诊号 {visit_no} 开单数据失败: {e}")
            
            logger.info(f"患者开单数据同步完成，共 {total_orders} 条")
            
            conn.commit()
            logger.info(f"数据同步完成: 排班{len(schedules)}条, 挂号{total_registrations}条, 医嘱{total_orders}条")
            return True
            
        finally:
            conn.close()
        
    except Exception as e:
        logger.error(f"数据同步失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("独立定时同步任务进程启动")
    logger.info("=" * 50)
    
    # 从配置读取同步时间
    sync_hour = int(os.getenv('SYNC_HOUR', 6))
    sync_minute = int(os.getenv('SYNC_MINUTE', 0))
    
    logger.info(f"定时同步时间: 每天 {sync_hour:02d}:{sync_minute:02d}")
    
    # 启动时立即执行一次同步
    logger.info("启动时执行一次同步...")
    sync_all_data()
    
    # 定时循环
    while True:
        try:
            now = datetime.now()
            
            # 计算下次同步时间
            next_sync = now.replace(hour=sync_hour, minute=sync_minute, second=0, microsecond=0)
            if next_sync <= now:
                # 如果今天的时间已过，则设置为明天
                next_sync += timedelta(days=1)
            
            # 计算等待时间
            wait_seconds = (next_sync - now).total_seconds()
            wait_hours = wait_seconds / 3600
            
            logger.info(f"下次同步时间: {next_sync.strftime('%Y-%m-%d %H:%M:%S')} (距今 {wait_hours:.1f} 小时)")
            
            # 等待到下次同步时间
            time.sleep(wait_seconds)
            
            # 执行同步
            logger.info("到达定时同步时间，开始执行同步...")
            sync_all_data()
            
        except KeyboardInterrupt:
            logger.info("接收到中断信号，正在退出...")
            break
        except Exception as e:
            logger.error(f"定时任务执行异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 发生异常后等待1小时再继续
            time.sleep(3600)
    
    logger.info("独立定时同步任务进程已停止")


if __name__ == '__main__':
    main()
