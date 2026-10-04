# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import json
import frappe
from datetime import datetime
from frappe import _
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin, find_employee


@frappe.whitelist(allow_guest=True)
def hikvision_event_receiver():
    """
    Public webhook endpoint to receive real-time Hikvision event pushes (HTTP Listening / Alarm Host).
    Accepts JSON or multipart/form-data payloads from Hikvision MinMoe face terminals.
    """
    try:
        try:
            settings = frappe.get_cached_doc("Biometric Integration Settings")
        except Exception:
            settings = None

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

            # Smart employee lookup (supports leading zero normalization & custom naming series)
            emp = find_employee(emp_no)
            emp_name = emp.employee_name if emp else ""
            log_emp_no = (emp.attendance_device_id if emp and emp.get("attendance_device_id") else str(emp_no))

            # Candidates for matching existing daily attendance log
            candidates = [str(emp_no)]
            if log_emp_no not in candidates:
                candidates.append(log_emp_no)
            if str(emp_no).isdigit():
                stripped = str(emp_no).lstrip("0") or "0"
                if stripped not in candidates:
                    candidates.append(stripped)

            # 1. Update or create Biometric Attendance Log
            bal = frappe.get_all(
                "Biometric Attendance Log",
                filters={"employee_no": ["in", candidates], "event_date": event_datetime.date()},
                limit_page_length=1,
            )

            if bal:
                doc = frappe.get_doc("Biometric Attendance Log", bal[0].name)
            else:
                doc = frappe.new_doc("Biometric Attendance Log")
                doc.employee_no = log_emp_no
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
        frappe.log_error(title="Biometric Webhook Error", message=f"Hikvision webhook processing failed: {str(e)}")
        frappe.local.response["http_status_code"] = 500
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def push():
    """Short endpoint alias for hardware terminals with character limits."""
    return hikvision_event_receiver()


# -------------------------------------------------------------------------
# Access Control & Smart Door / Shutter APIs
# -------------------------------------------------------------------------

@frappe.whitelist()
def unlock_access_door(door_name):
    """
    Triggers an unlock relay pulse on an Access Door (Shelly, ESP32, or relay).
    Intended for mobile web / PWA 1-tap phone unlock by authorized users.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required to unlock doors."), frappe.PermissionError)

    if not frappe.db.exists("Access Door", door_name):
        frappe.throw(_("Access Door {0} not found.").format(door_name))

    door = frappe.get_doc("Access Door", door_name)
    if not door.allow_mobile_unlock:
        frappe.throw(_("Mobile phone unlock is disabled for door {0}.").format(door_name))

    return door.unlock(source="Mobile Web Button", user=frappe.session.user)


@frappe.whitelist()
def trigger_access_shutter(door_name):
    """
    Sends a momentary 0.5s cycle pulse to an industrial warehouse roller shutter.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required."), frappe.PermissionError)

    if not frappe.db.exists("Access Door", door_name):
        frappe.throw(_("Door / Shutter {0} not found.").format(door_name))

    door = frappe.get_doc("Access Door", door_name)
    return door.trigger_shutter(source="Mobile Web Button", user=frappe.session.user)


@frappe.whitelist(allow_guest=True)
def shelly_door_webhook(door=None, state=None, event=None):
    """
    Receives live door position sensor events from a Shelly 1 Plus (SW input)
    or ESP32 whenever a door or shutter physically opens or closes.
    """
    door_name = door or frappe.request.args.get("door")
    if not door_name and hasattr(frappe.request, "json") and frappe.request.json:
        door_name = frappe.request.json.get("door")

    if not door_name or not frappe.db.exists("Access Door", door_name):
        frappe.local.response["http_status_code"] = 404
        return {"status": "error", "message": f"Door {door_name} not found"}

    # Determine state: 'open', 'closed', 1, 0
    raw_state = state or frappe.request.args.get("state")
    if not raw_state and hasattr(frappe.request, "json") and frappe.request.json:
        raw_state = frappe.request.json.get("state") or frappe.request.json.get("status")

    is_open = str(raw_state).lower() in ["open", "1", "true", "opened"]

    door_doc = frappe.get_doc("Access Door", door_name)
    door_doc.update_sensor_state(is_open=is_open)

    return {
        "status": "success",
        "door": door_name,
        "current_state": door_doc.current_state
    }


@frappe.whitelist(allow_guest=True)
def verify_card_access(door=None, card_id=None):
    """
    Called by an ESP32 or smart Wiegand controller when an employee taps
    an Anti-Metal Phone Sticker or RFID keyfob at the door reader.
    Returns authorization decision and relay pulse seconds.
    """
    door_name = door or frappe.request.args.get("door")
    tag_id = card_id or frappe.request.args.get("card_id")

    if not tag_id:
        if hasattr(frappe.request, "json") and frappe.request.json:
            door_name = door_name or frappe.request.json.get("door")
            tag_id = frappe.request.json.get("card_id")

    if not door_name or not tag_id:
        frappe.local.response["http_status_code"] = 400
        return {"authorized": False, "message": "Missing door or card_id"}

    if not frappe.db.exists("Access Door", door_name):
        return {"authorized": False, "message": f"Door {door_name} not found"}

    door_doc = frappe.get_doc("Access Door", door_name)
    if not door_doc.enabled:
        return {"authorized": False, "message": "Door disabled"}

    # Smart lookup employee by attendance_device_id, card RFID, or employee naming series
    emp = find_employee(tag_id)

    # Check authorization against door permissions
    is_authorized = False
    deny_reason = "Unregistered Card"
    if emp:
        if emp.status != "Active":
            deny_reason = "Inactive Employee"
        elif not door_doc.is_user_authorized(employee_doc=emp):
            deny_reason = f"Unauthorized: Employee {emp.employee_name} has no permission for this door"
        else:
            is_authorized = True

    pulse = float(door_doc.relay_pulse_seconds or 3.0)

    log = frappe.get_doc({
        "doctype": "Door Access Log",
        "door": door_name,
        "timestamp": now_datetime(),
        "employee": emp.name if emp else None,
        "employee_name": emp.employee_name if emp else "Unknown Cardholder",
        "card_id": str(tag_id),
        "access_method": "RFID Phone Sticker",
        "status": "Granted" if is_authorized else "Denied",
        "details": f"Relay pulse: {pulse}s" if is_authorized else deny_reason
    })
    log.insert(ignore_permissions=True)

    return {
        "authorized": is_authorized,
        "pulse_seconds": pulse if is_authorized else 0,
        "employee_name": emp.employee_name if emp else ""
    }


@frappe.whitelist()
def get_accessible_doors():
    """
    Returns only the doors that the currently logged-in user / employee
    is authorized to see and unlock on their mobile dashboard.
    """
    if frappe.session.user == "Guest":
        return []

    user = frappe.session.user
    door_names = frappe.get_all(
        "Access Door",
        filters={"enabled": 1, "allow_mobile_unlock": 1},
        pluck="name",
        order_by="door_name asc"
    )

    authorized_doors = []
    for d_name in door_names:
        door = frappe.get_doc("Access Door", d_name)
        if door.is_user_authorized(user=user):
            authorized_doors.append({
                "name": door.name,
                "door_name": door.door_name,
                "door_type": door.door_type,
                "location": door.location,
                "current_state": door.current_state,
                "last_state_change": door.last_state_change,
                "relay_pulse_seconds": door.relay_pulse_seconds
            })

    return authorized_doors


