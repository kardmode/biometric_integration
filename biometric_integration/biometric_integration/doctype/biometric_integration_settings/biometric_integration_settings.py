# Copyright (c) 2025, NDV and contributors
# For license information, please see license.txt

import frappe
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timedelta
import pytz
from frappe.utils import get_system_timezone
from frappe.model.document import Document
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin


def get_device_base_url(settings):
    """Construct base URL using configured protocol, IP, and optional port."""
    protocol = (getattr(settings, "protocol", None) or "HTTP").lower()
    ip = settings.ip.strip() if settings.ip else ""
    port = getattr(settings, "port", None)
    if port and str(port).strip():
        return f"{protocol}://{ip}:{str(port).strip()}"
    return f"{protocol}://{ip}"


def get_device_tz_offset(settings=None):
    """Determine ISO-8601 timezone offset (e.g., +04:00, +05:30) dynamically."""
    tz_name = (settings and getattr(settings, "timezone", None)) or get_system_timezone() or "UTC"
    try:
        tz = pytz.timezone(tz_name)
        offset = datetime.now(tz).strftime("%z")  # e.g., '+0530', '+0800', '-0500'
        if len(offset) == 5:
            return f"{offset[:3]}:{offset[3:]}"
    except Exception:
        pass
    return "+00:00"


class BiometricIntegrationSettings(Document):
    def before_save(self):
        if not self.webhook_secret_key:
            self.webhook_secret_key = frappe.generate_hash(length=24)

        site_url = frappe.utils.get_url()
        self.webhook_endpoint_url = f"{site_url}/api/method/biometric_integration.biometric_integration.api.hikvision_event_receiver?token={self.webhook_secret_key}"

        try:
            if not self.ip or not self.username:
                return

            password = self.get_password("password")
            if not password:
                return

            base_url = get_device_base_url(self)
            url = f"{base_url}/ISAPI/System/deviceInfo"

            response = requests.get(
                url,
                auth=HTTPDigestAuth(self.username, password),
                timeout=10,
                verify=False
            )

            if response.status_code != 200:
                return

            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)
            ns = {'ns': 'http://www.isapi.org/ver20/XMLSchema'}

            self.device_name = root.find('ns:deviceName', ns).text if root.find('ns:deviceName', ns) is not None else ""
            self.device_id = root.find('ns:deviceID', ns).text if root.find('ns:deviceID', ns) is not None else ""
            self.model = root.find('ns:model', ns).text if root.find('ns:model', ns) is not None else ""
            self.device_serial_number = root.find('ns:serialNumber', ns).text if root.find('ns:serialNumber', ns) is not None else ""
            self.mac_address = root.find('ns:macAddress', ns).text if root.find('ns:macAddress', ns) is not None else ""

        except Exception as e:
            frappe.log_error(f"Device info fetch failed: {str(e)}", "Biometric Device Info")


@frappe.whitelist()
def generate_webhook_key():
    doc = frappe.get_doc("Biometric Integration Settings", "Biometric Integration Settings")
    doc.webhook_secret_key = frappe.generate_hash(length=24)
    site_url = frappe.utils.get_url()
    doc.webhook_endpoint_url = f"{site_url}/api/method/biometric_integration.biometric_integration.api.hikvision_event_receiver?token={doc.webhook_secret_key}"
    doc.save(ignore_permissions=True)
    return {
        "status": "success",
        "webhook_secret_key": doc.webhook_secret_key,
        "webhook_endpoint_url": doc.webhook_endpoint_url
    }


@frappe.whitelist()
def fetch_device_info():
    doc = frappe.get_doc("Biometric Integration Settings", "Biometric Integration Settings")
    doc.before_save()
    doc.save(ignore_permissions=True)

    return {
        "status": "success",
        "message": "Device info updated successfully"
    }


@frappe.whitelist()
def get_employee_face(emp_no):
    try:
        settings = frappe.get_doc("Biometric Integration Settings", "Biometric Integration Settings")
        password = settings.get_password("password")
        base_url = get_device_base_url(settings)

        url = f"{base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
        headers = {"Content-Type": "application/json"}

        payload = {
            "UserInfoSearchCond": {
                "searchID": "face-fetch",
                "searchResultPosition": 0,
                "maxResults": 1,
                "EmployeeNoList": [{"employeeNo": str(emp_no)}]
            }
        }

        response = requests.post(
            url,
            auth=HTTPDigestAuth(settings.username, password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=30,
        )

        if response.status_code != 200:
            return {"status": "error", "message": f"HTTP {response.status_code}"}

        data = response.json()
        user_info = data.get("UserInfoSearch", {}).get("UserInfo", [])

        if not user_info:
            return {"status": "error", "message": "Employee not found"}

        face_url = user_info[0].get("faceURL")
        face_data = user_info[0].get("faceData")

        if face_url:
            return {"status": "success", "type": "url", "data": face_url}

        if face_data:
            return {"status": "success", "type": "base64", "data": face_data}

        return {"status": "error", "message": "No face found"}

    except Exception as e:
        frappe.log_error(f"Face fetch failed: {str(e)}", "Biometric Face Fetch")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def check_machine_connection():
    try:
        settings = frappe.get_doc("Biometric Integration Settings", "Biometric Integration Settings")

        if not settings.ip or not settings.username:
            return {
                "status": "error",
                "message": "Please set IP and Username first.",
                "details": "Machine credentials are incomplete.",
            }

        password = settings.get_password("password")
        if not password:
            return {
                "status": "error",
                "message": "Please set Password first.",
                "details": "Machine password is missing.",
            }

        base_url = get_device_base_url(settings)
        tz_offset = get_device_tz_offset(settings)
        url = f"{base_url}/ISAPI/AccessControl/AcsEvent?format=json"
        headers = {"Content-Type": "application/json"}
        now = datetime.now().strftime("%Y-%m-%d")

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
            auth=HTTPDigestAuth(settings.username, password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=30,
        )

        if response.status_code == 200:
            return {
                "status": "success",
                "message": "Connection successful.",
                "details": f"Connected to {base_url}. Device response status: 200.",
            }

        return {
            "status": "error",
            "message": "Connection failed.",
            "details": f"HTTP {response.status_code}: {response.text}",
        }

    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": "Connection failed due to network/timeout issue.",
            "details": str(e),
        }
    except Exception as e:
        frappe.log_error(f"Machine connection check failed: {str(e)}", "Biometric Machine Connection Check")
        return {
            "status": "error",
            "message": "Connection check failed.",
            "details": str(e),
        }


def _get_employee_name_from_device(settings, password, emp_no):
    base_url = get_device_base_url(settings)
    url = f"{base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
    headers = {"Content-Type": "application/json"}

    payloads = [
        {
            "UserInfoSearchCond": {
                "searchID": "1",
                "searchResultPosition": 0,
                "maxResults": 1,
                "EmployeeNoList": [{"employeeNo": str(emp_no)}],
            }
        },
        {
            "UserInfoSearchCond": {
                "searchID": "1",
                "searchResultPosition": 0,
                "maxResults": 1,
                "employeeNoList": [{"employeeNo": str(emp_no)}],
            }
        },
    ]

    for payload in payloads:
        try:
            response = requests.post(
                url,
                auth=HTTPDigestAuth(settings.username, password),
                headers=headers,
                json=payload,
                verify=False,
                timeout=10,
            )
            if response.status_code != 200:
                continue

            data = response.json()
            user_info = data.get("UserInfoSearch", {}).get("UserInfo", [])
            if user_info and user_info[0].get("name"):
                return user_info[0].get("name")
        except Exception:
            continue

    return ""


@frappe.whitelist()
def set_employee_name_on_device(emp_no, emp_name=None):
    try:
        settings = frappe.get_doc("Biometric Integration Settings", "Biometric Integration Settings")
        password = settings.get_password("password")
        base_url = get_device_base_url(settings)

        if not emp_no:
            return {"status": "error", "message": "Employee No is required"}

        url = f"{base_url}/ISAPI/AccessControl/UserInfo/Modify?format=json"
        headers = {"Content-Type": "application/json"}

        name_value = str(emp_name) if emp_name else ""

        payload = {
            "UserInfo": {
                "employeeNo": str(emp_no),
                "name": name_value
            }
        }

        response = requests.put(
            url,
            auth=HTTPDigestAuth(settings.username, password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=30,
        )

        if response.status_code == 200:
            if name_value:
                return {"status": "success", "message": f"Name '{name_value}' updated for employee {emp_no}"}
            else:
                return {"status": "success", "message": f"Name removed for employee {emp_no}"}

        return {"status": "error", "message": f"Device returned HTTP {response.status_code}: {response.text}"}

    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"Network error: {str(e)}"}
    except Exception as e:
        frappe.log_error(f"Set employee name failed: {str(e)}", "Biometric Set Employee Name")
        return {"status": "error", "message": str(e)}


def _get_employee_name(settings, password, emp_no, name_cache=None):
    cache = name_cache if isinstance(name_cache, dict) else {}
    cache_key = str(emp_no)

    if cache_key in cache:
        return cache[cache_key]

    # Fast lookup in local ERPNext Employee records first
    local_name = frappe.db.get_value("Employee", {"attendance_device_id": cache_key}, "employee_name")
    if local_name:
        cache[cache_key] = local_name
        return local_name

    employee_name = _get_employee_name_from_device(settings, password, emp_no)
    employee_name = employee_name or ""
    cache[cache_key] = employee_name
    return employee_name


@frappe.whitelist()
def sync_attendance(from_date=None, from_time=None, to_date=None, to_time=None):
    try:
        settings = frappe.get_doc("Biometric Integration Settings", "Biometric Integration Settings")
        base_url = get_device_base_url(settings)
        tz_offset = get_device_tz_offset(settings)
        url = f"{base_url}/ISAPI/AccessControl/AcsEvent?format=json"
        decrypted_password = settings.get_password("password")

        _from_date = from_date or (getattr(settings, "start_date_and_time", None) and settings.start_date_and_time.split(" ")[0]) or datetime.now().strftime("%Y-%m-%d")
        _from_time = from_time or "00:00:00"
        _to_date = to_date or (getattr(settings, "end_date_and_time", None) and settings.end_date_and_time.split(" ")[0]) or datetime.now().strftime("%Y-%m-%d")
        _to_time = to_time or "23:59:59"

        start_time = datetime.strptime(f"{_from_date} {_from_time}", "%Y-%m-%d %H:%M:%S").strftime(f"%Y-%m-%dT%H:%M:%S{tz_offset}")
        end_time = datetime.strptime(f"{_to_date} {_to_time}", "%Y-%m-%d %H:%M:%S").strftime(f"%Y-%m-%dT%H:%M:%S{tz_offset}")

        headers = {"Content-Type": "application/json"}

        payload = {
            "AcsEventCond": {
                "searchID": "attendance-sync",
                "searchResultPosition": 0,
                "maxResults": 1,
                "major": 5,
                "minor": 75,
                "startTime": start_time,
                "endTime": end_time,
            }
        }

        response = requests.post(
            url,
            auth=HTTPDigestAuth(settings.username, decrypted_password),
            headers=headers,
            json=payload,
            verify=False,
            timeout=60,
        )

        if response.status_code != 200:
            frappe.throw(f"Failed to connect to device. Status: {response.status_code}, Response: {response.text}")

        data = response.json()
        total_records = data.get("AcsEvent", {}).get("totalMatches", 0)

        if total_records == 0:
            return "No attendance records found for the given time period."

        count = 0
        skipped = 0
        employee_name_cache = {}
        position = 0
        batch_size = 50

        frappe.publish_progress(0, title="Attendance Sync", description=f"Found {total_records} records. Starting sync...")

        while True:
            payload["AcsEventCond"]["searchResultPosition"] = position
            payload["AcsEventCond"]["maxResults"] = batch_size

            response = requests.post(
                url,
                auth=HTTPDigestAuth(settings.username, decrypted_password),
                headers=headers,
                json=payload,
                verify=False,
                timeout=60,
            )

            if response.status_code != 200:
                frappe.publish_progress(100, title="Attendance Sync", description=f"Sync interrupted at position {position}.")
                frappe.throw(f"Failed to fetch logs at position {position}. Status: {response.status_code}")

            data = response.json()
            events = data.get("AcsEvent", {}).get("InfoList", [])

            if not events:
                break

            for log in events:
                emp_no = log.get("employeeNoString")
                event_timestamp = log.get("time", "")
                if not emp_no or not event_timestamp:
                    continue

                event_datetime = datetime.strptime(event_timestamp[:19], "%Y-%m-%dT%H:%M:%S")
                employee_name = _get_employee_name(settings, decrypted_password, emp_no, employee_name_cache)

                attendance_log = frappe.get_all(
                    "Biometric Attendance Log",
                    filters={"employee_no": emp_no, "event_date": event_datetime.date()},
                    limit_page_length=1,
                )

                if attendance_log:
                    doc = frappe.get_doc("Biometric Attendance Log", attendance_log[0].name)
                else:
                    doc = frappe.new_doc("Biometric Attendance Log")
                    doc.employee_no = emp_no
                    doc.event_date = event_datetime.date()

                if employee_name:
                    doc.employee_name = employee_name

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
                    try:
                        doc.save(ignore_permissions=True)
                        count += 1
                        create_employee_checkin(emp_no, event_datetime, log_type=None, device_id=settings.device_name or settings.ip)
                    except Exception as e:
                        frappe.log_error(f"Insert failed for employee {emp_no}: {str(e)}", "Biometric Punch Insert Error")
                        continue
                else:
                    skipped += 1

            position += len(events)
            progress_pct = min(100, int((position / total_records) * 100)) if total_records else 100
            frappe.publish_progress(progress_pct, title="Attendance Sync", description=f"Processed {position}/{total_records} records...")

            # Periodic commit to free lock buffer for large datasets
            if position % 200 == 0:
                frappe.db.commit()

            if len(events) < batch_size:
                break

        frappe.db.commit()
        frappe.publish_progress(100, title="Attendance Sync", description="Sync completed!")
        return f"{count} attendance records synced successfully. {skipped} duplicate punches skipped."

    except Exception as e:
        frappe.throw(f"Error syncing attendance: {str(e)}")


def scheduled_attendance_sync():
    try:
        today_date = datetime.now().date()
        yesterday_date = today_date - timedelta(days=1)
        day_before_yesterday_date = today_date - timedelta(days=2)

        # Sync all active devices if Biometric Device entries exist
        devices = frappe.get_all("Biometric Device", filters={"enabled": 1}, pluck="name") if frappe.db.table_exists("Biometric Device") else []
        if devices:
            from biometric_integration.biometric_integration.doctype.biometric_device.biometric_device import sync_all_active_devices
            sync_all_active_devices(
                from_date=str(day_before_yesterday_date),
                from_time="00:00:00",
                to_date=str(yesterday_date),
                to_time="23:59:59"
            )
        else:
            # Fallback to single settings
            sync_attendance(
                from_date=str(day_before_yesterday_date),
                from_time="00:00:00",
                to_date=str(yesterday_date),
                to_time="23:59:59"
            )

        frappe.logger().info("Scheduled attendance sync started successfully")

    except Exception as e:
        frappe.logger().error(f"Scheduled attendance sync failed: {str(e)}")
        frappe.log_error(f"Scheduled attendance sync failed: {str(e)}", "Daily Attendance Sync Error")


@frappe.whitelist()
def update_all_manual_punches():
    try:
        manual_punches = frappe.get_all("Biometric Manual Punch", fields=["employee", "punch_date", "punch_time"])

        for manual_punch in manual_punches:
            employee = manual_punch["employee"]
            punch_date = manual_punch["punch_date"]
            punch_time = manual_punch["punch_time"]

            attendance_device_id = frappe.db.get_value("Employee", employee, "attendance_device_id")
            employee_name = frappe.db.get_value("Employee", employee, "employee_name")

            if not attendance_device_id:
                continue

            if isinstance(punch_time, str):
                punch_time = punch_time.split(".")[0]
            elif isinstance(punch_time, timedelta):
                punch_time = (datetime.min + punch_time).time()

            punch_datetime = datetime.strptime(f"{punch_date} {punch_time}", "%Y-%m-%d %H:%M:%S")

            query = """
                SELECT name FROM `tabBiometric Attendance Log`
                WHERE employee_no = %s AND event_date = %s
            """
            attendance_log = frappe.db.sql(query, (attendance_device_id, punch_date), as_dict=True)

            if attendance_log:
                doc = frappe.get_doc("Biometric Attendance Log", attendance_log[0].name)
            else:
                doc = frappe.get_doc({"doctype": "Biometric Attendance Log", "employee_no": attendance_device_id, "event_date": punch_date})

            if employee_name:
                doc.employee_name = employee_name

            punches = []
            for punch in doc.get("punch_table", []):
                punch_time_value = punch.punch_time
                if isinstance(punch_time_value, str):
                    punch_time_value = datetime.strptime(punch_time_value, "%H:%M:%S").time()
                elif isinstance(punch_time_value, timedelta):
                    punch_time_value = (datetime.min + punch_time_value).time()
                punches.append({"punch_time": punch_time_value, "punch_type": punch.punch_type})

            if not any(p["punch_time"] == punch_datetime.time() for p in punches):
                punches.append({"punch_time": punch_datetime.time(), "punch_type": "Manual"})
                punches.sort(key=lambda x: x["punch_time"])

                doc.set("punch_table", [])
                for punch in punches:
                    doc.append("punch_table", punch)

                doc.save(ignore_permissions=True)
                create_employee_checkin(attendance_device_id, punch_datetime, log_type=None, device_id="Manual")

        frappe.db.commit()
        return {"status": "success", "message": "Manual punches updated successfully for all employees."}

    except frappe.ValidationError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"Error updating manual punches: {str(e)}"}