#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HIS WebAPI 适配层 - G0076接口专用
负责与HIS系统的G0076接口通信，获取医生信息
"""

import requests
import json
import logging
import base64
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import threading
import time

logger = logging.getLogger(__name__)


class HISWebAPIAdapter:
    """HIS WebAPI适配器 - 用于对接HIS的G0076等接口"""
    
    def __init__(self, base_url: str, meskey: str, timeout: int = 30):
        """
        初始化HIS WebAPI适配器
        
        Args:
            base_url: HIS服务基础URL，如 http://IP:端口号
            meskey: HIS提供的用户唯一ID
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip('/')
        self.meskey = meskey
        self.timeout = timeout
        self.session = requests.Session()
        
        # 设置请求头
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # 缓存
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = 300  # 默认缓存5分钟
        
        logger.info(f"HIS WebAPI适配器初始化完成，目标: {base_url}")
    
    def _generate_mesid(self) -> str:
        """
        生成消息ID
        格式: yyyymmddhh24missff6 (年月日时分秒微秒)
        
        Returns:
            消息ID字符串
        """
        now = datetime.now()
        # 格式: 年月日时分秒 + 6位微秒
        return now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond:06d}"
    
    def _encode_base64(self, data: Dict) -> str:
        """
        BASE64编码
        将字典编码为BASE64字符串
        
        Args:
            data: 待编码的字典
            
        Returns:
            BASE64编码后的字符串
        """
        # 使用indent=4和\r\n换行符，与HIS示例格式一致
        json_str = json.dumps(data, ensure_ascii=False, indent=4, separators=(',', ': '))
        # 确保使用Windows风格换行符(\r\n)
        json_str = json_str.replace('\n', '\r\n')
        encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        return encoded
    
    def _decode_base64(self, encoded_str: str) -> Dict:
        """
        BASE64解码
        将BASE64字符串解码为字典
        
        Args:
            encoded_str: BASE64编码的字符串
            
        Returns:
            解码后的字典
        """
        if not encoded_str:
            return {}
        
        try:
            decoded = base64.b64decode(encoded_str).decode('utf-8')
            return json.loads(decoded)
        except Exception as e:
            logger.warning(f"BASE64解码失败: {e}")
            return {}
    
    def _build_request_payload(self, service_code: str, list_params: List[Dict], use_encryption: bool = False) -> Dict:
        """
        构建请求消息体
        
        Args:
            service_code: 服务编码，如 G0076
            list_params: 查询条件集合
            use_encryption: 是否使用BASE64加密（INDATA方式）
            
        Returns:
            请求消息体字典
        """
        mesid = self._generate_mesid()
        
        if use_encryption:
            # 使用BASE64加密方式（INDATA）
            # 内层数据：完整的请求体
            inner_data = {
                "MESKEY": self.meskey,
                "MESID": mesid,
                "MESTYPE": service_code,
                "LIST": list_params,
                "INDATA": ""
            }
            
            # 外层数据：LIST置为空对象，INDATA为加密后的内层数据
            return {
                "MESKEY": self.meskey,
                "MESID": mesid,
                "MESTYPE": service_code,
                "LIST": [{}],  # 空对象
                "INDATA": self._encode_base64(inner_data)
            }
        else:
            # 不使用加密（明文方式）
            return {
                "MESKEY": self.meskey,
                "MESID": mesid,
                "MESTYPE": service_code,
                "LIST": list_params,
                "INDATA": ""
            }
    
    def _request(self, service_code: str, list_params: List[Dict], use_encryption: bool = False) -> Dict:
        """
        发送HTTP请求到HIS接口
        
        Args:
            service_code: 服务编码
            list_params: 查询条件集合
            use_encryption: 是否使用BASE64加密
            
        Returns:
            解析后的JSON响应（自动解密DATA字段）
        """
        url = f"{self.base_url}/api/HisInterface/HisRequst"
        payload = self._build_request_payload(service_code, list_params, use_encryption)
        
        logger.debug(f"HIS请求 [{service_code}]: {json.dumps(payload, ensure_ascii=False)}")
        
        try:
            response = self.session.post(
                url=url,
                headers=self.headers,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            
            # 检查响应中是否有加密的DATA字段，如有则解密
            encrypted_data = result.get("DATA")
            if encrypted_data and isinstance(encrypted_data, str):
                try:
                    decrypted_data = self._decode_base64(encrypted_data)
                    if decrypted_data:
                        # 解密后的数据格式: {"OUDATA": [...]}
                        if "MES" not in result:
                            result["MES"] = {}
                        # 将解密后的OUDATA放入MES
                        if isinstance(decrypted_data, dict) and "OUDATA" in decrypted_data:
                            result["MES"]["OUDATA"] = decrypted_data["OUDATA"]
                        elif isinstance(decrypted_data, list):
                            result["MES"]["OUDATA"] = decrypted_data
                        elif isinstance(decrypted_data, dict):
                            result["MES"]["OUDATA"] = [decrypted_data]
                        logger.debug(f"DATA字段解密成功")
                except Exception as e:
                    logger.warning(f"DATA字段解密失败: {e}")
            
            logger.debug(f"HIS响应 [{service_code}]: {json.dumps(result, ensure_ascii=False)}")
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"HIS请求超时: {url}")
            raise HISConnectionError("HIS服务连接超时")
        except requests.exceptions.ConnectionError:
            logger.error(f"HIS连接失败: {url}")
            raise HISConnectionError("无法连接到HIS服务")
        except json.JSONDecodeError as e:
            logger.error(f"HIS响应解析失败: {e}")
            raise HISResponseError("HIS响应格式错误")
        except Exception as e:
            logger.error(f"HIS请求异常: {str(e)}")
            raise HISAdapterError(f"HIS请求失败: {str(e)}")
    
    def _check_response(self, response: Dict) -> Tuple[bool, str, Dict]:
        """
        检查HIS响应状态
        
        Args:
            response: HIS返回的JSON数据
            
        Returns:
            (是否成功, 消息, 数据)
        """
        code = response.get("CODE", "-1")
        message = response.get("MESSAGE", "未知错误")
        data = response.get("MES", {})
        
        if code == "1":
            return True, message, data
        else:
            return False, message, data
    
    # ============ 缓存管理 ============
    
    def _get_cache_key(self, prefix: str, **params) -> str:
        """生成缓存键"""
        sorted_params = sorted(params.items())
        param_str = '&'.join([f"{k}={v}" for k, v in sorted_params])
        return f"{prefix}:{param_str}"
    
    def _get_cached(self, key: str) -> Optional[Dict]:
        """获取缓存数据"""
        with self._cache_lock:
            if key in self._cache:
                data, expire_time = self._cache[key]
                if datetime.now() < expire_time:
                    logger.debug(f"缓存命中: {key}")
                    return data
                else:
                    del self._cache[key]
        return None
    
    def _set_cache(self, key: str, data: Dict, ttl: int = None):
        """设置缓存数据"""
        ttl = ttl or self._cache_ttl
        with self._cache_lock:
            self._cache[key] = (data, datetime.now() + __import__('datetime').timedelta(seconds=ttl))
    
    def clear_cache(self):
        """清除所有缓存"""
        with self._cache_lock:
            self._cache.clear()
        logger.info("HIS缓存已清除")
    
    # ============ G0076 门诊护士获取医生信息 ============
    
    def get_doctors(
        self, 
        ono: int = 1, 
        eno: int = 50,
        use_cache: bool = True,
        use_encryption: bool = False
    ) -> Dict:
        """
        获取医生信息（G0076接口）
        
        Args:
            ono: 开始序号，从1开始
            eno: 结束序号，每次查询eno-ono不可超过50
            use_cache: 是否使用缓存
            use_encryption: 是否使用BASE64加密（INDATA方式）
            
        Returns:
            {
                "success": True/False,
                "message": "操作结果消息",
                "total_count": 总记录数,
                "doctors": [
                    {
                        "DOCTOR_ID": "医生唯一ID",
                        "DOCTOR_CODE": "医生工号",
                        "NAME": "姓名",
                        "TITLE": "职称",
                        "TITLE_CODE": "职称编码",
                        "SPECIALTY": "专长",
                        "ROOM": "诊室",
                        "ROOM_CODE": "诊室编码",
                        "DEPT_CODE": "所属科室编码",
                        "DEPT_NAME": "所属科室名称",
                        "PHONE": "联系电话",
                        "STATUS": "出诊状态",
                        "ITEMNO": 序号
                    }
                ]
            }
        """
        # 参数校验
        if eno - ono > 50:
            raise ValueError("每次查询范围不可超过50条记录")
        
        if ono < 1:
            raise ValueError("开始序号必须大于等于1")
        
        # 缓存检查
        cache_key = self._get_cache_key('G0076_doctors', ono=ono, eno=eno, encrypted=use_encryption)
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                return cached
        
        # 构建查询参数
        list_params = [{
            "ONO": str(ono),
            "ENO": str(eno)
        }]
        
        try:
            # 发送请求（根据use_encryption决定是否加密）
            response = self._request("G0076", list_params, use_encryption=use_encryption)
            
            # 检查响应
            success, message, data = self._check_response(response)
            
            if not success:
                logger.error(f"G0076接口返回错误: {message}")
                return {
                    "success": False,
                    "message": message,
                    "total_count": 0,
                    "doctors": []
                }
            
            # 提取医生数据
            oudata = data.get("OUDATA", [])
            
            result = {
                "success": True,
                "message": message,
                "total_count": len(oudata),
                "doctors": oudata
            }
            
            # 缓存结果
            if use_cache:
                self._set_cache(cache_key, result, ttl=300)  # 缓存5分钟
            
            return result
            
        except HISAdapterError as e:
            logger.error(f"获取医生信息失败: {e}")
            return {
                "success": False,
                "message": str(e),
                "total_count": 0,
                "doctors": []
            }
    
    def get_all_doctors(self, batch_size: int = 50, use_encryption: bool = False) -> Dict:
        """
        获取所有医生信息（自动分页）
        
        Args:
            batch_size: 每批次获取数量，最大50
            use_encryption: 是否使用BASE64加密
            
        Returns:
            {
                "success": True/False,
                "message": "操作结果消息",
                "total_count": 总记录数,
                "doctors": [...]
            }
        """
        all_doctors = []
        ono = 1
        
        while True:
            eno = ono + batch_size - 1
            result = self.get_doctors(ono=ono, eno=eno, use_cache=False, use_encryption=use_encryption)
            
            if not result.get("success"):
                return result
            
            doctors = result.get("doctors", [])
            all_doctors.extend(doctors)
            
            # 如果返回数量小于批次大小，说明已经取完
            if len(doctors) < batch_size:
                break
            
            ono += batch_size
        
        return {
            "success": True,
            "message": "获取成功",
            "total_count": len(all_doctors),
            "doctors": all_doctors
        }
    
    def get_doctors_by_dept(self, dept_code: str = None, dept_name: str = None, use_encryption: bool = False) -> Dict:
        """
        根据科室筛选医生
        
        Args:
            dept_code: 科室编码
            dept_name: 科室名称
            use_encryption: 是否使用BASE64加密
            
        Returns:
            筛选后的医生列表
        """
        result = self.get_all_doctors(use_encryption=use_encryption)
        
        if not result.get("success"):
            return result
        
        doctors = result.get("doctors", [])
        
        # 筛选
        filtered = []
        for doc in doctors:
            if dept_code and doc.get("DEPT_CODE") == dept_code:
                filtered.append(doc)
            elif dept_name and dept_name in (doc.get("DEPT_NAME") or ""):
                filtered.append(doc)
            elif not dept_code and not dept_name:
                filtered.append(doc)
        
        return {
            "success": True,
            "message": "筛选成功",
            "total_count": len(filtered),
            "doctors": filtered
        }
    
    def sync_doctors_to_db(self, db_connection) -> Dict:
        """
        将HIS医生信息同步到本地数据库
        
        Args:
            db_connection: 数据库连接对象
            
        Returns:
            同步结果
        """
        from datetime import datetime
        
        # 获取所有医生
        result = self.get_all_doctors()
        
        if not result.get("success"):
            return result
        
        doctors = result.get("doctors", [])
        
        try:
            cursor = db_connection.cursor()
            
            # 先标记所有医生为未更新
            cursor.execute("UPDATE doctors SET sync_status = 0")
            
            sync_count = 0
            update_count = 0
            
            for doc in doctors:
                doctor_id = doc.get("DOCTOR_ID")
                
                # 检查医生是否已存在
                cursor.execute(
                    "SELECT doctor_id FROM doctors WHERE doctor_id = %s",
                    (doctor_id,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有医生
                    cursor.execute("""
                        UPDATE doctors SET
                            doctor_code = %s,
                            name = %s,
                            title = %s,
                            title_code = %s,
                            specialty = %s,
                            room = %s,
                            room_code = %s,
                            dept_code = %s,
                            dept_name = %s,
                            phone = %s,
                            work_status = %s,
                            sync_status = 1,
                            updated_at = %s
                        WHERE doctor_id = %s
                    """, (
                        doc.get("DOCTOR_CODE"),
                        doc.get("NAME"),
                        doc.get("TITLE"),
                        doc.get("TITLE_CODE"),
                        doc.get("SPECIALTY"),
                        doc.get("ROOM"),
                        doc.get("ROOM_CODE"),
                        doc.get("DEPT_CODE"),
                        doc.get("DEPT_NAME"),
                        doc.get("PHONE"),
                        doc.get("STATUS"),
                        datetime.now(),
                        doctor_id
                    ))
                    update_count += 1
                else:
                    # 插入新医生
                    cursor.execute("""
                        INSERT INTO doctors (
                            doctor_id, doctor_code, name, title, title_code,
                            specialty, room, room_code, dept_code, dept_name,
                            phone, work_status, status, sort_order, sync_status,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        doctor_id,
                        doc.get("DOCTOR_CODE"),
                        doc.get("NAME"),
                        doc.get("TITLE"),
                        doc.get("TITLE_CODE"),
                        doc.get("SPECIALTY"),
                        doc.get("ROOM"),
                        doc.get("ROOM_CODE"),
                        doc.get("DEPT_CODE"),
                        doc.get("DEPT_NAME"),
                        doc.get("PHONE"),
                        doc.get("STATUS"),
                        1,  # status
                        doc.get("ITEMNO", 0),  # sort_order
                        1,  # sync_status
                        datetime.now(),
                        datetime.now()
                    ))
                    sync_count += 1
            
            # 删除未更新的医生（已不在HIS中的）
            cursor.execute("DELETE FROM doctors WHERE sync_status = 0")
            delete_count = cursor.rowcount
            
            db_connection.commit()
            
            return {
                "success": True,
                "message": "同步成功",
                "added": sync_count,
                "updated": update_count,
                "deleted": delete_count,
                "total": len(doctors)
            }
            
        except Exception as e:
            db_connection.rollback()
            logger.error(f"同步医生数据到数据库失败: {e}")
            return {
                "success": False,
                "message": f"同步失败: {str(e)}",
                "added": 0,
                "updated": 0,
                "deleted": 0,
                "total": 0
            }
    
    def health_check(self) -> Dict:
        """
        健康检查 - 测试G0076接口连通性
        
        Returns:
            健康状态
        """
        try:
            # 尝试获取第一条医生记录
            result = self.get_doctors(ono=1, eno=1, use_cache=False)
            
            if result.get("success"):
                return {
                    "success": True,
                    "status": "connected",
                    "message": "HIS接口连接正常",
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "status": "error",
                    "message": result.get("message", "HIS接口返回错误"),
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            return {
                "success": False,
                "status": "disconnected",
                "message": f"HIS接口连接失败: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }


# ============ 异常类 ============

class HISAdapterError(Exception):
    """HIS适配器基础异常"""
    pass


class HISConnectionError(HISAdapterError):
    """HIS连接异常"""
    pass


class HISResponseError(HISAdapterError):
    """HIS响应异常"""
    pass


# ============ 单例模式 ============

_his_webapi_adapter = None

def get_his_webapi_adapter(base_url: str = None, meskey: str = None, timeout: int = 30) -> HISWebAPIAdapter:
    """
    获取HIS WebAPI适配器实例（单例）
    
    Args:
        base_url: HIS服务地址
        meskey: HIS用户ID
        timeout: 超时时间
        
    Returns:
        HISWebAPIAdapter实例
    """
    global _his_webapi_adapter
    if _his_webapi_adapter is None and base_url and meskey:
        _his_webapi_adapter = HISWebAPIAdapter(base_url, meskey, timeout)
    return _his_webapi_adapter


def reset_his_webapi_adapter():
    """重置HIS WebAPI适配器（用于切换环境）"""
    global _his_webapi_adapter
    _his_webapi_adapter = None
