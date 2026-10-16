# Hikvision MinMoe Employee Enrollment Guide
*Step-by-step instructions for adding workers, capturing face profiles, and mapping them to ERPNext / Frappe.*

---

## ⚠️ The Golden Rule of Integration

Before adding any worker into Hikvision, remember this critical link:

```
+------------------------------------+          +------------------------------------+
|         HIKVISION TERMINAL         |          |          ERPNEXT HRMS              |
|                                    |          |                                    |
|   Employee No / ID: "1042"         |<========>|   Attendance Device ID: "1042"     |
+------------------------------------+          +------------------------------------+
```

* **The Rule:** The **Employee No.** entered in the Hikvision terminal **MUST EXACTLY MATCH** the **`Attendance Device ID`** on the Employee master in ERPNext.
* When the worker scans their face, Hikvision transmits `{"employeeNo": "1042"}` to Frappe. Frappe looks up the Employee with `attendance_device_id == "1042"` and generates the attendance check-in.

---

## Method 1: On the Terminal Touchscreen (Fastest at the Gate)

Use this method when onboarding workers directly at the entrance or turnstile.

### Step 1: Access Admin Settings
1. Wake up the terminal screen.
2. Long-press the screen for 3 seconds (or swipe down from the top edge).
3. Enter the device **Admin Password** (or scan the Admin face).

### Step 2: Open User Creation
1. On the main menu, tap **User** (or **User Management**).
2. Tap **+ Add** (top-right corner).

### Step 3: Enter Worker Information
1. **Employee No:** Type the worker's unique company ID (e.g. `1042`).
2. **Name:** Type the worker's full name (e.g. `Ahmed Khan`).

### Step 4: Capture Face Data
1. Tap the **Face** icon.
2. Have the worker stand 0.5 to 1.0 meters in front of the camera.
3. Position their face inside the green target circle on the screen:
   * *Ensure eyes, nose, and mouth are clearly visible.*
   * *Remove dark-tinted safety goggles or sunglasses.*
   * *Standard hardhats, caps, and hijabs/turbans are fully supported.*
4. The terminal will capture the face, beep, and display: *"Collected successfully."*

### Step 5: (Optional) Register Card or Phone Sticker
1. If the worker carries an RFID card or phone sticker:
2. Tap the **Card** field on the screen.
3. Tap the card or phone against the card-reading icon on the terminal. The terminal will beep and store the card number.

### Step 6: Save
1. Tap the **Save** (check-mark) icon in the top-right corner.
2. **Verification:** Have the worker step back and walk up to the terminal. The screen should immediately flash green and say: *"Thank you, Ahmed Khan"*.

---

## Method 2: Via Web Browser (From HR / Admin Office)

Use this method to enroll employees remotely from your office PC using existing badge photos or passport pictures.

### Step 1: Log In to the Terminal
1. Open Google Chrome on your office PC.
2. In the address bar, type the terminal's local IP address (e.g. `http://192.168.1.60`).
3. Log in with:
   * **Username:** `admin`
   * **Password:** *(Your device password)*

### Step 2: Navigate to Person Management
1. In the top navigation bar, go to **User** (or **Access Control** → **Person**).
2. Click the **+ Add** button.

### Step 3: Fill in Personal Details
1. **ID:** `1042` *(Must match ERPNext `Attendance Device ID`)*.
2. **Name:** `Ahmed Khan`.
3. **Gender:** Select Male / Female.

### Step 4: Add Face Data
Choose either of the two collection methods:
* **Option A (Upload Existing Photo):**
  * Click **Upload Photo**.
  * Select a clean JPG/PNG image from your computer (passport-style white-background photo works best).
  * The web interface will validate the photo quality automatically.
* **Option B (Remote Collection from Gate):**
  * If the worker is standing near the gate terminal, click **Remote Collection**.
  * The terminal camera snaps the photo live and transmits it directly into your browser screen.

### Step 5: (Optional) Add RFID Card / Sticker
1. Under the **Card** section, click **+ Add**.
2. Either type the card number manually, or click **Remote Read** and have the worker tap their card at the terminal.

### Step 6: Save
1. Click **Save** at the bottom of the page.
2. The terminal immediately synchronizes the new user into its local memory.

---

## Method 3: Via iVMS-4200 (Batch / Mass Enrollment)

Use this method when importing 20+ workers simultaneously from an Excel file.

### Step 1: Bulk Import Identity Data
1. Launch **iVMS-4200** on your management PC.
2. Open the **Person** module.
3. Click **Import** → Download the Excel template.
4. Fill in: `Person ID` (must match ERPNext ID), `Name`, `Department`.
5. Upload the completed Excel file back into iVMS-4200.

### Step 2: Attach Photos
1. For each person in the list, click the **Face** icon.
2. Upload their respective JPG photos from a local folder.

### Step 3: Apply to Device
1. Open the **Access Control** module in iVMS-4200.
2. Go to **Access Group** → Select your group.
3. Check the newly enrolled employees.
4. Check the **MinMoe Attendance Terminal**.
5. Click **Save and Apply to Device**.
6. iVMS-4200 deploys all face models and user IDs to the terminal across the local network.

---

## Environmental & Quality Tips for Dubai Factories

1. **Backlighting Prevention:** Never mount the face terminal facing a bright outdoor doorway where afternoon sun creates a silhouette behind workers' heads. Ambient, diffuse, or overhead shaded light yields 99.9% accuracy.
2. **Lens Maintenance:** Factory sand and dust can settle on the dual optical/infrared lenses. Wipe the lenses weekly with a dry microfiber cloth to keep recognition speeds under 0.2 seconds.
3. **Beards & Facial Hair:** MinMoe's deep-learning dual-lens algorithm tracks 3D bone structure (pupillary distance, nose bridge, cheekbones), so workers growing or shaving beards will still be recognized without needing re-enrollment.
