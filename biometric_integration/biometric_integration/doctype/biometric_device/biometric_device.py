# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timedelta
try:
    import pytz
except ImportError:
    pytz = None
from frappe.utils import get_system_timezone, now_datetime
from frappe.model.document import Document
import xml.etree.ElementTree as ET
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin
from biometric_integration.biometric_integration.hikvision_isapi import (
    validate_door_schedule,
    sync_door_open_schedule,
    set_door_hardware_mode
)


class BiometricDevice(Document):
    def get_base_url(self):
        protocol = (self.protocol or "HTTP").lower()
        ip = self.ip.strip() if self.ip else ""
        if self.port and str(self.port).strip():
            return f"{protocol}://{ip}:{str(self.port).strip()}"
        return f"{protocol}://{ip}"

    def get_tz_offset(self):
        tz_name = self.timezone or get_system_timezone() or "UTC"
        if pytz:
            try:
                tz = pytz.timezone(tz_name)
                offset = datetime.now(tz).strftime("%z")
                if len(offset) == 5:
                    return f"{offset[:3]}:{offset[3:]}"
            except Exception:
                pass
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
            offset = datetime.now(tz).strftime("%z")
            if len(offset) == 5:
                return f"{offset[:3]}:{offset[3:]}"
        except Exception:
            pass
        return "+00:00"

    def validate(self):
        self.validate_door_schedule_settings()

    def validate_door_schedule_settings(self):
        """Strictly validates door open schedule times and intervals."""
        schedule_rows = self.get("door_open_schedule") or []
        enable_schedule = bool(getattr(self, "enable_free_passage", False))
        validate_door_schedule(schedule_rows, enable_free_passage=enable_schedule)

    @frappe.whitelist()
    def sync_door_schedule(self):
        """Pushes door open (free passage) schedule to Hikvision terminal."""
        if not self.enable_access_control:
            frappe.throw(frappe._("Access Control is not enabled for this device."))
        res = sync_door_open_schedule(self)
        if res.get("status") == "error":
            frappe.throw(res.get("message"))
        return res

    @frappe.whitelist()
    def set_door_mode(self, command):
        """Sets hardware door mode (open, alwaysOpen, alwaysClose, resume)."""
        if not self.enable_access_control:
            frappe.throw(frappe._("Access Control is not enabled for this device."))

        invoker = frappe.session.user
        res = set_door_hardware_mode(self, command)
        if res.get("status") == "error":
            frappe.throw(res.get("message"))

        # Log action to Door Access Log
        if frappe.db.table_exists("Door Access Log"):
            try:
                log = frappe.new_doc("Door Access Log")
                log.update({
                    "device": self.name,
                    "timestamp": now_datetime(),
                    "status": "Granted",
                    "access_method": f"Door Mode: {command}",
                    "details": f"Door mode '{command}' set by {invoker}"
                })
                log.insert(ignore_permissions=True)
            except Exception:
                pass

        return res

    def before_save(self):
        import secrets
        from frappe.utils import get_url

        # Ensure webhook token exists
        if not self.webhook_secret_key:
            self.webhook_secret_key = secrets.token_hex(12)

        # Generate copy-paste push endpoint URL
        site_url = get_url()
        self.webhook_endpoint_url = f"{site_url}/api/method/biometric_integration.api.push?token={self.webhook_secret_key}"

        # Ensure default cooldown
        if not self.punch_cooldown_minutes or self.punch_cooldown_minutes < 0:
            self.punch_cooldown_minutes = 5

        if not self.ip or not self.username:
            return

        password = self.get_password("password")
        if not password:
            return

        try:
            url = f"{self.get_base_url()}/ISAPI/System/deviceInfo"
            response = requests.get(
                url,
                auth=HTTPDigestAuth(self.username, password),
                timeout=2,
                verify=False
            )
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                ns = {'ns': 'http://www.isapi.org/ver20/XMLSchema'}
                self.device_id = root.find('ns:deviceID', ns).text if root.find('ns:deviceID', ns) is not None else ""
                self.model = root.find('ns:model', ns).text if root.find('ns:model', ns) is not None else ""
                self.device_serial_number = root.find('ns:serialNumber', ns).text if root.find('ns:serialNumber', ns) is not None else ""
                self.mac_address = root.find('ns:macAddress', ns).text if root.find('ns:macAddress', ns) is not None else ""
                self.status = "Online"
            else:
                self.status = "Offline"
        except Exception:
            # Device might be behind a remote NAT router or offline.
            # Never block saving the record.
            self.status = "Offline"

    def is_remote_user_authorized(self, user=None, return_reason=False, dt_obj=None):
        """
        Validates if a Frappe User has permission to trigger remote desk unlock.
        Checks Frappe User and Role permissions, gated by assigned Biometric Access Shift time intervals.
        Administrator and System Manager are exempt (24/7 access).
        """
        user = user or frappe.session.user

        # 1. Administrator and System Manager always have 24/7 emergency access
        if user == "Administrator":
            return (True, None) if return_reason else True
        user_roles = set(frappe.get_roles(user))
        if "System Manager" in user_roles:
            return (True, None) if return_reason else True

        # Helper to check shift time
        def check_shift(shift_name):
            if not shift_name:
                return True, None  # No shift set = 24/7 access
            try:
                shift_doc = frappe.get_cached_doc("Biometric Access Shift", shift_name)
                is_active, msg = shift_doc.is_active_now(dt_obj=dt_obj)
                return is_active, msg
            except Exception:
                return True, None

        # 2. Check specifically allowed Frappe Users
        matched_user_shifts = []
        user_matched = False
        for u in self.get("remote_allowed_users") or []:
            if getattr(u, "user", None) == user:
                user_matched = True
                shift_name = getattr(u, "access_shift", None)
                active, msg = check_shift(shift_name)
                if active:
                    return (True, None) if return_reason else True
                matched_user_shifts.append(msg)

        if user_matched and matched_user_shifts:
            reason = f"User '{user}' is not permitted to remotely unlock outside their assigned shift ({matched_user_shifts[0]})"
            return (False, reason) if return_reason else False

        # 3. Check allowed Frappe Roles
        matched_role_shifts = []
        role_matched = False
        for r in self.get("remote_allowed_roles") or []:
            role_name = getattr(r, "role", None)
            if role_name and role_name in user_roles:
                role_matched = True
                shift_name = getattr(r, "access_shift", None)
                active, msg = check_shift(shift_name)
                if active:
                    return (True, None) if return_reason else True
                matched_role_shifts.append((role_name, msg))

        if role_matched and matched_role_shifts:
            reasons = "; ".join([f"{r}: {m}" for r, m in matched_role_shifts])
            reason = f"Remote unlock outside allowed hours ({reasons})"
            return (False, reason) if return_reason else False

        reason = "User is not authorized for remote unlock on this door."
        return (False, reason) if return_reason else False

    def get_employee_plan_template_no(self, employee_doc):
        """
        Determines the Hikvision planTemplateNo for an authorized employee.
        Checks matching allowed_employees or allowed_access_roles row for an access_shift.
        """
        emp_name = employee_doc.get("name") if hasattr(employee_doc, "get") else getattr(employee_doc, "name", None)

        # 1. Check direct employee override row
        for e in self.get("allowed_employees") or []:
            if getattr(e, "employee", None) == emp_name:
                shift_name = getattr(e, "access_shift", None)
                if shift_name:
                    return self._get_plan_no_from_shift(shift_name)

        # 2. Check matching access role row
        door_role_map = {r.access_role: getattr(r, "access_shift", None) for r in self.get("allowed_access_roles") or [] if getattr(r, "access_role", None)}
        if door_role_map:
            emp_roles = employee_doc.get("custom_biometric_access_roles") or []
            for r in emp_roles:
                r_name = r.get("access_role") if hasattr(r, "get") else getattr(r, "access_role", None)
                if r_name in door_role_map:
                    shift_name = door_role_map[r_name]
                    if shift_name:
                        return self._get_plan_no_from_shift(shift_name)

        return 1

    def _get_plan_no_from_shift(self, shift_name):
        try:
            return frappe.db.get_value("Biometric Access Shift", shift_name, "hikvision_plan_no") or 1
        except Exception:
            return 1

    def is_employee_physically_authorized(self, employee_doc=None, employee_name=None):
        """
        Validates if an Employee has physical access authorization to be provisioned
        on this physical biometric terminal (Face, Card, PIN).
        """
        emp = employee_doc
        if not emp and employee_name:
            emp = frappe.get_doc("Employee", employee_name)

        if not emp:
            return False

        # Status must be Active
        status = emp.get("status") if hasattr(emp, "get") else getattr(emp, "status", None)
        if status != "Active":
            return False

        # Exemption check
        is_exempt = emp.get("custom_biometric_exempt") if hasattr(emp, "get") else getattr(emp, "custom_biometric_exempt", 0)
        if is_exempt:
            return False

        # 1. Open to all active employees on this physical terminal
        if getattr(self, "allow_all_active_employees", False):
            return True

        # 2. Check individual employee overrides (one-off access exceptions)
        emp_name = emp.get("name") if hasattr(emp, "get") else getattr(emp, "name", None)
        allowed_emps = {e.employee for e in self.get("allowed_employees") or [] if getattr(e, "employee", None)}
        if emp_name in allowed_emps:
            return True

        # 3. Check matching physical Biometric Access Roles
        door_roles = {r.access_role for r in self.get("allowed_access_roles") or [] if getattr(r, "access_role", None)}
        if door_roles:
            emp_roles_list = emp.get("custom_biometric_access_roles") or []
            emp_roles = set()
            for r in emp_roles_list:
                role_val = r.get("access_role") if hasattr(r, "get") else getattr(r, "access_role", None)
                if role_val:
                    emp_roles.add(role_val)
            if emp_roles.intersection(door_roles):
                return True

        return False

    def is_user_authorized(self, user=None, employee_doc=None):
        """Backward-compatible alias: physical check if employee given, else remote check."""
        if employee_doc:
            return self.is_employee_physically_authorized(employee_doc=employee_doc)
        return self.is_remote_user_authorized(user=user)

    @frappe.whitelist()
    def unlock_door(self, source="Remote Desk Unlock", user=None):
        """
        Triggers a remote unlock pulse on this device's relay (Built-in ISAPI or External Shelly).
        """
        if not self.enable_access_control:
            frappe.throw(frappe._("Door Access Control is not enabled on this device."))

        invoker = user or frappe.session.user
        if not self.is_remote_user_authorized(invoker):
            frappe.throw(frappe._("User {0} is not authorized to remotely unlock {1}.").format(invoker, self.name), frappe.PermissionError)

        # 1. Trigger Built-in Terminal Relay via Hikvision ISAPI
        if getattr(self, "relay_control_type", None) == "Built-in Terminal Relay (Hikvision ISAPI)" or not self.relay_control_type:
            password = self.get_password("password")
            if not self.ip:
                frappe.throw(frappe._("Device IP is unknown yet. Please wait for the device to connect/send an event, or enter its local IP manually."))
            if not self.username or not password:
                frappe.throw(frappe._("Device username and password are required to trigger unlock."))

            url = f"{self.get_base_url()}/ISAPI/AccessControl/RemoteControl/door/1"
            headers = {"Content-Type": "application/xml"}
            payload = "<RemoteControlDoor><cmd>open</cmd></RemoteControlDoor>"

            try:
                resp = requests.put(
                    url,
                    data=payload,
                    headers=headers,
                    auth=HTTPDigestAuth(self.username, password),
                    timeout=5,
                    verify=False
                )
                if resp.status_code not in (200, 204):
                    frappe.throw(frappe._("Hikvision terminal returned error status {0}: {1}").format(resp.status_code, resp.text[:200]))
            except Exception as e:
                frappe.throw(frappe._("Failed to connect to Hikvision terminal at {0}: {1}").format(self.ip, str(e)))

        # 2. Trigger External Relay (Shelly Plus / Pro / Dry Contact / Classic)
        elif "Shelly" in (self.relay_control_type or ""):
            relay_ip = (getattr(self, "external_relay_ip", None) or self.ip or "").strip()
            if not relay_ip:
                frappe.throw(frappe._("External Relay IP / Hostname is required for Shelly relay."))

            relay_host = relay_ip.replace("http://", "").replace("https://", "").rstrip("/")
            channel = getattr(self, "external_relay_channel", 0) or 0
            pulse_sec = getattr(self, "relay_pulse_seconds", 3) or 3

            # Shelly Gen 2 / Gen 3 / Pro (including Shelly Pro 1/2 Dry Contacts) uses RPC Switch.Set
            rpc_url = f"http://{relay_host}/rpc/Switch.Set?id={channel}&on=true&toggle_after={pulse_sec}"
            try:
                resp = requests.get(rpc_url, timeout=5)
                # Fallback to Gen 1 legacy endpoint if 404
                if resp.status_code == 404:
                    legacy_url = f"http://{relay_host}/relay/{channel}?turn=on&timer={pulse_sec}"
                    resp = requests.get(legacy_url, timeout=5)

                if resp.status_code not in (200, 204):
                    frappe.throw(frappe._("Shelly relay at {0} returned error {1}: {2}").format(relay_host, resp.status_code, resp.text[:200]))
            except Exception as e:
                frappe.throw(frappe._("Failed to connect to Shelly relay at {0}: {1}").format(relay_host, str(e)))

        # 3. Trigger External Relay (ESP32 / Custom HTTP)
        elif "ESP32" in (self.relay_control_type or "") or "Custom HTTP" in (self.relay_control_type or ""):
            relay_target = (getattr(self, "external_relay_ip", None) or self.ip or "").strip()
            if not relay_target:
                frappe.throw(frappe._("External Relay IP / URL is required for ESP32 relay."))

            channel = getattr(self, "external_relay_channel", 0) or 0
            pulse_sec = getattr(self, "relay_pulse_seconds", 3) or 3

            if not relay_target.startswith("http://") and not relay_target.startswith("https://"):
                base_url = f"http://{relay_target}"
            else:
                base_url = relay_target.rstrip("/")

            # If full URL endpoint path not specified, use default /unlock
            if base_url.count("/") <= 2:
                url = f"{base_url}/unlock"
            else:
                url = base_url

            try:
                resp = requests.get(url, params={"pulse": pulse_sec, "channel": channel}, timeout=5)
                if resp.status_code not in (200, 204):
                    if resp.status_code in (404, 405):
                        resp = requests.post(url, json={"pulse": pulse_sec, "channel": channel, "command": "unlock"}, timeout=5)
                    if resp.status_code not in (200, 204):
                        frappe.throw(frappe._("ESP32 relay at {0} returned error {1}: {2}").format(url, resp.status_code, resp.text[:200]))
            except Exception as e:
                frappe.throw(frappe._("Failed to connect to ESP32 relay at {0}: {1}").format(url, str(e)))

        # Update last unlock
        now = now_datetime()
        self.db_set("last_unlock_time", now)
        self.db_set("last_unlock_user", invoker)

        # Log to Door Access Log
        if frappe.db.table_exists("Door Access Log"):
            try:
                log = frappe.new_doc("Door Access Log")
                log.update({
                    "device": self.name,
                    "timestamp": now,
                    "status": "Granted",
                    "access_method": source,
                    "details": f"Remote unlock triggered by {invoker}"
                })
                log.insert(ignore_permissions=True)
            except Exception:
                pass

        return {"status": "success", "message": frappe._("Door unlock pulse triggered successfully!")}


@frappe.whitelist()
def check_device_connection(device_name):
    doc = frappe.get_doc("Biometric Device", device_name)
    password = doc.get_password("password")
    if not password:
        return {"status": "error", "message": "Password is required."}

    try:
        url = f"{doc.get_base_url()}/ISAPI/AccessControl/AcsEvent?format=json"
        headers = {"Content-Type": "application/json"}
        now = datetime.now().strftime("%Y-%m-%d")
        tz_offset = doc.get_tz_offset()

        payload = {
            "AcsEventCond": {
                "searchID": "connection-check",
                "searchResultPosition": 0,
                "maxResults": 1,
                "major": 5,
                "minor": 75,
                "startTime": f"{now}T00:00:00{tz_offset}",
                "endTime": f"{now}T23:59:59{tz_offset}",
            }
        }

        response = requests.post(
            url,
            auth=HTTPDigestAuth(doc.username, password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=15,
        )

        if response.status_code == 200:
            doc.db_set("status", "Online")
            return {
                "status": "success",
                "message": f"Connected successfully to {doc.get_base_url()}",
                "details": f"Device {doc.name} responded with status 200."
            }
        else:
            doc.db_set("status", "Offline")
            return {
                "status": "error",
                "message": f"Connection failed (HTTP {response.status_code})",
                "details": response.text
            }
    except Exception as e:
        doc.db_set("status", "Offline")
        return {"status": "error", "message": "Connection error", "details": str(e)}


@frappe.whitelist()
def fetch_device_info(device_name):
    doc = frappe.get_doc("Biometric Device", device_name)
    doc.before_save()
    doc.save(ignore_permissions=True)
    return {"status": "success", "message": f"Device info updated. Status: {doc.status}"}


@frappe.whitelist()
def sync_device_attendance(device_name, from_date=None, from_time=None, to_date=None, to_time=None):
    device = frappe.get_doc("Biometric Device", device_name)
    if not device.enabled:
        frappe.throw(f"Device {device_name} is disabled.")

    password = device.get_password("password")
    base_url = device.get_base_url()
    tz_offset = device.get_tz_offset()
    url = f"{base_url}/ISAPI/AccessControl/AcsEvent?format=json"

    _from_date = from_date or datetime.now().strftime("%Y-%m-%d")
    _from_time = from_time or "00:00:00"
    _to_date = to_date or datetime.now().strftime("%Y-%m-%d")
    _to_time = to_time or "23:59:59"

    start_time = datetime.strptime(f"{_from_date} {_from_time}", "%Y-%m-%d %H:%M:%S").strftime(f"%Y-%m-%dT%H:%M:%S{tz_offset}")
    end_time = datetime.strptime(f"{_to_date} {_to_time}", "%Y-%m-%d %H:%M:%S").strftime(f"%Y-%m-%dT%H:%M:%S{tz_offset}")

    headers = {"Content-Type": "application/json"}
    payload = {
        "AcsEventCond": {
            "searchID": f"sync-{device_name}",
            "searchResultPosition": 0,
            "maxResults": 1,
            "major": 5,
            "minor": 75,
            "startTime": start_time,
            "endTime": end_time,
        }
    }

    try:
        response = requests.post(
            url,
            auth=HTTPDigestAuth(device.username, password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=60,
        )

        if response.status_code != 200:
            device.db_set("status", "Offline")
            frappe.throw(f"Failed to fetch logs from {device_name}. Status: {response.status_code}")

        data = response.json()
        total_records = data.get("AcsEvent", {}).get("totalMatches", 0)

        if total_records == 0:
            device.db_set("status", "Online")
            device.db_set("last_sync", now_datetime())
            return f"No attendance records found for {device_name} in the given period."

        count = 0
        skipped = 0
        position = 0
        batch_size = 50
        name_cache = {}

        while True:
            payload["AcsEventCond"]["searchResultPosition"] = position
            payload["AcsEventCond"]["maxResults"] = batch_size

            response = requests.post(
                url,
                auth=HTTPDigestAuth(device.username, password),
                headers=headers,
                json=payload,
                verify=False,
                timeout=60,
            )

            if response.status_code != 200:
                break

            events = response.json().get("AcsEvent", {}).get("InfoList", [])
            if not events:
                break

            for log in events:
                emp_no = log.get("employeeNoString")
                event_timestamp = log.get("time", "")
                if not emp_no or not event_timestamp:
                    continue

                event_datetime = datetime.strptime(event_timestamp[:19], "%Y-%m-%dT%H:%M:%S")

                # Name lookup
                emp_name = name_cache.get(str(emp_no))
                if not emp_name:
                    emp_name = frappe.db.get_value("Employee", {"attendance_device_id": str(emp_no)}, "employee_name") or ""
                    name_cache[str(emp_no)] = emp_name

                log_direction = device.device_direction if device.device_direction in ("IN", "OUT") else None
                checkin_id = create_employee_checkin(
                    emp_no,
                    event_datetime,
                    log_type=log_direction,
                    device_id=device.name,
                    cooldown_minutes=5
                )
                if checkin_id:
                    count += 1

            position += len(events)
            if position % 200 == 0:
                frappe.db.commit()

            if len(events) < batch_size:
                break

        device.db_set("status", "Online")
        device.db_set("last_sync", now_datetime())
        frappe.db.commit()

        return f"[{device_name}] Synced {count} punches. Skipped {skipped} duplicates."

    except Exception as e:
        device.db_set("status", "Offline")
        frappe.throw(f"Error syncing {device_name}: {str(e)}")


@frappe.whitelist()
def sync_all_active_devices(from_date=None, from_time=None, to_date=None, to_time=None):
    """Sync attendance from all active Biometric Devices."""
    active_devices = frappe.get_all("Biometric Device", filters={"enabled": 1}, pluck="name")
    results = []

    for dev_name in active_devices:
        try:
            res = sync_device_attendance(dev_name, from_date, from_time, to_date, to_time)
            results.append(res)
        except Exception as e:
            results.append(f"[{dev_name}] Failed: {str(e)}")

    return "\n".join(results) if results else "No active devices found."
