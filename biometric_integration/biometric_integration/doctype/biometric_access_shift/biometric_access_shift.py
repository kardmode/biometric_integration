# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

from datetime import datetime

try:
    import frappe
    from frappe import _
    from frappe.model.document import Document
except ImportError:
    class Document:
        pass
    def _(msg):
        return msg

from biometric_integration.biometric_integration.hikvision_isapi import (
    validate_door_schedule,
    parse_time_to_seconds,
    format_seconds_to_time_str
)


class BiometricAccessShift(Document):
    def get(self, key, default=None):
        val = getattr(self, key, default)
        return val if val is not None else default

    def validate(self):
        # Validate Hikvision plan template number
        plan_no = getattr(self, "hikvision_plan_no", 1) or 1
        if plan_no < 1 or plan_no > 255:
            frappe.throw(_("Hikvision Plan Template No must be between 1 and 255."))

        # Validate schedule items using strict overlap & inverted time rules
        items = self.get("schedule_items") or []
        validate_door_schedule(items, enable_free_passage=True)

    def is_active_now(self, dt_obj=None):
        """
        Evaluates whether the current moment (or a given datetime) falls
        within any configured schedule interval for the current day of the week.
        Returns (is_active, formatted_allowed_window_or_message).
        """
        now = dt_obj or datetime.now()
        day_name = now.strftime("%A")  # Monday, Tuesday, etc.
        now_sec = now.hour * 3600 + now.minute * 60 + now.second

        items = self.get("schedule_items") or []
        today_intervals = []

        for row in items:
            row_day = row.get("day_of_week") if hasattr(row, "get") else getattr(row, "day_of_week", None)
            if row_day != day_name:
                continue

            start_val = row.get("start_time") if hasattr(row, "get") else getattr(row, "start_time", None)
            end_val = row.get("end_time") if hasattr(row, "get") else getattr(row, "end_time", None)

            start_sec = parse_time_to_seconds(start_val)
            end_sec = parse_time_to_seconds(end_val)

            if start_sec is not None and end_sec is not None:
                today_intervals.append((start_sec, end_sec))
                if start_sec <= now_sec <= end_sec:
                    return True, f"{day_name} {format_seconds_to_time_str(start_sec)} - {format_seconds_to_time_str(end_sec)}"

        if today_intervals:
            windows = ", ".join([f"{format_seconds_to_time_str(s)} - {format_seconds_to_time_str(e)}" for s, e in today_intervals])
            return False, f"Allowed today ({day_name}) only during: {windows}"

        shift_label = getattr(self, 'shift_name', None) or getattr(self, 'name', 'Access Shift')
        return False, f"No access intervals configured for {day_name} in shift '{shift_label}'."
