# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import json
import frappe
from datetime import datetime
from frappe import _
from frappe.utils import now_datetime
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin, find_employee


def _find_val(obj, keys):
    """Recursively search for any of the given keys in a nested dict or list."""
    if not obj:
        return None
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] is not None and str(obj[k]).strip() != "":
                return obj[k]
        for v in obj.values():
            val = _find_val(v, keys)
            if val:
                return val
    elif isinstance(obj, list):
        for item in obj:
            val = _find_val(item, keys)
            if val:
                return val
    return None


def _parse_xml_hikvision_event(xml_text):
    """Parses Hikvision XML event alert payload (EventNotificationAlert / AcsEvent)."""
    if not xml_text or not isinstance(xml_text, str) or "<" not in xml_text:
        return None
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]

        emp_no = None
        for tag in ("employeeNoString", "employeeNo", "cardNo"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                emp_no = node.text.strip()
                break

        time_str = None
        for tag in ("time", "dateTime"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                time_str = node.text.strip()
                break

        dev_name = None
        for tag in ("deviceName", "devName", "devSerial", "macAddress"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                dev_name = node.text.strip()
                break

        ip_addr = None
        for tag in ("ipAddress", "ip", "deviceIp"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                ip_addr = node.text.strip()
                break

        mac_addr = None
        for tag in ("macAddress", "mac"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                mac_addr = node.text.strip()
                break

        major_type = None
        for tag in ("majorEventType", "major"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                try:
                    major_type = int(node.text.strip())
                    break
                except Exception:
                    pass

        sub_type = None
        for tag in ("subEventType", "minor"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                try:
                    sub_type = int(node.text.strip())
                    break
                except Exception:
                    pass

        event_type = None
        for tag in ("eventType", "event"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                event_type = node.text.strip()
                break

        event_desc = None
        for tag in ("eventDescription", "description"):
            node = root.find(f".//{tag}")
            if node is not None and node.text:
                event_desc = node.text.strip()
                break

        if (emp_no and time_str) or (time_str and (event_type or sub_type is not None or major_type is not None)) or (event_type or sub_type is not None):
            res = {
                "employeeNoString": emp_no,
                "time": time_str or now_datetime().isoformat(),
                "devName": dev_name or "Hikvision Terminal"
            }
            if major_type is not None:
                res["majorEventType"] = major_type
            if sub_type is not None:
                res["subEventType"] = sub_type
            if event_type:
                res["eventType"] = event_type
            if event_desc:
                res["eventDescription"] = event_desc
            if ip_addr:
                res["ipAddress"] = ip_addr
            if mac_addr:
                res["macAddress"] = mac_addr
            return res
    except Exception:
        pass
    return None


def _extract_device_info_from_xml(xml_text):
    """Extracts device metadata (ipAddress, macAddress, serialNumber, devName) from raw XML."""
    if not xml_text or not isinstance(xml_text, str) or "<" not in xml_text:
        return {}
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]
        info = {}
        for tag, key in (
            ("ipAddress", "ip"),
            ("macAddress", "mac_address"),
            ("serialNumber", "device_serial_number"),
            ("subSerialNumber", "device_serial_number"),
            ("model", "model"),
            ("deviceID", "device_id"),
            ("deviceId", "device_id"),
            ("deviceName", "device_name"),
            ("devName", "device_name")
        ):
            node = root.find(f".//{tag}")
            if node is not None and node.text and node.text.strip():
                info[key] = node.text.strip()
        return info
    except Exception:
        return {}


def classify_alarm_event(ev):
    """
    Checks if an event payload represents a physical or biometric security alarm:
    - Duress Alarm (subEventType 67 or 'duress')
    - Blacklist Scan Attempt (subEventType 68 or 'blacklist')
    - Tamper Alarm (subEventType 72 or 'tamper')
    - Door Forced Open (subEventType 39 or 'forced')
    - Door Held Open Alert (subEventType 73 or 'open timeout' / 'held open')
    Returns a tuple (status, method, alarm_details) or None if normal event.
    """
    if not isinstance(ev, dict):
        return None

    sub_ev = ev.get("AccessControllerEvent") or ev.get("AcsEvent") or ev
    if not isinstance(sub_ev, dict):
        sub_ev = ev

    sub_type = None
    for k in ("subEventType", "subType", "minor"):
        val = sub_ev.get(k) or ev.get(k)
        if val is not None:
            try:
                sub_type = int(val)
                break
            except Exception:
                pass

    desc = str(
        sub_ev.get("eventDescription")
        or sub_ev.get("eventType")
        or ev.get("eventDescription")
        or ev.get("eventType")
        or ""
    ).lower()

    # 1. Duress Alarm (Duress PIN or Duress Card)
    if sub_type == 67 or "duress" in desc:
        return ("Duress Alarm", "Duress PIN", "Duress alarm triggered at terminal")

    # 2. Blacklist Scan Attempt
    if sub_type == 68 or "blacklist" in desc or "black list" in desc:
        return ("Blacklist Attempt", "Blacklist Scan", "Blacklisted individual scan attempt detected")

    # 3. Tamper Alarm (Case opened, device dismantled)
    if sub_type == 72 or "tamper" in desc:
        return ("Tamper Alarm", "Tamper Sensor", "Physical tamper sensor triggered on device casing")

    # 4. Door Forced Open
    if sub_type == 39 or "forced" in desc or "force" in desc:
        return ("Door Forced Open", "Door Position Sensor", "Door forced open without authorized unlock")

    # 5. Door Held Open Alert / Timeout
    if sub_type == 73 or "held open" in desc or "timeout" in desc or "timed out" in desc:
        return ("Door Held Open Alert", "Door Position Sensor", "Door held open beyond permitted time limit")

    return None


def notify_security_alarm(device_name, status, details, timestamp, employee_name=None):
    """
    Sends real-time UI notification and creates system Notification Log alerts for managers.
    """
    subject = f"[SECURITY ALARM] {status} at {device_name}"
    full_details = details
    if employee_name:
        full_details += f" (Subject: {employee_name})"

    # 1. Real-time WebSocket event
    try:
        frappe.publish_realtime(
            "biometric_security_alarm",
            {
                "title": f"SECURITY ALERT: {status}",
                "device": device_name,
                "status": status,
                "details": full_details,
                "timestamp": str(timestamp)
            }
        )
    except Exception:
        pass

    # 2. Immutable security log in Error Log
    try:
        frappe.log_error(
            title=subject,
            message=f"Timestamp: {timestamp}\nDevice: {device_name}\nStatus: {status}\nDetails: {full_details}"
        )
    except Exception:
        pass

    # 3. Notification Log entry for System Managers and HR Managers
    try:
        if frappe.db.table_exists("Notification Log"):
            recipients = frappe.get_all(
                "Has Role",
                filters={"role": ["in", ["System Manager", "HR Manager"]], "parenttype": "User"},
                pluck="parent"
            )
            for user in set(recipients) - {"Administrator", "Guest"}:
                try:
                    notif = frappe.new_doc("Notification Log")
                    notif.for_user = user
                    notif.type = "Alert"
                    notif.subject = subject
                    notif.email_content = (
                        f"<b>Device:</b> {device_name}<br>"
                        f"<b>Status:</b> <span style='color:red;'><b>{status}</b></span><br>"
                        f"<b>Details:</b> {full_details}<br>"
                        f"<b>Timestamp:</b> {timestamp}"
                    )
                    notif.insert(ignore_permissions=True)
                except Exception:
                    pass
    except Exception:
        pass


@frappe.whitelist(allow_guest=True)
def hikvision_event_receiver():
    """
    Public webhook endpoint to receive real-time Hikvision event pushes (HTTP Listening / Alarm Host).
    Accepts JSON, XML, or multipart/form-data payloads from Hikvision MinMoe face terminals.
    """
    try:
        # Validate secret token and resolve Biometric Device
        token = frappe.request.args.get("token") or frappe.request.headers.get("X-Webhook-Token")
        matched_device = None

        if token and frappe.db.table_exists("Biometric Device"):
            matched_device = frappe.db.get_value(
                "Biometric Device",
                {"webhook_secret_key": token, "enabled": 1},
                ["name", "device_name", "device_direction", "punch_cooldown_minutes", "mac_address", "ip", "device_id", "device_serial_number", "model", "enable_attendance", "enable_access_control"],
                as_dict=True
            )

        if not matched_device:
            frappe.local.response["http_status_code"] = 401
            return {"status": "error", "message": "Invalid or missing webhook token."}

        # Parse payload safely without triggering Werkzeug 415 on non-application/json content types
        events_data = None
        raw_text = None
        try:
            raw_text = frappe.request.get_data(as_text=True)
        except Exception:
            try:
                raw_text = frappe.request.data.decode("utf-8", errors="ignore") if frappe.request.data else ""
            except Exception:
                raw_text = ""

        # 1. Check form / multipart data
        if hasattr(frappe.request, "form") and frappe.request.form:
            for key, val in frappe.request.form.items():
                try:
                    events_data = json.loads(val)
                    break
                except Exception:
                    xml_ev = _parse_xml_hikvision_event(val)
                    if xml_ev:
                        events_data = [xml_ev]
                        break

        # 2. Check uploaded multipart files (Hikvision sends event json/xml as part 1)
        if not events_data and hasattr(frappe.request, "files") and frappe.request.files:
            for fname, fstorage in frappe.request.files.items():
                try:
                    fcontent = fstorage.read().decode("utf-8", errors="ignore")
                    fstorage.seek(0)
                    try:
                        events_data = json.loads(fcontent)
                        break
                    except Exception:
                        xml_ev = _parse_xml_hikvision_event(fcontent)
                        if xml_ev:
                            events_data = [xml_ev]
                            break
                except Exception:
                    pass

        # 3. Check raw body as JSON or XML
        if not events_data and raw_text:
            try:
                events_data = json.loads(raw_text)
            except Exception:
                xml_ev = _parse_xml_hikvision_event(raw_text)
                if xml_ev:
                    events_data = [xml_ev]

        # 4. Silent JSON getter fallback (never raises 415)
        if not events_data and hasattr(frappe.request, "get_json"):
            try:
                events_data = frappe.request.get_json(silent=True)
            except Exception:
                pass

        # Auto-track device local IP, MAC address, Serial Number, Model, and Device ID dynamically
        detected_ip = None
        detected_mac = None
        detected_serial = None
        detected_model = None
        detected_device_id = None

        if raw_text and "<" in raw_text:
            xml_meta = _extract_device_info_from_xml(raw_text)
            detected_ip = xml_meta.get("ip")
            detected_mac = xml_meta.get("mac_address")
            detected_serial = xml_meta.get("device_serial_number")
            detected_model = xml_meta.get("model")
            detected_device_id = xml_meta.get("device_id")

        if isinstance(events_data, dict):
            if not detected_ip:
                detected_ip = _find_val(events_data, ("ipAddress", "ip", "deviceIp"))
            if not detected_mac:
                detected_mac = _find_val(events_data, ("macAddress", "mac", "mac_address"))
            if not detected_serial:
                detected_serial = _find_val(events_data, ("serialNumber", "deviceSerial", "devSerial", "subSerialNumber"))
            if not detected_model:
                detected_model = _find_val(events_data, ("model", "deviceModel"))
            if not detected_device_id:
                detected_device_id = _find_val(events_data, ("deviceID", "deviceId", "devId"))
        elif isinstance(events_data, list) and events_data and isinstance(events_data[0], dict):
            if not detected_ip:
                detected_ip = _find_val(events_data[0], ("ipAddress", "ip", "deviceIp"))
            if not detected_mac:
                detected_mac = _find_val(events_data[0], ("macAddress", "mac", "mac_address"))
            if not detected_serial:
                detected_serial = _find_val(events_data[0], ("serialNumber", "deviceSerial", "devSerial", "subSerialNumber"))
            if not detected_model:
                detected_model = _find_val(events_data[0], ("model", "deviceModel"))
            if not detected_device_id:
                detected_device_id = _find_val(events_data[0], ("deviceID", "deviceId", "devId"))

        if not detected_ip and hasattr(frappe.request, "remote_addr"):
            detected_ip = frappe.request.remote_addr

        if matched_device and matched_device.get("name"):
            dev_updates = {}
            if detected_ip and str(detected_ip).strip() and str(detected_ip).strip() != (matched_device.get("ip") or ""):
                dev_updates["ip"] = str(detected_ip).strip()
                matched_device["ip"] = str(detected_ip).strip()

            if detected_mac and str(detected_mac).strip() and str(detected_mac).strip() != (matched_device.get("mac_address") or ""):
                dev_updates["mac_address"] = str(detected_mac).strip()
                matched_device["mac_address"] = str(detected_mac).strip()

            if detected_serial and str(detected_serial).strip() and str(detected_serial).strip() != (matched_device.get("device_serial_number") or ""):
                dev_updates["device_serial_number"] = str(detected_serial).strip()
                matched_device["device_serial_number"] = str(detected_serial).strip()

            if detected_model and str(detected_model).strip() and str(detected_model).strip() != (matched_device.get("model") or ""):
                dev_updates["model"] = str(detected_model).strip()
                matched_device["model"] = str(detected_model).strip()

            if detected_device_id and str(detected_device_id).strip() and str(detected_device_id).strip() != (matched_device.get("device_id") or ""):
                dev_updates["device_id"] = str(detected_device_id).strip()
                matched_device["device_id"] = str(detected_device_id).strip()

            dev_updates["status"] = "Online"
            dev_updates["last_sync"] = frappe.utils.now_datetime()

            try:
                frappe.db.set_value("Biometric Device", matched_device["name"], dev_updates, update_modified=False)
            except Exception:
                pass

        # Silently acknowledge idle device heartbeats and system sensor events without creating error logs
        if isinstance(events_data, dict):
            event_type = str(events_data.get("eventType") or events_data.get("eventDescription") or "").lower()
            if "heartbeat" in event_type:
                return {
                    "statusCode": 1,
                    "statusString": "OK",
                    "subStatusCode": "ok",
                    "message": "Heartbeat acknowledged"
                }

            ace = events_data.get("AccessControllerEvent", {}) if isinstance(events_data.get("AccessControllerEvent"), dict) else events_data
            # majorEventType 1, 2, 3 without employee (e.g. system status, door sensor 80)
            if ace.get("majorEventType") in (1, 2, 3) and not _find_val(events_data, ("employeeNoString", "employeeNo", "cardNo", "employee_no")):
                # Check if this is a security alarm before acknowledging!
                if not classify_alarm_event(events_data):
                    return {
                        "statusCode": 1,
                        "statusString": "OK",
                        "subStatusCode": "ok",
                        "message": "System event acknowledged"
                    }

        if not events_data:
            frappe.local.response["http_status_code"] = 400
            return {"status": "error", "message": "No valid event payload found."}

        # Normalize events list
        event_list = []
        if isinstance(events_data, dict):
            if "InfoList" in events_data and isinstance(events_data["InfoList"], list):
                event_list.extend(events_data["InfoList"])
            elif "AcsEvent" in events_data and isinstance(events_data["AcsEvent"], dict):
                info_list = events_data["AcsEvent"].get("InfoList") or [events_data["AcsEvent"]]
                event_list.extend(info_list if isinstance(info_list, list) else [info_list])
            elif "AccessControllerEvent" in events_data and isinstance(events_data["AccessControllerEvent"], dict):
                sub = events_data["AccessControllerEvent"]
                if "dateTime" not in sub and "dateTime" in events_data:
                    sub["dateTime"] = events_data["dateTime"]
                if "deviceName" not in sub and "deviceName" in events_data:
                    sub["deviceName"] = events_data["deviceName"]
                event_list.append(sub)
            elif "events" in events_data and isinstance(events_data["events"], list):
                event_list.extend(events_data["events"])
            else:
                event_list.append(events_data)
        elif isinstance(events_data, list):
            event_list.extend(events_data)

        matched_dev_name = matched_device.get("device_name") or matched_device.get("name") if matched_device else None
        dev_direction = matched_device.get("device_direction") if matched_device and matched_device.get("device_direction") in ("IN", "OUT") else None
        cooldown = matched_device.get("punch_cooldown_minutes") or 5 if matched_device else 5

        processed = 0
        for ev in event_list:
            if not isinstance(ev, dict):
                continue

            # Check if this event is a security alarm (Duress, Tamper, Door Forced, Blacklist, Held Open)
            alarm_info = classify_alarm_event(ev)

            # Recursive search for employee ID across all possible Hikvision key names
            emp_no = _find_val(ev, ("employeeNoString", "employeeNo", "cardNo", "employee_no"))
            # Recursive search for event timestamp
            event_timestamp = _find_val(ev, ("time", "dateTime", "eventTime", "recvTime"))
            dev_name = matched_dev_name or frappe.request.args.get("device") or _find_val(ev, ("deviceName", "devName", "devSerial", "macAddress")) or "Hikvision Terminal"

            # Parse datetime
            event_datetime = None
            if event_timestamp:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        event_datetime = datetime.strptime(str(event_timestamp)[:19], fmt)
                        break
                    except Exception:
                        pass
            if not event_datetime:
                event_datetime = now_datetime()

            # 1. Handle Security Alarm
            if alarm_info:
                alarm_status, alarm_method, alarm_desc = alarm_info
                emp_id = None
                emp_name = None
                if emp_no:
                    emp = frappe.db.get_value("Employee", {"attendance_device_id": emp_no}, ["name", "employee_name"], as_dict=True)
                    if not emp:
                        emp = frappe.db.get_value("Employee", {"name": emp_no}, ["name", "employee_name"], as_dict=True)
                    if emp:
                        emp_id = emp.name
                        emp_name = emp.employee_name

                if frappe.db.table_exists("Door Access Log"):
                    try:
                        access_log = frappe.new_doc("Door Access Log")
                        access_log.update({
                            "device": matched_dev_name or dev_name,
                            "timestamp": event_datetime,
                            "status": alarm_status,
                            "access_method": alarm_method,
                            "employee": emp_id,
                            "employee_name": emp_name,
                            "card_id": str(emp_no) if emp_no else None,
                            "details": f"{alarm_desc} on {matched_dev_name or dev_name}"
                        })
                        access_log.insert(ignore_permissions=True)
                        processed += 1
                    except Exception as e:
                        frappe.log_error(f"Failed to create Door Access Log for alarm: {e}", "Biometric Integration")

                notify_security_alarm(
                    device_name=matched_dev_name or dev_name,
                    status=alarm_status,
                    details=alarm_desc,
                    timestamp=event_datetime,
                    employee_name=emp_name
                )
                continue

            # Non-alarm events require emp_no and event_timestamp
            if not emp_no or not event_timestamp:
                continue

            enable_att = bool(matched_device.get("enable_attendance", 1)) if matched_device and "enable_attendance" in matched_device else True
            enable_acc = bool(matched_device.get("enable_access_control", 0)) if matched_device else False

            # Check if this regular access event was Denied or Granted
            sub_type = None
            ace_ev = ev.get("AccessControllerEvent") if isinstance(ev.get("AccessControllerEvent"), dict) else ev
            if ace_ev.get("subEventType") is not None:
                try:
                    sub_type = int(ace_ev.get("subEventType"))
                except Exception:
                    pass

            is_denied = (sub_type in (2, 5, 75)) or ("fail" in str(ev.get("eventDescription") or "").lower()) or ("denied" in str(ev.get("eventDescription") or "").lower())
            access_status = "Denied" if is_denied else "Granted"

            # Determine access method
            access_method = "Face Recognition"
            if sub_type in (4, 5, 38) or ev.get("cardNo"):
                access_method = "Keyfob / Card"
            elif sub_type in (15,):
                access_method = "Keypad PIN"

            # Attendance Checkin (only for Granted access)
            if enable_att and not is_denied:
                checkin_id = create_employee_checkin(
                    emp_no,
                    event_datetime,
                    log_type=dev_direction,
                    device_id=dev_name,
                    cooldown_minutes=cooldown
                )
                if checkin_id:
                    processed += 1

            # Door Access Security Log
            if enable_acc and frappe.db.table_exists("Door Access Log"):
                try:
                    emp = frappe.db.get_value("Employee", {"attendance_device_id": emp_no}, ["name", "employee_name"], as_dict=True)
                    if not emp:
                        emp = frappe.db.get_value("Employee", {"name": emp_no}, ["name", "employee_name"], as_dict=True)
                    emp_id = emp.name if emp else None
                    emp_name = emp.employee_name if emp else None

                    access_log = frappe.new_doc("Door Access Log")
                    access_log.update({
                        "device": matched_dev_name or dev_name,
                        "timestamp": event_datetime,
                        "status": access_status,
                        "access_method": access_method,
                        "employee": emp_id,
                        "employee_name": emp_name,
                        "card_id": str(emp_no),
                        "details": f"Authenticated at {dev_name} ({access_status})"
                    })
                    access_log.insert(ignore_permissions=True)
                    if not enable_att or is_denied:
                        processed += 1
                except Exception:
                    pass

        frappe.db.commit()

        if processed == 0 and isinstance(events_data, dict):
            ace = events_data.get("AccessControllerEvent", {}) if isinstance(events_data.get("AccessControllerEvent"), dict) else events_data
            if ace.get("majorEventType") == 5:
                frappe.log_error(
                    title="Hikvision Access Event Skipped",
                    message=f"Access event missing employee details:\n{json.dumps(events_data, indent=2, default=str)[:2000]}"
                )

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
    Triggers an unlock relay pulse on a Biometric / Access Device.
    Intended for mobile web / PWA 1-tap phone unlock by authorized users.
    """
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required to unlock doors."), frappe.PermissionError)

    device_name = door_name
    if not frappe.db.exists("Biometric Device", device_name):
        dev = frappe.db.get_value("Biometric Device", {"device_name": door_name}, "name")
        if dev:
            device_name = dev
        else:
            frappe.throw(_("Device / Door {0} not found.").format(door_name))

    device = frappe.get_doc("Biometric Device", device_name)
    if not device.enable_access_control:
        frappe.throw(_("Door access control is not enabled on {0}.").format(device.device_name))

    if not device.is_user_authorized(user=frappe.session.user):
        frappe.throw(_("You are not authorized to unlock {0}.").format(device.device_name), frappe.PermissionError)

    return device.unlock_door(source="Mobile Web Button", user=frappe.session.user)


@frappe.whitelist()
def trigger_access_shutter(door_name):
    """
    Sends a momentary cycle pulse to a roller shutter or barrier gate.
    """
    return unlock_access_door(door_name)


@frappe.whitelist(allow_guest=True)
def door_sensor_webhook(door=None, device=None, state=None, event=None, channel=None):
    """
    Receives live door position sensor events from a Shelly (Plus / Pro / Gen 1)
    or ESP32 whenever a door or shutter physically opens or closes.
    """
    target = device or door or frappe.request.args.get("device") or frappe.request.args.get("door")
    if not target and hasattr(frappe.request, "json") and frappe.request.json:
        target = frappe.request.json.get("device") or frappe.request.json.get("door")

    device_name = target
    if not frappe.db.exists("Biometric Device", device_name):
        dev = frappe.db.get_value("Biometric Device", {"device_name": target}, "name")
        if dev:
            device_name = dev
        else:
            frappe.local.response["http_status_code"] = 404
            return {"status": "error", "message": f"Device / Door {target} not found"}

    raw_state = state or frappe.request.args.get("state") or frappe.request.args.get("status")
    if not raw_state and hasattr(frappe.request, "json") and frappe.request.json:
        raw_state = frappe.request.json.get("state") or frappe.request.json.get("status")

    is_open = str(raw_state).lower() in ["open", "1", "true", "opened", "on"]

    if frappe.db.table_exists("Door Access Log"):
        try:
            log = frappe.new_doc("Door Access Log")
            log.update({
                "device": device_name,
                "timestamp": now_datetime(),
                "status": "Door Opened" if is_open else "Door Closed",
                "access_method": "Door Position Sensor",
                "details": f"Sensor state changed to {'Open' if is_open else 'Closed'}"
            })
            log.insert(ignore_permissions=True)
        except Exception:
            pass

    return {
        "status": "success",
        "device": device_name,
        "current_state": "Open" if is_open else "Closed"
    }


@frappe.whitelist(allow_guest=True)
def shelly_door_webhook(door=None, device=None, state=None, event=None, channel=None):
    """Backwards-compatible alias for door_sensor_webhook."""
    return door_sensor_webhook(door=door, device=device, state=state, event=event, channel=channel)


@frappe.whitelist(allow_guest=True)
def esp32_door_webhook(door=None, device=None, state=None, event=None, channel=None):
    """Alias for door_sensor_webhook used by ESP32 microcontrollers."""
    return door_sensor_webhook(door=door, device=device, state=state, event=event, channel=channel)


@frappe.whitelist(allow_guest=True)
def verify_card_access(door=None, device=None, card_id=None):
    """
    Called by an ESP32 or smart Wiegand controller when an employee taps
    an RFID keyfob or sticker at the reader. Returns authorization decision.
    """
    target = device or door or frappe.request.args.get("device") or frappe.request.args.get("door")
    tag_id = card_id or frappe.request.args.get("card_id")

    if not tag_id:
        if hasattr(frappe.request, "json") and frappe.request.json:
            target = target or frappe.request.json.get("device") or frappe.request.json.get("door")
            tag_id = frappe.request.json.get("card_id")

    if not target or not tag_id:
        frappe.local.response["http_status_code"] = 400
        return {"authorized": False, "message": "Missing device/door or card_id"}

    device_name = target
    if not frappe.db.exists("Biometric Device", device_name):
        dev = frappe.db.get_value("Biometric Device", {"device_name": target}, "name")
        if dev:
            device_name = dev
        else:
            return {"authorized": False, "message": f"Device {target} not found"}

    device = frappe.get_doc("Biometric Device", device_name)
    if not device.enabled:
        return {"authorized": False, "message": "Device disabled"}

    emp = find_employee(tag_id)

    is_authorized = False
    deny_reason = "Unregistered Card"
    if emp:
        if emp.status != "Active":
            deny_reason = "Inactive Employee"
        elif not device.is_user_authorized(employee_doc=emp):
            deny_reason = f"Unauthorized: Employee {emp.employee_name} has no permission for this door"
        else:
            is_authorized = True

    pulse = float(getattr(device, "relay_pulse_seconds", 3) or 3.0)

    if frappe.db.table_exists("Door Access Log"):
        try:
            log = frappe.get_doc({
                "doctype": "Door Access Log",
                "device": device_name,
                "timestamp": now_datetime(),
                "employee": emp.name if emp else None,
                "employee_name": emp.employee_name if emp else "Unknown Cardholder",
                "card_id": str(tag_id),
                "access_method": "RFID Phone Sticker",
                "status": "Granted" if is_authorized else "Denied",
                "details": f"Relay pulse: {pulse}s" if is_authorized else deny_reason
            })
            log.insert(ignore_permissions=True)
        except Exception:
            pass

    return {
        "authorized": is_authorized,
        "pulse_seconds": pulse if is_authorized else 0,
        "employee_name": emp.employee_name if emp else ""
    }


@frappe.whitelist()
def get_accessible_doors():
    """
    Returns only the devices/doors that the currently logged-in user / employee
    is authorized to see and unlock on their mobile dashboard.
    """
    if frappe.session.user == "Guest":
        return []

    user = frappe.session.user
    device_names = frappe.get_all(
        "Biometric Device",
        filters={"enabled": 1, "enable_access_control": 1},
        pluck="name",
        order_by="device_name asc"
    )

    authorized_doors = []
    for d_name in device_names:
        device = frappe.get_doc("Biometric Device", d_name)
        if device.is_user_authorized(user=user):
            authorized_doors.append({
                "name": device.name,
                "door_name": device.device_name,
                "door_type": getattr(device, "door_type", "Maglock Door") or "Maglock Door",
                "location": device.location or "Factory",
                "current_state": "Closed",
                "relay_pulse_seconds": getattr(device, "relay_pulse_seconds", 3) or 3
            })

    return authorized_doors


