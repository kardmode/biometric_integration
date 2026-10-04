# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
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
