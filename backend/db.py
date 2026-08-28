#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接管理
"""

import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
import logging
from config import DB_CONFIG

logger = logging.getLogger(__name__)

class Database:
    """数据库连接池管理"""
    
    def __init__(self):
        self.config = DB_CONFIG
    
    def get_connection(self):
        """获取数据库连接"""
        try:
            conn = pymysql.connect(
                host=self.config['host'],
                port=self.config['port'],
                user=self.config['user'],
                password=self.config['password'],
                database=self.config['database'],
                charset=self.config['charset'],
                cursorclass=DictCursor,
                autocommit=False
            )
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
    
    @contextmanager
    def get_cursor(self):
        """上下文管理器获取游标"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database transaction error: {e}")
            raise
        finally:
            cursor.close()
            conn.close()
    
    def execute_one(self, sql, params=None):
        """执行单条查询，返回一条结果"""
        with self.get_cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchone()
    
    def execute_many(self, sql, params=None):
        """执行查询，返回多条结果"""
        with self.get_cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    
    def execute_insert(self, sql, params=None):
        """执行插入，返回最后插入的ID"""
        with self.get_cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.lastrowid
    
    def execute_update(self, sql, params=None):
        """执行更新，返回影响的行数"""
        with self.get_cursor() as cursor:
            return cursor.execute(sql, params or ())

# 全局数据库实例
db = Database()
