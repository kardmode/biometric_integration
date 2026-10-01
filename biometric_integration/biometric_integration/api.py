# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import json
import frappe
from datetime import datetime
from frappe import _
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin


@frappe.whitelist(allow_guest=True)
def hikvision_event_receiver():
    """
    Public webhook endpoint to receive real-time Hikvision event pushes (HTTP Listening / Alarm Host).
    Accepts JSON or multipart/form-data payloads from Hikvision MinMoe face terminals.
    """
    try:
        settings = frappe.get_single("Biometric Integration Settings") if frappe.db.table_exists("Biometric Integration Settings") else None
        if not settings or not getattr(settings, "enable_webhook_receiver", 1):
            frappe.local.response["http_status_code"] = 403
            return {"status": "error", "message": "Webhook receiver is disabled."}

        # Validate secret token
        token = frappe.request.args.get("token") or frappe.request.headers.get("X-Webhook-Token")
        expected_token = getattr(settings, "webhook_secret_key", None)
        if expected_token and token != expected_token:
            frappe.local.response["http_status_code"] = 401
            return {"status": "error", "message": "Invalid or missing webhook token."}

        # Parse payload
        events_data = None
        content_type = frappe.request.headers.get("Content-Type", "")

        if "multipart/form-data" in content_type:
            # Check form parts
            if "event_log" in frappe.request.form:
                try:
                    events_data = json.loads(frappe.request.form["event_log"])
                except Exception:
                    pass
            elif "AcsEvent" in frappe.request.form:
                try:
                    events_data = json.loads(frappe.request.form["AcsEvent"])
                except Exception:
                    pass
        elif "application/json" in content_type or frappe.request.data:
            try:
                events_data = json.loads(frappe.request.data)
            except Exception:
                pass

        if not events_data and hasattr(frappe.request, "json") and frappe.request.json:
            events_data = frappe.request.json

        if not events_data:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "No valid event payload found."}

        # Normalize events list
        event_list = []
        if isinstance(events_data, dict):
            if "AcsEvent" in events_data and isinstance(events_data["AcsEvent"], dict):
                info_list = events_data["AcsEvent"].get("InfoList") or [events_data["AcsEvent"]]
                event_list.extend(info_list if isinstance(info_list, list) else [info_list])
            elif "events" in events_data and isinstance(events_data["events"], list):
                event_list.extend(events_data["events"])
            else:
                event_list.append(events_data)
        elif isinstance(events_data, list):
            event_list.extend(events_data)

        processed = 0
        for ev in event_list:
            if not isinstance(ev, dict):
                continue

            emp_no = ev.get("employeeNoString") or ev.get("employeeNo") or ev.get("cardNo")
            event_timestamp = ev.get("time") or ev.get("dateTime")
            dev_name = ev.get("devName") or ev.get("devSerial") or ev.get("deviceName") or "Hikvision Terminal"

            if not emp_no or not event_timestamp:
                continue

            # Parse datetime
            try:
                event_datetime = datetime.strptime(str(event_timestamp)[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                try:
                    event_datetime = datetime.strptime(str(event_timestamp)[:19], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    continue

            # Employee name lookup
            emp_name = frappe.db.get_value("Employee", {"attendance_device_id": str(emp_no)}, "employee_name") or ""

            # 1. Update or create Biometric Attendance Log
            bal = frappe.get_all(
                "Biometric Attendance Log",
                filters={"employee_no": str(emp_no), "event_date": event_datetime.date()},
                limit_page_length=1,
            )

            if bal:
                doc = frappe.get_doc("Biometric Attendance Log", bal[0].name)
            else:
                doc = frappe.new_doc("Biometric Attendance Log")
                doc.employee_no = str(emp_no)
                doc.event_date = event_datetime.date()

            if emp_name:
                doc.employee_name = emp_name

            existing_punch = frappe.db.sql(
                """
                SELECT COUNT(*)
                FROM `tabBiometric Attendance Punch Table`
                WHERE parent = %(parent)s
                AND punch_time = %(punch_time)s
                """,
                {"parent": doc.name, "punch_time": event_datetime.time()},
            )[0][0] > 0

            if not existing_punch:
                doc.append(
                    "punch_table",
                    {
                        "punch_time": event_datetime.time(),
                        "punch_type": "Auto",
                    },
                )
                doc.save(ignore_permissions=True)

            # 2. Standard HRMS Employee Checkin creation
            create_employee_checkin(emp_no, event_datetime, log_type=None, device_id=dev_name)
            processed += 1

        frappe.db.commit()

        # Hikvision expected response
        return {
            "statusCode": 1,
            "statusString": "OK",
            "subStatusCode": "ok",
            "processed": processed
        }

    except Exception as e:
        frappe.log_error(f"Hikvision webhook processing failed: {str(e)}", "Biometric Webhook Error")
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}
