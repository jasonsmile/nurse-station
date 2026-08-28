#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gunicorn 配置文件
纯内网环境优化
"""

import multiprocessing
import os

# ============ 服务器绑定 ============
# 监听本地地址，通过 Nginx 反向代理访问
bind = "127.0.0.1:5000"

# ============ 工作进程 ============
# 工作进程数 = CPU核心数 * 2 + 1
workers = multiprocessing.cpu_count() * 2 + 1

# 工作模式：sync（同步）适合内网低延迟环境
worker_class = "sync"

# 每个工作进程处理的最大请求数（防止内存泄漏）
max_requests = 10000
max_requests_jitter = 1000

# ============ 超时设置 ============
# 内网环境，超时时间可以设置较短
timeout = 30
keepalive = 2
graceful_timeout = 10

# ============ 日志配置 ============
log_dir = "/opt/nurse-station/logs"
os.makedirs(log_dir, exist_ok=True)

accesslog = f"{log_dir}/gunicorn-access.log"
errorlog = f"{log_dir}/gunicorn-error.log"
loglevel = "info"

# 日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ============ 进程管理 ============
# 进程名称
proc_name = "nurse-station"

# PID 文件
pidfile = f"{log_dir}/gunicorn.pid"

# 后台运行（由 Systemd 管理时设为 False）
daemon = False

# ============ 预加载应用 ============
# 预加载应用，节省内存
preload_app = True

# ============ 安全设置 ============
# 限制请求头大小（防止攻击）
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# ============ 内网优化 ============
# 禁用 sendfile（内网环境可能不需要）
sendfile = False

# 使用 TCP socket（内网环境更稳定）
# unix socket 在 Windows 上不支持，Linux 上可以使用
