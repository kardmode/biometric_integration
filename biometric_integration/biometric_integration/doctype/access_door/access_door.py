# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
import requests
from requests.auth import HTTPDigestAuth
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class AccessDoor(Document):
    def is_user_authorized(self, user=None, employee_doc=None):
        """
        Validates if the user or employee has authorization for this door.
        """
        user = user or frappe.session.user
        
        # 1. System Manager always has access
        if "System Manager" in frappe.get_roles(user):
            return True

        # Resolve employee
        emp = employee_doc
        if not emp and user != "Guest":
            emp = frappe.db.get_value(
                "Employee",
                {"user_id": user},
                ["name", "employee_name", "status"],
                as_dict=True
            )

        if not emp or emp.get("status") != "Active":
            return False

        # 2. If open to all active employees (e.g. Main Gate)
        if self.allow_all_active_employees:
            return True

        # 3. Check allowed roles
        user_roles = set(frappe.get_roles(user))
        allowed_roles = {r.role for r in self.get("allowed_roles") or []}
        if user_roles.intersection(allowed_roles):
            return True

        # 4. Check specific allowed employees
        allowed_emps = {e.employee for e in self.get("allowed_employees") or []}
        if emp.get("name") in allowed_emps:
            return True

        return False

    def unlock(self, source="Mobile Web Button", user=None, skip_auth_check=False):
        """
        Sends an unlock pulse to the controller (Shelly, ESP32, Hikvision, or custom relay)
        and creates an audit log entry in Door Access Log.
        """
        if not self.enabled:
            frappe.throw(_("Door {0} is currently disabled.").format(self.door_name))

        user_name = user or frappe.session.user
        emp = frappe.db.get_value("Employee", {"user_id": user_name}, ["name", "employee_name", "status"], as_dict=True)

        # Check authorization
        if not skip_auth_check and not self.is_user_authorized(user=user_name, employee_doc=emp):
            # Log denied attempt
            log = frappe.get_doc({
                "doctype": "Door Access Log",
                "door": self.name,
                "timestamp": now_datetime(),
                "employee": emp.name if emp else None,
                "employee_name": emp.employee_name if emp else user_name,
                "access_method": source,
                "status": "Denied",
                "details": "Unauthorized: User does not have permission for this door."
            })
            log.insert(ignore_permissions=True)
            frappe.throw(_("You do not have permission to unlock {0}.").format(self.door_name), frappe.PermissionError)

        pulse = float(self.relay_pulse_seconds or 3.0)
        success = False
        error_msg = ""

        try:
            if self.controller_type == "Shelly Plus 1 (HTTP)":
                success, error_msg = self._trigger_shelly_http(pulse)
            elif self.controller_type == "ESP32 Controller":
                success, error_msg = self._trigger_esp32_http(pulse)
            elif self.controller_type == "Hikvision ISAPI":
                success, error_msg = self._trigger_hikvision_isapi(pulse)
            elif self.controller_type == "Shelly (MQTT)":
                success, error_msg = self._trigger_mqtt(pulse)
            elif self.controller_type == "Custom Webhook":
                success, error_msg = self._trigger_custom_webhook(pulse)
            else:
                error_msg = f"Unsupported controller type: {self.controller_type}"
        except Exception as e:
            error_msg = str(e)
            frappe.log_error(title=f"AccessDoor Unlock Error: {self.door_name}", message=frappe.get_traceback())

        # Log the access attempt
        log = frappe.get_doc({
            "doctype": "Door Access Log",
            "door": self.name,
            "timestamp": now_datetime(),
            "employee": emp.name if emp else None,
            "employee_name": emp.employee_name if emp else (user_name if user_name != "Guest" else "Anonymous"),
            "access_method": source,
            "status": "Granted" if success else "Denied",
            "details": f"Relay pulse: {pulse}s" if success else f"Failed: {error_msg}"
        })
        log.insert(ignore_permissions=True)

        if not success:
            frappe.throw(_("Failed to trigger door {0}: {1}").format(self.door_name, error_msg))

        return {
            "status": "success",
            "message": _("{0} Unlocked ({1}s)!").format(self.door_name, pulse),
            "door": self.name,
            "duration": pulse
        }

    def trigger_shutter(self, source="Mobile Web Button", user=None):
        """
        Specialized trigger for motorized rolling shutters. Sends a short momentary pulse (0.5s)
        to cycle the motor: Down -> Stop -> Up.
        """
        original_pulse = self.relay_pulse_seconds
        self.relay_pulse_seconds = 0.5
        try:
            res = self.unlock(source=source or "Shutter Toggle", user=user)
            res["message"] = _("{0} Toggled!").format(self.door_name)
            return res
        finally:
            self.relay_pulse_seconds = original_pulse

    def update_sensor_state(self, is_open):
        """
        Called when a door contact / floor reed sensor reports state change.
        """
        new_state = "Open" if is_open else "Closed"
        prev_state = self.current_state

        self.current_state = new_state
        self.last_state_change = now_datetime()
        self.save(ignore_permissions=True)

        if prev_state != new_state:
            log = frappe.get_doc({
                "doctype": "Door Access Log",
                "door": self.name,
                "timestamp": now_datetime(),
                "access_method": "Door Position Sensor",
                "status": "Door Opened" if is_open else "Door Closed",
                "details": f"Sensor state changed: {prev_state} -> {new_state}"
            })
            log.insert(ignore_permissions=True)

    def _trigger_shelly_http(self, pulse):
        if not self.ip_address:
            return False, "IP address / Hostname is missing"

        base_ip = self.ip_address.strip().rstrip("/")
        if not base_ip.startswith("http://") and not base_ip.startswith("https://"):
            base_ip = f"http://{base_ip}"

        auth = None
        password = self.get_password("http_auth_token") if hasattr(self, "get_password") else None
        if password:
            auth = ("admin", password)

        # 1. Gen 2/3 RPC
        rpc_url = f"{base_ip}/rpc/Switch.Set"
        try:
            resp = requests.get(rpc_url, params={"id": 0, "on": True, "toggle_after": pulse}, auth=auth, timeout=3)
            if resp.status_code == 200:
                return True, ""
        except Exception:
            pass

        # 2. Gen 1 Fallback
        gen1_url = f"{base_ip}/relay/0"
        try:
            resp = requests.get(gen1_url, params={"turn": "on", "timer": pulse}, auth=auth, timeout=3)
            if resp.status_code == 200:
                return True, ""
            return False, f"HTTP Status {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            return False, str(e)

    def _trigger_hikvision_isapi(self, pulse):
        """
        Controls future Hikvision Face Terminals or Access Controllers via ISAPI.
        Endpoint: PUT /ISAPI/AccessControl/RemoteControl/door/<door_no>
        """
        if not self.ip_address:
            return False, "Hikvision IP address is missing"

        ip = self.ip_address.strip().rstrip("/")
        port = str(self.port or 80).strip()
        url = f"http://{ip}:{port}/ISAPI/AccessControl/RemoteControl/door/{self.door_no or 1}"
        password = self.get_password("password") if hasattr(self, "get_password") else None

        xml_body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<RemoteControlDoor xmlns="http://www.isapi.org/ver20/XMLSchema" version="2.0">'
            '<cmd>open</cmd>'
            '</RemoteControlDoor>'
        )

        try:
            resp = requests.put(
                url,
                data=xml_body,
                headers={"Content-Type": "application/xml"},
                auth=HTTPDigestAuth(self.username, password) if self.username and password else None,
                timeout=5,
                verify=False
            )
            if resp.status_code in [200, 204] or "OK" in resp.text:
                return True, ""
            return False, f"ISAPI error {resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            return False, str(e)

    def _trigger_esp32_http(self, pulse):
        if not self.ip_address:
            return False, "IP address is missing"

        base_ip = self.ip_address.strip().rstrip("/")
        if not base_ip.startswith("http://") and not base_ip.startswith("https://"):
            base_ip = f"http://{base_ip}"

        try:
            resp = requests.get(f"{base_ip}/unlock", params={"pulse": pulse}, timeout=3)
            if resp.status_code == 200:
                return True, ""
            return False, f"ESP32 HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def _trigger_mqtt(self, pulse):
        topic = self.mqtt_topic or f"factory/door/{self.name}/command"
        payload = {"action": "unlock", "pulse": pulse}
        frappe.publish_realtime("access_door_mqtt", {"topic": topic, "payload": payload})
        return True, ""

    def _trigger_custom_webhook(self, pulse):
        if not self.ip_address:
            return False, "Webhook URL is missing"
        resp = requests.post(self.ip_address, json={"door": self.name, "pulse": pulse}, timeout=4)
        return resp.status_code in [200, 201, 204], resp.text[:100]
