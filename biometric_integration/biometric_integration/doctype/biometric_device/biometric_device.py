# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timedelta
import pytz
from frappe.utils import get_system_timezone, now_datetime
from frappe.model.document import Document
import xml.etree.ElementTree as ET
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin


class BiometricDevice(Document):
    def get_base_url(self):
        protocol = (self.protocol or "HTTP").lower()
        ip = self.ip.strip() if self.ip else ""
        if self.port and str(self.port).strip():
            return f"{protocol}://{ip}:{str(self.port).strip()}"
        return f"{protocol}://{ip}"

    def get_tz_offset(self):
        tz_name = self.timezone or get_system_timezone() or "UTC"
        try:
            tz = pytz.timezone(tz_name)
            offset = datetime.now(tz).strftime("%z")
            if len(offset) == 5:
                return f"{offset[:3]}:{offset[3:]}"
        except Exception:
            pass
        return "+00:00"

    def before_save(self):
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

                # Log lookup or creation
                bal = frappe.get_all(
                    "Biometric Attendance Log",
                    filters={"employee_no": emp_no, "event_date": event_datetime.date()},
                    limit_page_length=1,
                )

                if bal:
                    doc = frappe.get_doc("Biometric Attendance Log", bal[0].name)
                else:
                    doc = frappe.new_doc("Biometric Attendance Log")
                    doc.employee_no = emp_no
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
                    count += 1
                    log_direction = device.device_direction if device.device_direction in ("IN", "OUT") else None
                    create_employee_checkin(emp_no, event_datetime, log_type=log_direction, device_id=device.name)
                else:
                    skipped += 1

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
