# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cstr,
	flt,
	format_date,
	get_datetime,
	get_time,
	getdate,
	nowdate,
	time_diff,
	time_diff_in_seconds,
)

from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from hrms.hr.doctype.attendance.attendance import Attendance


class CustomAttendance(Attendance):
	def validate(self):
		super().validate()
		self.calculate_total_hours()
		if flt(getattr(self, "custom_normal_time", 0)) < 0:
			frappe.throw(_("Working Time cannot be less than 0, date {0}").format(self.attendance_date))

	def validate_attendance_date(self):
		date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")
		new_date = add_days(getdate(nowdate()), 45)

		# Custom: leaves can be marked for future dates up to 45 days
		if (
			self.status != "On Leave"
			and not getattr(self, "leave_application", None)
			and getdate(self.attendance_date) > new_date
		):
			frappe.throw(_("Attendance can not be marked for more than 45 days in the future"))
		elif date_of_joining and getdate(self.attendance_date) < getdate(date_of_joining):
			frappe.throw(
				_("Attendance date {0} can not be less than employee {1}'s joining date: {2}").format(
					frappe.bold(format_date(self.attendance_date)),
					frappe.bold(self.employee),
					frappe.bold(format_date(date_of_joining)),
				)
			)

	def calculate_total_hours(self):
		# 1. Resolve Arrival Time
		arrival_raw = getattr(self, "custom_arrival_time", None)
		if not arrival_raw and self.in_time:
			try:
				arrival_raw = get_time(self.in_time).strftime("%H:%M:%S")
			except Exception:
				arrival_raw = None

		# 2. Resolve Departure Time
		departure_raw = getattr(self, "custom_departure_time", None)
		if not departure_raw and self.out_time:
			try:
				departure_raw = get_time(self.out_time).strftime("%H:%M:%S")
			except Exception:
				departure_raw = None

		# 3. Sanitize empty or placeholder values to "00:00:00"
		if not arrival_raw or str(arrival_raw).strip() in ["#--:--", "00:00", "0:00:00", "00:00:0", "00:00:00", "None", ""]:
			arrival_raw = "00:00:00"

		if not departure_raw or str(departure_raw).strip() in ["#--:--", "00:00", "0:00:00", "00:00:0", "00:00:00", "None", ""]:
			departure_raw = "00:00:00"

		try:
			arrival_str = get_time(arrival_raw).strftime("%H:%M:%S")
		except Exception as e:
			frappe.throw(_("Possible error in arrival time {0} for employee {1}: {2}").format(arrival_raw, self.employee, cstr(e)))

		try:
			departure_str = get_time(departure_raw).strftime("%H:%M:%S")
		except Exception as e:
			frappe.throw(_("Possible error in departure time {0} for employee {1}: {2}").format(departure_raw, self.employee, cstr(e)))

		self.custom_arrival_time = arrival_str
		self.custom_departure_time = departure_str

		totalworkhours = 0
		try:
			totalworkhours = flt(time_diff_in_seconds(departure_str, arrival_str)) / 3600
		except Exception:
			try:
				diff_t = time_diff(departure_str, arrival_str)
				totalworkhours = flt(diff_t.hour) + flt(diff_t.minute) / 60 + flt(diff_t.second) / 3600
			except Exception:
				frappe.throw(_("Possible error in arrival time {0} or departure time {1} for employee {2}").format(arrival_str, departure_str, self.employee))

		if totalworkhours < 0:
			frappe.throw(_("Working time cannot be negative. Please check arrival time {0} or departure time {1} for employee {2} on date {3}").format(arrival_str, departure_str, self.employee, self.attendance_date))
		elif totalworkhours > 24:
			frappe.throw(_("Working time cannot be greater than 24. Please check arrival time {0} or departure time {1} for employee {2} on date {3}").format(arrival_str, departure_str, self.employee, self.attendance_date))

		self.custom_working_time = totalworkhours

		if not getattr(self, "department", None):
			self.department = frappe.db.get_value("Employee", self.employee, "department")

		# Check MRP Working Hours table
		working_hours = None
		if frappe.db.table_exists("MRP Working Hours"):
			working_hours = frappe.db.sql(
				"""select working_hours from `tabMRP Working Hours`
				where %s >= from_date AND %s <= to_date and (department = %s or department = 'All Departments' or ISNULL(NULLIF(department, '')))""",
				(self.attendance_date, self.attendance_date, self.department),
			)

		if working_hours and working_hours[0][0]:
			normal_time_val = flt(working_hours[0][0])
		else:
			# MRP Regulations is a Single (stored in tabSingles), so table_exists() is always False for it
			# and must not guard this read; 8 is only the fallback when the doctype or value is missing
			normal_time_val = 8.0
			if frappe.db.exists("DocType", "MRP Regulations"):
				normal_time_val = flt(frappe.db.get_single_value("MRP Regulations", "working_hours")) or 8.0

		# Weekends check from MRP Day Selector / MRP Regulations
		weekends = []
		if frappe.db.table_exists("MRP Day Selector"):
			weekend_tb = frappe.get_list(
				"MRP Day Selector",
				["day"],
				filters={"parent": "MRP Regulations", "parenttype": "MRP Regulations", "parentfield": "weekends"},
				parent_doctype="MRP Regulations",
			)
			for d in weekend_tb:
				weekends.append(d.day)

		weekday_name = get_datetime(self.attendance_date).strftime("%A")

		overtime_val = 0
		overtime_fridays_val = 0
		overtime_holidays_val = 0
		total_overtime_val = 0
		overtime_type_val = "Weekdays"

		if self.status not in ["On Leave", "Half Day"]:
			self.status = "Present"

		if len(self.get_holidays_for_employee(self.attendance_date, self.attendance_date)):
			normal_time_val = 0
			overtime_holidays_val = flt(totalworkhours) - flt(normal_time_val)
			total_overtime_val = overtime_holidays_val
			overtime_type_val = "Holidays"
		elif weekday_name in weekends:
			normal_time_val = 0
			overtime_fridays_val = flt(totalworkhours) - flt(normal_time_val)
			total_overtime_val = overtime_fridays_val
			overtime_type_val = "Weekends"
		else:
			if totalworkhours > normal_time_val:
				overtime_val = flt(totalworkhours) - flt(normal_time_val)
				total_overtime_val = overtime_val
				overtime_type_val = "Weekdays"
				if self.status == "On Leave":
					frappe.throw(_("Employee on leave this day but has attendance. Please check the time for employee {0}, date {1}").format(self.employee, self.attendance_date))
			elif totalworkhours > 2:
				normal_time_val = totalworkhours
				if self.status == "On Leave":
					frappe.throw(_("Employee on leave this day but has attendance. Please check the time for employee {0}, date {1}").format(self.employee, self.attendance_date))
			elif totalworkhours > 0:
				frappe.throw(_("Work Hours under 2. Please check the time for employee {0}, date {1}").format(self.employee, self.attendance_date))
			elif totalworkhours < 0:
				frappe.throw(_("Work Hours negative. Please check the time for employee {0}, date {1}").format(self.employee, self.attendance_date))
			else:
				if arrival_str == "00:00:00" and departure_str == "00:00:00":
					normal_time_val = 0
					self.custom_working_time = 0
					if self.status != "On Leave":
						self.status = "Absent"
				else:
					frappe.throw(_("Work Hours equal 0. Please check the time for employee {0}, date {1}, arrival time {2}, departure time {3}").format(self.employee, self.attendance_date, arrival_str, departure_str))

		# Write clean custom fields ONLY
		self.custom_normal_time = normal_time_val
		self.custom_overtime = overtime_val
		self.custom_overtime_fridays = overtime_fridays_val
		self.custom_overtime_holidays = overtime_holidays_val
		self.custom_total_overtime = total_overtime_val
		self.custom_overtime_type = overtime_type_val

	def check_leave_record(self):
		"""
		hrms check_leave_record, adjusted for MRP leave handling:
		- Leave in MRP's 'Back From Leave' status still counts (hrms only matches 'Approved').
		  custom_actual_return_date is the first day back at work, so once recorded the leave
		  ends the day before it (early or late return), otherwise on to_date.
		- A holiday inside a leave whose Leave Type excludes holidays is not a leave day:
		  it is marked Present rather than On Leave (or Absent).
		"""
		LeaveApplication = frappe.qb.DocType("Leave Application")
		within_leave_end = self.attendance_date <= LeaveApplication.to_date
		if frappe.db.has_column("Leave Application", "custom_actual_return_date"):
			within_leave_end = (
				LeaveApplication.custom_actual_return_date.isnull() & (self.attendance_date <= LeaveApplication.to_date)
			) | (self.attendance_date < LeaveApplication.custom_actual_return_date)

		leave_record = (
			frappe.qb.from_(LeaveApplication)
			.select(
				LeaveApplication.leave_type,
				LeaveApplication.half_day,
				LeaveApplication.half_day_date,
				LeaveApplication.name,
			)
			.where(
				(LeaveApplication.employee == self.employee)
				& (self.attendance_date >= LeaveApplication.from_date)
				& within_leave_end
				& (LeaveApplication.status.isin(["Approved", "Back From Leave"]))
				& (LeaveApplication.docstatus == 1)
			)
		).run(as_dict=True)

		if leave_record and cstr(getdate(self.attendance_date)) in self.get_holidays_for_employee(
			self.attendance_date, self.attendance_date
		):
			leave_record = [
				d for d in leave_record if frappe.get_cached_value("Leave Type", d.leave_type, "include_holiday")
			]
			if not leave_record:
				# holiday within the leave, not counted as leave: neither On Leave nor Absent
				self.status = "Present"
				self.leave_type = None
				self.leave_application = None
				return

		if leave_record:
			for d in leave_record:
				self.leave_type = d.leave_type
				self.leave_application = d.name
				if d.half_day_date == getdate(self.attendance_date):
					self.status = "Half Day"
					frappe.msgprint(
						_("Employee {0} on Half day on {1}").format(self.employee, format_date(self.attendance_date))
					)
				else:
					self.status = "On Leave"
					frappe.msgprint(
						_("Employee {0} is on Leave on {1}").format(self.employee, format_date(self.attendance_date))
					)

		if self.status in ("On Leave", "Half Day"):
			if not leave_record:
				frappe.msgprint(
					_("No leave record found for employee {0} on {1}").format(
						self.employee, format_date(self.attendance_date)
					),
					alert=1,
				)
		elif self.leave_type:
			self.leave_type = None
			self.leave_application = None

	def get_holidays_for_employee(self, start_date, end_date):
		# The employee's holiday list, else the company default (same rule as erpnext). The old version fell
		# back to a default list per date, so a day missing from the employee's own list could still count
		# as a holiday, and it relied on an is_default field Holiday List doesn't have.
		holiday_list = get_holiday_list_for_employee(self.employee, raise_exception=False)
		if not holiday_list:
			return []

		holidays = frappe.get_all(
			"Holiday",
			filters={"parent": holiday_list, "holiday_date": ["between", [start_date, end_date]]},
			pluck="holiday_date",
		)
		return [cstr(d) for d in holidays]
