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
    
    def _decode_base64(self, encoded_str: str) -> Optional[Dict]:
        """
        BASE64解码
        将BASE64字符串解码为字典
        
        Args:
            encoded_str: BASE64编码的字符串
            
        Returns:
            解码后的字典，失败返回None
        """
        if not encoded_str:
            return None
        
        try:
            decoded = base64.b64decode(encoded_str).decode('utf-8')
            return json.loads(decoded)
        except Exception as e:
            logger.warning(f"BASE64解码失败: {e}")
            return None
    
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
            
            # 外层数据：LIST置为包含空对象的列表，INDATA为加密后的内层数据
            return {
                "MESKEY": self.meskey,
                "MESID": mesid,
                "MESTYPE": service_code,
                "LIST": [{}],  # 包含一个空对象的列表（HIS要求）
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
            
            # 记录原始响应内容用于调试
            raw_text = response.text
            logger.debug(f"HIS原始响应 [{service_code}]: {raw_text[:500]}")
            
            result = response.json()
            
            # 检查响应中是否有加密的DATA字段，如有则解密
            encrypted_data = result.get("DATA")
            if encrypted_data and isinstance(encrypted_data, str):
                try:
                    decrypted_data = self._decode_base64(encrypted_data)
                    if decrypted_data is not None:
                        # 确保result中有MES字段
                        if result.get("MES") is None:
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
    
    def _check_response(self, response: Dict) -> Tuple[bool, str, Optional[Dict]]:
        """
        检查HIS响应状态
        
        Args:
            response: HIS返回的JSON数据
            
        Returns:
            (是否成功, 消息, 数据)
        """
        if not response or not isinstance(response, dict):
            return False, "响应格式错误", None
        
        code = response.get("CODE", "-1")
        message = response.get("MESSAGE", "未知错误")
        data = response.get("MES") or {}
        
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
    
    # ============ G0078 门诊护士获取号别排班 ============
    
    def get_clinic_schedules(
        self,
        clinic_date: str,
        ono: int = 1,
        eno: int = 50,
        use_cache: bool = True,
        use_encryption: bool = False
    ) -> Dict:
        """
        获取门诊号别排班信息（G0078接口）
        
        Args:
            clinic_date: 就诊日期，格式 YYYY-MM-DD
            ono: 开始序号，从1开始
            eno: 结束序号，每次查询eno-ono不可超过50
            use_cache: 是否使用缓存
            use_encryption: 是否使用BASE64加密
            
        Returns:
            {
                "success": True/False,
                "message": "操作结果消息",
                "total_count": 总记录数,
                "schedules": [
                    {
                        "CLINIC_DEPT": "科室编码",
                        "DEPT_NAME": "科室名称",
                        "CLINIC_LABEL": "号别",
                        "TIME_DESC": "午别",
                        "REGISTRATION_LIMITS": 限号数,
                        "REGISTRATION_NUM": 已挂号数,
                        "REGIST_PRICE": 挂号费,
                        "CLINIC_TYPE": "号类",
                        "STATES": "状态",
                        "PNUM": 序号
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
        cache_key = self._get_cache_key('G0078_schedules', clinic_date=clinic_date, ono=ono, eno=eno, encrypted=use_encryption)
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                return cached
        
        # 构建查询参数
        list_params = [{
            "CLINIC_DATE": clinic_date,
            "ONO": str(ono),
            "ENO": str(eno)
        }]
        
        try:
            response = self._request("G0078", list_params, use_encryption=use_encryption)
            success, message, data = self._check_response(response)
            
            if not success:
                logger.error(f"G0078接口返回错误: {message}")
                return {
                    "success": False,
                    "message": message,
                    "total_count": 0,
                    "schedules": []
                }
            
            oudata = data.get("OUDATA", []) if data else []
            
            result = {
                "success": True,
                "message": message,
                "total_count": len(oudata),
                "schedules": oudata
            }
            
            if use_cache:
                self._set_cache(cache_key, result, ttl=300)
            
            return result
            
        except HISAdapterError as e:
            logger.error(f"获取号别排班失败: {e}")
            return {
                "success": False,
                "message": str(e),
                "total_count": 0,
                "schedules": []
            }
    
    def get_all_clinic_schedules(self, clinic_date: str, batch_size: int = 50, use_encryption: bool = False) -> Dict:
        """
        获取所有号别排班信息（自动分页）
        
        Args:
            clinic_date: 就诊日期
            batch_size: 每批次获取数量，最大50
            use_encryption: 是否使用BASE64加密
            
        Returns:
            所有号别排班信息
        """
        all_schedules = []
        ono = 1
        
        while True:
            eno = ono + batch_size - 1
            result = self.get_clinic_schedules(
                clinic_date=clinic_date,
                ono=ono,
                eno=eno,
                use_cache=False,
                use_encryption=use_encryption
            )
            
            if not result.get("success"):
                return result
            
            schedules = result.get("schedules", [])
            all_schedules.extend(schedules)
            
            if len(schedules) < batch_size:
                break
            
            ono += batch_size
        
        return {
            "success": True,
            "message": "获取成功",
            "total_count": len(all_schedules),
            "schedules": all_schedules
        }
    
    # ============ G0079 门诊护士获取挂号信息 ============
    
    def get_patient_registrations(
        self,
        visit_date: str,
        clinic_label: str,
        visit_time_desc: str,
        ono: int = 1,
        eno: int = 50,
        use_cache: bool = True,
        use_encryption: bool = False
    ) -> Dict:
        """
        获取患者挂号信息（G0079接口）
        
        Args:
            visit_date: 就诊日期，格式 YYYY-MM-DD
            clinic_label: 号别
            visit_time_desc: 午别（上午/下午/晚上）
            ono: 开始序号，从1开始
            eno: 结束序号，每次查询eno-ono不可超过50
            use_cache: 是否使用缓存
            use_encryption: 是否使用BASE64加密
            
        Returns:
            {
                "success": True/False,
                "message": "操作结果消息",
                "total_count": 总记录数,
                "registrations": [
                    {
                        "VISIT_DATE": "就诊日期",
                        "VISIT_NO": "就诊号",
                        "VISIT_TIME_DESC": "午别",
                        "PATIENT_ID": "患者ID",
                        "CARD_ID": "卡号",
                        "NAME": "姓名",
                        "SEX": "性别",
                        "AGE": 年龄,
                        "CHARGE_TYPE": "费别",
                        "SERIAL_NO": 就诊序号,
                        "PNUM": 序号
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
        cache_key = self._get_cache_key('G0079_registrations', 
                                       visit_date=visit_date, 
                                       clinic_label=clinic_label,
                                       visit_time_desc=visit_time_desc,
                                       ono=ono, eno=eno, encrypted=use_encryption)
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                return cached
        
        # 构建查询参数
        list_params = [{
            "VISIT_DATE": visit_date,
            "CLINIC_LABEL": clinic_label,
            "VISIT_TIME_DESC": visit_time_desc,
            "ONO": str(ono),
            "ENO": str(eno)
        }]
        
        try:
            response = self._request("G0079", list_params, use_encryption=use_encryption)
            success, message, data = self._check_response(response)
            
            if not success:
                logger.error(f"G0079接口返回错误: {message}")
                return {
                    "success": False,
                    "message": message,
                    "total_count": 0,
                    "registrations": []
                }
            
            oudata = data.get("OUDATA", []) if data else []
            
            result = {
                "success": True,
                "message": message,
                "total_count": len(oudata),
                "registrations": oudata
            }
            
            if use_cache:
                self._set_cache(cache_key, result, ttl=300)
            
            return result
            
        except HISAdapterError as e:
            logger.error(f"获取患者挂号信息失败: {e}")
            return {
                "success": False,
                "message": str(e),
                "total_count": 0,
                "registrations": []
            }
    
    # ============ G0080 门诊护士获取开单信息 ============
    
    def get_patient_orders(
        self,
        visit_date: str,
        visit_no: str,
        ono: int = 1,
        eno: int = 50,
        use_cache: bool = True,
        use_encryption: bool = False
    ) -> Dict:
        """
        获取患者开单信息（G0080接口）
        
        Args:
            visit_date: 就诊日期，格式 YYYY-MM-DD
            visit_no: 就诊号
            ono: 开始序号，从1开始
            eno: 结束序号，每次查询eno-ono不可超过50
            use_cache: 是否使用缓存
            use_encryption: 是否使用BASE64加密
            
        Returns:
            {
                "success": True/False,
                "message": "操作结果消息",
                "total_count": 总记录数,
                "orders": [
                    {
                        "PATIENT_ID": "患者ID",
                        "CARD_ID": "卡号",
                        "PRESC_ATTR": "处方属性",
                        "STATES": "状态",
                        "TEST_NO": "申请单号",
                        "TEMPLATE_NAME": "模板名称",
                        "PRESC_DATE": "处方日期",
                        "PRESC_NO": "处方号",
                        "ITEM_NO": 处方序号,
                        "DIAGNOSES": "诊断",
                        "CLASS_NAME": "项目类别",
                        "ITEM_CODE": "项目编码",
                        "ITEM_NAME": "项目名称",
                        "PACKAGE_SPEC": "包装规格",
                        "PACKAGE_UNITS": "包装单位",
                        "FIRM_ID": "产家",
                        "ADMINISTRATION": "用法",
                        "FREQUENCY": "频次",
                        "QUANTITY": 数量,
                        "PRICE": 单价,
                        "PNUM": 序号
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
        cache_key = self._get_cache_key('G0080_orders',
                                       visit_date=visit_date,
                                       visit_no=visit_no,
                                       ono=ono, eno=eno, encrypted=use_encryption)
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                return cached
        
        # 构建查询参数
        list_params = [{
            "VISIT_DATE": visit_date,
            "VISIT_NO": visit_no,
            "ONO": str(ono),
            "ENO": str(eno)
        }]
        
        try:
            response = self._request("G0080", list_params, use_encryption=use_encryption)
            success, message, data = self._check_response(response)
            
            if not success:
                logger.error(f"G0080接口返回错误: {message}")
                return {
                    "success": False,
                    "message": message,
                    "total_count": 0,
                    "orders": []
                }
            
            oudata = data.get("OUDATA", []) if data else []
            
            result = {
                "success": True,
                "message": message,
                "total_count": len(oudata),
                "orders": oudata
            }
            
            if use_cache:
                self._set_cache(cache_key, result, ttl=300)
            
            return result
            
        except HISAdapterError as e:
            logger.error(f"获取患者开单信息失败: {e}")
            return {
                "success": False,
                "message": str(e),
                "total_count": 0,
                "orders": []
            }
    
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
            # 注意：文档中服务编码写的是 G0012，但示例和实际使用的是 G0076
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
            oudata = data.get("OUDATA", []) if data else []
            
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
    
    def sync_clinic_schedules_to_db(self, db_connection, clinic_date: str) -> Dict:
        """
        将G0078号别排班数据同步到数据库
        
        Args:
            db_connection: 数据库连接对象
            clinic_date: 就诊日期
            
        Returns:
            同步结果
        """
        from datetime import datetime
        
        # 获取所有号别排班
        result = self.get_all_clinic_schedules(clinic_date=clinic_date)
        
        if not result.get("success"):
            return result
        
        schedules = result.get("schedules", [])
        
        try:
            cursor = db_connection.cursor()
            
            # 先标记该日期的所有排班为未更新
            cursor.execute("UPDATE clinic_schedules SET sync_status = 0 WHERE clinic_date = %s", (clinic_date,))
            
            sync_count = 0
            update_count = 0
            
            for schedule in schedules:
                # 生成唯一ID
                schedule_id = f"{schedule.get('CLINIC_DEPT')}_{schedule.get('CLINIC_LABEL')}_{clinic_date}_{schedule.get('TIME_DESC')}"
                
                # 检查是否已存在
                cursor.execute(
                    "SELECT schedule_id FROM clinic_schedules WHERE schedule_id = %s",
                    (schedule_id,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    cursor.execute("""
                        UPDATE clinic_schedules SET
                            dept_name = %s,
                            registration_limits = %s,
                            registration_num = %s,
                            regist_price = %s,
                            clinic_type = %s,
                            states = %s,
                            pnum = %s,
                            sync_status = 1,
                            sync_time = %s,
                            updated_at = %s
                        WHERE schedule_id = %s
                    """, (
                        schedule.get("DEPT_NAME"),
                        schedule.get("REGISTRATION_LIMITS", 0),
                        schedule.get("REGISTRATION_NUM", 0),
                        schedule.get("REGIST_PRICE", 0),
                        schedule.get("CLINIC_TYPE"),
                        schedule.get("STATES"),
                        schedule.get("PNUM", 0),
                        datetime.now(),
                        datetime.now(),
                        schedule_id
                    ))
                    update_count += 1
                else:
                    # 插入新记录
                    cursor.execute("""
                        INSERT INTO clinic_schedules (
                            schedule_id, clinic_date, clinic_dept, dept_name,
                            clinic_label, time_desc, registration_limits,
                            registration_num, regist_price, clinic_type,
                            states, pnum, sync_status, sync_time,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        schedule_id,
                        clinic_date,
                        schedule.get("CLINIC_DEPT"),
                        schedule.get("DEPT_NAME"),
                        schedule.get("CLINIC_LABEL"),
                        schedule.get("TIME_DESC"),
                        schedule.get("REGISTRATION_LIMITS", 0),
                        schedule.get("REGISTRATION_NUM", 0),
                        schedule.get("REGIST_PRICE", 0),
                        schedule.get("CLINIC_TYPE"),
                        schedule.get("STATES"),
                        schedule.get("PNUM", 0),
                        1,
                        datetime.now(),
                        datetime.now(),
                        datetime.now()
                    ))
                    sync_count += 1
            
            # 删除未更新的记录（已不在HIS中的）
            cursor.execute("DELETE FROM clinic_schedules WHERE sync_status = 0 AND clinic_date = %s", (clinic_date,))
            delete_count = cursor.rowcount
            
            db_connection.commit()
            
            return {
                "success": True,
                "message": "同步成功",
                "added": sync_count,
                "updated": update_count,
                "deleted": delete_count,
                "total": len(schedules)
            }
            
        except Exception as e:
            db_connection.rollback()
            logger.error(f"同步号别排班数据到数据库失败: {e}")
            return {
                "success": False,
                "message": f"同步失败: {str(e)}",
                "added": 0,
                "updated": 0,
                "deleted": 0,
                "total": 0
            }
    
    def sync_patient_registrations_to_db(self, db_connection, visit_date: str, clinic_label: str, visit_time_desc: str) -> Dict:
        """
        将G0079患者挂号数据同步到数据库
        
        Args:
            db_connection: 数据库连接对象
            visit_date: 就诊日期
            clinic_label: 号别
            visit_time_desc: 午别
            
        Returns:
            同步结果
        """
        from datetime import datetime
        
        # 获取患者挂号信息
        result = self.get_patient_registrations(
            visit_date=visit_date,
            clinic_label=clinic_label,
            visit_time_desc=visit_time_desc,
            use_cache=False
        )
        
        if not result.get("success"):
            return result
        
        registrations = result.get("registrations", [])
        
        try:
            cursor = db_connection.cursor()
            
            # 先标记该号别的所有挂号为未更新
            cursor.execute("""
                UPDATE patient_registrations SET sync_status = 0 
                WHERE visit_date = %s AND clinic_label = %s AND visit_time_desc = %s
            """, (visit_date, clinic_label, visit_time_desc))
            
            sync_count = 0
            update_count = 0
            
            for reg in registrations:
                # 生成唯一ID
                registration_id = f"{visit_date}_{reg.get('VISIT_NO')}"
                
                # 检查是否已存在
                cursor.execute(
                    "SELECT registration_id FROM patient_registrations WHERE registration_id = %s",
                    (registration_id,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    cursor.execute("""
                        UPDATE patient_registrations SET
                            patient_id = %s,
                            card_id = %s,
                            name = %s,
                            sex = %s,
                            age = %s,
                            charge_type = %s,
                            serial_no = %s,
                            pnum = %s,
                            sync_status = 1,
                            sync_time = %s,
                            updated_at = %s
                        WHERE registration_id = %s
                    """, (
                        reg.get("PATIENT_ID"),
                        reg.get("CARD_ID"),
                        reg.get("NAME"),
                        reg.get("SEX"),
                        reg.get("AGE"),
                        reg.get("CHARGE_TYPE"),
                        reg.get("SERIAL_NO", 0),
                        reg.get("PNUM", 0),
                        datetime.now(),
                        datetime.now(),
                        registration_id
                    ))
                    update_count += 1
                else:
                    # 插入新记录
                    cursor.execute("""
                        INSERT INTO patient_registrations (
                            registration_id, visit_date, visit_no, visit_time_desc,
                            clinic_label, patient_id, card_id, name, sex, age,
                            charge_type, serial_no, pnum, sync_status, sync_time,
                            created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        registration_id,
                        visit_date,
                        reg.get("VISIT_NO"),
                        visit_time_desc,
                        clinic_label,
                        reg.get("PATIENT_ID"),
                        reg.get("CARD_ID"),
                        reg.get("NAME"),
                        reg.get("SEX"),
                        reg.get("AGE"),
                        reg.get("CHARGE_TYPE"),
                        reg.get("SERIAL_NO", 0),
                        reg.get("PNUM", 0),
                        1,
                        datetime.now(),
                        datetime.now(),
                        datetime.now()
                    ))
                    sync_count += 1
            
            # 删除未更新的记录
            cursor.execute("""
                DELETE FROM patient_registrations 
                WHERE sync_status = 0 AND visit_date = %s AND clinic_label = %s AND visit_time_desc = %s
            """, (visit_date, clinic_label, visit_time_desc))
            delete_count = cursor.rowcount
            
            db_connection.commit()
            
            return {
                "success": True,
                "message": "同步成功",
                "added": sync_count,
                "updated": update_count,
                "deleted": delete_count,
                "total": len(registrations)
            }
            
        except Exception as e:
            db_connection.rollback()
            logger.error(f"同步患者挂号数据到数据库失败: {e}")
            return {
                "success": False,
                "message": f"同步失败: {str(e)}",
                "added": 0,
                "updated": 0,
                "deleted": 0,
                "total": 0
            }
    
    def sync_patient_orders_to_db(self, db_connection, visit_date: str, visit_no: str) -> Dict:
        """
        将G0080患者开单数据同步到数据库
        
        Args:
            db_connection: 数据库连接对象
            visit_date: 就诊日期
            visit_no: 就诊号
            
        Returns:
            同步结果
        """
        from datetime import datetime
        
        # 获取患者开单信息
        result = self.get_patient_orders(
            visit_date=visit_date,
            visit_no=visit_no,
            use_cache=False
        )
        
        if not result.get("success"):
            return result
        
        orders = result.get("orders", [])
        
        try:
            cursor = db_connection.cursor()
            
            # 先标记该就诊号的所有开单为未更新
            cursor.execute("""
                UPDATE patient_orders SET sync_status = 0 
                WHERE visit_date = %s AND visit_no = %s
            """, (visit_date, visit_no))
            
            sync_count = 0
            update_count = 0
            
            for order in orders:
                # 生成唯一ID
                order_id = f"{visit_no}_{order.get('PRESC_NO')}_{order.get('ITEM_NO')}"
                
                # 检查是否已存在
                cursor.execute(
                    "SELECT order_id FROM patient_orders WHERE order_id = %s",
                    (order_id,)
                )
                existing = cursor.fetchone()
                
                if existing:
                    # 更新现有记录
                    cursor.execute("""
                        UPDATE patient_orders SET
                            patient_id = %s,
                            card_id = %s,
                            presc_attr = %s,
                            states = %s,
                            test_no = %s,
                            template_name = %s,
                            presc_date = %s,
                            diagnoses = %s,
                            class_name = %s,
                            item_code = %s,
                            item_name = %s,
                            package_spec = %s,
                            package_units = %s,
                            firm_id = %s,
                            administration = %s,
                            frequency = %s,
                            quantity = %s,
                            price = %s,
                            pnum = %s,
                            sync_status = 1,
                            sync_time = %s,
                            updated_at = %s
                        WHERE order_id = %s
                    """, (
                        order.get("PATIENT_ID"),
                        order.get("CARD_ID"),
                        order.get("PRESC_ATTR"),
                        order.get("STATES"),
                        order.get("TEST_NO"),
                        order.get("TEMPLATE_NAME"),
                        order.get("PRESC_DATE"),
                        order.get("DIAGNOSES"),
                        order.get("CLASS_NAME"),
                        order.get("ITEM_CODE"),
                        order.get("ITEM_NAME"),
                        order.get("PACKAGE_SPEC"),
                        order.get("PACKAGE_UNITS"),
                        order.get("FIRM_ID"),
                        order.get("ADMINISTRATION"),
                        order.get("FREQUENCY"),
                        order.get("QUANTITY", 0),
                        order.get("PRICE", 0),
                        order.get("PNUM", 0),
                        datetime.now(),
                        datetime.now(),
                        order_id
                    ))
                    update_count += 1
                else:
                    # 插入新记录
                    cursor.execute("""
                        INSERT INTO patient_orders (
                            order_id, visit_date, visit_no, patient_id, card_id,
                            presc_attr, states, test_no, template_name, presc_date,
                            presc_no, item_no, diagnoses, class_name, item_code,
                            item_name, package_spec, package_units, firm_id,
                            administration, frequency, quantity, price, pnum,
                            sync_status, sync_time, created_at, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        order_id,
                        visit_date,
                        visit_no,
                        order.get("PATIENT_ID"),
                        order.get("CARD_ID"),
                        order.get("PRESC_ATTR"),
                        order.get("STATES"),
                        order.get("TEST_NO"),
                        order.get("TEMPLATE_NAME"),
                        order.get("PRESC_DATE"),
                        order.get("PRESC_NO"),
                        order.get("ITEM_NO", 0),
                        order.get("DIAGNOSES"),
                        order.get("CLASS_NAME"),
                        order.get("ITEM_CODE"),
                        order.get("ITEM_NAME"),
                        order.get("PACKAGE_SPEC"),
                        order.get("PACKAGE_UNITS"),
                        order.get("FIRM_ID"),
                        order.get("ADMINISTRATION"),
                        order.get("FREQUENCY"),
                        order.get("QUANTITY", 0),
                        order.get("PRICE", 0),
                        order.get("PNUM", 0),
                        1,
                        datetime.now(),
                        datetime.now(),
                        datetime.now()
                    ))
                    sync_count += 1
            
            # 删除未更新的记录
            cursor.execute("""
                DELETE FROM patient_orders 
                WHERE sync_status = 0 AND visit_date = %s AND visit_no = %s
            """, (visit_date, visit_no))
            delete_count = cursor.rowcount
            
            db_connection.commit()
            
            return {
                "success": True,
                "message": "同步成功",
                "added": sync_count,
                "updated": update_count,
                "deleted": delete_count,
                "total": len(orders)
            }
            
        except Exception as e:
            db_connection.rollback()
            logger.error(f"同步患者开单数据到数据库失败: {e}")
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
