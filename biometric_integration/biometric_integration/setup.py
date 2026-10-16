# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
	"""
	Ensure custom fields exist on Attendance and Employee doctypes.
	Called automatically after bench migrate.
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
				"read_only": 1,
				"description": "Active hardware ID currently provisioned on physical biometric terminals",
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
				"permlevel": 1,
				"description": "Tag this employee with one or more physical access roles (e.g. Server Room, Warehouse, Main Gate)",
				"insert_after": "custom_biometric_exempt",
			},
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True)
