# Hikvision MinMoe Hardware Features, Settings & Integration Roadmap

This document breaks down the advanced settings found in the **Hikvision MinMoe Terminal Web Interface** (`Configuration` menu), explaining what each setting does, why it exists, and how it connects to **ERPNext Biometric Integration**.

---

## 📋 Table of Contents
1. [User & Credential Settings](#1-user--credential-settings)
2. [PIN Mode (Platform Applied vs Device Set)](#2-pin-mode-platform-applied-vs-device-set)
3. [Card, M1 Encryption & Mobile NFC](#3-card-m1-encryption--mobile-nfc)
4. [Bluetooth Option & Mobile Badges](#4-bluetooth-option--mobile-badges)
5. [Linkage Settings (Event-Driven Hardware Automation)](#5-linkage-settings-event-driven-hardware-automation)
6. [Serial Port, RS-485, Wiegand & Secure Door Control](#6-serial-port-rs-485-wiegand--secure-door-control)
7. [Actionable Integration Roadmap for ERPNext](#7-actionable-integration-roadmap-for-erpnext)

---

## 1. User & Credential Settings

Found under: **Configuration > User Management > User**

### A. Person Type
Hikvision terminals categorize users into 3 fundamental hardware types:
* **Normal User (Default)**: Standard employees and authorized personnel. They authenticate via face, card, PIN, or fingerprint based on their assigned time schedule.
* **Visitor**: Temporary personnel. The hardware applies stricter validity checks, maximum passage counts (e.g. 1-time entry), and automatic revocation.
* **Blacklist / Blocklist**: If a blacklisted person scans their face or card:
  - Access is **immediately denied**.
  - The terminal triggers an **audible alarm** or sends a high-priority alert (`alarmType: "blacklist"`).
  - *ERPNext Roadmap*: Employees marked as *Terminated / Suspended with Cause* can be flagged as Blacklist on hardware to alert security guards at turnstiles.

### B. Administrator
* **What it does**: Designates this specific user as an on-device local administrator.
* **Why it matters**: When this user scans their face or enters their PIN on the terminal screen, the **hardware settings menu unlocks** directly on the terminal display without needing to type the master admin password.
* **Best Practice**: Limit this to 1 or 2 IT / Security managers so unauthorized staff cannot tamper with device network or relay settings.

### C. Long-Term Effective User vs Validity Period
* **Long-Term Effective User**: The employee never expires on hardware. The terminal sets `beginTime: 1970-01-01T00:00:00` and `endTime: 2037-12-31T23:59:59`. Ideal for permanent employees.
* **Validity Period**: Enforces a strict start date/time and expiration date/time. The terminal automatically rejects access the minute the expiration timestamp passes, even if the terminal is offline from ERPNext.
* **ERPNext Implementation**: ERPNext automatically uses *Validity Period* for `Biometric Visitor Pass` and contract/temporary workers, while using *Long-Term* for permanent active staff.

---

## 2. PIN Mode (Platform Applied vs Device Set)

Found under: **Configuration > Access Control > User / Credential Parameters**

Hikvision terminals offer two distinct ways to assign keypad PIN codes:

| Mode | How it Works | Recommendation for ERPNext |
| :--- | :--- | :--- |
| **Platform Applied (Server-Driven)** | The PIN is generated and managed centrally by ERPNext / software. The terminal accepts the PIN pushed via ISAPI (`custom_biometric_pin`) and does not allow users to randomly change it on the terminal. | **Recommended**. Keeps ERPNext as the Single Source of Truth for passwords. |
| **Device Set (Local)** | The user or technician types the PIN directly into the terminal screen. If ERPNext later pushes a user sync, it could overwrite the user's local PIN unless specifically preserved. | Only use if terminals are standalone without centralized software. |

---

## 3. Card, M1 Encryption & Mobile NFC

Found under: **Configuration > Access Control > Card Parameters**

### A. M1 (Mifare Classic 13.56 MHz) vs EM (125 kHz)
* MinMoe terminals equipped with RFID typically support 13.56 MHz Mifare (M1) or dual-frequency cards.
* By default, readers read the **CSN (Card Serial Number)** or UID (unencrypted 32-bit / 56-bit number).

### B. M1 Encryption (Sector Protection)
* **The Vulnerability**: Standard Mifare Classic CSNs can be easily cloned using cheap handheld RFID copiers or flipper devices.
* **M1 Encryption Solution**: The terminal writes and reads data from encrypted data sectors on the card using proprietary AES/DES security keys. If an unencrypted cloned card is presented, the terminal rejects it.
* **When to enable**: High-security facilities (banks, server rooms, R&D labs). Requires pre-formatting cards using a USB desk reader with matching encryption keys.

### C. NFC (Near Field Communication)
* Allows Android smartphones or smartwatches with NFC to act as access cards.
* *Note on Apple Wallet / iPhones*: iOS randomizes NFC UIDs for security. To support iPhones, you must either use Hikvision's mobile credential app (Hik-Connect via Bluetooth) or configure Apple VAS (Value Added Services) credentials.

---

## 4. Bluetooth Option & Mobile Badges

Found under: **Configuration > System > System Settings > External Device** or **Access Control**

* **What it does**: Activates the internal Bluetooth Low Energy (BLE) transceiver on supported MinMoe models (e.g. DS-K1T342MBFWX).
* **How it works**:
  - Staff install the **Hik-Connect** app on iOS or Android.
  - When walking up to the door within 1–3 meters, the phone automatically handshakes with the terminal over BLE and pulses the door open without taking the phone out of their pocket.
* **ERPNext Opportunity**: Can be integrated by issuing digital card numbers in ERPNext that match the user's Hik-Connect virtual credential.

---

## 5. Linkage Settings (Event-Driven Hardware Automation)

Found under: **Configuration > Event / Alarm > Linkage Method**

Linkage settings define **"If Event X occurs, automatically trigger Hardware Action Y"**. This executes directly inside the terminal's DSP chip without requiring a network or server connection.

### Key Linkage Scenarios:

```
┌────────────────────────────────────────┐         Hardware Trigger         ┌────────────────────────────────────────┐
│  Trigger Event                         │ ════════════════════════════════ │  Automated Terminal Response           │
│  - Door Forced Open (Break-in)         │                                  │  - Sound Audible Siren / Buzzer        │
│  - Duress PIN entered by hostage       │                                  │  - Trigger External Relay (Strobe Light)│
│  - Blacklisted Face detected           │                                  │  - Capture & Upload Snapshot to ERPNext│
│  - Tamper Sensor (Ripped off wall)     │                                  │  - Send Alarm Webhook to Security Desk │
└────────────────────────────────────────┘                                  └────────────────────────────────────────┘
```

1. **Door Forced Open (Magnetic Sensor)**:
   - If the magnetic door sensor opens without a valid face/card/button scan, the terminal sounds an on-board buzzer and pulses an alarm output to notify security.
2. **Duress PIN / Duress Fingerprint**:
   - If a staff member is held at gunpoint/coerced, they enter a secret **Duress PIN** (e.g., standard PIN is `1234`, Duress PIN is `9999`).
   - The door unlocks normally so the attacker is unaware, but the terminal secretly fires a silent **Duress Alarm webhook** to ERPNext and the security guard desk.
3. **Blacklist Linkage**:
   - Denies door entry, captures a high-resolution snapshot, and triggers the terminal flash light.

---

## 6. Serial Port, RS-485, Wiegand & Secure Door Control

Found under: **Configuration > System > System Settings > External Device** (RS-485 / Wiegand)

### A. Why would a MinMoe terminal connect to a card reader?
Even though the MinMoe terminal already has face recognition, a keypad, and a card reader on the front, connecting an external reader is extremely common for **Dual-Direction Door Control**:

```
 ┌─────────────────────────┐                                    ┌─────────────────────────┐
 │   OUTSIDE (Entrance)    │                                    │     INSIDE (Exit)       │
 │                         │                                    │                         │
 │   Hikvision MinMoe      │                                    │   Cheaper Slave Reader  │
 │   Face / Card / PIN     │ ═══════ RS-485 or Wiegand ════════ │   (RS-485 Card/Finger)  │
 │   (Terminal Relay Out)  │                                    │   or Push-to-Exit Button│
 └────────────┬────────────┘                                    └────────────┬────────────┘
              │                                                              │
              └─────────────────────── Control Lock ─────────────────────────┘
```

* **Cost Efficiency**: You place **one MinMoe** on the outside of the door (entrance). On the inside, instead of buying a second expensive face terminal, you connect a **$30 Hikvision RS-485 card/fingerprint reader** (e.g. DS-K1107 / DS-K1201).
* **True IN/OUT Attendance**: The MinMoe records `Direction: IN` when staff use the face screen, and records `Direction: OUT` when staff tap the RS-485 reader inside!

---

### B. Secure Door Control Unit (DS-K2M060 / DS-K2M061)
This is one of the most critical security settings in physical access control:

#### ⚠️ The Security Risk of Built-in Relays:
If the MinMoe is mounted outside on an exterior wall, an intruder could pry the terminal off the wall, expose the wires, and touch the two lock wires together to short the relay and open the door.

#### 🛡️ The Secure Door Unit Solution:
1. In the terminal settings, set **Serial Port** $\rightarrow$ **Secure Door Control Unit**.
2. Mount the **Hikvision DS-K2M060 Secure Door Unit** *inside the secure building* (e.g. above the ceiling tiles or in the IT server rack).
3. The MinMoe terminal no longer connects directly to the magnetic lock. Instead, the MinMoe connects to the DS-K2M060 over an **encrypted RS-485 communication line**.
4. When a face is recognized, the MinMoe sends an encrypted digital command to the secure unit inside, and the secure unit physically unlocks the door. If someone destroys or rips the terminal off the wall outside, the door remains deadlocked!

---

### C. Access Controller Mode (DS-K2600 / DS-K2800)
* If your building already has a central multi-door access control cabinet (e.g. 4-door or 8-door Hikvision master controller), you set the MinMoe to **Access Controller Mode**.
* The MinMoe acts purely as a biometric sensor, transmitting scanned card and face events to the master controller, which makes the unlock decision.

---

### D. Wiegand Output
* Used for legacy 3rd-party building systems (Honeywell, Paxton, HID, Gallagher).
* When a face is verified on the MinMoe, it converts the employee ID into a Wiegand 26-bit or 34-bit card signal and pulses it across copper wires to an existing 3rd-party alarm panel.

---

## 7. Actionable Integration Roadmap for ERPNext

Based on these hardware capabilities, here is what we can directly expose and automate in the `biometric_integration` app:

| Hardware Feature | ERPNext Implementation Roadmap | Priority |
| :--- | :--- | :--- |
| **Platform Applied PIN** | Ensure `custom_biometric_pin` pushes directly as `password` with platform enforcement flag. *(Already supported in ISAPI)* | Done |
| **Person Type (Blacklist)** | Add `is_blacklisted` check on Employee / Visitor. Pushes `userType: "blackList"` to terminal. | High |
| **Secure Door Unit Status** | Add a field on `Biometric Device`: *"Using Secure Door Control Unit (DS-K2M060)"* to log secure relay events. | Medium |
| **Duress Alarm Webhook** | Listen for `alarmType: "duress"` in `api.push` and trigger urgent ERPNext desktop notification / email to security team. | High |
| **Door Forced / Tamper Alarms** | Listen for `event_type: "door_forced"` or `tamper` in webhook to create real-time security incident logs in `Door Access Log`. | High |
| **Sub-Reader IN/OUT Splitting** | Distinguish punches originating from the main terminal camera (`Direction: IN`) vs external RS-485 sub-reader (`Direction: OUT`). | Medium |
| **Device Administrator Tag** | Add a checkbox on Employee: *"Biometric Hardware Device Admin"* to automatically grant device-menu access on terminals. | Low |
