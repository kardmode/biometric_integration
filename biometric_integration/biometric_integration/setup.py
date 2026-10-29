# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
	"""
	Ensure custom fields exist on Attendance and Employee doctypes.
	Called automatically after bench migrate or manually via bench execute.
	"""
	custom_fields = {
		"Attendance": [
			{
				"fieldname": "custom_review_status",
				"label": "Review Status",
				"fieldtype": "Select",
				"options": "Normal\nMust Check\nVerified",
				"default": "Normal",
				"in_list_view": 1,
				"in_standard_filter": 1,
				"insert_after": "status",
			},
			{
				"fieldname": "custom_review_reason",
				"label": "Review Reason",
				"fieldtype": "Data",
				"in_list_view": 0,
				"insert_after": "custom_review_status",
			},
			{
				"fieldname": "custom_attendance_times_section",
				"label": "Daily Hours & Overtime Details",
				"fieldtype": "Section Break",
				"insert_after": "custom_review_reason",
			},
			{
				"fieldname": "custom_arrival_time",
				"label": "Arrival Time",
				"fieldtype": "Time",
				"in_list_view": 1,
				"insert_after": "custom_attendance_times_section",
			},
			{
				"fieldname": "custom_departure_time",
				"label": "Departure Time",
				"fieldtype": "Time",
				"in_list_view": 1,
				"insert_after": "custom_arrival_time",
			},
			{
				"fieldname": "custom_col_break_hours",
				"fieldtype": "Column Break",
				"insert_after": "custom_departure_time",
			},
			{
				"fieldname": "custom_working_time",
				"label": "Working Time (Hours)",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": "custom_col_break_hours",
			},
			{
				"fieldname": "custom_normal_time",
				"label": "Normal Time (Hours)",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": "custom_working_time",
			},
			{
				"fieldname": "custom_overtime_section",
				"label": "Overtime Breakdown",
				"fieldtype": "Section Break",
				"insert_after": "custom_normal_time",
			},
			{
				"fieldname": "custom_overtime",
				"label": "Overtime (Weekdays)",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": "custom_overtime_section",
			},
			{
				"fieldname": "custom_overtime_fridays",
				"label": "Overtime (Fridays / Weekends)",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": "custom_overtime",
			},
			{
				"fieldname": "custom_col_break_ot",
				"fieldtype": "Column Break",
				"insert_after": "custom_overtime_fridays",
			},
			{
				"fieldname": "custom_overtime_holidays",
				"label": "Overtime (Holidays)",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": "custom_col_break_ot",
			},
			{
				"fieldname": "custom_total_overtime",
				"label": "Total Overtime",
				"fieldtype": "Float",
				"read_only": 1,
				"insert_after": "custom_overtime_holidays",
			},
			{
				"fieldname": "custom_overtime_type",
				"label": "Overtime Type",
				"fieldtype": "Select",
				# leading blank option: otherwise Frappe defaults new records to "Weekdays",
				# making attendance that was never calculated look like a real weekday record
				"options": "\nWeekdays\nWeekends\nHolidays",
				"read_only": 1,
				"insert_after": "custom_total_overtime",
			},
		],
		"Employee": [
			{
				"fieldname": "custom_biometric_section",
				"label": "Biometric & Door Access",
				"fieldtype": "Section Break",
				"insert_after": "attendance_device_id",
			},
			{
				"fieldname": "custom_biometric_face_image",
				"label": "Biometric Face Capture",
				"fieldtype": "Attach Image",
				"in_list_view": 0,
				"description": "Verified biometric face capture retrieved from enrollment terminal and replicated across doors",
				"insert_after": "custom_biometric_section",
			},
			{
				"fieldname": "custom_biometric_card_no",
				"label": "Access Card / RFID No",
				"fieldtype": "Data",
				"in_list_view": 0,
				"insert_after": "custom_biometric_face_image",
			},
			{
				"fieldname": "custom_biometric_pin",
				"label": "Door Access PIN",
				"fieldtype": "Data",
				"description": "4-6 digit keypad entry PIN",
				"in_list_view": 0,
				"insert_after": "custom_biometric_card_no",
			},
			{
				"fieldname": "custom_column_break_bio",
				"fieldtype": "Column Break",
				"insert_after": "custom_biometric_pin",
			},
			{
				"fieldname": "custom_biometric_sync_status",
				"label": "Biometric Sync Status",
				"fieldtype": "Select",
				"options": "Not Synced\nSynced\nPending\nFailed",
				"default": "Not Synced",
				"read_only": 1,
				"in_list_view": 1,
				"in_standard_filter": 1,
				"insert_after": "custom_column_break_bio",
			},
			{
				"fieldname": "custom_biometric_last_synced",
				"label": "Biometric Last Synced",
				"fieldtype": "Datetime",
				"read_only": 1,
				"insert_after": "custom_biometric_sync_status",
			},
			{
				"fieldname": "custom_biometric_device_enrolled_id",
				"label": "Enrolled Device ID",
				"fieldtype": "Data",
				"read_only": 0,
				"description": "Active hardware ID currently provisioned on physical biometric terminals (editable for legacy migrations)",
				"insert_after": "custom_biometric_last_synced",
			},
			{
				"fieldname": "custom_biometric_exempt",
				"label": "Exempt from Biometric Sync",
				"fieldtype": "Check",
				"default": "0",
				"description": "Exclude contractor or remote employee from physical door terminals",
				"insert_after": "custom_biometric_device_enrolled_id",
			},
			{
				"fieldname": "custom_biometric_access_roles",
				"label": "Physical Door Access Roles",
				"fieldtype": "Table",
				"options": "Biometric Employee Access Role",
				"description": "Tag this employee with one or more physical access roles (e.g. Server Room, Warehouse, Main Gate)",
				"insert_after": "custom_biometric_exempt",
			},
			{
				"fieldname": "custom_biometric_blacklisted",
				"label": "Blacklist on Hardware (Deny Entry)",
				"fieldtype": "Check",
				"default": "0",
				"description": "Instantly block physical terminal access and trigger hardware alarms upon scan",
				"insert_after": "custom_biometric_access_roles",
			},
			{
				"fieldname": "custom_biometric_device_admin",
				"label": "Hardware Device Administrator",
				"fieldtype": "Check",
				"default": "0",
				"description": "Grant on-device local administrator menu access on physical terminal screens",
				"insert_after": "custom_biometric_blacklisted",
			},
			{
				"fieldname": "custom_biometric_long_term",
				"label": "Long-Term Effective User",
				"fieldtype": "Check",
				"default": "1",
				"description": "User credentials on physical terminal never expire (1970 - 2037). Uncheck to enforce contract / relieving expiration.",
				"insert_after": "custom_biometric_device_admin",
			},
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True)

	# Ensure permlevel is 0 so fields are visible on the Employee form
	if frappe.db.table_exists("Custom Field"):
		frappe.db.sql("""
			UPDATE `tabCustom Field`
			SET permlevel = 0
			WHERE dt = 'Employee'
			  AND fieldname IN ('custom_biometric_access_roles', 'custom_biometric_blacklisted', 'custom_biometric_device_admin', 'custom_biometric_long_term', 'custom_biometric_device_enrolled_id')
		""")
		frappe.db.sql("""
			UPDATE `tabCustom Field`
			SET read_only = 0
			WHERE dt = 'Employee'
			  AND fieldname = 'custom_biometric_device_enrolled_id'
		""")


def copy_legacy_attendance_data():
	"""
	Step 2 Method: Copies historical data from legacy attendance columns into custom_* columns.
	Handles MariaDB strict mode by only updating where custom_* IS NULL (avoids comparing TIME columns with '').
	Run manually via:
	  bench --site mrp.maarifagroup.com execute biometric_integration.biometric_integration.setup.copy_legacy_attendance_data
	"""
	if not frappe.db.table_exists("Attendance"):
		print("tabAttendance does not exist.")
		return

	# Mapping: (legacy column, new custom_* column, is_time_field)
	cols = [
		("arrival_time", "custom_arrival_time", True),
		("departure_time", "custom_departure_time", True),
		("working_time", "custom_working_time", False),
		("normal_time", "custom_normal_time", False),
		("overtime", "custom_overtime", False),
		("overtime_fridays", "custom_overtime_fridays", False),
		("overtime_holidays", "custom_overtime_holidays", False),
		("mrp_overtime", "custom_total_overtime", False),
		("mrp_overtime_type", "custom_overtime_type", False),
	]

	print("\n--- Starting Legacy Attendance Data Copy ---")
	for old_col, new_col, is_time in cols:
		has_old = frappe.db.has_column("Attendance", old_col)
		has_new = frappe.db.has_column("Attendance", new_col)

		if not has_old:
			print(f"[{old_col}] Legacy column not present in table. Skipped.")
			continue

		if not has_new:
			print(f"[{new_col}] New custom column not present in table. Please run bench migrate or sync first.")
			continue

		if is_time:
			# In MariaDB, comparing a TIME column with '' throws error 1292.
			# We only compare with NULL or valid time length > 0.
			old_cnt = frappe.db.sql(
				f"SELECT COUNT(*) FROM `tabAttendance` WHERE `{old_col}` IS NOT NULL"
			)[0][0]

			frappe.db.sql(f"""
				UPDATE `tabAttendance`
				SET `{new_col}` = `{old_col}`
				WHERE `{old_col}` IS NOT NULL
				  AND `{new_col}` IS NULL
			""")
		else:
			old_cnt = frappe.db.sql(
				f"SELECT COUNT(*) FROM `tabAttendance` WHERE `{old_col}` IS NOT NULL AND `{old_col}` != 0"
			)[0][0]

			frappe.db.sql(f"""
				UPDATE `tabAttendance`
				SET `{new_col}` = `{old_col}`
				WHERE `{old_col}` IS NOT NULL
				  AND (`{new_col}` IS NULL OR `{new_col}` = 0)
			""")

		frappe.db.commit()

		new_cnt = frappe.db.sql(
			f"SELECT COUNT(*) FROM `tabAttendance` WHERE `{new_col}` IS NOT NULL"
		)[0][0]

		print(f"{old_col} ({old_cnt} rows) -> {new_col} ({new_cnt} rows) [Copied Successfully]")

	print("--- Copy Completed Successfully! ---\n")


def remove_legacy_attendance_columns():
	"""
	Step 3 Method: Safely removes legacy attendance columns AFTER you have verified the copy.
	Run manually via:
	  bench --site mrp.maarifagroup.com execute biometric_integration.biometric_integration.setup.remove_legacy_attendance_columns
	"""
	if not frappe.db.table_exists("Attendance"):
		print("tabAttendance does not exist.")
		return

	cols = [
		("arrival_time", "custom_arrival_time"),
		("departure_time", "custom_departure_time"),
		("working_time", "custom_working_time"),
		("normal_time", "custom_normal_time"),
		("overtime", "custom_overtime"),
		("overtime_fridays", "custom_overtime_fridays"),
		("overtime_holidays", "custom_overtime_holidays"),
		("mrp_overtime", "custom_total_overtime"),
		("mrp_overtime_type", "custom_overtime_type"),
	]

	print("\n--- Removing Legacy Attendance Columns & Custom Fields ---")
	for old_col, new_col in cols:
		if not frappe.db.has_column("Attendance", old_col):
			print(f"[{old_col}] Already removed.")
			continue

		# Safety Verification: Ensure new column has data before dropping old
		unmigrated = 0
		if frappe.db.has_column("Attendance", new_col):
			unmigrated = frappe.db.sql(f"""
				SELECT COUNT(*) FROM `tabAttendance`
				WHERE `{old_col}` IS NOT NULL
				  AND `{new_col}` IS NULL
			""")[0][0]

		if unmigrated > 0:
			print(f"SAFETY ABORT for {old_col}: {unmigrated} records not copied into {new_col}! Column NOT dropped.")
			continue

		# 1. Delete Custom Field doc if managed by Frappe
		cf_name = f"Attendance-{old_col}"
		if frappe.db.exists("Custom Field", cf_name):
			frappe.delete_doc("Custom Field", cf_name, ignore_permissions=True)
			print(f"Deleted Custom Field record: {cf_name}")

		# 2. Drop the physical database column if still present
		if frappe.db.has_column("Attendance", old_col):
			try:
				frappe.db.sql(f"ALTER TABLE `tabAttendance` DROP COLUMN `{old_col}`")
				print(f"Dropped physical column: {old_col}")
			except Exception as e:
				print(f"Note: Could not drop column {old_col}: {e}")

		frappe.db.commit()

	print("--- Cleanup Finished! ---\n")
