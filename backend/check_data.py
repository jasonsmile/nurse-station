#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查数据库中的挂号数据"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import db

with db.get_cursor() as cursor:
    # 查看今天的数据
    cursor.execute("SELECT visit_date, clinic_label, visit_time_desc, COUNT(*) as cnt FROM patient_registrations WHERE visit_date = CURDATE() GROUP BY visit_date, clinic_label, visit_time_desc")
    rows = cursor.fetchall()
    print("=== 今天的挂号数据 ===")
    for r in rows:
        print("  {} | {} | {} | {}条".format(r["visit_date"], r["clinic_label"], r["visit_time_desc"], r["cnt"]))
    if not rows:
        print("  (无数据)")

    # 查看所有数据
    cursor.execute("SELECT visit_date, clinic_label, visit_time_desc, COUNT(*) as cnt FROM patient_registrations GROUP BY visit_date, clinic_label, visit_time_desc ORDER BY visit_date DESC LIMIT 20")
    rows = cursor.fetchall()
    print()
    print("=== 所有挂号数据(最近20条) ===")
    for r in rows:
        print("  {} | {} | {} | {}条".format(r["visit_date"], r["clinic_label"], r["visit_time_desc"], r["cnt"]))
    if not rows:
        print("  (无数据)")

    # 查看 clinic_schedules 表
    cursor.execute("SELECT clinic_date, clinic_label, time_desc, clinic_dept, dept_name FROM clinic_schedules WHERE clinic_date = CURDATE() LIMIT 20")
    rows = cursor.fetchall()
    print()
    print("=== 今天的排班数据 ===")
    for r in rows:
        print("  {} | {} | {} | {} | {}".format(r["clinic_date"], r["clinic_label"], r["time_desc"], r["clinic_dept"], r["dept_name"]))
    if not rows:
        print("  (无数据)")

    # 检查 clinic_label 精确匹配
    cursor.execute("SELECT DISTINCT clinic_label FROM patient_registrations LIMIT 20")
    rows = cursor.fetchall()
    print()
    print("=== patient_registrations中的clinic_label值 ===")
    for r in rows:
        print("  [{}]".format(r["clinic_label"]))
    if not rows:
        print("  (无数据)")

    cursor.execute("SELECT DISTINCT clinic_label FROM clinic_schedules LIMIT 20")
    rows = cursor.fetchall()
    print()
    print("=== clinic_schedules中的clinic_label值 ===")
    for r in rows:
        print("  [{}]".format(r["clinic_label"]))
    if not rows:
        print("  (无数据)")
