# Factory Access Control and Attendance Integration Guide
*A complete operational and technical handbook for deploying modern, heat-and-dust resilient access control, attendance, and shutter automation in Dubai factory environments with ERPNext / Frappe.*

---

## System Architecture and Core Philosophy

### Why Old Virdi Systems Failed
* **Optical Prism Clouding:** Desert sand (silica) and greasy hands scratch optical glass; thermal cycling (45°C–50°C summer heat) degrades prism adhesive.
* **Touchscreen Burnout:** LCD and capacitive touchscreens delaminate under direct/reflected heat.
* **Fragile Architecture:** Placing expensive $400 all-in-one screens directly on harsh outdoor gates creates a single point of failure.

### The Modern Modular Architecture
We separate the system into two distinct layers:
1. **Attendance Station (One central unit):** 1x Outdoor Hikvision MinMoe face terminal installed under a sun hood at the main worker entrance. Dedicated **solely to payroll attendance punch-in/out** (no door lock relays wired to it).
2. **Access Control (All doors, gates and shutters):** Managed by cheap, rugged, solid-state controllers (**Shelly Plus 1 / ESP32**) safely housed indoors or inside sealed enclosures, paired with **potted IP68 dummy readers** that have no screens and cost only AED ~50 to replace.

```
                              +------------------------------------+
                              |         ERPNext / Frappe           |
                              |    (biometric_integration App)     |
                              +------------------------------------+
                                  |             |             |
       +--------------------------+             |             +--------------------------+
       | (ISAPI Event Push & Pull)              | (Local LAN HTTP / MQTT)                | (Local LAN HTTP / MQTT)
       v                                        v                                        v
+--------------------------+         +--------------------------+         +--------------------------+
| 1x Attendance Station    |         | Doors & Pedestrian Gate  |         | Warehouse Roller Shutter |
| Hikvision Face Terminal  |         | Shelly 1 Plus / ESP32    |         | Shelly Plus 1 (220V AC)  |
| Shaded under Sun Hood    |         | 12V Power Box + Maglock  |         | Parallel to Push Button  |
| Creates Employee Checkin |         | Potted IP68 RFID Reader  |         | Safety Beams Intact +    |
| (NO Door Relays Wired)   |         | "NO TOUCH" IR Exit Wave  |         | Floor Contact Sensor     |
+--------------------------+         +--------------------------+         +--------------------------+
```

---

## Hardware and Wiring Guide

### Standard Doors and Pedestrian Gate
Most factory doors already have a **12V Access Control Power Supply Box** with a backup battery. We keep the existing Maglock and inside "NO TOUCH" wave sensor.

#### Wiring Diagram
```
  [ 12V ACCESS CONTROL POWER SUPPLY BOX ]
  +----------------------------------------------+
  | Terminals:                                   |
  |  +12V  -----> Powers Shelly (12V pin) & Lock |
  |  GND   -----> Powers Shelly (L pin) & Lock   |
  |                                              |
  |  PUSH  --------------------+                 |
  |  GND   ------------+       |                 |
  +--------------------|-------|-----------------+
                       |       |
      +----------------+       |
      |                        |
  [ NO TOUCH IR SENSOR ]       |
  (Waves hand -> shorts        |
   PUSH to GND for 3s)         |
                               |
  [ SHELLY PLUS 1 RELAY ] <----+
  (Pin I to PUSH, Pin O to GND)
  (Frappe trigger -> shorts
   PUSH to GND for 3s)
```
* **How It Works:** The `PUSH` terminal is designed to drop maglock power whenever shorted to `GND`. Both the "NO TOUCH" exit sensor and the Shelly relay are wired in parallel across `PUSH` and `GND`. Pressing/waving inside unlocks the door; tapping phone/sticker outside unlocks the door.

---

### Industrial Warehouse Rolling Shutter
Motorized rolling shutters use a 220V AC motor control panel with a push-button switch station (Down → Stop → Up).

#### Wiring Diagram
```
  [ SHUTTER MOTOR CONTROL PANEL ]
  +-------------------------------------------------+
  | MAINS POWER:                                    |
  |   Line (220V AC)     -----> Shelly Pin L        |
  |   Neutral            -----> Shelly Pin N        |
  |                                                 |
  | WALL BUTTON INPUTS:                             |
  |   Push Button (PB)   -----> Shelly Relay Pin I  |
  |   Common (COM)       -----> Shelly Relay Pin O  |
  |                                                 |
  | SAFETY SENSORS:                                 |
  |   Photo-eye Beams    -----> (Remain untouched!) |
  +-------------------------------------------------+
```
* **Why Safety Sensors are Preserved:** Because the Shelly relay is connected across the manual push-button input, the motor controller treats a phone command **identically to a human finger pressing the wall button**. If a forklift or worker blocks the optical safety beam near the floor, the motor immediately stops and reverses, exactly as intended.

---

### Door Position Sensing
To monitor whether doors or shutters are open or closed, install a magnetic reed contact and connect it to the **`SW` (Switch)** terminal of the Shelly.

| Door Type | Sensor Hardware | Mounting |
| :--- | :--- | :--- |
| **Standard Door** | Armored Surface Magnetic Contact (AED ~25) | Top of door frame and door slab. |
| **Outdoor Gate** | Wide-Gap Armored Gate Contact (AED ~35) | Top gate frame (40mm gap tolerance for wind). |
| **Warehouse Shutter** | Forklift-Proof Floor Roller Shutter Contact (AED ~35) | Bolted to concrete floor; magnet on bottom slat. |

#### Shelly Configuration
* In the Shelly web interface, set **Input Mode:** `"Detached"`.
* **What "Detached" means:** The magnetic switch does **not** click the lock relay. It operates purely as a status sensor that sends an instant webhook/MQTT state (`Open` / `Closed`) to Frappe.
* **Door-Held-Open (DHO) Alarm:** If the door remains open longer than `max_open_seconds` (default: 60s), Frappe triggers an alert banner on the dashboard to prevent air conditioning loss.

---

### Attendance Station
* **Model:** Hikvision DS-K1T673DX or DS-K1T680DFW (IP65, -30°C to +60°C operating temp).
* **Location:** Shaded beneath an aluminum weather hood at the primary workforce entrance.
* **Role:** Dedicated purely to facial recognition punch-in / punch-out (0.2s recognition).
* **Daily Operation:** Talks directly to Frappe over local network HTTP. **No lock relays wired here.**

---

## Anti-Metal Phone Sticker Strategy

Commercial mobile credentials (HID / Salto) charge $5–$10/user/year because Apple locks down iPhone NFC. We bypass this completely using passive **Anti-Metal 13.56 MHz Mifare Stickers**:

```
        +--------------------------------------------------------+
        |                 SMARTPHONE BACK / CASE                 |
        |                                                        |
        |   +------------------------------------------------+   |
        |   | [ Anti-Metal 13.56MHz Mifare Sticker (AED 1.50)|   |
        |   | • Ferrite shielding layer prevents metal detune|   |
        |   | • Permanent unique factory serial ID           |   |
        |   +------------------------------------------------+   |
        |                                                        |
        +--------------------------------------------------------+
                                     |
                         (Tap 2-5cm from reader)
                                     v
                 [ Potted IP68 Waterproof Reader (AED 50) ]
```

### Key Rules
1. **Always buy "Anti-Metal" (Ferrite-backed):** Normal RFID stickers fail when stuck to a phone because the phone's lithium battery and metal casing absorb the radio waves. Anti-Metal stickers have a magnetic ferrite barrier that allows the signal to transmit effortlessly.
2. **Frequency Matching:** Always purchase **13.56 MHz (Mifare / IC)** readers and stickers.
3. **Enrollment Workflow:**
   * Hand the sticker to the employee (stick on back of phone or inside phone case).
   * Employee taps reader once → Reader beeps (access denied).
   * Open ERPNext **Door Access Log** → Find the denied entry showing `Card ID: 8492015`.
   * Open that employee's **Employee** record → Paste `8492015` into the `Attendance Device ID` field → Save.
   * Next tap grants immediate access!
4. **Instant Revocation:** When an employee leaves the company, set their Employee status to **"Left" / "Inactive"** in ERPNext. The sticker becomes useless plastic immediately across all doors.

---

## Controllers Compared Shelly vs ESP32

| Feature | Shelly Plus 1 (Stock Firmware) | DIY ESP32 Controller Board |
| :--- | :--- | :--- |
| **Best Used For** | Warehouse Rolling Shutters & Phone-Only Doors | Outdoor Wiegand Card Readers + 100% Offline Immunity |
| **Setup Effort** | Zero coding. Screw in wires, configure via browser. | Moderate. Requires flashing Arduino/ESPHome code. |
| **Relay & Power** | Built-in isolated dry contact relay. Accepts 12V DC or 220V AC. | Needs external 5V relay module and 12V-to-5V buck converter. |
| **Wiegand Reader Support** | ❌ No native Wiegand port. | ✅ Reads Wiegand D0/D1 wires directly. |
| **Local Hostname (mDNS)** | ✅ Yes (`shellyplus1-xxxx.local`) | ✅ Yes (`workshop-door.local`) |
| **Offline Card Memory** | ❌ None (Relies on network signal) | ✅ **Stores 500+ card IDs in local flash memory** |
| **Cost** | AED 65 – 80 | AED 45 – 55 (Board + Relay module) |

---

## Internet Loss and Offline Resilience

### How Attendance Handles Internet Outage
1. **On-Device Buffer:** The Hikvision terminal stores up to **100,000+ offline event logs** in internal flash memory.
2. **Workers Are Never Blocked:** Face recognition operates locally in 0.2s and saves punches with accurate local timestamps even with the network cable disconnected.
3. **Push + Scheduled Pull Reconciliation:**
   * **Push:** When internet returns, the terminal flushes its unsent webhook buffer to `/api/method/biometric_integration.biometric_integration.api.hikvision_event_receiver`.
   * **Pull:** Frappe's background cron (`sync_device_attendance`) queries the terminal's database between `startTime` and `endTime` to catch any dropped records.
   * **No Duplicates:** The app checks existing timestamps before inserting punches.

### How Door Access Handles Internet Outage
* **If Frappe is On-Premises (Factory LAN):** Internet loss has **zero impact**. All devices communicate over local switch/Wi-Fi.
* **If Frappe is in the Cloud:**
  * The ESP32 caches authorized card IDs in its local flash memory (SPIFFS). If the cloud is unreachable (timeout > 500ms), it verifies the card locally and opens the door.
  * The inside **"NO TOUCH" exit sensor is hardwired** to the 12V maglock power supply—it never requires internet or software to let people out safely.

---

## Frappe Setup and Permissions

### Do Employees Need ERPNext Accounts
* **Sticker / Keyfob Tap:** **NO.** Laborers only need an `Employee` record with their sticker number. No passwords, no logins, no license seats consumed.
* **Mobile Web Button (`/app/door-control`):** **YES.** Supervisors and managers who want to tap a button on their phone must log into Frappe.

### Permission Hierarchy on Access Door
1. **`Allow All Active Employees` = ON:** (e.g. Main Pedestrian Gate). Any active employee can unlock.
2. **`Allow All Active Employees` = OFF:** (e.g. Warehouse Shutter, Server Room). Access is restricted to:
   * **Allowed User Roles** table (e.g. *Manufacturing Supervisor*, *Forklift Driver*).
   * **Allowed Specific Employees** table (e.g. *EMP-0012 Ahmed Khan*).
3. **Mobile Dashboard Filtering:** The `/app/door-control` page calls `get_accessible_doors()` which automatically **hides unauthorized doors from unauthorized users' screens**.

---

## Dubai Procurement and Bill of Materials

All items can be purchased immediately in **Deira (Naif/Sabkha CCTV market around Sikkat Al Khail street)** or on **Amazon.ae**:

| Component | Recommended Model / Search Term | Est. Unit Price (AED) | Sourcing |
| :--- | :--- | :--- | :--- |
| **Attendance Terminal** | Hikvision DS-K1T673DX Outdoor Face Terminal | AED 850 – 1,100 | Deira / ScreenCheck / Amazon.ae |
| **Terminal Weatherhood** | Universal Rain/Sun Shield for Face Terminals | AED 40 – 60 | Deira CCTV shops / 3D Print |
| **Outdoor Gate Lock** | IP67 Waterproof Outdoor Maglock (600lb / 1200lb Stainless) | AED 180 – 250 | Deira / Amazon.ae |
| **Door/Shutter Controllers**| Shelly Plus 1 (Dry Contact Smart Relay) | AED 65 – 80 | Amazon.ae / Local distributors |
| **Outdoor Card Readers** | Potted IP68 Waterproof 13.56MHz Mifare Wiegand Reader | AED 45 – 60 | Deira / Dragon Mart / Amazon.ae |
| **Shutter Floor Sensor** | Industrial Roller Shutter Floor Magnetic Contact (Heavy-Duty) | AED 35 – 50 | Deira Alarm shops / Amazon.ae |
| **Door Frame Sensors** | Armored Surface-Mount Magnetic Contacts | AED 20 – 30 | Deira / Amazon.ae |
| **Phone Stickers** | Anti-Metal 13.56MHz Mifare / NFC RFID Stickers | AED 75 – 90 (Pack of 50) | Amazon.ae / Dragon Mart |
| **Laborer Keyfobs** | 13.56MHz Mifare Classic 1K Plastic Keyfobs | AED 45 – 60 (Pack of 50) | Deira / Dragon Mart |

---

## Quick Cheatsheet and Troubleshooting

### Shelly Plus 1 Quick Setup
1. Power on with 12V DC (doors) or 220V AC (shutter).
2. Connect phone to temporary Wi-Fi `ShellyPlus1-XXXXXX` → Open `192.168.33.1`.
3. Under **Wi-Fi**, join your factory network.
4. Under **Input/Output Settings**:
   * Set Relay type: **Momentary**
   * Set Auto-Off Timer: **3.0s** (for maglocks) or **0.5s** (for shutter pulse).
   * If magnetic sensor is connected to `SW`: Set Button Type to **"Detached"**.
5. Note its hostname: `http://shellyplus1-xxxxxx.local` and enter it into Frappe `Access Door`.

### Connecting Hikvision Attendance Terminal to ERPNext

Follow these exact steps to connect your Hikvision MinMoe face terminal so it automatically sends punches in real-time to your ERPNext server:

#### Step 1: Get Your Webhook Details from ERPNext
1. In ERPNext, search for and open **Biometric Integration Settings**.
2. Make sure **Enable Webhook Receiver** is checked.
3. You will see two fields:
   * **Webhook Secret Key:** *(e.g. `a1b2c3d4e5f67890abcdef12`)*
   * **Webhook Endpoint URL:** Copy this full URL. It looks like:
     ```
     http://<your-erpnext-ip-or-domain>:8000/api/method/biometric_integration.biometric_integration.api.hikvision_event_receiver?token=<secret_key>
     ```

#### Step 2: Configure Push on the Hikvision Terminal (HTTP or HTTPS)
1. Open Google Chrome on your PC and navigate to your terminal's IP (e.g. `http://192.168.1.60`).
2. Log in with `admin` and your device password.
3. In the top/left menu, navigate to:
   **Configuration → Network → Advanced Settings → HTTP Listening**  
   *(On some firmware versions, this is labeled **Alarm Host** or **Center Information**).*
4. Fill in the exact fields:
   * **Enable:** Check the box to activate.
   * **Destination IP / Domain:** Enter your Frappe server IP or domain (e.g. `192.168.1.10` or `erp.yourcompany.com` — *do not include `http://` or `https://` in this field*).
   * **Port:** 
     * Use `8000` (for direct bench/development port)
     * Use `80` (for standard HTTP with Nginx)
     * Use **`443`** (for **HTTPS** with SSL)
   * **URL Path / Request URL:**
     ```
     /api/method/biometric_integration.biometric_integration.api.hikvision_event_receiver?token=<your_webhook_secret_key>
     ```
   * **Protocol:** Select **`HTTP`** or **`HTTPS`** (Select `HTTPS` whenever your ERPNext site has an SSL certificate).
   * **Data Format:** Select `JSON` (or `Default`).
   * **Events to Upload:** Ensure **Access Control Events** (Major: 5, Minor: 75 - Face Authentication Succeeded) is checked.
5. Click **Save** at the bottom.

#### Using HTTPS with SSL Certificates:
Hikvision terminals natively support HTTPS to encrypt all face, card, and attendance payloads over TLS:
* **Public Domain with SSL (Let's Encrypt, Cloudflare, DigiCert):**
  * If your ERPNext site is `https://erp.yourcompany.com`, set **Port:** `443` and **Protocol:** `HTTPS`.
  * Works 100% out of the box—Hikvision’s firmware includes root CA certificates and securely verifies the connection.
* **Self-Signed Certificates (Local IP without a public domain):**
  * If you generated a private self-signed certificate on a local IP (e.g. `https://192.168.1.10`), Hikvision may reject it by default as an "Untrusted CA".
  * To fix: Go to **Configuration → Network → Advanced Settings → HTTPS / Security** in the terminal and check *"Allow untrusted / self-signed certificate"* (or upload your internal root `.crt` file).
* **Python Backend Compatibility:**
  * In this app, `Biometric Device` and `Biometric Integration Settings` already use `verify=False` in Python requests, ensuring scheduled pull syncs always succeed even with self-signed SSL certificates.


#### Step 3: Configure Timezone & NTP (Crucial for Dubai!)
If the terminal's clock drifts, attendance punches will have the wrong time in ERPNext.
1. On the Hikvision web page, go to:
   **Configuration → System → System Settings → Time Settings**.
2. **Time Zone:** Select **`(GMT+04:00) Abu Dhabi, Muscat`** (UAE local time).
3. **Enable NTP:** Check **Enable NTP**.
   * **Server Address:** `pool.ntp.org` (or `time.google.com` or your local router IP).
   * **NTP Port:** `123`.
   * **Interval:** `60` minutes.
4. Click **Save**. The terminal will synchronize with UAE standard time.

#### Step 4: Register Device in ERPNext for Scheduled Backups
To enable the scheduled safety-net pull sync (which catches any punches missed during an internet outage):
1. In ERPNext, search for and open **Biometric Device** → Click **Add Biometric Device**.
2. **Device Name:** *Main Attendance Station*
3. **IP Address:** Terminal's local IP (e.g. `192.168.1.60`).
4. **Port:** `80` (or `443`).
5. **Username:** `admin`.
6. **Password:** Your terminal admin password.
7. **Device Direction:** `Auto` (or `IN`).
8. Click **Save**, then click the **Check Connection** button.
   * The status badge will turn green: **Online**.

#### Step 5: Test Verification
1. Walk up to the Hikvision terminal and scan your face (ensure your Employee ID in Hikvision matches your `Attendance Device ID` in ERPNext).
2. The terminal beeps green: *"Authenticated"*.
3. In ERPNext, open **Biometric Attendance Log** or HRMS **Employee Checkin**:
   * Your check-in appears in real-time with the exact timestamp!


---

## Hikvision MinMoe Employee Enrollment

### The Golden Rule of Integration
The **Employee No. / ID** assigned in Hikvision **MUST EXACTLY MATCH** the **`Attendance Device ID`** on the Employee master in ERPNext:
```
[ In Hikvision Terminal ]                      [ In ERPNext Employee Record ]
Employee No: "1042"      <==================>  Attendance Device ID: "1042"
```

### Method 1: On the Terminal Touchscreen (Fastest at Gate)
1. Long-press screen for 3 seconds → Enter device **Admin Password**.
2. Tap **User** (or **User Management**) → Tap **+ Add** (top-right corner).
3. **Employee No:** Type the worker's unique company ID (e.g. `1042`).
4. **Name:** Type the worker's full name (e.g. `Ahmed Khan`).
5. Tap **Face**: Worker stands 0.5–1.0m away, fits face inside the green circle. (Remove dark safety goggles; hardhats and caps are fine). Terminal beeps: *"Collected successfully"*.
6. *(Optional)* Tap **Card**: Tap their RFID card or phone sticker against the card icon.
7. Tap **Save** (check-mark icon).

### Method 2: Via Web Browser (From HR / Admin Office)
1. Open Google Chrome → Navigate to terminal IP (e.g. `http://192.168.1.60`).
2. Log in with `admin` and device password.
3. Go to **User** (or **Access Control** → **Person**) → Click **+ Add**.
4. Enter **ID:** `1042` and **Name:** `Ahmed Khan`.
5. Under **Face**:
   * **Upload Photo:** Upload a clear white-background passport photo (JPG/PNG).
   * **Remote Collection:** Click Remote Collection to snap the worker standing at the gate live.
6. Under **Card**: Click **+ Add** to enter card number or click **Remote Read**.
7. Click **Save**.

### Method 3: Via iVMS-4200 (Batch Import)
1. In iVMS-4200, open **Person** module → Click **Import** → Fill in the Excel template with `Person ID` and `Name` → Upload.
2. Attach photos for each person.
3. Go to **Access Control** → **Access Group** → Select employees & MinMoe terminal → Click **Save and Apply to Device**.

