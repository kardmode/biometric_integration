import frappe
from datetime import datetime
from frappe.model.document import Document
from biometric_integration.biometric_integration.checkin_utils import create_employee_checkin


class BiometricManualPunch(Document):
    def after_insert(self):
        add_manual_punch(self.employee, self.punch_date, self.punch_time)

    def on_update(self):
        add_manual_punch(self.employee, self.punch_date, self.punch_time)


@frappe.whitelist()
def add_manual_punch(employee, punch_date, punch_time):
    try:
        employee_name = frappe.db.get_value("Employee", employee, "employee_name")
        punch_time = str(punch_time).split(".")[0]
        punch_datetime = datetime.strptime(f"{punch_date} {punch_time}", "%Y-%m-%d %H:%M:%S")

        create_employee_checkin(employee, punch_datetime, log_type=None, device_id="Manual", cooldown_minutes=0)
        frappe.db.commit()

        return {"status": "success", "message": f"Manual punch for {employee_name} on {punch_date} at {punch_time} added successfully."}

    except Exception as e:
        return {"status": "error", "message": f"Error adding manual punch: {str(e)}"}


@frappe.whitelist()
def delete_manual_punch(doc, method=None):
    try:
        employee = doc.get("employee")
        punch_date = doc.get("punch_date")
        punch_time = str(doc.get("punch_time")).split(".")[0]
        punch_datetime_str = f"{punch_date} {punch_time}"

        # Delete corresponding Employee Checkin if exists
        checkins = frappe.get_all(
            "Employee Checkin",
            filters={"employee": employee, "time": punch_datetime_str, "device_id": "Manual"},
            pluck="name"
        )
        for cname in checkins:
            frappe.delete_doc("Employee Checkin", cname, ignore_permissions=True)

        frappe.db.commit()
    except Exception as e:
        frappe.log_error(title="Delete Manual Punch Error", message=str(e))