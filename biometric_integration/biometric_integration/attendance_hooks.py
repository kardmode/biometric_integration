# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_time


def before_validate_attendance(doc, method=None):
	"""
	Hook called before Attendance.validate() runs.
	1. Automatically synchronizes standard ERPNext in_time -> arrival_time
	   and out_time -> departure_time.
	2. Sanitizes empty, None, and placeholder strings to "00:00:00".
	3. Preserves genuine punch times without fabricating exit/arrival times,
	   allowing existing attendance catches and reports to surface missing punches
	   for HR review and manual resolution.
	"""
	# 1. Sync in_time to arrival_time if arrival_time is empty or not set
	if doc.in_time and (
		not getattr(doc, "arrival_time", None)
		or str(doc.arrival_time).strip() in ["00:00:00", "00:00", "0:00:00", "00:00:0", "#--:--", "None", ""]
	):
		try:
			doc.arrival_time = get_time(doc.in_time).strftime("%H:%M:%S")
		except Exception:
			pass

	# 2. Sync out_time to departure_time if departure_time is empty or not set
	if doc.out_time and (
		not getattr(doc, "departure_time", None)
		or str(doc.departure_time).strip() in ["00:00:00", "00:00", "0:00:00", "00:00:0", "#--:--", "None", ""]
	):
		try:
			doc.departure_time = get_time(doc.out_time).strftime("%H:%M:%S")
		except Exception:
			pass

	# 3. Sanitize empty, None, or placeholder values to "00:00:00"
	if not getattr(doc, "arrival_time", None) or str(doc.arrival_time).strip() in [
		"#--:--", "00:00", "0:00:00", "00:00:0", "None", ""
	]:
		doc.arrival_time = "00:00:00"

	if not getattr(doc, "departure_time", None) or str(doc.departure_time).strip() in [
		"#--:--", "00:00", "0:00:00", "00:00:0", "None", ""
	]:
		doc.departure_time = "00:00:00"


def validate_salary_slip(doc, method=None):
	"""
	Safety Gate: Blocks Salary Slip creation/submission if the employee has
	unresolved 'Must Check' attendance records during the payroll period.
	"""
	if not doc.employee or not doc.start_date or not doc.end_date:
		return

	# Only check if custom_review_status field exists on tabAttendance
	if not frappe.db.has_column("Attendance", "custom_review_status"):
		return

	must_check_records = frappe.get_all(
		"Attendance",
		filters={
			"employee": doc.employee,
			"attendance_date": ["between", [doc.start_date, doc.end_date]],
			"docstatus": ["<", 2],
			"custom_review_status": "Must Check",
		},
		fields=["name", "attendance_date", "custom_review_reason", "status"],
		order_by="attendance_date asc",
	)

	if must_check_records:
		dates_list = []
		for r in must_check_records:
			reason = f" — <i>{r.custom_review_reason}</i>" if r.custom_review_reason else ""
			dates_list.append(f"• <b>{r.attendance_date}</b> ({r.status}){reason}")

		formatted_dates = "<br>".join(dates_list)
		msg = _(
			"<b>Cannot process Salary Slip for {0} ({1})</b>:<br><br>"
			"The following attendance dates are marked <b>'Must Check'</b> and require HR verification before payroll can proceed:<br><br>"
			"{2}<br><br>"
			"<i>Action: Open these records in the <b>Attendance</b> list, verify the times, and change Review Status to 'Verified'.</i>"
		).format(doc.employee_name or doc.employee, doc.employee, formatted_dates)

		frappe.throw(msg, title=_("Unverified Attendance Found"))
