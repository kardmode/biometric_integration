# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup_custom_fields():
	"""
	Ensure custom_review_status and custom_review_reason exist on Attendance doctype.
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
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True)
