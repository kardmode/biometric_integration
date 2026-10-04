# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from datetime import datetime


def find_employee(employee_id_or_device_id):
    """
    Intelligently resolves an active Employee record from various ID formats:
    1. Exact attendance_device_id match (e.g. '001', '1', '105', card RFID)
    2. Leading-zero normalized attendance_device_id (e.g. matches '001' <-> '1')
    3. Exact Employee name/ID (e.g. 'HR-EMP-00001', 'EMP-001')
    4. Numeric suffix of Employee name (e.g. if name is 'HR-EMP-0001' and device sends '1' or '001')
    """
    if not employee_id_or_device_id:
        return None

    raw = str(employee_id_or_device_id).strip()
    if not raw:
        return None

    stripped = raw.lstrip("0") or "0"

    # 1. Exact match on attendance_device_id
    emp = frappe.db.get_value(
        "Employee",
        {"attendance_device_id": raw, "status": "Active"},
        ["name", "employee_name", "attendance_device_id"],
        as_dict=True
    )
    if emp:
        return emp

    # 2. Match with leading zeroes stripped or padded on attendance_device_id
    if raw.isdigit():
        emp_match = frappe.db.sql("""
            SELECT name, employee_name, attendance_device_id
            FROM `tabEmployee`
            WHERE status = 'Active'
              AND attendance_device_id IS NOT NULL
              AND attendance_device_id != ''
              AND (
                  attendance_device_id = %s
                  OR attendance_device_id = %s
                  OR TRIM(LEADING '0' FROM attendance_device_id) = %s
              )
            LIMIT 1
        """, (raw, stripped, stripped), as_dict=True)
        if emp_match:
            return emp_match[0]

    # 3. Exact match on Employee name (primary key)
    emp = frappe.db.get_value(
        "Employee",
        {"name": raw, "status": "Active"},
        ["name", "employee_name", "attendance_device_id"],
        as_dict=True
    )
    if emp:
        return emp

    # 4. If raw is numeric (e.g. 1 or 001), check if Employee name ends with that number pattern
    # e.g. HR-EMP-00001 or EMP-001 or custom naming series
    if raw.isdigit():
        emp_match = frappe.db.sql("""
            SELECT name, employee_name, attendance_device_id
            FROM `tabEmployee`
            WHERE status = 'Active'
              AND (
                  name LIKE %s
                  OR TRIM(LEADING '0' FROM SUBSTRING_INDEX(name, '-', -1)) = %s
              )
            LIMIT 1
        """, (f"%{stripped}", stripped), as_dict=True)
        if emp_match:
            return emp_match[0]

    return None


def create_employee_checkin(employee_id_or_device_id, punch_datetime, log_type=None, device_id=None):
    """
    Creates an ERPNext/HRMS standard Employee Checkin record.
    Matches employee by attendance_device_id or employee name with smart zero-normalization.
    """
    if not frappe.db.table_exists("Employee Checkin"):
        return None

    try:
        # Check if settings allow syncing to Employee Checkin
        settings = frappe.get_single("Biometric Integration Settings") if frappe.db.table_exists("Biometric Integration Settings") else None
        if settings and hasattr(settings, "sync_to_employee_checkin") and not settings.sync_to_employee_checkin:
            return None

        # Resolve employee
        emp = find_employee(employee_id_or_device_id)
        if not emp:
            return None

        # Ensure punch_datetime is a datetime object or valid string
        if isinstance(punch_datetime, str):
            punch_time_str = punch_datetime[:19]
        elif isinstance(punch_datetime, datetime):
            punch_time_str = punch_datetime.strftime("%Y-%m-%d %H:%M:%S")
        else:
            return None

        # Check for existing Employee Checkin
        existing = frappe.db.exists(
            "Employee Checkin",
            {"employee": emp.name, "time": punch_time_str}
        )

        if existing:
            return existing

        checkin = frappe.new_doc("Employee Checkin")
        checkin.employee = emp.name
        checkin.time = punch_time_str
        if log_type in ("IN", "OUT"):
            checkin.log_type = log_type
        if device_id:
            checkin.device_id = str(device_id)

        checkin.flags.ignore_permissions = True
        checkin.insert(ignore_permissions=True)
        return checkin.name

    except Exception as e:
        frappe.log_error(title="Biometric Checkin Error", message=f"Failed for {employee_id_or_device_id}: {str(e)}")
        return None
