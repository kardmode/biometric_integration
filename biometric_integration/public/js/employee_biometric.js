// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on('Employee', {
    refresh(frm) {
        if (frm.is_new()) return;

        // Custom buttons for Biometric Credential Management
        frm.add_custom_button(__('Sync to Terminals'), function() {
            frappe.call({
                method: 'biometric_integration.biometric_integration.employee_sync.sync_employee_to_devices',
                args: { employee_name: frm.doc.name },
                freeze: true,
                freeze_message: __('Syncing credentials to Biometric Devices...'),
                callback: function(r) {
                    if (r.message) {
                        const res = r.message;
                        const indicator = res.status === 'success' ? 'green' : (res.status === 'warning' ? 'orange' : 'red');
                        frappe.msgprint({
                            title: __('Biometric Sync Result'),
                            indicator: indicator,
                            message: res.message
                        });
                        frm.reload_doc();
                    }
                }
            });
        }, __('Biometric Access'));

        frm.add_custom_button(__('Revoke Access'), function() {
            frappe.confirm(
                __('Are you sure you want to revoke biometric and door access for <b>{0}</b> across all physical terminals?', [frm.doc.employee_name || frm.doc.name]),
                function() {
                    frappe.call({
                        method: 'biometric_integration.biometric_integration.employee_sync.remove_employee_from_devices',
                        args: { employee_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Revoking access on all terminals...'),
                        callback: function(r) {
                            if (r.message) {
                                frappe.msgprint({
                                    title: __('Access Revoked'),
                                    indicator: 'orange',
                                    message: r.message.message
                                });
                                frm.reload_doc();
                            }
                        }
                    });
                }
            );
        }, __('Biometric Access'));

        frm.add_custom_button(__('Fetch Face from Terminal'), function() {
            frappe.call({
                method: 'biometric_integration.biometric_integration.employee_sync.fetch_face_from_device',
                args: { employee_name: frm.doc.name },
                freeze: true,
                freeze_message: __('Downloading biometric face capture from terminal...'),
                callback: function(r) {
                    if (r.message) {
                        const res = r.message;
                        const indicator = res.status === 'success' ? 'green' : 'red';
                        frappe.msgprint({
                            title: res.status === 'success' ? __('Face Capture Saved') : __('Face Retrieval Failed'),
                            indicator: indicator,
                            message: res.message
                        });
                        if (res.status === 'success') {
                            frm.reload_doc();
                        }
                    }
                }
            });
        }, __('Biometric Access'));

        // Display sync status indicator on form if available
        if (frm.doc.custom_biometric_sync_status) {
            let color = 'gray';
            if (frm.doc.custom_biometric_sync_status === 'Synced') color = 'green';
            else if (frm.doc.custom_biometric_sync_status === 'Pending') color = 'orange';
            else if (frm.doc.custom_biometric_sync_status === 'Failed') color = 'red';

            const faceStatus = frm.doc.custom_biometric_face_image ? __(' | Face: Enrolled') : __(' | Face: None');
            const enrolledId = frm.doc.custom_biometric_device_enrolled_id ? __(' | Hardware ID: {0}', [frm.doc.custom_biometric_device_enrolled_id]) : '';
            
            frm.dashboard.set_headline_alert(
                __('Biometric Sync: <b>{0}</b> (Last Synced: {1}){2}{3}', [
                    frm.doc.custom_biometric_sync_status,
                    frm.doc.custom_biometric_last_synced || __('Never'),
                    enrolledId,
                    faceStatus
                ]),
                color
            );

            // If ID changed and not yet synced to hardware, alert HR
            const currentId = (frm.doc.attendance_device_id || frm.doc.name || '').trim();
            const enrolled = (frm.doc.custom_biometric_device_enrolled_id || '').trim();
            if (enrolled && currentId && enrolled !== currentId) {
                frm.dashboard.add_comment(
                    __('Device ID has changed! Terminal currently has <b>{0}</b>, but Attendance ID is set to <b>{1}</b>. Click <b>Biometric Access &gt; Sync to Terminals</b> to migrate the hardware ID and credentials.', [enrolled, currentId]),
                    'orange',
                    true
                );
            }
        }
    },

    attendance_device_id(frm) {
        if (frm.doc.attendance_device_id) {
            const raw = frm.doc.attendance_device_id;
            const cleaned = raw.replace(/[^a-zA-Z0-9]/g, '');
            if (raw !== cleaned) {
                frm.set_value('attendance_device_id', cleaned);
                frappe.show_alert({
                    message: __('Hardware Terminal ID sanitized: special characters removed ({0} &rarr; {1})', [raw, cleaned]),
                    indicator: 'blue'
                });
            }
        }
    }
});

