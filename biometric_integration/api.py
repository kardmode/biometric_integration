# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from biometric_integration.biometric_integration.api import hikvision_event_receiver


@frappe.whitelist(allow_guest=True)
def push():
    """
    Ultra-short webhook endpoint alias designed specifically for hardware
    terminals (like Hikvision) that enforce short URL input limits.
    Endpoint: /api/method/biometric_integration.api.push
    """
    return hikvision_event_receiver()
