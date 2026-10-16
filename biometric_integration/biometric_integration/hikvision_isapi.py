# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import json
import logging
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timedelta

try:
    import pytz
except ImportError:
    pytz = None

try:
    from frappe.utils import get_system_timezone
except ImportError:
    def get_system_timezone():
        return "UTC"

logger = logging.getLogger(__name__)


def _get_device_auth_and_url(device, endpoint):
    """Constructs base URL and HTTPDigestAuth from a BiometricDevice doc."""
    base_url = device.get_base_url().rstrip("/")
    clean_endpoint = endpoint.lstrip("/")
    url = f"{base_url}/{clean_endpoint}"
    password = device.get_password("password")
    auth = HTTPDigestAuth(device.username, password) if device.username and password else None
    return url, auth


def _format_iso_time(dt_obj, tz_name=None):
    """Formats datetime with ISO offset, required by Hikvision ISAPI."""
    if not dt_obj:
        return None
    tz_str = tz_name or get_system_timezone() or "UTC"
    if pytz:
        try:
            tz = pytz.timezone(tz_str)
            if dt_obj.tzinfo is None:
                dt_obj = tz.localize(dt_obj)
            else:
                dt_obj = dt_obj.astimezone(tz)
            return dt_obj.strftime("%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            pass

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_str)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=tz)
        else:
            dt_obj = dt_obj.astimezone(tz)
        return dt_obj.strftime("%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        pass

    return dt_obj.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def get_enrolled_user_count(device):
    """
    Returns the total number of persons enrolled on the Hikvision terminal.
    Attempts UserInfo/Count first, falling back to UserInfo/Search.
    """
    url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/UserInfo/Count?format=json")
    try:
        resp = requests.get(url, auth=auth, timeout=5, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            return int(data.get("UserInfoCount", {}).get("userNumber", 0))
    except Exception as e:
        logger.debug(f"UserInfo/Count failed on {device.name}: {e}")

    # Fallback to UserInfo/Search
    search_url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/UserInfo/Search?format=json")
    payload = {
        "UserInfoSearchCond": {
            "searchID": "count-fallback",
            "searchResultPosition": 0,
            "maxResults": 1
        }
    }
    try:
        resp = requests.post(search_url, auth=auth, json=payload, timeout=5, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            return int(data.get("UserInfoSearch", {}).get("totalMatches", 0))
    except Exception as e:
        logger.error(f"Failed to get user count from {device.name}: {e}")
    return 0


def get_enrolled_users(device, max_users=1000):
    """
    Fetches the list of enrolled users from the terminal via ISAPI UserInfo/Search.
    Returns a list of dicts: [{'employeeNo': '...', 'name': '...', 'userType': '...'}, ...]
    """
    search_url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/UserInfo/Search?format=json")
    all_users = []
    position = 0
    batch_size = 50

    while position < max_users:
        payload = {
            "UserInfoSearchCond": {
                "searchID": "search-enrolled-users",
                "searchResultPosition": position,
                "maxResults": batch_size
            }
        }
        try:
            resp = requests.post(search_url, auth=auth, json=payload, timeout=10, verify=False)
            if resp.status_code != 200:
                break
            data = resp.json().get("UserInfoSearch", {})
            users = data.get("UserInfo", [])
            if not users:
                break
            if isinstance(users, dict):
                users = [users]
            for u in users:
                emp_no = str(u.get("employeeNo", "")).strip()
                if emp_no:
                    all_users.append({
                        "employeeNo": emp_no,
                        "name": str(u.get("name", "")).strip(),
                        "userType": u.get("userType", "normal")
                    })
            total = int(data.get("totalMatches", len(all_users)))
            position += len(users)
            if position >= total or len(users) < batch_size:
                break
        except Exception as e:
            logger.error(f"Failed to search enrolled users on {device.name}: {e}")
            break

    return all_users


def build_user_info_payload(employee_no, name, pin=None, door_no=1, user_type="normal", user_role="normal", is_admin=False, is_long_term=True, valid_from=None, valid_to=None, max_times=None, tz_name=None, plan_template_no=1, **kwargs):
    """
    Builds the standard UserInfo dict for Hikvision ISAPI.
    user_type: "normal", "visitor", "blackList"
    is_admin / user_role: "admin" -> sets localUIRight: True (on-screen local terminal administrator)
    is_long_term: if True, sets beginTime to 2000-01-01 and endTime to 2037-12-31 (never expires on hardware)
    """
    now = datetime.now()
    if is_long_term:
        default_begin = datetime(2000, 1, 1, 0, 0, 0)
        default_end = datetime(2037, 12, 31, 23, 59, 59)
    else:
        default_begin = now
        default_end = now + timedelta(days=365)

    begin_str = _format_iso_time(valid_from or default_begin, tz_name)
    end_str = _format_iso_time(valid_to or default_end, tz_name)

    # Ensure ISO string has colon in timezone offset (+0400 -> +04:00)
    def fix_tz(s):
        if s and len(s) >= 5 and s[-5] in ("+", "-"):
            return s[:-2] + ":" + s[-2:]
        return s

    begin_str = fix_tz(begin_str)
    end_str = fix_tz(end_str)

    has_admin_rights = bool(is_admin or user_role == "admin" or kwargs.get("is_device_admin"))

    user_info = {
        "employeeNo": str(employee_no),
        "name": str(name)[:32],  # Hikvision name limit
        "userType": user_type or "normal",
        "closeDelayEnabled": False,
        "localUIRight": has_admin_rights,
        "Valid": {
            "enable": not bool(is_long_term),
            "beginTime": begin_str,
            "endTime": end_str,
            "timeType": "local"
        },
        "doorRight": "1",
        "RightPlan": [{"doorNo": int(door_no or 1), "planTemplateNo": str(plan_template_no or 1)}]
    }

    if pin:
        user_info["password"] = str(pin).strip()

    if max_times is not None and int(max_times) > 0:
        user_info["maxOpenDoorTime"] = int(max_times)

    return user_info


def sync_person_to_device(device, employee_no, name, card_no=None, pin=None, door_no=1, user_type="normal", user_role="normal", is_admin=False, is_long_term=True, valid_from=None, valid_to=None, face_image_bytes=None, plan_template_no=1, **kwargs):
    """
    Safely syncs employee info to a Hikvision terminal.
    
    IMPORTANT: We attempt 'UserInfo/Modify' first. This is a merge operation in ISAPI
    that updates name, PIN, and validity WITHOUT touching or resetting existing face
    and fingerprint templates. If the user does not exist on the device, we fall back
    to 'UserInfo/Record' to create the user profile.
    """
    if not device.ip or not device.username:
        return {"status": "error", "message": f"Device {device.name} is missing IP or credentials."}

    has_admin = bool(is_admin or user_role == "admin" or kwargs.get("is_device_admin"))

    user_payload = build_user_info_payload(
        employee_no=employee_no,
        name=name,
        pin=pin,
        door_no=door_no,
        user_type=user_type,
        is_admin=has_admin,
        is_long_term=is_long_term,
        valid_from=valid_from,
        valid_to=valid_to,
        tz_name=device.timezone,
        plan_template_no=plan_template_no
    )

    modify_url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/UserInfo/Modify?format=json")
    record_url, _ = _get_device_auth_and_url(device, "ISAPI/AccessControl/UserInfo/Record?format=json")

    action_taken = "modified"
    try:
        # 1. Attempt UserInfo/Modify first (Preserves Biometrics)
        resp = requests.put(
            modify_url,
            auth=auth,
            json={"UserInfo": user_payload},
            timeout=10,
            verify=False
        )

        user_exists = False
        if resp.status_code == 200:
            res_data = resp.json()
            status_str = (res_data.get("subStatusCode") or res_data.get("statusString") or "").lower()
            # If status string indicates person doesn't exist, proceed to Record
            if "notexist" not in status_str and "not exist" not in status_str and res_data.get("statusCode") == 1:
                user_exists = True

        # 2. If user does not exist, use UserInfo/Record (Create via POST)
        if not user_exists:
            action_taken = "created"
            resp = requests.post(
                record_url,
                auth=auth,
                json={"UserInfo": user_payload},
                timeout=10,
                verify=False
            )

        if resp.status_code not in (200, 204):
            return {
                "status": "error",
                "message": f"Device returned HTTP {resp.status_code}: {resp.text[:300]}"
            }

        # 3. If card_no provided, attach card via CardInfo/Record
        if card_no and str(card_no).strip():
            card_res = set_card_on_device(device, employee_no, str(card_no).strip())
            if card_res.get("status") == "error":
                logger.warning(f"User synced but card failed on {device.name}: {card_res.get('message')}")

        # 4. If face_image_bytes provided, replicate face image to device
        if face_image_bytes:
            face_res = upload_face_image_to_device(device, employee_no, face_image_bytes)
            if face_res.get("status") == "error":
                logger.warning(f"User synced but face upload failed on {device.name}: {face_res.get('message')}")

        return {
            "status": "success",
            "action": action_taken,
            "message": f"Successfully {action_taken} employee {employee_no} ({name}) on {device.name} (Face/Fingerprint preserved)."
        }

    except Exception as e:
        return {"status": "error", "message": f"Connection error on {device.name}: {str(e)}"}


def set_card_on_device(device, employee_no, card_no):
    """Attaches an RFID card to an employee on the terminal."""
    url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/CardInfo/Record?format=json")
    payload = {
        "CardInfo": {
            "employeeNo": str(employee_no),
            "cardNo": str(card_no).strip(),
            "cardType": "normalCard"
        }
    }
    try:
        # Some firmware takes POST, others take PUT
        resp = requests.post(url, auth=auth, json=payload, timeout=8, verify=False)
        if resp.status_code not in (200, 204):
            resp = requests.put(url, auth=auth, json=payload, timeout=8, verify=False)

        if resp.status_code in (200, 204):
            return {"status": "success", "message": f"Card {card_no} linked to employee {employee_no}."}
        return {"status": "error", "message": f"Card write returned HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to set card on {device.name}: {str(e)}"}


def delete_card_from_device(device, card_no):
    """Deletes an RFID card from the terminal (strictly HTTP PUT)."""
    url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/CardInfo/Delete?format=json")
    payload = {"CardInfoDelCond": {"CardNoList": [{"cardNo": str(card_no).strip()}]}}
    try:
        resp = requests.put(url, auth=auth, json=payload, timeout=8, verify=False)
        return {"status": "success" if resp.status_code in (200, 204) else "error", "details": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_person_from_device(device, employee_no):
    """
    Deletes an employee from the terminal, instantly revoking all access.
    Hikvision ISAPI UserInfo/Delete strictly requires HTTP PUT.
    """
    url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/UserInfo/Delete?format=json")
    payload = {"UserInfoDelCond": {"EmployeeNoList": [{"employeeNo": str(employee_no)}]}}
    try:
        resp = requests.put(url, auth=auth, json=payload, timeout=8, verify=False)
        if resp.status_code in (200, 204):
            return {"status": "success", "message": f"Employee {employee_no} removed from {device.name}."}

        # If user does not exist on device, it is already clean
        try:
            err_json = resp.json()
            sub_code = (err_json.get("subStatusCode") or "").lower()
            if "notexist" in sub_code or "not exist" in sub_code:
                return {"status": "success", "message": f"Employee {employee_no} was not on {device.name} (already clean)."}
        except Exception:
            pass

        return {"status": "error", "message": f"Delete returned HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to delete {employee_no} from {device.name}: {str(e)}"}


def download_face_image_from_device(device, employee_no):
    """
    Downloads the enrolled biometric face capture of an employee from the terminal.
    Tries AccessControl/Face/Search first, then FDLib/FDSearch.
    Returns (image_bytes, error_message).
    """
    import base64

    if not device.ip or not device.username:
        return None, f"Device {device.name} missing IP or credentials."

    base_url = device.get_base_url().rstrip("/")
    search_url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/Face/Search?format=json")
    payload = {
        "FaceInfoSearchCond": {
            "searchID": f"face-{employee_no}",
            "searchResultPosition": 0,
            "maxResults": 1,
            "employeeNo": str(employee_no)
        }
    }

    try:
        resp = requests.post(search_url, auth=auth, json=payload, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            face_info_list = data.get("FaceInfoSearch", {}).get("FaceInfo", [])
            if isinstance(face_info_list, dict):
                face_info_list = [face_info_list]

            if face_info_list:
                item = face_info_list[0]
                face_url = item.get("faceURL")
                face_data = item.get("faceData")

                if face_data:
                    return base64.b64decode(face_data), None

                if face_url:
                    if not face_url.startswith("http"):
                        face_url = f"{base_url}/{face_url.lstrip('/')}"
                    img_resp = requests.get(face_url, auth=auth, timeout=15, verify=False)
                    if img_resp.status_code == 200 and img_resp.content:
                        return img_resp.content, None
    except Exception as e:
        logger.debug(f"Face/Search failed on {device.name}: {e}")

    # Fallback to FDLib/FDSearch
    fd_url, auth = _get_device_auth_and_url(device, "ISAPI/Intelligent/FDLib/FDSearch?format=json")
    fd_payload = {
        "searchResultPosition": 0,
        "maxResults": 1,
        "faceLibType": "blackFD",
        "FDID": "1",
        "name": str(employee_no)
    }
    try:
        resp = requests.post(fd_url, auth=auth, json=fd_payload, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            matches = data.get("MatchList", [])
            if matches:
                item = matches[0]
                face_url = item.get("faceURL")
                face_data = item.get("faceData")
                if face_data:
                    return base64.b64decode(face_data), None
                if face_url:
                    if not face_url.startswith("http"):
                        face_url = f"{base_url}/{face_url.lstrip('/')}"
                    img_resp = requests.get(face_url, auth=auth, timeout=15, verify=False)
                    if img_resp.status_code == 200 and img_resp.content:
                        return img_resp.content, None
    except Exception as e:
        logger.debug(f"FDLib search failed on {device.name}: {e}")

    return None, f"No enrolled face capture found for employee {employee_no} on {device.name}."


def upload_face_image_to_device(device, employee_no, image_bytes):
    """
    Pushes a JPEG face image to the terminal's face library.
    Uses multipart/form-data with FaceDataRecord JSON + FaceImage binary JPEG.
    """
    if not device.ip or not device.username:
        return {"status": "error", "message": f"Device {device.name} missing credentials."}

    # Approach 1: AccessControl/Face/Record
    url, auth = _get_device_auth_and_url(device, "ISAPI/AccessControl/Face/Record?format=json")
    record_json = {
        "faceLibType": "blackFD",
        "FDID": "1",
        "FPID": str(employee_no),
        "employeeNo": str(employee_no)
    }

    files = {
        "FaceDataRecord": (None, json.dumps(record_json), "application/json"),
        "img": ("face.jpg", image_bytes, "image/jpeg")
    }

    try:
        resp = requests.post(url, auth=auth, files=files, timeout=15, verify=False)
        if resp.status_code not in (200, 204):
            resp = requests.put(url, auth=auth, files=files, timeout=15, verify=False)

        if resp.status_code in (200, 204):
            return {"status": "success", "message": f"Face replicated successfully to {device.name}."}

        # Approach 2 Fallback: FDLib/FaceDataRecord
        fd_url, auth = _get_device_auth_and_url(device, "ISAPI/Intelligent/FDLib/FaceDataRecord?format=json")
        fd_record = {
            "faceLibType": "blackFD",
            "FDID": "1",
            "FPID": str(employee_no),
            "name": str(employee_no)
        }
        fd_files = {
            "FaceDataRecord": (None, json.dumps(fd_record), "application/json"),
            "FaceImage": ("face.jpg", image_bytes, "image/jpeg")
        }
        resp2 = requests.post(fd_url, auth=auth, files=fd_files, timeout=15, verify=False)
        if resp2.status_code in (200, 204):
            return {"status": "success", "message": f"Face replicated successfully via FDLib to {device.name}."}

        return {
            "status": "error",
            "message": f"Device returned HTTP {resp.status_code}: {resp.text[:200]}"
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to upload face to {device.name}: {str(e)}"}



# -------------------------------------------------------------
# Door Schedule (Normally-Open / Free Passage) ISAPI Handlers
# -------------------------------------------------------------

VALID_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def parse_time_to_seconds(val):
    """Converts various time representations (timedelta, time, str) into seconds from midnight."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if hasattr(val, "total_seconds"):
        return int(val.total_seconds())
    if hasattr(val, "hour") and hasattr(val, "minute") and hasattr(val, "second"):
        return val.hour * 3600 + val.minute * 60 + val.second
    val_str = str(val).strip()
    if not val_str:
        return None
    parts = val_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 3600 + int(parts[1]) * 60
        elif len(parts) >= 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def format_seconds_to_time_str(seconds):
    """Formats seconds from midnight into HH:MM:SS string."""
    if seconds is None:
        return "00:00:00"
    hours = (seconds // 3600) % 24
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def validate_door_schedule(schedule_rows, enable_free_passage=True):
    """
    Strictly validates door open schedule intervals in ERPNext:
    1. Start time and end time must be present and parseable.
    2. End time must be strictly later than start time (end_time > start_time).
    3. Intervals on the same day must not overlap (e.g. 09:00-14:00 vs 12:00-17:00).
    4. Intervals on the same day must not exceed 8 segments (Hikvision hardware limit).
    5. Flags contiguous intervals (e.g. 09:00-14:00 and 14:00-18:00) so they can be merged.
    """
    try:
        import frappe
        _ = frappe._
        throw_func = frappe.throw
    except Exception:
        def _(msg):
            return msg
        def throw_func(msg):
            raise ValueError(msg)

    if enable_free_passage and not schedule_rows:
        throw_func(_("Door Open Schedule is enabled, but no schedule intervals were added. Please add at least one interval (e.g. Monday 09:00:00 to 14:00:00) or uncheck 'Enable Door Open Schedule'."))

    if not schedule_rows:
        return True

    day_map = {day: [] for day in VALID_DAYS}

    for idx, row in enumerate(schedule_rows, start=1):
        if hasattr(row, "get"):
            day = row.get("day_of_week")
            start = row.get("start_time")
            end = row.get("end_time")
        else:
            day = getattr(row, "day_of_week", None)
            start = getattr(row, "start_time", None)
            end = getattr(row, "end_time", None)

        row_idx = getattr(row, "idx", idx)

        if not day or day not in VALID_DAYS:
            throw_func(_("Row #{0}: Please select a valid Day of the Week.").format(row_idx))

        if start is None or str(start).strip() == "":
            throw_func(_("Row #{0} ({1}): Start Time is required.").format(row_idx, day))

        if end is None or str(end).strip() == "":
            throw_func(_("Row #{0} ({1}): End Time is required.").format(row_idx, day))

        start_sec = parse_time_to_seconds(start)
        if start_sec is None:
            throw_func(_("Row #{0} ({1}): Invalid Start Time '{2}'. Expected format is HH:MM:SS.").format(row_idx, day, start))

        end_sec = parse_time_to_seconds(end)
        if end_sec is None:
            throw_func(_("Row #{0} ({1}): Invalid End Time '{2}'. Expected format is HH:MM:SS.").format(row_idx, day, end))

        start_fmt = format_seconds_to_time_str(start_sec)
        end_fmt = format_seconds_to_time_str(end_sec)

        # Validation: End Time must be strictly later than Start Time
        if end_sec <= start_sec:
            throw_func(
                _("Row #{0} ({1}): End Time ({2}) must be strictly later than Start Time ({3}). "
                  "Overnight intervals crossing midnight must be split into two separate rows "
                  "(e.g. 22:00:00 to 23:59:59 and 00:00:00 to 06:00:00).").format(
                    row_idx, day, end_fmt, start_fmt
                )
            )

        day_map[day].append({
            "idx": row_idx,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "start_time": start_fmt,
            "end_time": end_fmt
        })

    # Validate intervals per day
    for day, intervals in day_map.items():
        if not intervals:
            continue

        # Check maximum 8 segments per day (Hikvision limit)
        if len(intervals) > 8:
            throw_func(
                _("Day {0} has {1} schedule intervals. Hikvision terminals support a maximum of 8 intervals per day.").format(
                    day, len(intervals)
                )
            )

        # Sort chronologically by start time
        intervals.sort(key=lambda x: x["start_sec"])

        for i in range(len(intervals) - 1):
            curr = intervals[i]
            nxt = intervals[i + 1]

            # Check overlap
            if curr["end_sec"] > nxt["start_sec"]:
                throw_func(
                    _("Overlapping schedule intervals detected on {0}: "
                      "Row #{1} [{2} - {3}] overlaps with Row #{4} [{5} - {6}]. "
                      "Please adjust your schedule times.").format(
                        day,
                        curr["idx"], curr["start_time"], curr["end_time"],
                        nxt["idx"], nxt["start_time"], nxt["end_time"]
                    )
                )

            # Check contiguous (end == start)
            if curr["end_sec"] == nxt["start_sec"]:
                throw_func(
                    _("Contiguous intervals detected on {0}: "
                      "Row #{1} ends at {2} and Row #{3} starts at {4}. "
                      "Please merge them into a single interval ({5} - {6}) to avoid hardware schedule conflicts.").format(
                        day,
                        curr["idx"], curr["end_time"],
                        nxt["idx"], nxt["start_time"],
                        curr["start_time"], nxt["end_time"]
                    )
                )

    return True


def build_open_status_plan_payload(schedule_rows=None, enable=True, door_no=1):
    """
    Builds the OpenStatusPlan JSON structure for Hikvision ISAPI.
    """
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_map = {d: [] for d in days}

    if enable and schedule_rows:
        for row in schedule_rows:
            if hasattr(row, "get"):
                day_name = (row.get("day_of_week") or "").strip().lower()
                start = row.get("start_time")
                end = row.get("end_time")
            else:
                day_name = (getattr(row, "day_of_week", "") or "").strip().lower()
                start = getattr(row, "start_time", None)
                end = getattr(row, "end_time", None)

            if day_name in day_map and start and end:
                s_sec = parse_time_to_seconds(start)
                e_sec = parse_time_to_seconds(end)
                if s_sec is not None and e_sec is not None and e_sec > s_sec:
                    day_map[day_name].append({
                        "start_sec": s_sec,
                        "beginTime": format_seconds_to_time_str(s_sec),
                        "endTime": format_seconds_to_time_str(e_sec)
                    })

    week_plan = []
    for day_name in days:
        segs = day_map[day_name]
        segs.sort(key=lambda x: x["start_sec"])
        time_segments = []
        for idx, seg in enumerate(segs, start=1):
            time_segments.append({
                "id": idx,
                "beginTime": seg["beginTime"],
                "endTime": seg["endTime"]
            })
        week_plan.append({
            "week": day_name,
            "TimeSegment": time_segments
        })

    payload = {
        "OpenStatusPlan": {
            "doorNo": int(door_no or 1),
            "enable": bool(enable),
            "weekPlan": week_plan
        }
    }
    return payload


def sync_door_open_schedule(device, schedule_rows=None, enable=None, door_no=1):
    """
    Syncs the door open (free passage) schedule to the Hikvision terminal.
    Validates times first, formats payload, and puts to OpenStatusPlan endpoint.
    """
    if not device.ip or not device.username:
        return {"status": "error", "message": f"Device {device.name} is missing IP or credentials."}

    if schedule_rows is None:
        if hasattr(device, "get_door_schedule_rows"):
            schedule_rows = device.get_door_schedule_rows()
        elif hasattr(device, "get") and device.get("free_passage_shift"):
            try:
                import frappe
                shift = frappe.get_doc("Biometric Access Shift", device.get("free_passage_shift"))
                schedule_rows = shift.get("schedule_items") or []
            except Exception:
                schedule_rows = device.get("door_open_schedule") or []
        else:
            schedule_rows = device.get("door_open_schedule") or []

    if enable is None:
        enable = bool(device.enable_free_passage)

    # 1. Validate schedule rows
    try:
        validate_door_schedule(schedule_rows, enable_free_passage=enable)
    except Exception as e:
        return {"status": "error", "message": f"Schedule validation failed: {str(e)}"}

    # 2. Build payload
    payload = build_open_status_plan_payload(schedule_rows, enable=enable, door_no=door_no)

    # 3. Push to terminal
    url, auth = _get_device_auth_and_url(device, f"ISAPI/AccessControl/OpenStatusPlan/door/{door_no}?format=json")
    try:
        resp = requests.put(url, auth=auth, json=payload, timeout=10, verify=False)
        if resp.status_code not in (200, 204):
            # Fallback endpoint DoorOpenPlan
            alt_url, _ = _get_device_auth_and_url(device, f"ISAPI/AccessControl/DoorOpenPlan/door/{door_no}?format=json")
            resp = requests.put(alt_url, auth=auth, json={"DoorOpenPlan": payload.get("OpenStatusPlan")}, timeout=10, verify=False)

        if resp.status_code in (200, 204):
            try:
                import frappe
                from frappe.utils import now_datetime
                device.db_set("schedule_sync_status", "Synced")
                device.db_set("schedule_last_synced", now_datetime())
            except Exception:
                pass
            state_desc = "Enabled (Schedule Active)" if enable else "Disabled (Normal Security)"
            return {
                "status": "success",
                "message": f"Door open schedule successfully synced to {device.name}. Mode: {state_desc}."
            }
        else:
            try:
                device.db_set("schedule_sync_status", f"Error {resp.status_code}")
            except Exception:
                pass
            return {
                "status": "error",
                "message": f"Terminal returned HTTP {resp.status_code}: {resp.text[:250]}"
            }
    except Exception as e:
        try:
            device.db_set("schedule_sync_status", f"Failed: {str(e)[:50]}")
        except Exception:
            pass
        return {"status": "error", "message": f"Failed to push schedule to {device.name}: {str(e)}"}


def set_door_hardware_mode(device, command, door_no=1):
    """
    Sends hardware door mode command to Hikvision terminal.
    Commands:
      - 'open': Pulse unlock (unlocks, pulses for relay_pulse_seconds, then relocks)
      - 'close': Lock immediately
      - 'alwaysOpen': Free passage / hold open
      - 'alwaysClose': Lockdown / hold closed
      - 'resume': Resume normal security / scheduled access
    """
    cmd_map = {
        "open": "open",
        "unlock": "open",
        "close": "close",
        "lock": "close",
        "alwaysopen": "alwaysOpen",
        "always_open": "alwaysOpen",
        "hold_open": "alwaysOpen",
        "alwaysclose": "alwaysClose",
        "always_close": "alwaysClose",
        "lockdown": "alwaysClose",
        "resume": "resume",
        "normal": "resume"
    }

    clean_cmd = cmd_map.get(str(command).strip().lower())
    if not clean_cmd:
        return {"status": "error", "message": f"Unsupported door command '{command}'."}

    if not device.ip or not device.username:
        return {"status": "error", "message": f"Device {device.name} is missing IP or credentials."}

    url, auth = _get_device_auth_and_url(device, f"ISAPI/AccessControl/RemoteControl/door/{door_no}")
    headers = {"Content-Type": "application/xml"}
    payload = f"<RemoteControlDoor><cmd>{clean_cmd}</cmd></RemoteControlDoor>"

    try:
        resp = requests.put(url, auth=auth, data=payload, headers=headers, timeout=8, verify=False)
        if resp.status_code not in (200, 204):
            # Fallback to JSON
            json_url, _ = _get_device_auth_and_url(device, f"ISAPI/AccessControl/RemoteControl/door/{door_no}?format=json")
            resp = requests.put(json_url, auth=auth, json={"RemoteControlDoor": {"cmd": clean_cmd}}, timeout=8, verify=False)

        if resp.status_code in (200, 204):
            return {
                "status": "success",
                "command": clean_cmd,
                "message": f"Door command '{clean_cmd}' executed successfully on {device.name}."
            }
        return {
            "status": "error",
            "message": f"Device returned HTTP {resp.status_code}: {resp.text[:200]}"
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to execute '{clean_cmd}' on {device.name}: {str(e)}"}
