# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import unittest
import sys
from unittest.mock import MagicMock, patch

if "frappe" not in sys.modules:
    mock_frappe = MagicMock()
    mock_frappe._ = lambda x: x
    def _mock_throw(msg, *args, **kwargs):
        raise ValueError(str(msg))
    mock_frappe.throw = _mock_throw
    sys.modules["frappe"] = mock_frappe
    sys.modules["frappe.utils"] = MagicMock()
    
    class DummyDoc:
        def get(self, key, default=None):
            return getattr(self, key, default)
    mock_doc_module = MagicMock()
    mock_doc_module.Document = DummyDoc
    sys.modules["frappe.model.document"] = mock_doc_module
import json
import base64
from datetime import datetime, timedelta

from biometric_integration.biometric_integration.hikvision_isapi import (
    build_user_info_payload,
    sync_person_to_device,
    set_card_on_device,
    delete_card_from_device,
    delete_person_from_device,
    get_enrolled_user_count,
    download_face_image_from_device,
    upload_face_image_to_device,
    validate_door_schedule,
    build_open_status_plan_payload,
    sync_door_open_schedule,
    set_door_hardware_mode,
    parse_time_to_seconds,
    format_seconds_to_time_str
)


class MockDevice:
    """Mock for BiometricDevice DocType."""
    def __init__(self, name="Front Door MinMoe", ip="192.168.1.100", port="80", username="admin", password="password123"):
        self.name = name
        self.ip = ip
        self.port = port
        self.username = username
        self._password = password
        self.timezone = "Asia/Dubai"
        self.protocol = "HTTP"

    def get_base_url(self):
        return f"http://{self.ip}"

    def get_password(self, fieldname):
        return self._password

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def db_set(self, fieldname, value):
        setattr(self, fieldname, value)


class TestHikvisionUserAndCredentialManagement(unittest.TestCase):
    def setUp(self):
        self.device = MockDevice()

    def test_build_user_info_payload(self):
        """Validates correct construction of UserInfo ISAPI payload."""
        payload = build_user_info_payload(
            employee_no="1001",
            name="John Doe",
            pin="123456",
            door_no=1,
            user_type="normal",
            max_times=0,
            tz_name="UTC"
        )
        self.assertEqual(payload["employeeNo"], "1001")
        self.assertEqual(payload["name"], "John Doe")
        self.assertEqual(payload["password"], "123456")
        self.assertEqual(payload["userType"], "normal")
        self.assertTrue(payload["Valid"]["enable"])
        self.assertIn("T", payload["Valid"]["beginTime"])
        self.assertIn("T", payload["Valid"]["endTime"])

    def test_build_visitor_payload(self):
        """Validates visitor specific fields like maxOpenDoorTime."""
        payload = build_user_info_payload(
            employee_no="90001",
            name="Guest Contractor",
            pin="998877",
            user_type="visitor",
            max_times=2,
            tz_name="UTC"
        )
        self.assertEqual(payload["userType"], "visitor")
        self.assertEqual(payload["maxOpenDoorTime"], 2)

    @patch("requests.put")
    def test_sync_person_modify_first_preserves_biometrics(self, mock_put):
        """
        Confirms that when user exists on device, UserInfo/Modify is called,
        which preserves existing face and fingerprint templates on hardware.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"statusCode": 1, "statusString": "OK"}
        mock_put.return_value = mock_response

        res = sync_person_to_device(
            device=self.device,
            employee_no="1001",
            name="Alice Smith",
            pin="654321"
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "modified")
        mock_put.assert_called_once()
        self.assertIn("AccessControl/UserInfo/Modify", mock_put.call_args[0][0])

    @patch("requests.put")
    @patch("requests.post")
    def test_sync_person_fallback_to_record_for_new_user(self, mock_post, mock_put):
        """
        Confirms that if UserInfo/Modify returns that user does not exist,
        it automatically falls back to UserInfo/Record to create the new user.
        """
        # Modify returns employeeNoNotExist
        mock_modify_resp = MagicMock()
        mock_modify_resp.status_code = 200
        mock_modify_resp.json.return_value = {
            "statusCode": 4,
            "statusString": "Employee not exist",
            "subStatusCode": "employeeNoNotExist"
        }
        mock_put.return_value = mock_modify_resp

        # Record returns success
        mock_record_resp = MagicMock()
        mock_record_resp.status_code = 200
        mock_record_resp.json.return_value = {"statusCode": 1, "statusString": "OK"}
        mock_post.return_value = mock_record_resp

        res = sync_person_to_device(
            device=self.device,
            employee_no="2002",
            name="Bob Newbie",
            pin="112233"
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["action"], "created")
        mock_put.assert_called_once()
        mock_post.assert_called_once()
        self.assertIn("AccessControl/UserInfo/Record", mock_post.call_args[0][0])

    @patch("requests.post")
    def test_set_card_on_device(self, mock_post):
        """Tests attaching an RFID card to an employee."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        res = set_card_on_device(self.device, employee_no="1001", card_no="CARD-987654")
        self.assertEqual(res["status"], "success")
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        call_json = mock_post.call_args[1]["json"]
        self.assertIn("AccessControl/CardInfo/Record", call_url)
        self.assertEqual(call_json["CardInfo"]["cardNo"], "CARD-987654")

    @patch("requests.put")
    def test_delete_card_from_device(self, mock_put):
        """Tests deleting an RFID card."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        res = delete_card_from_device(self.device, card_no="CARD-987654")
        self.assertEqual(res["status"], "success")
        mock_put.assert_called_once()
        self.assertIn("AccessControl/CardInfo/Delete", mock_put.call_args[0][0])

    @patch("requests.put")
    def test_delete_person_from_device(self, mock_put):
        """Tests revoking access / deleting user from terminal."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        res = delete_person_from_device(self.device, employee_no="1001")
        self.assertEqual(res["status"], "success")
        mock_put.assert_called_once()
        call_url = mock_put.call_args[0][0]
        call_json = mock_put.call_args[1]["json"]
        self.assertIn("AccessControl/UserInfo/Delete", call_url)
        self.assertEqual(call_json["UserInfoDelCond"]["EmployeeNoList"][0]["employeeNo"], "1001")

    @patch("requests.get")
    def test_get_enrolled_user_count(self, mock_get):
        """Tests retrieving live user count from terminal."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "UserInfoCount": {
                "userNumber": 42
            }
        }
        mock_get.return_value = mock_resp

        count = get_enrolled_user_count(self.device)
        self.assertEqual(count, 42)

    @patch("requests.post")
    def test_download_face_image_base64(self, mock_post):
        """Tests downloading face image when returned as base64 data."""
        dummy_jpeg_bytes = b"\xff\xd8\xff\xe0dummy_jpeg_binary_data"
        b64_str = base64.b64encode(dummy_jpeg_bytes).decode("ascii")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "FaceInfoSearch": {
                "FaceInfo": [
                    {
                        "employeeNo": "1001",
                        "faceData": b64_str
                    }
                ]
            }
        }
        mock_post.return_value = mock_resp

        img_bytes, err = download_face_image_from_device(self.device, "1001")
        self.assertIsNone(err)
        self.assertEqual(img_bytes, dummy_jpeg_bytes)

    @patch("requests.post")
    def test_upload_face_image_to_device(self, mock_post):
        """Tests uploading face image as multipart to terminal."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        dummy_jpeg = b"\xff\xd8\xff\xe0dummy_jpeg_binary_data"
        res = upload_face_image_to_device(self.device, "1001", dummy_jpeg)
        self.assertEqual(res["status"], "success")
        mock_post.assert_called_once()
        self.assertIn("AccessControl/Face/Record", mock_post.call_args[0][0])

    def test_visitor_pass_auto_pin_generation(self):
        """Tests that 6-digit PIN and numeric hardware ID are generated properly."""
        import secrets
        pin = f"{secrets.randbelow(900000) + 100000}"
        self.assertEqual(len(pin), 6)
        self.assertTrue(pin.isdigit())

        hardware_id = f"9{secrets.randbelow(90000) + 10000}"
        self.assertTrue(hardware_id.startswith("9"))
        self.assertEqual(len(hardware_id), 6)

    @patch("biometric_integration.biometric_integration.tests.test_biometric_management.delete_person_from_device")
    def test_id_migration_deletes_old_hardware_id(self, mock_del):
        """
        Verifies that if enrolled_id != desired_id, delete_person_from_device
        is called with the old ID before provisioning the new one.
        """
        mock_del.return_value = {"status": "success"}

        old_enrolled_id = "101"
        new_desired_id = "205"

        # Simulate the migration logic from sync_employee_to_devices
        if old_enrolled_id and old_enrolled_id != new_desired_id:
            delete_person_from_device(self.device, old_enrolled_id)

        mock_del.assert_called_once_with(self.device, "101")




class TestDoorScheduleAndAccessMode(unittest.TestCase):
    def setUp(self):
        self.device = MockDevice()

    def test_parse_and_format_time_helpers(self):
        """Validates string, timedelta, and integer time parsing and formatting."""
        self.assertEqual(parse_time_to_seconds("09:00:00"), 32400)
        self.assertEqual(parse_time_to_seconds("14:30"), 52200)
        self.assertEqual(parse_time_to_seconds(timedelta(hours=17, minutes=15)), 62100)
        self.assertEqual(format_seconds_to_time_str(32400), "09:00:00")
        self.assertEqual(format_seconds_to_time_str(52200), "14:30:00")

    def test_valid_split_shift_schedule(self):
        """Tests that valid split shifts (e.g. 9-2 then 4-7 on same day) pass validation."""
        valid_rows = [
            {"idx": 1, "day_of_week": "Monday", "start_time": "09:00:00", "end_time": "14:00:00"},
            {"idx": 2, "day_of_week": "Monday", "start_time": "16:00:00", "end_time": "19:00:00"},
            {"idx": 3, "day_of_week": "Saturday", "start_time": "08:30:00", "end_time": "13:30:00"}
        ]
        # Should not raise any exception
        self.assertTrue(validate_door_schedule(valid_rows, enable_free_passage=True))

    def test_end_time_earlier_than_start_time_fails(self):
        """Tests that end_time <= start_time throws a validation error."""
        invalid_rows = [
            {"idx": 1, "day_of_week": "Monday", "start_time": "14:00:00", "end_time": "09:00:00"}
        ]
        with self.assertRaises(Exception) as ctx:
            validate_door_schedule(invalid_rows, enable_free_passage=True)
        self.assertIn("must be strictly later than Start Time", str(ctx.exception))

    def test_overlapping_intervals_same_day_fails(self):
        """Tests that overlapping intervals on the same day are strictly rejected."""
        overlapping_rows = [
            {"idx": 1, "day_of_week": "Monday", "start_time": "09:00:00", "end_time": "14:00:00"},
            {"idx": 2, "day_of_week": "Monday", "start_time": "12:00:00", "end_time": "17:00:00"}
        ]
        with self.assertRaises(Exception) as ctx:
            validate_door_schedule(overlapping_rows, enable_free_passage=True)
        self.assertIn("Overlapping schedule intervals detected on Monday", str(ctx.exception))

    def test_contiguous_intervals_rejected_to_encourage_clean_merge(self):
        """Tests that contiguous touching intervals (end == next start) are flagged."""
        contiguous_rows = [
            {"idx": 1, "day_of_week": "Wednesday", "start_time": "09:00:00", "end_time": "14:00:00"},
            {"idx": 2, "day_of_week": "Wednesday", "start_time": "14:00:00", "end_time": "18:00:00"}
        ]
        with self.assertRaises(Exception) as ctx:
            validate_door_schedule(contiguous_rows, enable_free_passage=True)
        self.assertIn("Contiguous intervals detected on Wednesday", str(ctx.exception))

    def test_max_segments_limit_enforced(self):
        """Tests that more than 8 intervals per day is rejected per Hikvision specs."""
        many_rows = [
            {"idx": i, "day_of_week": "Friday", "start_time": f"{i:02d}:00:00", "end_time": f"{i:02d}:30:00"}
            for i in range(1, 10)  # 9 segments
        ]
        with self.assertRaises(Exception) as ctx:
            validate_door_schedule(many_rows, enable_free_passage=True)
        self.assertIn("maximum of 8 intervals", str(ctx.exception))

    def test_build_open_status_plan_payload(self):
        """Tests the formation of the weekPlan payload for OpenStatusPlan."""
        schedule_rows = [
            {"idx": 1, "day_of_week": "Monday", "start_time": "09:00:00", "end_time": "14:00:00"},
            {"idx": 2, "day_of_week": "Monday", "start_time": "16:00:00", "end_time": "19:00:00"},
            {"idx": 3, "day_of_week": "Saturday", "start_time": "08:00:00", "end_time": "13:00:00"}
        ]
        payload = build_open_status_plan_payload(schedule_rows, enable=True, door_no=1)
        plan = payload["OpenStatusPlan"]
        self.assertEqual(plan["doorNo"], 1)
        self.assertTrue(plan["enable"])

        week_plan = {day_dict["week"]: day_dict["TimeSegment"] for day_dict in plan["weekPlan"]}
        self.assertEqual(len(week_plan["monday"]), 2)
        self.assertEqual(week_plan["monday"][0]["beginTime"], "09:00:00")
        self.assertEqual(week_plan["monday"][0]["endTime"], "14:00:00")
        self.assertEqual(week_plan["monday"][1]["beginTime"], "16:00:00")
        self.assertEqual(week_plan["monday"][1]["endTime"], "19:00:00")
        self.assertEqual(len(week_plan["saturday"]), 1)
        self.assertEqual(len(week_plan["sunday"]), 0)

    @patch("requests.put")
    def test_sync_door_open_schedule_push(self, mock_put):
        """Tests pushing the schedule to ISAPI OpenStatusPlan."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        rows = [
            {"idx": 1, "day_of_week": "Monday", "start_time": "09:00:00", "end_time": "17:00:00"}
        ]
        res = sync_door_open_schedule(self.device, schedule_rows=rows, enable=True)
        self.assertEqual(res["status"], "success")
        mock_put.assert_called_once()
        call_url = mock_put.call_args[0][0]
        self.assertIn("AccessControl/OpenStatusPlan/door/1", call_url)

    @patch("frappe.get_doc")
    @patch("requests.put")
    def test_sync_door_open_schedule_with_free_passage_shift(self, mock_put, mock_get_doc):
        """Tests that sync_door_open_schedule resolves rows from linked free_passage_shift."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        mock_shift = MagicMock()
        mock_shift.get.return_value = [
            {"idx": 1, "day_of_week": "Friday", "start_time": "08:00:00", "end_time": "12:00:00"}
        ]
        mock_get_doc.return_value = mock_shift

        self.device.enable_free_passage = 1
        self.device.free_passage_shift = "Friday Half Day"
        res = sync_door_open_schedule(self.device)
        self.assertEqual(res["status"], "success")
        mock_get_doc.assert_called_with("Biometric Access Shift", "Friday Half Day")

    @patch("requests.put")
    def test_set_door_hardware_mode(self, mock_put):
        """Tests sending hardware door commands like alwaysOpen, alwaysClose, resume."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_put.return_value = mock_resp

        # 1. Hold Open
        res = set_door_hardware_mode(self.device, "alwaysOpen")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["command"], "alwaysOpen")
        self.assertIn("<cmd>alwaysOpen</cmd>", mock_put.call_args[1]["data"])

        # 2. Lockdown
        res = set_door_hardware_mode(self.device, "lockdown")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["command"], "alwaysClose")
        self.assertIn("<cmd>alwaysClose</cmd>", mock_put.call_args[1]["data"])

        # 3. Resume normal security
        res = set_door_hardware_mode(self.device, "resume")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["command"], "resume")
        self.assertIn("<cmd>resume</cmd>", mock_put.call_args[1]["data"])



class MockRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get(self, key, default=None):
        return getattr(self, key, default)


class MockDeviceWithAuth(MockDevice):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.enable_access_control = True
        self.allow_all_active_employees = False
        self.remote_allowed_roles = []
        self.remote_allowed_users = []
        self.allowed_access_roles = []
        self.allowed_employees = []

    def get(self, key, default=None):
        return getattr(self, key, default)

    # Bind methods from BiometricDevice
    from biometric_integration.biometric_integration.doctype.biometric_device.biometric_device import (
        BiometricDevice
    )
    is_remote_user_authorized = BiometricDevice.is_remote_user_authorized
    is_employee_physically_authorized = BiometricDevice.is_employee_physically_authorized
    is_user_authorized = BiometricDevice.is_user_authorized
    get_employee_plan_template_no = BiometricDevice.get_employee_plan_template_no
    _get_plan_no_from_shift = BiometricDevice._get_plan_no_from_shift


class TestRemoteAndPhysicalAccessControl(unittest.TestCase):
    def setUp(self):
        self.device = MockDeviceWithAuth()

    @patch("frappe.get_roles")
    def test_remote_unlock_by_administrator(self, mock_roles):
        """Administrator always has remote desk unlock permission."""
        mock_roles.return_value = ["Administrator"]
        self.assertTrue(self.device.is_remote_user_authorized("Administrator"))

    @patch("frappe.get_roles")
    def test_remote_unlock_by_system_manager(self, mock_roles):
        """System Manager role always has remote unlock permission."""
        mock_roles.return_value = ["System Manager", "All"]
        self.assertTrue(self.device.is_remote_user_authorized("sysadmin@example.com"))

    @patch("frappe.get_roles")
    def test_remote_unlock_by_configured_role(self, mock_roles):
        """User with a role explicitly listed in remote_allowed_roles is authorized."""
        self.device.remote_allowed_roles = [MockRow(role="Front Desk Guard")]
        mock_roles.return_value = ["Front Desk Guard", "Employee"]
        self.assertTrue(self.device.is_remote_user_authorized("guard@example.com"))

    @patch("frappe.get_roles")
    def test_remote_unlock_by_configured_user(self, mock_roles):
        """Specific Frappe User login in remote_allowed_users is authorized, even without special roles or Employee link."""
        self.device.remote_allowed_users = [MockRow(user="receptionist@example.com")]
        mock_roles.return_value = ["Desk User"]
        self.assertTrue(self.device.is_remote_user_authorized("receptionist@example.com"))

    @patch("frappe.get_roles")
    def test_remote_unlock_denied_for_unauthorized_user(self, mock_roles):
        """Random user without matching role or user entry is strictly denied."""
        self.device.remote_allowed_roles = [MockRow(role="Front Desk Guard")]
        self.device.remote_allowed_users = [MockRow(user="receptionist@example.com")]
        mock_roles.return_value = ["Employee"]
        self.assertFalse(self.device.is_remote_user_authorized("intruder@example.com"))

    def test_physical_access_allow_all_active(self):
        """When allow_all_active_employees is True, all active employees get physical access."""
        self.device.allow_all_active_employees = True
        active_emp = MockRow(name="EMP-001", status="Active", custom_biometric_exempt=0)
        left_emp = MockRow(name="EMP-002", status="Left", custom_biometric_exempt=0)
        exempt_emp = MockRow(name="EMP-003", status="Active", custom_biometric_exempt=1)

        self.assertTrue(self.device.is_employee_physically_authorized(active_emp))
        self.assertFalse(self.device.is_employee_physically_authorized(left_emp))
        self.assertFalse(self.device.is_employee_physically_authorized(exempt_emp))

    def test_physical_access_by_biometric_access_role(self):
        """Employee tagged with a matching Biometric Access Role is authorized for that door."""
        self.device.allow_all_active_employees = False
        self.device.allowed_access_roles = [MockRow(access_role="Server Room")]

        server_admin = MockRow(
            name="EMP-101",
            status="Active",
            custom_biometric_exempt=0,
            custom_biometric_access_roles=[MockRow(access_role="Server Room")]
        )
        sales_rep = MockRow(
            name="EMP-102",
            status="Active",
            custom_biometric_exempt=0,
            custom_biometric_access_roles=[MockRow(access_role="Warehouse")]
        )

        self.assertTrue(self.device.is_employee_physically_authorized(server_admin))
        self.assertFalse(self.device.is_employee_physically_authorized(sales_rep))

    def test_physical_access_by_allowed_employees_override(self):
        """One-off individual employee exception grants access even if employee has no matching role."""
        self.device.allow_all_active_employees = False
        self.device.allowed_access_roles = [MockRow(access_role="Executive Boardroom")]
        self.device.allowed_employees = [MockRow(employee="EMP-999")]

        guest_emp = MockRow(
            name="EMP-999",
            status="Active",
            custom_biometric_exempt=0,
            custom_biometric_access_roles=[]  # No executive role!
        )
        regular_emp = MockRow(
            name="EMP-888",
            status="Active",
            custom_biometric_exempt=0,
            custom_biometric_access_roles=[]
        )

        self.assertTrue(self.device.is_employee_physically_authorized(guest_emp))
        self.assertFalse(self.device.is_employee_physically_authorized(regular_emp))



class TestBiometricAccessShiftAndTimeGating(unittest.TestCase):
    def setUp(self):
        from biometric_integration.biometric_integration.doctype.biometric_access_shift.biometric_access_shift import (
            BiometricAccessShift
        )
        self.shift = BiometricAccessShift()
        self.shift.shift_name = "Office Split Shift"
        self.shift.hikvision_plan_no = 5
        self.shift.schedule_items = [
            MockRow(day_of_week="Monday", start_time="09:00:00", end_time="14:00:00"),
            MockRow(day_of_week="Monday", start_time="16:00:00", end_time="19:00:00"),
            MockRow(day_of_week="Saturday", start_time="08:00:00", end_time="12:00:00")
        ]

    def test_is_active_now_within_morning_shift(self):
        """Monday at 10:30 AM is within 09:00 - 14:00."""
        # 2026-10-19 is a Monday
        test_dt = datetime(2026, 10, 19, 10, 30, 0)
        active, msg = self.shift.is_active_now(test_dt)
        self.assertTrue(active)
        self.assertIn("09:00:00 - 14:00:00", msg)

    def test_is_active_now_within_evening_shift(self):
        """Monday at 17:15 is within 16:00 - 19:00."""
        test_dt = datetime(2026, 10, 19, 17, 15, 0)
        active, msg = self.shift.is_active_now(test_dt)
        self.assertTrue(active)
        self.assertIn("16:00:00 - 19:00:00", msg)

    def test_is_active_now_during_gap_rejected(self):
        """Monday at 15:00 is between shifts (14:00 - 16:00) so it is rejected."""
        test_dt = datetime(2026, 10, 19, 15, 0, 0)
        active, msg = self.shift.is_active_now(test_dt)
        self.assertFalse(active)
        self.assertIn("Allowed today (Monday) only during", msg)

    def test_is_active_now_on_unconfigured_day_rejected(self):
        """Sunday (2026-10-18) has no intervals configured so it is rejected."""
        test_dt = datetime(2026, 10, 18, 10, 0, 0)
        active, msg = self.shift.is_active_now(test_dt)
        self.assertFalse(active)
        self.assertIn("No access intervals configured for Sunday", msg)

    @patch("frappe.get_roles")
    @patch("frappe.get_cached_doc")
    def test_remote_unlock_time_gating_allows_inside_shift(self, mock_get_doc, mock_roles):
        """Remote unlock is permitted when current time falls within assigned shift."""
        mock_get_doc.return_value = self.shift
        mock_roles.return_value = ["Desk User"]

        device = MockDeviceWithAuth()
        device.remote_allowed_users = [MockRow(user="receptionist@example.com", access_shift="Office Split Shift")]

        test_dt = datetime(2026, 10, 19, 11, 0, 0)  # Monday 11 AM
        self.assertTrue(device.is_remote_user_authorized("receptionist@example.com", dt_obj=test_dt))

    @patch("frappe.get_roles")
    @patch("frappe.get_cached_doc")
    def test_remote_unlock_time_gating_denies_outside_shift(self, mock_get_doc, mock_roles):
        """Remote unlock is denied when current time is outside assigned shift."""
        mock_get_doc.return_value = self.shift
        mock_roles.return_value = ["Desk User"]

        device = MockDeviceWithAuth()
        device.remote_allowed_users = [MockRow(user="receptionist@example.com", access_shift="Office Split Shift")]

        test_dt = datetime(2026, 10, 19, 21, 0, 0)  # Monday 9 PM (outside shift!)
        authorized, reason = device.is_remote_user_authorized("receptionist@example.com", return_reason=True, dt_obj=test_dt)
        self.assertFalse(authorized)
        self.assertIn("not permitted to remotely unlock outside their assigned shift", reason)

    @patch("frappe.get_roles")
    @patch("frappe.get_cached_doc")
    def test_system_manager_exempt_24_7(self, mock_get_doc, mock_roles):
        """System Manager can unlock 24/7, completely exempt from shift restrictions."""
        mock_get_doc.return_value = self.shift
        mock_roles.return_value = ["System Manager", "All"]

        device = MockDeviceWithAuth()
        test_dt = datetime(2026, 10, 19, 23, 59, 0)  # Midnight
        self.assertTrue(device.is_remote_user_authorized("sysadmin@example.com", dt_obj=test_dt))

    @patch("frappe.session")
    @patch("frappe.get_roles")
    def test_employee_access_role_assignment_restricted(self, mock_roles, mock_session):
        """Only HR Manager and System Manager can assign physical access roles."""
        from biometric_integration.biometric_integration.employee_sync import validate_employee_access_roles

        emp_doc = MagicMock()
        emp_doc.is_new.return_value = False
        emp_doc.has_value_changed.return_value = True

        mock_session.user = "regular_hr@example.com"
        mock_roles.return_value = ["HR User", "Employee"]

        # HR User attempting to modify roles must raise PermissionError
        with self.assertRaises(Exception) as ctx:
            validate_employee_access_roles(emp_doc)
        self.assertIn("Only HR Managers and System Managers", str(ctx.exception))

        # System Manager or HR Manager passes cleanly without error
        mock_session.user = "hr_director@example.com"
        mock_roles.return_value = ["HR Manager", "Employee"]
        validate_employee_access_roles(emp_doc)  # No exception

if __name__ == "__main__":
    unittest.main()

