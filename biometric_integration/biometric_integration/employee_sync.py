# Copyright (c) 2026, NDV and contributors
# For license information, please see license.txt

import re
import json
import frappe
from frappe import _
from frappe.utils import now_datetime
from biometric_integration.biometric_integration.hikvision_isapi import (
    sync_person_to_device,
    delete_person_from_device,
    get_enrolled_user_count,
    get_enrolled_users,
    download_face_image_from_device,
    upload_face_image_to_device
)


def sanitize_hardware_id(id_val):
    """
    Sanitizes an employee or attendance device ID to conform strictly to Hikvision hardware limits:
    - Alphanumeric characters only [A-Za-z0-9]
    - Strips hyphens (-), slashes (/), underscores (_), spaces, and special symbols
    - e.g. 'NDV-HR-EMP-00001' -> 'NDVHREMP00001'
    - e.g. 'EMP/0001' -> 'EMP0001'
    """
    if not id_val:
        return ""
    return re.sub(r'[^A-Za-z0-9]', '', str(id_val).strip())


def get_employee_face_bytes(employee_doc_or_dict):
    """Retrieves binary bytes of custom_biometric_face_image from Frappe file system."""
    face_url = employee_doc_or_dict.get("custom_biometric_face_image")
    if not face_url:
        return None
    try:
        from frappe.utils.file_manager import get_file_path
        file_path = get_file_path(face_url)
        if file_path:
            with open(file_path, "rb") as f:
                return f.read()
    except Exception as e:
        frappe.log_error(f"Error reading face image: {e}", "Biometric Integration")
    return None


def get_target_devices_for_employee(employee_doc):
    """
    Determines which active Biometric Devices this employee should be provisioned to.
    - If device has enable_access_control: Checks device authorization rules (Allowed Roles, Whitelist, All Employees).
    - If device only has enable_attendance (pure timeclock): All active non-exempt employees get synced.
    """
    devices = frappe.get_all(
        "Biometric Device",
        filters={"enabled": 1},
        fields=["name", "enable_attendance", "enable_access_control"]
    )
    target_devices = []
    for d in devices:
        dev_doc = frappe.get_doc("Biometric Device", d.name)
        if not dev_doc.ip or not dev_doc.username:
            continue

        # 1. Door Access Control: Strict physical authorization check (Physical Roles / Allowed Employees / All Active)
        if dev_doc.enable_access_control:
            if dev_doc.is_employee_physically_authorized(employee_doc=employee_doc):
                target_devices.append(dev_doc)
            continue

        # 2. Pure Time & Attendance terminal (no physical door locking relay)
        if dev_doc.enable_attendance:
            target_devices.append(dev_doc)

    return target_devices


@frappe.whitelist()
def fetch_face_from_device(employee_name, device_name=None):
    """
    Downloads the verified biometric face capture of an employee from a device
    and saves it to the Employee doctype under custom_biometric_face_image.
    """
    emp = frappe.get_doc("Employee", employee_name)
    emp_no = sanitize_hardware_id(emp.attendance_device_id or emp.name)
    enrolled_id = sanitize_hardware_id(emp.get("custom_biometric_device_enrolled_id"))

    if device_name:
        devices = [frappe.get_doc("Biometric Device", device_name)]
    else:
        # Default: try all active terminals
        device_names = frappe.get_all("Biometric Device", filters={"enabled": 1}, pluck="name")
        devices = [frappe.get_doc("Biometric Device", d) for d in device_names]

    if not devices:
        frappe.throw(_("No active biometric devices found to fetch face from."))

    img_bytes = None
    source_device = None
    last_err = ""

    for dev in devices:
        if not dev.ip or not dev.username:
            continue
        data, err = download_face_image_from_device(dev, emp_no)
        # Fallback to enrolled_id if ID was recently changed in ERPNext
        if not data and enrolled_id and enrolled_id != emp_no:
            data, err = download_face_image_from_device(dev, enrolled_id)
        if data:
            img_bytes = data
            source_device = dev
            break
        last_err = err or last_err

    if not img_bytes:
        return {
            "status": "error",
            "message": _("Could not find enrolled face for {0} (ID: {1}).<br>Reason: {2}").format(
                emp.employee_name or emp.name, emp_no, last_err
            )
        }

    # Save to Frappe file system
    from frappe.utils.file_manager import save_file
    file_doc = save_file(
        fname=f"bio_face_{emp_no}.jpg",
        content=img_bytes,
        dt="Employee",
        dn=emp.name,
        is_private=1,
        df="custom_biometric_face_image"
    )

    emp.db_set("custom_biometric_face_image", file_doc.file_url)

    return {
        "status": "success",
        "file_url": file_doc.file_url,
        "message": _("Successfully retrieved biometric face from <b>{0}</b> and saved to Employee!").format(source_device.name)
    }


@frappe.whitelist()
def sync_employee_to_devices(employee_name):
    """
    Whitelisted API to sync a specific Employee to all authorized Biometric Devices.
    Safe: uses ISAPI UserInfo/Modify to preserve existing face and fingerprints.
    Replicates custom_biometric_face_image if available.
    Automatically removes old hardware ID if attendance_device_id was changed.
    """
    emp = frappe.get_doc("Employee", employee_name)
    if emp.get("custom_biometric_exempt"):
        return {"status": "warning", "message": _("Employee {0} is marked as exempt from biometric sync.").format(emp.name)}

    # Determine desired hardware ID (strictly alphanumeric for Hikvision hardware)
    emp_no = sanitize_hardware_id(emp.attendance_device_id or emp.name)
    enrolled_id = sanitize_hardware_id(emp.get("custom_biometric_device_enrolled_id"))
    emp_name = emp.employee_name or emp.name
    card_no = emp.get("custom_biometric_card_no")
    pin = emp.get("custom_biometric_pin")
    face_bytes = get_employee_face_bytes(emp)
    is_blacklisted = bool(emp.get("custom_biometric_blacklisted"))
    is_admin = bool(emp.get("custom_biometric_device_admin"))
    user_type = "blackList" if is_blacklisted else "normal"
    user_role = "admin" if is_admin else "normal"
    is_long_term = emp.get("custom_biometric_long_term") if emp.get("custom_biometric_long_term") is not None else 1
    valid_from = emp.get("date_of_joining") if not is_long_term else None
    valid_to = (emp.get("contract_end_date") or emp.get("relieving_date")) if not is_long_term else None

    target_devices = get_target_devices_for_employee(emp)
    if not target_devices:
        return {"status": "info", "message": _("No active biometric devices found or authorized for {0}.").format(emp.name)}

    # If the ID changed, wipe the old hardware ID first from all devices
    if enrolled_id and enrolled_id != emp_no:
        for dev in target_devices:
            delete_person_from_device(dev, enrolled_id)

    # Clean up credentials from any door terminals where employee is NOT authorized
    all_doors = frappe.get_all(
        "Biometric Device",
        filters={"enabled": 1, "enable_access_control": 1},
        pluck="name"
    )
    target_device_names = {d.name for d in target_devices}
    for door_name in all_doors:
        if door_name not in target_device_names:
            door_dev = frappe.get_doc("Biometric Device", door_name)
            if door_dev.ip and door_dev.username:
                delete_person_from_device(door_dev, emp_no)
                if enrolled_id and enrolled_id != emp_no:
                    delete_person_from_device(door_dev, enrolled_id)

    success_devices = []
    failed_devices = []

    for dev in target_devices:
        plan_no = dev.get_employee_plan_template_no(emp) if hasattr(dev, "get_employee_plan_template_no") else 1
        res = sync_person_to_device(
            device=dev,
            employee_no=emp_no,
            name=emp_name,
            card_no=card_no,
            pin=pin,
            user_type=user_type,
            user_role=user_role,
            is_long_term=bool(is_long_term),
            valid_from=valid_from,
            valid_to=valid_to,
            face_image_bytes=face_bytes,
            plan_template_no=plan_no
        )
        if res.get("status") == "success":
            success_devices.append(f"{dev.name} ({res.get('action')})")
        else:
            failed_devices.append(f"{dev.name}: {res.get('message')}")

    now = now_datetime()
    if success_devices:
        emp.db_set("custom_biometric_device_enrolled_id", emp_no)

    if success_devices and not failed_devices:
        emp.db_set("custom_biometric_sync_status", "Synced")
        emp.db_set("custom_biometric_last_synced", now)
        return {
            "status": "success",
            "message": _("Synced to: {0} (Hardware ID: {1})").format(", ".join(success_devices), emp_no)
        }
    elif success_devices and failed_devices:
        emp.db_set("custom_biometric_sync_status", "Pending")
        emp.db_set("custom_biometric_last_synced", now)
        return {
            "status": "warning",
            "message": _("Partial success.<br>Synced: {0}<br>Failed: {1}").format(", ".join(success_devices), "<br>".join(failed_devices))
        }
    else:
        emp.db_set("custom_biometric_sync_status", "Failed")
        return {
            "status": "error",
            "message": _("Failed to sync on all devices:<br>{0}").format("<br>".join(failed_devices))
        }


@frappe.whitelist()
def remove_employee_from_devices(employee_name):
    """
    Whitelisted API to delete an Employee from all Biometric Devices, revoking access.
    Wipes both current desired ID and previous enrolled ID.
    """
    emp = frappe.get_doc("Employee", employee_name)
    emp_no = sanitize_hardware_id(emp.attendance_device_id or emp.name)
    enrolled_id = sanitize_hardware_id(emp.get("custom_biometric_device_enrolled_id"))

    ids_to_remove = set()
    if emp_no:
        ids_to_remove.add(emp_no)
    if enrolled_id:
        ids_to_remove.add(enrolled_id)

    devices = frappe.get_all("Biometric Device", filters={"enabled": 1}, pluck="name")
    results = []

    for dev_name in devices:
        dev = frappe.get_doc("Biometric Device", dev_name)
        if not dev.ip or not dev.username:
            continue
        for id_val in ids_to_remove:
            delete_person_from_device(dev, id_val)
        results.append(f"{dev.name}: Removed ID(s) {', '.join(ids_to_remove)}")

    emp.db_set("custom_biometric_sync_status", "Not Synced")
    emp.db_set("custom_biometric_device_enrolled_id", None)
    return {"status": "success", "message": "<br>".join(results)}


@frappe.whitelist()
def sync_all_active_employees_to_device(device_name):
    """
    Bulk pushes all active, non-exempt employees to a specific Biometric Device.
    Preserves existing face and fingerprint templates on the device.
    Replicates biometric face captures if available on Employee.
    """
    device = frappe.get_doc("Biometric Device", device_name)
    if not device.enabled:
        frappe.throw(_("Device {0} is disabled.").format(device_name))

    # Fetch active employees
    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=[
            "name",
            "employee_name",
            "attendance_device_id",
            "custom_biometric_device_enrolled_id",
            "custom_biometric_card_no",
            "custom_biometric_pin",
            "custom_biometric_face_image",
            "custom_biometric_exempt",
            "custom_biometric_blacklisted",
            "custom_biometric_device_admin",
            "custom_biometric_long_term",
            "date_of_joining",
            "contract_end_date",
            "relieving_date"
        ]
    )

    # Pre-fetch physical access roles for all active employees
    role_map = {}
    try:
        roles = frappe.get_all("Biometric Employee Access Role", filters={"parenttype": "Employee"}, fields=["parent", "access_role"])
        for r in roles:
            role_map.setdefault(r.parent, []).append({"access_role": r.access_role})
    except Exception:
        role_map = {}

    synced_count = 0
    skipped_count = 0
    errors = []

    for emp_data in employees:
        if emp_data.get("custom_biometric_exempt"):
            skipped_count += 1
            continue

        emp_data["custom_biometric_access_roles"] = role_map.get(emp_data.name, [])

        emp_no = sanitize_hardware_id(emp_data.get("attendance_device_id") or emp_data.get("name"))
        enrolled_id = sanitize_hardware_id(emp_data.get("custom_biometric_device_enrolled_id"))
        emp_name = emp_data.get("employee_name") or emp_data.get("name")
        card_no = emp_data.get("custom_biometric_card_no")
        pin = emp_data.get("custom_biometric_pin")
        face_bytes = get_employee_face_bytes(emp_data)
        is_blacklisted = bool(emp_data.get("custom_biometric_blacklisted"))
        is_admin = bool(emp_data.get("custom_biometric_device_admin"))
        user_type = "blackList" if is_blacklisted else "normal"
        user_role = "admin" if is_admin else "normal"
        is_long_term = emp_data.get("custom_biometric_long_term") if emp_data.get("custom_biometric_long_term") is not None else 1
        valid_from = emp_data.get("date_of_joining") if not is_long_term else None
        valid_to = (emp_data.get("contract_end_date") or emp_data.get("relieving_date")) if not is_long_term else None

        # Clean up old ID if changed
        if enrolled_id and enrolled_id != emp_no:
            delete_person_from_device(device, enrolled_id)

        # Check authorization if device controls a physical door
        if device.enable_access_control and not device.is_employee_physically_authorized(employee_doc=emp_data):
            delete_person_from_device(device, emp_no)
            skipped_count += 1
            continue

        plan_no = device.get_employee_plan_template_no(emp_data) if hasattr(device, "get_employee_plan_template_no") else 1
        res = sync_person_to_device(
            device=device,
            employee_no=emp_no,
            name=emp_name,
            card_no=card_no,
            pin=pin,
            user_type=user_type,
            user_role=user_role,
            is_long_term=bool(is_long_term),
            valid_from=valid_from,
            valid_to=valid_to,
            face_image_bytes=face_bytes,
            plan_template_no=plan_no
        )

        if res.get("status") == "success":
            synced_count += 1
            # Mark employee sync status and enrolled ID
            frappe.db.set_value("Employee", emp_data.name, {
                "custom_biometric_sync_status": "Synced",
                "custom_biometric_last_synced": now_datetime(),
                "custom_biometric_device_enrolled_id": emp_no
            }, update_modified=False)
        else:
            errors.append(f"{emp_name} ({emp_no}): {res.get('message')}")

    frappe.db.commit()

    msg = _("Sync completed on {0}.<br>Successfully synced: <b>{1}</b> employees.<br>Skipped: <b>{2}</b>.").format(
        device_name, synced_count, skipped_count
    )
    if errors:
        msg += f"<br><br><b>Errors ({len(errors)}):</b><br>" + "<br>".join(errors[:10])
        if len(errors) > 10:
            msg += f"<br><i>...and {len(errors) - 10} more.</i>"

    return {"status": "success", "message": msg}


@frappe.whitelist()
def fetch_enrolled_user_count(device_name):
    """Fetches real-time count of enrolled users from the terminal's ISAPI."""
    device = frappe.get_doc("Biometric Device", device_name)
    count = get_enrolled_user_count(device)
    return {"status": "success", "enrolled_users": count}


@frappe.whitelist()
def get_orphan_device_users(device_name):
    """
    Compares users enrolled on the physical terminal with ERPNext records.
    Returns a list of orphan users present on hardware but not recognized in ERPNext.
    """
    device = frappe.get_doc("Biometric Device", device_name)
    terminal_users = get_enrolled_users(device)

    # Build ERPNext whitelist:
    # 1. All employees (Active, etc.) - check attendance ID, enrolled ID, and document name
    employees = frappe.get_all(
        "Employee",
        fields=["name", "attendance_device_id", "custom_biometric_device_enrolled_id"]
    )
    whitelist_ids = set()
    for e in employees:
        if e.get("attendance_device_id"):
            whitelist_ids.add(sanitize_hardware_id(e.attendance_device_id))
        if e.get("custom_biometric_device_enrolled_id"):
            whitelist_ids.add(sanitize_hardware_id(e.custom_biometric_device_enrolled_id))
        if e.get("name"):
            whitelist_ids.add(sanitize_hardware_id(e.name))

    # 2. Also check Visitor Passes if table exists
    if frappe.db.table_exists("Biometric Visitor Pass"):
        passes = frappe.get_all(
            "Biometric Visitor Pass",
            filters={"docstatus": 1, "status": "Active"},
            pluck="visitor_device_id"
        )
        for vp in passes:
            if vp:
                whitelist_ids.add(sanitize_hardware_id(vp))

    # Identify orphans
    orphans = []
    for tu in terminal_users:
        emp_no = tu.get("employeeNo")
        if emp_no and emp_no not in whitelist_ids:
            orphans.append(tu)

    return {
        "status": "success",
        "total_enrolled": len(terminal_users),
        "orphan_count": len(orphans),
        "orphans": orphans
    }


@frappe.whitelist()
def cleanup_orphan_device_users(device_name, user_ids=None):
    """
    Deletes the specified orphan user IDs from the terminal.
    Safe: double-checks each ID against active ERPNext employees before deletion.
    """
    if isinstance(user_ids, str):
        try:
            user_ids = json.loads(user_ids)
        except Exception:
            user_ids = [u.strip() for u in user_ids.split(",") if u.strip()]

    device = frappe.get_doc("Biometric Device", device_name)

    if not user_ids:
        # Detect all orphans automatically
        res = get_orphan_device_users(device_name)
        user_ids = [u["employeeNo"] for u in res.get("orphans", [])]

    if not user_ids:
        return {"status": "info", "message": _("No orphan users found on {0}.").format(device_name)}

    # Ensure none of the IDs belong to active employees (safety whitelist)
    emp_ids = set(frappe.get_all("Employee", filters={"status": "Active"}, pluck="attendance_device_id"))
    emp_ids.update(frappe.get_all("Employee", filters={"status": "Active"}, pluck="custom_biometric_device_enrolled_id"))
    emp_ids.update(frappe.get_all("Employee", filters={"status": "Active"}, pluck="name"))
    safe_emp_ids = {sanitize_hardware_id(i) for i in emp_ids if i}

    deleted = []
    skipped_protected = []
    errors = []

    for uid in user_ids:
        clean_uid = sanitize_hardware_id(uid)
        if clean_uid in safe_emp_ids:
            skipped_protected.append(clean_uid)
            continue
        del_res = delete_person_from_device(device, clean_uid)
        if del_res.get("status") == "success":
            deleted.append(clean_uid)
        else:
            errors.append(f"{clean_uid}: {del_res.get('message')}")

    msg = _("Cleaned up {0} orphan user(s) on {1}.").format(len(deleted), device_name)
    if deleted:
        msg += f"<br>Removed IDs: <b>{', '.join(deleted)}</b>"
    if skipped_protected:
        msg += f"<br><span class='text-warning'>Skipped {len(skipped_protected)} ID(s) matching active employees.</span>"
    if errors:
        msg += f"<br><span class='text-danger'>Errors: {', '.join(errors)}</span>"

    return {"status": "success", "message": msg, "deleted_count": len(deleted)}


# -------------------------------------------------------------
# Hooks for Employee Doc Events (Registered in hooks.py)
# -------------------------------------------------------------

def on_employee_update(doc, method):
    """
    Triggered when an Employee document is saved/updated in ERPNext.
    - Auto-populates attendance_device_id from naming series if left empty.
    - If status changed to Left / Inactive / Suspended -> revoke device credentials.
    - If active and not exempt -> automatically sync credentials.
    """
    # Auto-populate attendance_device_id from doc.name if left empty on creation
    if not doc.get("attendance_device_id") and doc.name:
        clean_id = sanitize_hardware_id(doc.name)
        if clean_id:
            doc.db_set("attendance_device_id", clean_id)
            doc.attendance_device_id = clean_id

    # Check if doc has custom fields before running (in case migration not yet run)
    if not hasattr(doc, "custom_biometric_sync_status"):
        return

    if doc.status == "Suspended":
        # Immediate security lockout for suspended employees
        try:
            remove_employee_from_devices(doc.name)
        except Exception as e:
            frappe.log_error(f"Failed to auto-revoke biometric access for {doc.name}: {str(e)}", "Biometric Integration")
    elif doc.status == "Active" and not doc.get("custom_biometric_exempt"):
        # If card, PIN, or attendance ID changed, push updates
        try:
            sync_employee_to_devices(doc.name)
        except Exception as e:
            frappe.log_error(f"Failed to auto-sync biometric access for {doc.name}: {str(e)}", "Biometric Integration")


def revoke_departed_employees(leeway_days=1):
    """
    Scheduled daily job: safely removes credentials from physical terminals for employees
    who have departed (status == 'Left') and whose relieving_date is at least `leeway_days` in the past.
    This gives departing staff leeway to work and clock out on their final day without mid-day lockouts.
    """
    from frappe.utils import today, date_diff, getdate

    departed_employees = frappe.get_all(
        "Employee",
        filters={
            "status": "Left",
            "custom_biometric_sync_status": "Synced"
        },
        fields=["name", "relieving_date", "modified"]
    )

    from datetime import date, datetime
    try:
        from frappe.utils import today
        raw_today = today()
        if isinstance(raw_today, str):
            current_date = datetime.strptime(raw_today[:10], "%Y-%m-%d").date()
        else:
            current_date = date.today()
    except Exception:
        current_date = date.today()

    revoked_count = 0

    for emp in departed_employees:
        # Determine effective departure date
        ref_date = emp.relieving_date
        if not ref_date and emp.get("modified"):
            ref_date = emp.modified

        if not ref_date:
            continue

        try:
            if hasattr(ref_date, "date"):
                ref_date = ref_date.date()
            elif isinstance(ref_date, str):
                from datetime import datetime
                ref_date = datetime.strptime(str(ref_date)[:10], "%Y-%m-%d").date()

            diff = (current_date - ref_date).days
        except Exception:
            continue

        # Only revoke once the leeway period has elapsed past their relieving date
        if diff >= leeway_days:
            try:
                remove_employee_from_devices(emp.name)
                revoked_count += 1
            except Exception as e:
                frappe.log_error(f"Daily scheduler failed to revoke departed employee {emp.name}: {e}", "Biometric Integration")

    if revoked_count > 0:
        frappe.logger("biometric_integration").info(f"Daily cleanup revoked {revoked_count} departed employee(s) past relieving leeway.")

    return revoked_count


def on_employee_trash(doc, method):
    """
    Triggered when an Employee document is deleted.
    Ensures employee credentials are wiped from physical terminals.
    """
    try:
        remove_employee_from_devices(doc.name)
    except Exception as e:
        frappe.log_error(f"Failed to delete biometric access on employee trash {doc.name}: {str(e)}", "Biometric Integration")


def validate_employee_access_roles(doc, method=None):
    """
    Enforces that only HR Manager or System Manager can assign or modify:
    - Physical door access roles (custom_biometric_access_roles)
    - Hardware blacklist flag (custom_biometric_blacklisted)
    - Hardware device administrator flag (custom_biometric_device_admin)
    Also automatically sanitizes attendance_device_id to alphanumeric characters.
    """
    # Auto-sanitize attendance_device_id to alphanumeric characters [A-Za-z0-9]
    if doc.get("attendance_device_id"):
        clean_id = sanitize_hardware_id(doc.attendance_device_id)
        if clean_id != doc.attendance_device_id:
            doc.attendance_device_id = clean_id
    elif doc.name and not doc.is_new():
        doc.attendance_device_id = sanitize_hardware_id(doc.name)

    if not hasattr(frappe, "session") or not getattr(frappe.session, "user", None):
        return

    user = frappe.session.user
    if user in ("Administrator", "System"):
        return

    restricted_fields = [
        "custom_biometric_access_roles",
        "custom_biometric_blacklisted",
        "custom_biometric_device_admin"
    ]

    has_restricted_change = False
    if doc.is_new():
        for f in restricted_fields:
            if doc.get(f):
                has_restricted_change = True
                break
    else:
        for f in restricted_fields:
            if doc.has_value_changed(f):
                has_restricted_change = True
                break

    if has_restricted_change:
        user_roles = set(frappe.get_roles(user))
        if not user_roles.intersection({"System Manager", "HR Manager"}):
            frappe.throw(
                frappe._("Only HR Managers and System Managers are permitted to modify Physical Door Access Roles, Blacklist status, or Device Administrator privileges."),
                frappe.PermissionError
            )
