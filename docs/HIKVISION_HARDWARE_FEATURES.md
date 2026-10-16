# Hikvision MinMoe Hardware Features, Settings & Integration Roadmap

This document provides an in-depth technical breakdown of the advanced features and configurations found in the **Hikvision MinMoe Terminal Web Interface** (`Configuration` menu). It details how each hardware setting works, how it integrates with **ERPNext**, and how to build your own custom mobile applications (Flutter / React Native / iOS / Android) to interact with the hardware over **Bluetooth (BLE)** and **NFC**.

---

## 📋 Table of Contents
1. [User & Credential Settings](#1-user--credential-settings)
2. [PIN Mode: Platform Applied vs. Device Set](#2-pin-mode-platform-applied-vs-device-set)
3. [NFC & RFID Card Settings (Android vs. iOS Deep Dive)](#3-nfc--rfid-card-settings-android-vs-ios-deep-dive)
4. [Bluetooth Low Energy (BLE) Deep Dive & Hik-Connect](#4-bluetooth-low-energy-ble-deep-dive--hik-connect)
5. [Building Your Own Custom Mobile Access App (Architectures)](#5-building-your-own-custom-mobile-access-app-architectures)
6. [Linkage Settings (Event-Driven Hardware Automation)](#6-linkage-settings-event-driven-hardware-automation)
7. [Serial Port, RS-485, Wiegand & Secure Door Control](#7-serial-port-rs-485-wiegand--secure-door-control)
8. [Actionable Integration Roadmap for ERPNext](#8-actionable-integration-roadmap-for-erpnext)

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

### C. Long-Term Effective User vs. Validity Period
* **Long-Term Effective User**: The employee never expires on hardware. The terminal sets `beginTime: 1970-01-01T00:00:00` and `endTime: 2037-12-31T23:59:59`. Ideal for permanent employees.
* **Validity Period**: Enforces a strict start date/time and expiration date/time. The terminal automatically rejects access the minute the expiration timestamp passes, even if the terminal is offline from ERPNext.
* **ERPNext Implementation**: ERPNext automatically uses *Validity Period* for `Biometric Visitor Pass` and contract/temporary workers, while using *Long-Term* for permanent active staff.

---

## 2. PIN Mode: Platform Applied vs. Device Set

Found under: **Configuration > Access Control > User / Credential Parameters**

Hikvision terminals offer two distinct ways to assign keypad PIN codes:

| Mode | How it Works | Recommendation for ERPNext |
| :--- | :--- | :--- |
| **Platform Applied (Server-Driven)** | The PIN is generated and managed centrally by ERPNext / software. The terminal accepts the PIN pushed via ISAPI (`custom_biometric_pin`) and does not allow users to randomly change it on the terminal. | **Recommended**. Keeps ERPNext as the Single Source of Truth for passwords. |
| **Device Set (Local)** | The user or technician types the PIN directly into the terminal screen. If ERPNext later pushes a user sync, it could overwrite the user's local PIN unless specifically preserved. | Only use if terminals are standalone without centralized software. |

---

## 3. NFC & RFID Card Settings (Android vs. iOS Deep Dive)

Found under: **Configuration > Access Control > Card Parameters**

### A. M1 (Mifare Classic 13.56 MHz) vs. EM (125 kHz)
* MinMoe terminals equipped with RFID typically support 13.56 MHz Mifare (M1) or dual-frequency cards.
* By default, readers read the **CSN (Card Serial Number)** or UID (unencrypted 32-bit / 56-bit number).

### B. M1 Encryption (Sector Protection)
* **The Vulnerability**: Standard Mifare Classic CSNs can be easily cloned using cheap handheld RFID copiers or flipper devices.
* **M1 Encryption Solution**: The terminal writes and reads data from encrypted data sectors on the card using proprietary AES/DES security keys. If an unencrypted cloned card is presented, the terminal rejects it.
* **When to enable**: High-security facilities (banks, server rooms, R&D labs). Requires pre-formatting cards using a USB desk reader with matching encryption keys.

---

### C. Smartphone NFC (Near Field Communication)

```
┌───────────────────────────────────────┐             ┌───────────────────────────────────────┐
│              ANDROID                  │             │                 iOS                   │
├───────────────────────────────────────┤             ├───────────────────────────────────────┤
│ • Supports Host Card Emulation (HCE)  │             │ ❌ Apple locks NFC to Apple Pay       │
│ • Custom apps can transmit static UID │             │ ❌ Randomizes NFC UID on every tap    │
│ • Tap phone to reader works natively  │             │ ❌ 3rd-party apps cannot emulate card │
│                                       │             │                                       │
│ ✅ Direct Tap-to-Unlock is easy       │             │ ⚠️ Requires BLE, Sticker, or VAS Pass │
└───────────────────────────────────────┘             └───────────────────────────────────────┘
```

#### 1. How Android NFC Works (Host Card Emulation - HCE)
Android operating systems natively support **Host Card Emulation (HCE)**:
* A custom mobile app running on Android can implement an Android service (`HostApduService`).
* When the Android phone is tapped against the MinMoe reader, the phone emulates an ISO 14443-4 contactless smart card.
* The app sends the employee's `custom_biometric_card_no` (configured in ERPNext) to the reader.
* The MinMoe reader reads this digital card number and unlocks the door seamlessly.

#### 2. The iOS / iPhone NFC Wall & Why it Fails by Default
If you try to tap an iPhone on a standard MinMoe RFID reader out of the box, it will **not work**:
1. **Apple NFC Lockout**: Apple strictly prohibits third-party iOS apps from emulating arbitrary Mifare or ISO 14443 card UIDs (Apple CoreNFC is restricted to reading passive tags, Apple Pay, or Apple Wallet passes).
2. **UID Randomization**: For anti-tracking privacy, iOS transmits a **randomized, temporary UID** every time the iPhone enters an NFC RF field. If you tap the iPhone 5 times, the MinMoe terminal will see 5 completely different card numbers!

#### 3. Four Practical Fixes & Workarounds for iPhones:

* **Fix 1: Bluetooth (BLE) as the Primary iPhone Credential (Industry Standard)**
  - This is why commercial access control leaders (HID Mobile Access, Brivo, Kisi, Hikvision) use **Bluetooth** instead of NFC for iPhones.
  - iOS gives background permissions to `CoreBluetooth`. The iPhone acts as a Bluetooth peripheral, handshaking securely with the terminal when walking up to the door.

* **Fix 2: Ultra-Thin RFID Phone Sticker (The $0.50 Zero-Tech Fix)**
  - Place a paper-thin **Mifare 13.56 MHz anti-metal adhesive sticker** (cost: ~$0.50) inside the employee's protective phone case or on the back of the iPhone.
  - Register that sticker's permanent UID in ERPNext under `custom_biometric_card_no`.
  - To the user, they simply "tap their phone" on the door reader. To the terminal, it reads a 100% compliant physical Mifare tag. Requires zero battery, zero apps, and works on any phone.

* **Fix 3: Dynamic On-Screen 2D QR Code**
  - MinMoe face terminals equipped with wide-angle cameras also read 2D QR codes!
  - Your custom mobile app displays a time-expiring rolling QR code (TOTP valid for 30 seconds).
  - The employee flashes their screen in front of the MinMoe camera $\rightarrow$ unlocks instantly.

* **Fix 4: Apple Wallet Access Pass (Apple VAS / ECP)**
  - For enterprise deployments, deploy digital badges directly into the native Apple Wallet app.
  - Requires an Apple Developer Enterprise account with Apple VAS (Value Added Services) certificate and an ECP-compliant reader firmware.

---

## 4. Bluetooth Low Energy (BLE) Deep Dive & Hik-Connect

Found under: **Configuration > System > System Settings > External Device > Bluetooth** (or **Access Control > System Parameters**)

### A. How Bluetooth Works on MinMoe Terminals
Terminals with built-in Bluetooth (e.g. `DS-K1T342MBFWX`, `DS-K1T673MBFWX`) contain a 2.4 GHz BLE transceiver that continuously broadcasts an encrypted advertisement beacon.

### B. Terminal Web UI Bluetooth Configuration Parameters:

1. **Bluetooth Function**: `Enable / Disable`
2. **Sensing Distance Sensitivity**:
   - **Close Range / Tap-to-Unlock (-80 dBm, ~0.3m – 0.5m)**: User must bring phone within inches of the terminal. Prevents accidental unlocks from people walking past inside the room.
   - **Medium Range (-70 dBm, ~1.0m – 1.5m)**: Unlocks as the user reaches for the door handle.
   - **Long Range / Hands-Free (-60 dBm, ~2.5m – 3.0m)**: Automatically unlocks as you approach the door (ideal for turnstiles or barrier gates).
3. **Verification / Trigger Mode**:
   - *Manual Tap / Button in App*: User opens the app and presses "Unlock".
   - *Shake to Open*: User shakes their phone near the terminal to trigger.
   - *Hands-Free Proximity*: Unlocks purely based on walking within the configured signal strength window.

---

### C. The Official Hik-Connect Workflow
1. The company registers the terminal in **HikCentral** or **Hik-ProConnect**.
2. An administrator issues a **Mobile Credential** (Virtual Card) to the employee's email/phone.
3. The employee installs the **Hik-Connect** app and logs in.
4. When near the door, the Hik-Connect app exchanges an encrypted challenge-response handshake over BLE with the terminal.
5. The terminal verifies the virtual card number against its local database and trips the relay.

---

## 5. Building Your Own Custom Mobile Access App (Architectures)

If you want to build your own custom branded mobile app (using **Flutter**, **React Native**, **Swift**, or **Kotlin**) for employees to unlock doors, you have two architectural paths:

### Architecture Path A: The "Beacon + Cloud/Local Relay" Pattern (Recommended)

This is the fastest, most reliable architecture. It completely bypasses proprietary Bluetooth encryption, requires zero vendor SDKs, and works identically on both **iOS and Android**.

```
┌─────────────────────────────────┐
│     Employee Smartphone         │
│     (Flutter / React Native)    │
└──────────────┬──────────────────┘
               │ 1. Senses MinMoe BLE Beacon within 1 meter
               ▼
┌─────────────────────────────────┐
│     MinMoe BLE Beacon           │
│     (Broadcasting MAC / UUID)   │
└─────────────────────────────────┘
               │
               │ 2. App sends authenticated REST API:
               │    POST /api/method/biometric_integration...unlock_door
               ▼
┌─────────────────────────────────┐
│     ERPNext Cloud Server        │
│     - Checks User Permissions   │
│     - Verifies Access Shift     │
│     - Creates Door Access Log   │
└──────────────┬──────────────────┘
               │ 3. Triggers relay pulse over Tailscale / LAN
               ▼
┌─────────────────────────────────┐
│     Hikvision Terminal Relay    │ ───► [ Door Unlocks! ]
└─────────────────────────────────┘
```

#### Implementation Steps:
1. **MinMoe Beacon**: The MinMoe terminal continuously broadcasts its Bluetooth MAC address or iBeacon UUID.
2. **App Detection**: Use standard open-source mobile packages (`flutter_blue_plus` for Flutter or `react-native-ble-plx` for React Native) to listen for the terminal's BLE signal.
3. **Proximity Trigger**: When the RSSI signal is stronger than `-70 dBm` (meaning the employee is standing right at the door), the app displays an **"Unlock Front Door"** button or automatically fires the request.
4. **ERPNext Secure Execution**:
   - The app calls the whitelisted ERPNext endpoint:
     `POST /api/method/biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.unlock_door`
   - ERPNext validates that the user is logged in, checks if their role or `Biometric Access Shift` permits unlocking right now, logs the event in `Door Access Log`, and sends the pulse to the terminal over Tailscale!

---

### Architecture Path B: Direct Hardware BLE (Hikvision Mobile SDK)

If you require **offline unlocking** (e.g. your mobile app must unlock doors even if the internet or ERPNext server is completely down):

1. **Hikvision Mobile Access SDK**:
   - Obtain the official `Hikvision Mobile Access SDK` (iOS Objective-C framework and Android `.aar` library) from the Hikvision Developer Portal.
2. **Direct GATT Handshake**:
   - The app establishes a direct BLE GATT connection to the terminal's Access Control Service UUID (`0000fee0-...`).
   - The app sends a cryptographically signed authentication packet containing the employee's ID.
   - The terminal's internal CPU validates the token offline and unlocks the relay.

---

## 6. Linkage Settings (Event-Driven Hardware Automation)

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

## 7. Serial Port, RS-485, Wiegand & Secure Door Control

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

* **Cost Efficiency**: You place **one MinMoe** on the outside of the door (entrance). On the inside, instead of buying a second expensive face terminal, you connect an inexpensive **$30 Hikvision RS-485 card/fingerprint reader** (e.g. DS-K1107 / DS-K1201).
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

## 8. Actionable Integration Roadmap for ERPNext

Based on these hardware capabilities, here is what we can directly expose and automate in the `biometric_integration` app:

| Hardware Feature | ERPNext Implementation Roadmap | Status / Priority |
| :--- | :--- | :--- |
| **Platform Applied PIN** | Ensure `custom_biometric_pin` pushes directly as `password` with platform enforcement flag. | **Implemented** |
| **Time Schedules (Shifts)** | Replaced manual device tables with first-class `Biometric Access Shift` links. | **Implemented** |
| **Tailscale Subnet Routing** | Direct cloud ERPNext to local LAN device bridging documentation and setup. | **Implemented** |
| **Duress Alarm Webhook** | Listen for `alarmType: "duress"` in `api.push` and trigger urgent ERPNext desktop notification / email to security team. | **High Priority** |
| **Door Forced / Tamper Alarms** | Listen for `event_type: "door_forced"` or `tamper` in webhook to create real-time security incident logs in `Door Access Log`. | **High Priority** |
| **Person Type (Blacklist)** | Add `is_blacklisted` check on Employee / Visitor. Pushes `userType: "blackList"` to terminal. | **High Priority** |
| **Sub-Reader IN/OUT Splitting** | Distinguish punches originating from the main terminal camera (`Direction: IN`) vs external RS-485 sub-reader (`Direction: OUT`). | **Medium Priority** |
| **Mobile Proximity Relay API** | Expose a lightweight BLE beacon verification endpoint for custom mobile apps. | **Medium Priority** |
| **Secure Door Unit Status** | Add a field on `Biometric Device`: *"Using Secure Door Control Unit (DS-K2M060)"* to log secure relay events. | **Medium Priority** |
| **Device Administrator Tag** | Add a checkbox on Employee: *"Biometric Hardware Device Admin"* to automatically grant device-menu access on terminals. | **Low Priority** |
