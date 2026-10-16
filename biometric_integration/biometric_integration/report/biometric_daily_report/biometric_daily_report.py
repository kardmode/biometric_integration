import frappe
from frappe import _
from datetime import datetime, timedelta

def parse_time_to_seconds(time_val):
    if not time_val:
        return None
    if hasattr(time_val, "total_seconds"):
        return int(time_val.total_seconds())
    parts = str(time_val).split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = int(float(parts[2])) if len(parts) > 2 else 0
            return h * 3600 + m * 60 + s
        except (ValueError, TypeError):
            return None
    return None

def execute(filters=None):
    columns = [
        {"fieldname": "employee_name", "label": _("Name"), "fieldtype": "Data", "width": 300, "align": "left"},
        {"fieldname": "employee_id", "label": _("ID"), "fieldtype": "Data", "width": 100, "align": "center"},
        {"fieldname": "total_duration", "label": _("Total Hours"), "fieldtype": "Data", "width": 100, "align": "center"}
    ]
    
    if not filters or not filters.get('date'):
        frappe.throw(_("Please select a date."))
        
    selected_date = filters.get('date')
    formatted_date = datetime.strptime(selected_date, '%Y-%m-%d').strftime('%d-%b-%Y')
    
    columns[0]["label"] = formatted_date
    
    # Get all active employees with attendance device IDs and default shift
    all_active_employees = frappe.db.sql("""
        SELECT 
            name as employee,
            employee_name,
            attendance_device_id,
            default_shift
        FROM 
            tabEmployee
        WHERE 
            status = 'Active'
            AND attendance_device_id IS NOT NULL
            AND attendance_device_id != ''
        ORDER BY 
            attendance_device_id
    """, as_dict=True)
    
    # Get employees who had at least one punch that day with default shift
    present_employees = frappe.db.sql("""
        SELECT DISTINCT 
            e.name as employee,
            e.employee_name,
            e.attendance_device_id,
            e.default_shift
        FROM `tabEmployee Checkin` ec
        JOIN `tabEmployee` e ON e.name = ec.employee
        WHERE DATE(ec.time) = %(selected_date)s
    """, {"selected_date": selected_date}, as_dict=True)
    
    # Create a set of present employee IDs for faster lookup
    present_employee_ids = {emp.attendance_device_id for emp in present_employees}

    # Fetch all Shift Types for quick lookup
    shift_type_map = {}
    if frappe.db.table_exists("Shift Type"):
        st_records = frappe.db.sql("""
            SELECT name, start_time, end_time, early_exit_grace_period, late_entry_grace_period
            FROM `tabShift Type`
        """, as_dict=True)
        for st in st_records:
            shift_type_map[st.name] = st

    # Fetch dynamic Shift Assignments if HRMS Shift Assignment table exists
    shift_map = {}
    if frappe.db.table_exists("Shift Assignment"):
        shifts = frappe.db.sql("""
            SELECT sa.employee, st.name as shift_type, st.end_time, st.start_time, st.early_exit_grace_period, st.late_entry_grace_period
            FROM `tabShift Assignment` sa
            JOIN `tabShift Type` st ON st.name = sa.shift_type
            WHERE sa.start_date <= %(selected_date)s
              AND (sa.end_date IS NULL OR sa.end_date >= %(selected_date)s)
              AND sa.docstatus = 1
        """, {"selected_date": selected_date}, as_dict=True)
        for s in shifts:
            shift_map[s.employee] = s

    # Fetch approved standard Leave Applications for selected date
    leave_log_map = {}
    if frappe.db.table_exists("Leave Application"):
        leave_apps = frappe.db.sql("""
            SELECT e.attendance_device_id, la.half_day
            FROM `tabLeave Application` la
            JOIN `tabEmployee` e ON e.name = la.employee
            WHERE la.status = 'Approved'
              AND %(selected_date)s BETWEEN la.from_date AND la.to_date
        """, {"selected_date": selected_date}, as_dict=True)
        for la in leave_apps:
            emp_id = str(la.attendance_device_id or "")
            if emp_id:
                leave_log_map[emp_id] = {"leave_from": None, "leave_to": None, "full_day": 0 if la.half_day else 1}
    
    def natural_sort_key(emp):
        try:
            return int(emp["attendance_device_id"])
        except ValueError:
            return emp["attendance_device_id"]
    
    # Sort present employees by attendance_device_id (numeric)
    present_employees.sort(key=natural_sort_key)
    
    data = []
    max_punches = 0
    valid_minutes = []
    
    def is_time_between(timedelta_obj, start_hour, end_hour):
        """Check if timedelta falls between start_hour and end_hour"""
        if not timedelta_obj:
            return False
        total_seconds = timedelta_obj.total_seconds()
        hours = total_seconds / 3600
        return start_hour <= hours < end_hour

    def get_employee_shift_data(emp_doc_name, default_shift=None):
        """Resolves shift from dated Shift Assignment or Employee.default_shift."""
        if emp_doc_name and emp_doc_name in shift_map:
            return shift_map[emp_doc_name]
        if default_shift and default_shift in shift_type_map:
            return shift_type_map[default_shift]
        if emp_doc_name:
            emp_def = frappe.db.get_value("Employee", emp_doc_name, "default_shift")
            if emp_def and emp_def in shift_type_map:
                return shift_type_map[emp_def]
        return None

    def check_early_leave_present(first_punch_time, last_punch_time, employee_id, emp_doc_name=None, default_shift=None):
        """
        For present employees only.
        Checks leave_to against first punch, leave_from against last punch.
        """
        def fmt(total_seconds):
            h, m = divmod(int(total_seconds / 60), 60)
            return f"{h:02}:{m:02}"

        emp_id = str(employee_id)
        leave_entry = leave_log_map.get(emp_id)

        # Dynamic shift lookup: Dated Shift Assignment -> Employee.default_shift
        shift_data = get_employee_shift_data(emp_doc_name, default_shift)
        expected_end = None
        shift_end_tolerance = 30 * 60
        tolerance_seconds = 15 * 60

        if shift_data and shift_data.get("end_time"):
            end_t = shift_data["end_time"]
            expected_end = parse_time_to_seconds(end_t)
            if shift_data.get("early_exit_grace_period"):
                shift_end_tolerance = int(shift_data["early_exit_grace_period"]) * 60

        # If no shift is found, we cannot determine when they should have left, so return empty (no penalty flag)
        if expected_end is None:
            return ""

        if leave_entry is None:
            # No leave log — check if last punch is before shift end
            if last_punch_time is None:
                return ""
            last_punch_seconds = last_punch_time.total_seconds()
            if last_punch_seconds < (expected_end - shift_end_tolerance):
                return "2"
            return ""

        leave_from_seconds = leave_entry.get("leave_from")
        leave_to_seconds = leave_entry.get("leave_to")

        result_leave_to = None
        result_leave_from = None

        # Check leave_to against first punch
        if leave_to_seconds is not None:
            if first_punch_time is not None:
                first_punch_seconds = first_punch_time.total_seconds()
                diff = first_punch_seconds - leave_to_seconds
                if diff <= tolerance_seconds:
                    result_leave_to = "1"
                else:
                    result_leave_to = f"0 ({fmt(leave_to_seconds)})"

        # Check leave_from against last punch
        if leave_from_seconds is not None:
            if leave_from_seconds < (expected_end - shift_end_tolerance):
                if last_punch_time is not None:
                    last_punch_seconds = last_punch_time.total_seconds()
                    diff = last_punch_seconds - leave_from_seconds
                    if diff > tolerance_seconds:
                        result_leave_from = "1"
                    elif abs(diff) <= tolerance_seconds:
                        result_leave_from = "1"
                    else:
                        result_leave_from = f"0 ({fmt(leave_from_seconds)})"

        parts = [r for r in [result_leave_to, result_leave_from] if r is not None]

        if not parts:
            return "1"

        if all(p == "1" for p in parts):
            return "1"

        return " | ".join(parts)

    def check_early_leave_absent(employee_id, emp_doc_name=None, default_shift=None):
        shift_data = get_employee_shift_data(emp_doc_name, default_shift)
        if not shift_data:
            return ""

        emp_id = str(employee_id)
        leave_entry = leave_log_map.get(emp_id)

        if leave_entry is None:
            return "2"  # absent, no leave log

        if leave_entry.get("full_day") == 1:
            return "1"  # full day leave

        leave_from_seconds = leave_entry.get("leave_from")
        leave_to_seconds = leave_entry.get("leave_to")

        def fmt(total_seconds):
            h, m = divmod(int(total_seconds / 60), 60)
            return f"{h:02}:{m:02}"

        if leave_from_seconds is not None and leave_to_seconds is None:
            return f"0 ({fmt(leave_from_seconds)})"

        if leave_to_seconds is not None and leave_from_seconds is None:
            return f"0 ({fmt(leave_to_seconds)})"

        return "1"
    
    # First pass: determine max_punches
    for employee in present_employees:
        punches = frappe.db.sql("""
            SELECT TIME(time) as punch_time, 'Auto' as punch_type
            FROM `tabEmployee Checkin`
            WHERE employee = %(emp)s AND DATE(time) = %(selected_date)s
            ORDER BY time
        """, {"emp": employee.employee, "selected_date": selected_date}, as_dict=True)
        
        if not punches:
            continue
        
        # Check for <-- Check punch condition
        if len(punches) == 2:
            first_punch = punches[0]["punch_time"]
            second_punch = punches[1]["punch_time"]
            first_punch_valid = is_time_between(first_punch, 7, 10)
            second_punch_valid = is_time_between(second_punch, 19, 22)
            if first_punch_valid and second_punch_valid:
                punches.append({"punch_time": None, "punch_type": "<-- Check"})
        
        max_punches = max(max_punches, len(punches))

    # Add punch columns FIRST - before processing data
    punch_column_width = 100
    for i in range(1, max_punches + 1):
        columns.append({
            "fieldname": f"punch_{i}",
            "label": _("Punch " + str(i)),
            "fieldtype": "Data",
            "width": punch_column_width,
            "align": "center"
        })
    
    # Add early leave column as THE LAST column - AFTER all punch columns
    columns.append({
        "fieldname": "early_leave",
        "label": _("Early Leave"),
        "fieldtype": "Data",
        "width": 100,
        "align": "center"
    })

    # Second pass: Process data with correct column structure
    for employee in present_employees:
        punches = frappe.db.sql("""
            SELECT TIME(time) as punch_time, 'Auto' as punch_type
            FROM `tabEmployee Checkin`
            WHERE employee = %(emp)s AND DATE(time) = %(selected_date)s
            ORDER BY time
        """, {"emp": employee.employee, "selected_date": selected_date}, as_dict=True)
        
        if not punches:
            continue
                
            row_data = {}
            row_indicators = {}
            
            row_data["employee_name"] = employee.employee_name
            row_data["employee_id"] = employee.attendance_device_id
            
            if len(punches) % 2 != 0:
                total_duration_formatted = "Check -->"
                row_indicators["total_duration"] = "#ffff00"
            else:
                total_minutes = calculate_total_minutes(punches)
                total_duration_formatted = format_minutes_to_hhmm(total_minutes)
                if total_duration_formatted != "Check -->":
                    valid_minutes.append(total_minutes)
            
            row_data["total_duration"] = total_duration_formatted
            
            # Check for <-- Check punch condition
            if len(punches) == 2:
                first_punch = punches[0]["punch_time"]
                second_punch = punches[1]["punch_time"]
                first_punch_valid = is_time_between(first_punch, 7, 10)
                second_punch_valid = is_time_between(second_punch, 19, 22)
                if first_punch_valid and second_punch_valid:
                    punches.append({"punch_time": None, "punch_type": "<-- Check"})
            
            # Process all punches first
            for i, punch in enumerate(punches, 1):
                punch_field = f"punch_{i}"
                if punch.get("punch_type") == "<-- Check":
                    row_data[punch_field] = "<-- Check"
                    row_indicators[punch_field] = "#ffff00"
                else:
                    formatted_time = format_punch_with_type(punch)
                    if punch.get("punch_type") == "Manual":
                        row_data[punch_field] = formatted_time
                        row_indicators[punch_field] = "red"
                    else:
                        row_data[punch_field] = formatted_time
            
            # Fill empty punch columns with None
            for i in range(len(punches) + 1, max_punches + 1):
                row_data[f"punch_{i}"] = None
            
            # Process early leave AFTER all punches are processed
            if punches:
                actual_punches = [p for p in punches if p.get("punch_type") != "<-- Check"]
                if actual_punches:
                    first_punch = actual_punches[0]["punch_time"]
                    last_punch = actual_punches[-1]["punch_time"]
                    early_leave_status = check_early_leave_present(first_punch, last_punch, employee.attendance_device_id, employee.get("employee"), employee.get("default_shift"))
                    row_data["early_leave"] = early_leave_status
                    
                    # Highlight red for everything except pure "1"
                    if early_leave_status != "" and early_leave_status != "1":
                        row_indicators["early_leave"] = "red"
                else:
                    row_data["early_leave"] = ""
            else:
                row_data["early_leave"] = ""
            
            data.append({
                "data": row_data,
                "indicators": row_indicators
            })
    
    # Format data for report
    formatted_data = []
    for row in data:
        row_data = row["data"].copy()
        
        for field, color in row["indicators"].items():
            row_data[field] = frappe.render_template(
                '''<span style="color: {{ color }}">{{ value }}</span>''',
                {"value": row_data[field], "color": color}
            )
        
        formatted_data.append(row_data)
    
    # Add total row
    total_minutes = sum(valid_minutes)
    total_duration_formatted = format_minutes_to_hhmm(total_minutes)
    
    total_row = {
        "employee_name": "Total",
        "employee_id": len(present_employees),
        "total_duration": total_duration_formatted,
        "early_leave": ""
    }
    
    for i in range(1, max_punches + 1):
        total_row[f"punch_{i}"] = None
    
    formatted_data.append(total_row)
    
    # Add two blank rows
    blank_row = {field["fieldname"]: None for field in columns}
    formatted_data.append(blank_row)
    formatted_data.append(blank_row)
    
    # Add absent active employees and sort by attendance_device_id
    absent_active_employees = [
        employee for employee in all_active_employees
        if employee.attendance_device_id not in present_employee_ids
    ]
    absent_active_employees.sort(key=natural_sort_key)
    
    for employee in absent_active_employees:
        absent_row = {field["fieldname"]: None for field in columns}
        absent_row["employee_name"] = employee.employee_name
        absent_row["employee_id"] = employee.attendance_device_id

        early_leave_status = check_early_leave_absent(employee.attendance_device_id, employee.get("employee"), employee.get("default_shift"))
        absent_row["early_leave"] = early_leave_status

        for i in range(1, max_punches + 1):
            absent_row[f"punch_{i}"] = None
        formatted_data.append(absent_row)

    # Add one blank row then legend rows (one per line)
    blank_row = {field["fieldname"]: None for field in columns}
    formatted_data.append(blank_row)

    for legend_text in ["0 - Left Before / After Logged Leave Time", "1 - Leave Taken", "2 - No Leave Taken"]:
        legend_row = {field["fieldname"]: None for field in columns}
        legend_row["employee_name"] = legend_text
        formatted_data.append(legend_row)

    return columns, formatted_data

def calculate_total_minutes(punches):
    total_minutes = 0
    
    for i in range(0, len(punches) - 1, 2):
        try:
            punch_in = punches[i]["punch_time"]
            punch_out = punches[i + 1]["punch_time"]
            minutes_diff = int(punch_out.total_seconds() / 60) - int(punch_in.total_seconds() / 60)
            total_minutes += minutes_diff
        except Exception:
            return 0
    
    return total_minutes

def format_minutes_to_hhmm(minutes):
    hours, mins = divmod(minutes, 60)
    return f"{hours:02}:{mins:02}"

def format_timedelta_to_hhmm(td):
    if not td:
        return None
    
    total_minutes = int(td.total_seconds() / 60)
    hours, mins = divmod(total_minutes, 60)
    return f"{hours:02}:{mins:02}"

def format_punch_with_type(punch):
    if not punch.get("punch_time"):
        return None
    
    time_str = format_timedelta_to_hhmm(punch["punch_time"])
    if punch.get("punch_type") == "Manual":
        return f"{time_str} (MA)"
    return time_str