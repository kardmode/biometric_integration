# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import secrets
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime, get_datetime
from datetime import timedelta
from biometric_integration.biometric_integration.hikvision_isapi import (
    sync_person_to_device,
    delete_person_from_device
)


class BiometricVisitorPass(Document):
    def before_insert(self):
        # 1. Generate random 6-digit PIN if empty
        if not self.pin_code:
            self.pin_code = f"{secrets.randbelow(900000) + 100000}"

        # 2. Assign temporary numeric hardware ID (prefix 9 to differentiate from normal staff)
        if not self.visitor_device_id:
            self.visitor_device_id = f"9{secrets.randbelow(90000) + 10000}"

        # 3. Default validity dates
        now = now_datetime()
        if not self.valid_from:
            self.valid_from = now
        if not self.valid_to:
            # Default to 8 hours from now
            self.valid_to = now + timedelta(hours=8)

    def validate(self):
        if get_datetime(self.valid_to) <= get_datetime(self.valid_from):
            frappe.throw(_("Valid Until date must be later than Valid From date."))

    def after_insert(self):
        # Automatically provision on creation if Active
        if self.status == "Active":
            self.sync_to_devices()

    def on_trash(self):
        # Clean up from physical door terminals
        self.revoke_from_devices()

    def get_target_devices(self):
        """Returns target Biometric Devices for this visitor."""
        target_devices = []
        if self.doors:
            device_names = [d.device for d in self.doors if d.device]
            for name in device_names:
                doc = frappe.get_doc("Biometric Device", name)
                if doc.enabled and doc.ip and doc.username:
                    target_devices.append(doc)
        else:
            # Default to all active access control devices
            active = frappe.get_all("Biometric Device", filters={"enabled": 1, "enable_access_control": 1}, pluck="name")
            for name in active:
                doc = frappe.get_doc("Biometric Device", name)
                if doc.ip and doc.username:
                    target_devices.append(doc)
        return target_devices

    @frappe.whitelist()
    def sync_to_devices(self):
        """Pushes temporary visitor pass, validity window, and PIN to authorized door terminals."""
        if self.status != "Active":
            frappe.throw(_("Pass cannot be synced because it is {0}.").format(self.status))

        devices = self.get_target_devices()
        if not devices:
            frappe.throw(_("No active access control devices found to sync this visitor pass."))

        success_log = []
        error_log = []

        valid_from_dt = get_datetime(self.valid_from)
        valid_to_dt = get_datetime(self.valid_to)

        for dev in devices:
            res = sync_person_to_device(
                device=dev,
                employee_no=self.visitor_device_id,
                name=self.visitor_name,
                pin=self.pin_code,
                door_no=1,
                user_type="visitor",
                valid_from=valid_from_dt,
                valid_to=valid_to_dt
            )
            if res.get("status") == "success":
                success_log.append(f"{dev.name}: OK")
            else:
                error_log.append(f"{dev.name}: {res.get('message')}")

        now = now_datetime()
        log_text = "Synced: " + ", ".join(success_log) if success_log else ""
        if error_log:
            log_text += (" | " if log_text else "") + "Failed: " + "; ".join(error_log)

        self.db_set("last_synced", now)
        self.db_set("sync_details", log_text)

        if success_log and not error_log:
            return {"status": "success", "message": _("Visitor pass active on: {0}").format(", ".join(success_log))}
        elif success_log and error_log:
            return {"status": "warning", "message": _("Partial success.<br>{0}").format(log_text)}
        else:
            return {"status": "error", "message": _("Failed to push to devices:<br>{0}").format(log_text)}

    @frappe.whitelist()
    def revoke_from_devices(self):
        """Removes the visitor from hardware and sets status to Revoked."""
        devices = self.get_target_devices()
        results = []
        for dev in devices:
            res = delete_person_from_device(dev, self.visitor_device_id)
            results.append(f"{dev.name}: {res.get('message', res.get('status'))}")

        self.db_set("status", "Revoked")
        return {"status": "success", "message": _("Visitor pass revoked.<br>{0}").format("<br>".join(results))}


def expire_old_visitor_passes():
    """
    Scheduled cron job to clean up expired passes from physical door terminals.
    """
    now = now_datetime()
    expired_passes = frappe.get_all(
        "Biometric Visitor Pass",
        filters={"status": "Active", "valid_to": ["<", now]},
        pluck="name"
    )
    for pass_name in expired_passes:
        try:
            doc = frappe.get_doc("Biometric Visitor Pass", pass_name)
            doc.revoke_from_devices()
            doc.db_set("status", "Expired")
        except Exception as e:
            frappe.log_error(f"Error expiring visitor pass {pass_name}: {e}", "Biometric Integration")
