# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

from datetime import datetime
import frappe
from frappe import _
from frappe.utils import get_datetime, get_time, getdate

import hrms.hr.doctype.attendance.attendance as att
import hrms.hr.doctype.employee_checkin.employee_checkin as ec
from hrms.hr.doctype.shift_type.shift_type import ShiftType


class CustomShiftType(ShiftType):
	"""
	Customized ShiftType:
	1. get_assigned_employees: If no explicit Shift Assignments exist, automatically
	   includes all active employees.
	2. get_employee_checkins: Picks up all unassigned checkin logs for the date range
	   even if 'shift' was not pre-set on the checkin record.
	"""

	def get_assigned_employees(self, from_date=None, consider_default_shift=True):
		assigned = super().get_assigned_employees(from_date, consider_default_shift)
		if not assigned:
			# Fallback: Process all active employees automatically
			return frappe.get_all("Employee", filters={"status": "Active"}, pluck="name")
		return assigned

	def get_employee_checkins(self) -> list[dict]:
		# Fetch checkins matching this shift OR unassigned checkins
		EmployeeCheckin = frappe.qb.DocType("Employee Checkin")
		query = (
			frappe.qb.from_(EmployeeCheckin)
			.select(
				EmployeeCheckin.name,
				EmployeeCheckin.employee,
				EmployeeCheckin.log_type,
				EmployeeCheckin.time,
				EmployeeCheckin.shift,
				EmployeeCheckin.shift_start,
				EmployeeCheckin.shift_end,
				EmployeeCheckin.shift_actual_start,
				EmployeeCheckin.shift_actual_end,
				EmployeeCheckin.device_id,
			)
			.where(
				(EmployeeCheckin.skip_auto_attendance == 0)
				& ((EmployeeCheckin.attendance.isnull()) | (EmployeeCheckin.attendance == ""))
				& (EmployeeCheckin.time >= self.process_attendance_after)
				& (
					(EmployeeCheckin.shift == self.name)
					| (EmployeeCheckin.shift.isnull())
					| (EmployeeCheckin.shift == "")
				)
			)
			.orderby(EmployeeCheckin.employee)
			.orderby(EmployeeCheckin.time)
		)

		if self.last_sync_of_checkin:
			query = query.where(EmployeeCheckin.time < self.last_sync_of_checkin)

		return query.run(as_dict=True)


def custom_handle_attendance_exception(log_names: list, error_message: str):
	"""
	Replaces standard handle_attendance_exception.
	CRITICAL FIX: Standard HRMS calls skip_attendance_in_checkins(), permanently
	setting skip_auto_attendance = 1 on logs whenever validation fails.
	Our version NEVER sets skip_auto_attendance = 1 so checkin logs are preserved
	for review and subsequent re-processing!
	"""
	frappe.db.rollback(save_point="attendance_creation")
	frappe.clear_messages()
	# DO NOT call skip_attendance_in_checkins(log_names)!
	ec.add_comment_in_checkins(log_names, error_message)
	frappe.log_error(
		title=_("Auto Attendance Error (Checkins NOT Skipped)"),
		message=f"Error: {error_message}\nCheckin Logs: {', '.join(log_names)}",
	)


def custom_mark_attendance_and_link_log(
	logs,
	attendance_status,
	attendance_date,
	working_hours=None,
	late_entry=False,
	early_exit=False,
	in_time=None,
	out_time=None,
	shift=None,
):
	"""
	Replaces standard mark_attendance_and_link_log:
	1. Calls .save() instead of .submit() so Attendance stays as editable Draft (docstatus = 0).
	2. Flags missing checkouts/checkins with custom_review_status = 'Must Check'.
	3. Never permanently locks out logs on error.
	"""
	log_names = [x.name for x in logs]
	employee = logs[0].employee

	if attendance_status == "Skip":
		ec.skip_attendance_in_checkins(log_names)
		return None

	elif attendance_status in ("Present", "Absent", "Half Day"):
		try:
			frappe.db.savepoint("attendance_creation")
			attendance = frappe.new_doc("Attendance")
			attendance.update(
				{
					"doctype": "Attendance",
					"employee": employee,
					"attendance_date": attendance_date,
					"status": attendance_status,
					"working_hours": working_hours,
					"shift": shift,
					"late_entry": late_entry,
					"early_exit": early_exit,
					"in_time": in_time,
					"out_time": out_time,
				}
			)

			# Lenient missing punch tagging
			if not out_time and in_time:
				attendance.departure_time = "17:00:00"
				attendance.status = "Present"
				attendance.custom_review_status = "Must Check"
				attendance.custom_review_reason = "Missing checkout (Auto-completed 17:00:00)"
			elif not in_time and out_time:
				attendance.arrival_time = "07:00:00"
				attendance.status = "Present"
				attendance.custom_review_status = "Must Check"
				attendance.custom_review_reason = "Missing checkin (Auto-completed 07:00:00)"
			else:
				if not getattr(attendance, "custom_review_status", None):
					attendance.custom_review_status = "Normal"

			# Save as Draft (docstatus = 0) without submitting!
			attendance.flags.ignore_validate = False
			attendance.save()

			ec.update_attendance_in_checkins(log_names, attendance.name)
			return attendance

		except frappe.ValidationError as e:
			custom_handle_attendance_exception(log_names, str(e))
		except Exception as e:
			custom_handle_attendance_exception(log_names, str(e))

	else:
		frappe.throw(_("{} is an invalid Attendance Status.").format(attendance_status))


def custom_mark_attendance(
	employee,
	attendance_date,
	status,
	shift=None,
	leave_type=None,
	late_entry=False,
	early_exit=False,
):
	"""
	Replaces standard mark_attendance (used when marking Absent for dates with 0 checkins):
	1. Calls .save() instead of .submit() (docstatus = 0).
	2. Sets arrival_time = "00:00:00" and departure_time = "00:00:00".
	3. Flags custom_review_status = 'Must Check' with reason 'No checkins recorded'.
	"""
	savepoint = "attendance_creation"

	try:
		frappe.db.savepoint(savepoint)
		attendance = frappe.new_doc("Attendance")
		attendance.update(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": attendance_date,
				"status": status,
				"shift": shift,
				"leave_type": leave_type,
				"late_entry": late_entry,
				"early_exit": early_exit,
			}
		)

		if status == "Absent":
			attendance.arrival_time = "00:00:00"
			attendance.departure_time = "00:00:00"
			attendance.custom_review_status = "Must Check"
			attendance.custom_review_reason = "No checkins recorded"

		attendance.flags.ignore_validate = False
		attendance.save()
		return attendance.name

	except (att.DuplicateAttendanceError, att.OverlappingShiftAttendanceError):
		frappe.db.rollback(save_point=savepoint)
		return None
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		return None


def apply_hrms_patches():
	"""
	Apply safe in-memory monkey-patches to HRMS functions.
	"""
	ec.handle_attendance_exception = custom_handle_attendance_exception
	ec.mark_attendance_and_link_log = custom_mark_attendance_and_link_log
	att.mark_attendance = custom_mark_attendance
