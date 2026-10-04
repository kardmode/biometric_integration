// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on("Access Door", {
    refresh: function(frm) {
        if (!frm.is_new()) {
            let label = frm.doc.door_type === "Roller Shutter Gate" ? __("Trigger Shutter") : __("Test Unlock (Relay Pulse)");
            let icon = frm.doc.door_type === "Roller Shutter Gate" ? "es-line-switch" : "lock";

            frm.add_custom_button(label, function() {
                frappe.call({
                    method: "biometric_integration.biometric_integration.api.unlock_access_door",
                    args: {
                        door_name: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Sending signal to controller..."),
                    callback: function(r) {
                        if (r.message && r.message.status === "success") {
                            frappe.show_alert({
                                message: r.message.message,
                                indicator: "green"
                            }, 5);
                            frm.reload_doc();
                        }
                    }
                });
            }, icon).addClass("btn-primary");
        }

        // State indicator badge
        if (frm.doc.current_state === "Closed") {
            frm.dashboard.set_headline_alert(
                `<div class="indicator green">${__("Door is securely Closed")}</div>`
            );
        } else if (frm.doc.current_state === "Open") {
            frm.dashboard.set_headline_alert(
                `<div class="indicator orange">${__("Door is currently Open")}</div>`
            );
        } else if (frm.doc.current_state === "Held-Open Alert") {
            frm.dashboard.set_headline_alert(
                `<div class="indicator red">${__("ALERT: Door Held Open!")}</div>`
            );
        }
    }
});
