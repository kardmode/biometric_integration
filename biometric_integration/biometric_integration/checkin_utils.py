# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from datetime import datetime


def create_employee_checkin(employee_id_or_device_id, punch_datetime, log_type=None, device_id=None):
    """
    Creates an ERPNext/HRMS standard Employee Checkin record.
    Matches employee by attendance_device_id or employee name.
    """
    if not frappe.db.table_exists("Employee Checkin"):
        return None

    try:
        # Check if settings allow syncing to Employee Checkin
        settings = frappe.get_single("Biometric Integration Settings") if frappe.db.table_exists("Biometric Integration Settings") else None
        if settings and hasattr(settings, "sync_to_employee_checkin") and not settings.sync_to_employee_checkin:
            return None

        # Resolve employee
        emp = frappe.db.get_value(
            "Employee",
            {"attendance_device_id": str(employee_id_or_device_id), "status": "Active"},
            ["name", "employee_name"],
            as_dict=True
        )

        if not emp:
            # Fallback by employee ID (name)
            emp = frappe.db.get_value(
                "Employee",
                {"name": str(employee_id_or_device_id), "status": "Active"},
                ["name", "employee_name"],
                as_dict=True
            )

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
        frappe.log_error(f"Failed to create Employee Checkin for {employee_id_or_device_id}: {str(e)}", "Biometric Checkin Integration")
        return None
