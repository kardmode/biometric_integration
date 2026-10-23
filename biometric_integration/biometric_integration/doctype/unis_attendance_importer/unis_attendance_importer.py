# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, cstr, flt, time_diff_in_seconds


class UNISAttendanceImporter(Document):
	pass


@frappe.whitelist()
def upload():
	if not (frappe.has_permission("Attendance", "create") or frappe.has_permission("Attendance", "write")):
		raise frappe.PermissionError(_("You do not have permission to create or modify Attendance records."))

	from frappe.utils.csvutils import read_csv_content

	if not getattr(frappe.local, "uploaded_file", None):
		frappe.throw(_("No CSV file uploaded. Please select a valid UNIS export CSV file."))

	raw_rows = read_csv_content(frappe.local.uploaded_file)
	if not raw_rows:
		frappe.throw(_("The uploaded CSV file is empty."))

	import_unis_attendance(raw_rows)


def import_unis_attendance(raw_rows):
	raw_params = frappe.form_dict.get("params") or "{}"
	try:
		params = json.loads(raw_params) if isinstance(raw_params, str) else raw_params
	except Exception:
		params = {}

	import_settings = params.get("import_settings") or "Dry Run (Preview & Validate Only)"
	single_punch_handling = params.get("single_punch_handling") or "Skip & Report in Error Log"
	default_company = params.get("default_company") or frappe.defaults.get_user_default("Company")

	is_dry_run = "Dry Run" in import_settings

	# Step 1: Pre-cache employee lookups
	emp_cache = {}
	device_id_cache = {}

	employees = frappe.get_all(
		"Employee",
		fields=["name", "employee_name", "company", "department", "status", "custom_biometric_device_enrolled_id"]
	)
	for emp in employees:
		emp_cache[emp.name.strip().upper()] = emp
		if getattr(emp, "custom_biometric_device_enrolled_id", None):
			dev_id = str(emp.custom_biometric_device_enrolled_id).strip().lstrip("0")
			if dev_id:
				device_id_cache[dev_id] = emp

	# Step 2: Parse and filter UNIS raw punch lines
	valid_punches = []
	filtered_visitor_count = 0
	filtered_failed_count = 0
	parse_errors = []

	for idx, row in enumerate(raw_rows):
		if not row or not any(row):
			continue

		if len(row) > 0 and str(row[0]).strip().lower() in ["date", "c_date", "workdate", "time"]:
			continue

		if len(row) < 10:
			parse_errors.append(_("Row {0}: Malformed row with fewer than 10 columns.").format(idx + 1))
			continue

		date_str = str(row[0]).strip()
		time_str = str(row[1]).strip()
		dev_uid_str = str(row[3]).strip()
		emp_name_in_file = str(row[4]).strip()
		emp_id_in_file = str(row[5]).strip()
		user_type = str(row[6]).strip().lower()
		result_str = str(row[9]).strip().lower()

		if "visitor" in user_type or dev_uid_str == "****" or not dev_uid_str:
			filtered_visitor_count += 1
			continue

		if "success" not in result_str:
			filtered_failed_count += 1
			continue

		try:
			parsed_date = getdate(date_str)
		except Exception:
			parse_errors.append(_("Row {0}: Invalid date format '{1}' for employee {2}").format(idx + 1, date_str, emp_id_in_file or emp_name_in_file))
			continue

		matched_employee = None
		if emp_id_in_file and emp_id_in_file.upper() in emp_cache:
			matched_employee = emp_cache[emp_id_in_file.upper()]
		elif dev_uid_str:
			cleaned_dev_id = dev_uid_str.lstrip("0")
			if cleaned_dev_id in device_id_cache:
				matched_employee = device_id_cache[cleaned_dev_id]

		if not matched_employee:
			parse_errors.append(
				_("Row {0}: Employee '{1}' (Device UID {2}) does not exist in ERPNext.").format(
					idx + 1, emp_id_in_file or emp_name_in_file, dev_uid_str
				)
			)
			continue

		valid_punches.append({
			"employee": matched_employee["name"],
			"employee_name": matched_employee.get("employee_name") or emp_name_in_file,
			"company": matched_employee.get("company") or default_company,
			"department": matched_employee.get("department"),
			"date": parsed_date,
			"time": time_str,
			"row_idx": idx + 1
		})

	if not valid_punches and parse_errors:
		frappe.publish_realtime("import_unis_attendance", {
			"error": True,
			"messages": parse_errors
		})
		return

	# Step 3: Group punches by (Employee, Date)
	grouped_punches = defaultdict(list)
	for p in valid_punches:
		grouped_punches[(p["employee"], p["date"])].append(p)

	total_groups = len(grouped_punches)
	messages = []
	created_count = 0
	updated_count = 0
	skipped_count = 0
	single_punch_count = 0
	under_2h_count = 0
	error_count = 0

	# Step 4: Process Attendance records
	for loop_idx, ((emp_name, att_date), punch_list) in enumerate(grouped_punches.items()):
		sorted_times = sorted([p["time"] for p in punch_list])
		first_punch = sorted_times[0]
		last_punch = sorted_times[-1]

		single_punch = (len(sorted_times) == 1 or first_punch == last_punch)
		arrival_time = first_punch
		departure_time = last_punch if not single_punch else "00:00:00"

		# Calculate preliminary span hours
		span_hours = 0
		if not single_punch:
			try:
				span_hours = flt(time_diff_in_seconds(departure_time, arrival_time)) / 3600
			except Exception:
				span_hours = 0

		is_under_2h = (not single_punch and 0 < span_hours < 2.0)

		# Check existing record in DB
		existing = frappe.db.get_value(
			"Attendance",
			{"employee": emp_name, "attendance_date": att_date, "docstatus": ["<", 2]},
			["name", "docstatus", "status", "custom_review_status", "custom_arrival_time", "custom_departure_time"],
			as_dict=True
		)

		action_type = "Updated" if existing else "Created"

		# Handling for Single Punches
		if single_punch:
			single_punch_count += 1
			if single_punch_handling == "Skip & Report in Error Log" or is_dry_run:
				skipped_count += 1
				warn_text = _("<b>[Single Punch]</b> Employee {0} on {1} had only 1 punch ({2}). Departure missing — Skipped from save.").format(emp_name, att_date, arrival_time)
				messages.append(f"<span class='text-warning'>{warn_text}</span>")
				continue

		# Handling for Under 2 Hours
		if is_under_2h:
			under_2h_count += 1
			if single_punch_handling == "Skip & Report in Error Log" or is_dry_run:
				skipped_count += 1
				warn_text = _("<b>[Under 2 Hours]</b> Employee {0} on {1}: IN {2} | OUT {3} ({4:.2f} hrs). Work hours under 2 — Skipped from save.").format(emp_name, att_date, arrival_time, departure_time, span_hours)
				messages.append(f"<span class='text-warning'>{warn_text}</span>")
				continue

		# Check if already verified
		if existing and existing.custom_review_status == "Verified" and import_settings != "Overwrite All Records":
			skipped_count += 1
			if is_dry_run:
				messages.append(f"<span class='text-muted'><b>[Skipped]</b> Employee {0} on {1} is already 'Verified' by HR.</span>".format(emp_name, att_date))
			continue

		# Check idempotency
		if existing and import_settings != "Overwrite All Records":
			curr_arr = str(existing.custom_arrival_time or "")
			curr_dep = str(existing.custom_departure_time or "")
			if curr_arr == arrival_time and curr_dep == departure_time:
				skipped_count += 1
				continue

		if existing and import_settings == "Skip Existing Records":
			skipped_count += 1
			continue

		# --- DRY RUN PREVIEW MODE ---
		if is_dry_run:
			if action_type == "Created":
				created_count += 1
				msg = _("<b>[Would Create]</b> {0} on {1}: IN {2} | OUT {3} ({4:.2f} hrs)").format(
					emp_name, att_date, arrival_time, departure_time, span_hours
				)
				messages.append(f"<span class='text-success'>{msg}</span>")
			else:
				updated_count += 1
				msg = _("<b>[Would Update]</b> {0} on {1}: IN {2} | OUT {3} ({4:.2f} hrs)").format(
					emp_name, att_date, arrival_time, departure_time, span_hours
				)
				messages.append(f"<span class='text-info'>{msg}</span>")
			continue

		# --- LIVE EXECUTION MODE ---
		if existing:
			doc = frappe.get_doc("Attendance", existing.name)
		else:
			doc = frappe.new_doc("Attendance")
			doc.employee = emp_name
			doc.attendance_date = att_date
			doc.company = punch_list[0]["company"]
			doc.department = punch_list[0]["department"]

		doc.custom_arrival_time = arrival_time
		doc.custom_departure_time = departure_time
		doc.in_time = f"{att_date} {arrival_time}"
		doc.out_time = f"{att_date} {departure_time}" if not single_punch else None
		doc.status = "Present"

		if not getattr(doc, "custom_review_status", None) or doc.custom_review_status == "Must Check":
			doc.custom_review_status = "Normal"
			doc.custom_review_reason = ""

		savepoint_name = f"row_{loop_idx}"
		try:
			frappe.db.savepoint(savepoint_name)
			doc.save(ignore_permissions=True)
			if action_type == "Created":
				created_count += 1
			else:
				updated_count += 1

			msg = _("{0} Attendance for {1} on {2}: IN {3} | OUT {4}").format(
				action_type, emp_name, att_date, arrival_time, departure_time
			)
			messages.append(f"<span class='text-success'>{msg}</span>")
		except Exception as e:
			frappe.db.rollback(save_point=savepoint_name)
			error_count += 1
			err_msg = _("Error saving Attendance for {0} on {1}: {2}").format(emp_name, att_date, cstr(e))
			messages.append(f"<span class='text-danger'><b>{err_msg}</b></span>")
			frappe.log_error(title="UNIS Attendance Import Error", message=frappe.get_traceback())

		if loop_idx % 10 == 0 or loop_idx == total_groups - 1:
			frappe.publish_realtime("import_unis_attendance", {
				"progress": loop_idx + 1,
				"total": total_groups
			})

	# Summary Banner
	badge = "<span class='badge badge-warning' style='font-size: 13px; padding: 4px 8px;'>DRY RUN PREVIEW (NO DATA MODIFIED)</span>" if is_dry_run else "<span class='badge badge-success' style='font-size: 13px; padding: 4px 8px;'>LIVE IMPORT COMPLETED</span>"

	summary_header = f"""
	<div style="padding: 12px 16px; background-color: var(--bg-light-gray); border-radius: 6px; margin-bottom: 15px; border-left: 5px solid {'#d97706' if is_dry_run else '#16a34a'};">
		<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
			<h4 style="margin: 0;"><b>Import Summary:</b></h4>
			{badge}
		</div>
		<ul style="margin-bottom: 8px;">
			<li><b>{'Would Create' if is_dry_run else 'Created'}:</b> {created_count} records</li>
			<li><b>{'Would Update' if is_dry_run else 'Updated'}:</b> {updated_count} records</li>
			<li><b>Skipped:</b> {skipped_count} records (Unchanged, already Verified, or flagged single/under-2h)</li>
			<li><b style="color: #d97706;">Single Punch Days (Missing Exit):</b> {single_punch_count} records</li>
			<li><b style="color: #d97706;">Work Hours Under 2 Hours:</b> {under_2h_count} records</li>
			<li><b>Filtered Out:</b> {filtered_visitor_count} visitor/unmatched + {filtered_failed_count} failed captures</li>
			<li><b style="color: #dc2626;">Validation & Save Errors:</b> {error_count + len(parse_errors)}</li>
		</ul>
		{"<p style='margin-bottom: 0; color: #475569;'><i>To apply these changes, change Import Settings from 'Dry Run' to 'Update Existing Records' and upload again.</i></p>" if is_dry_run else ""}
	</div>
	"""

	all_logs = [summary_header] + parse_errors + messages
	frappe.publish_realtime("import_unis_attendance", {
		"messages": all_logs,
		"progress": total_groups,
		"total": total_groups
	})
