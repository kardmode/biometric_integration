# Biometric & Access Control Integration for ERPNext / Frappe

An enterprise-grade biometric integration and physical access control system for Frappe and ERPNext. It seamlessly bridges **Hikvision Face Recognition Terminals (MinMoe series)**, **RFID card readers**, **keypads**, and **external smart relays (Shelly Plus/Pro, ESP32)** directly into ERPNext.

---

## 🚀 Key Highlights & Architectural Upgrades

### 1. Dual-Purpose Hardware Management
- **Unified Biometric Device**: Single DocType manages device connection credentials, direction (IN/OUT/Auto), attendance check-in logging, and door access relay controls.
- **Relay Agnostic**: Supports built-in Hikvision terminal relays (via ISAPI), external Shelly relays (Shelly Plus, Shelly Pro, Dry Contacts via RPC), and ESP32 / custom HTTP dry-contact controllers.
- **Real-Time Push Webhook**: Hikvision terminals push real-time access events directly to ERPNext via `/api/method/biometric_integration.api.push?token=<device_token>` using multipart/form-data or XML.

### 2. Physical Terminal Access Control (On-Device Biometrics)
- **Biometric Access Roles**: Create granular physical access tags (e.g., *Server Room*, *Main Gate*, *Executive Wing*, *Warehouse Perimeter*).
- **Multi-Role Employee Tagging**: Employees can hold multiple physical access roles simultaneously (`custom_biometric_access_roles`).
- **Individual Overrides**: Doors support an `Allowed Employees` table for one-off individual exceptions without creating new roles.
- **Safe Biometric Replication**: Uses ISAPI `UserInfo/Modify` first—**safely updating names, PINs, and RFID cards without overwriting or wiping on-device face and fingerprint templates**.
- **Face Capture Sync**: Retrieve high-resolution enrolled face captures from a terminal into ERPNext and automatically replicate them across all authorized doors.
- **Auto-Revocation**: When an employee is marked *Left*, *Inactive*, *Suspended*, or untagged from a role, their credentials are automatically purged from hardware terminals.

### 3. Decoupled Remote Desk Unlock (Software / API)
- **Role & User-Based**: Operates strictly on Frappe `Role` and Frappe `User` logins (independent of Employee records).
- **Desk Action**: Authorized security guards, receptionists, or managers can trigger a remote door pulse with one click from Desk.
- **Emergency Bypass**: System Managers and Administrators have 24/7 unrestricted remote unlock access.

### 4. Reusable Time Schedules (`Biometric Access Shift`)
- **Multi-Segment Split Shifts**: Supports multiple intervals on the same day (e.g. `09:00 - 14:00` and `16:00 - 19:00`).
- **Strict Time Validation**: Inverted time prevention (`end_time > start_time`), chronological overlap detection, contiguous interval merge prompts, and hardware segment limits (max 8 per day).
- **Hardware Plan Mapping**: Maps seamlessly to Hikvision terminal `planTemplateNo` slots (1–255) for physical terminal enforcement.
- **Time-Gated Remote Unlock**: Gated desk users can only unlock doors during their assigned shift hours.

### 5. Biometric Visitor Management
- **Temporary Visitor Passes**: Issues 6-digit numeric hardware IDs (`9XXXX`) and auto-generated secure PINs with an expiration date/time and visit reason.
- **Multi-Door Provisioning**: Select specific authorized doors for each visitor.
- **Automated Lifecycle**: Background scheduler automatically purges expired visitor PINs and IDs from hardware terminals hourly.

### 6. Role Permission Security
- **Protected Role Assignment**: Employee physical access roles are locked to `permlevel: 1` and fortified with an unbypassable backend server-side Python guard. Only **HR Managers** and **System Managers** can assign or alter physical door roles.

---

## 🛠️ Step-by-Step Setup Guide

### Step 1: Install & Sync Database
Run these commands in your Frappe bench directory:

```bash
bench --site <site_name> install-app biometric_integration
bench --site <site_name> execute biometric_integration.biometric_integration.setup.setup_custom_fields
bench --site <site_name> clear-cache
```

---

### Step 2: Configure Time Schedules & Physical Access Roles
1. Navigate to **Biometric Integration > Access Shifts** (`Biometric Access Shift`):
   - Create shifts as needed (e.g., *Normal Office Hours 08:00 - 17:00*, *Cleaning Shift Evening 18:00 - 22:00*).
   - Enter your intervals for each day of the week.
2. Navigate to **Biometric Integration > Access Roles** (`Biometric Access Role`):
   - Define your physical access zones (e.g., *Main Office Gate*, *Server Room*, *Warehouse*).

---

### Step 3: Configure Your Hardware Terminal (`Biometric Device`)
1. In Frappe Desk, navigate to **Biometric Device** and click **New**.
2. Enter the terminal's **Device Name**, **IP Address**, **Username**, and **Password**.
3. Click **"Test Connection"** and **"Fetch Hardware Info"** to auto-detect model and serial number.
4. **Attendance Settings**: Set direction to `Auto`, `IN`, or `OUT`, and set the punch cooldown window (default: 5 minutes).
5. **Access Control Settings**:
   - Enable **Door Access Control**.
   - Choose relay type: *Built-in Terminal Relay (Hikvision ISAPI)*, *Shelly*, or *ESP32*.
6. **Permissions**:
   - **Remote Desk Unlock Permissions**: Select which Frappe Roles or specific User logins can click "Unlock Door" and optionally assign a shift restriction.
   - **Physical Terminal Access Permissions**: Check *Allow All Active Employees* for open turnstiles/gates, OR uncheck and select specific **Allowed Physical Access Roles** / **Allowed Individual Employees**.
7. **Configure Real-Time Push in Terminal**:
   - Copy the generated **Push Receiver URL** (`/api/method/biometric_integration.api.push?token=...`).
   - Log into your Hikvision terminal web interface.
   - Navigate to **Configuration > Network > Advanced Settings > HTTP Listening** (or *Alarm Host*).
   - Paste the URL, select HTTP/HTTPS, and enable event push.

---

### Step 4: Provision Employees & Replicate Biometrics
1. Open an active **Employee** document.
2. Under **Biometric & Door Access**:
   - Tag the employee with their authorized **Physical Door Access Roles**.
   - Optionally enter an **RFID Card No** or **Door PIN**.
3. **Enroll Face**:
   - If the employee was already enrolled on a terminal, click **"Fetch Face from Terminal"** to download their face capture into ERPNext.
   - Click **"Sync to Terminals"** to replicate the user profile, face capture, card, and PIN across all doors authorized for that employee.
4. *Note: Syncing uses non-destructive ISAPI modification. Existing face and fingerprint templates on hardware are never lost or overwritten.*

---

### Step 5: Visitor Passes
1. Navigate to **Biometric Visitor Pass** and click **New**.
2. Enter visitor name, phone number, visit reason, and valid from / valid to date and time.
3. Add the authorized doors to the table.
4. Click **Save**: A unique 6-digit numeric hardware ID (`9XXXX`) and secure PIN are generated and automatically pushed to the selected terminals.
5. Once the pass expires, the background scheduler automatically revokes the visitor from all terminals.

---

## 🔒 Security Architecture

| Access Layer | Controlled By | Validation / Enforcement |
| :--- | :--- | :--- |
| **Remote Desk Unlock** | Frappe User & Role | Verified at time of desk click / API call. Gated by `Biometric Access Shift`. System Manager & Administrator exempt 24/7. |
| **Physical Terminal Biometrics** | `Biometric Access Role` & `Allowed Employees` | Evaluated on Employee update, save, or manual sync. Only provisioned users exist on physical hardware. |
| **Physical Door Schedules** | `Biometric Access Shift` | Formatted into Hikvision 7-day `weekPlan` and pushed to hardware `planTemplateNo` slots (1–255). |
| **Role Assignment Authorization** | Frappe Permlevel & Python Guard | `custom_biometric_access_roles` is restricted to `permlevel: 1`. Server-side validation raises `PermissionError` for non-managers. |

---

## 🧪 Automated Test Suite
The app includes a comprehensive test suite covering all ISAPI payloads, time validations, multi-terminal face sync, and security permissions:

```bash
# Run unit tests from your bench directory
bench --site <site_name> run-tests --app biometric_integration
```

---

## 📡 Supported Hardware

Compatible with all **Hikvision MinMoe** face recognition terminals, access controllers, turnstiles, and speed gates supporting the Hikvision ISAPI Access Control protocol:

> **DS-K1T Series**: DS-K1T331, DS-K1T341, DS-K1T342, DS-K1T343, DS-K1T607, DS-K1T642, DS-K1T671, DS-K1T672, DS-K1T673, DS-K1T680, DS-K1T690, DS-K1TA70, DS-K1TV41, and derivatives.  
> **DS-K1A Series**: DS-K1A330, DS-K1A340, and derivatives.  
> **DS-K56 Series**: DS-K5604, DS-K5671, DS-K5672 turnstile face modules.  
> **External Relays**: Shelly Plus 1, Shelly Pro 1/2, Shelly Dry Contacts, ESP32 HTTP dry-contact boards.

---

## 📄 License
MIT License. Copyright (c) 2026 NDV and contributors.
