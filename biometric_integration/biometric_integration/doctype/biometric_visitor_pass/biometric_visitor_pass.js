// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on('Biometric Visitor Pass', {
    refresh(frm) {
        if (frm.is_new()) return;

        // Copy PIN button
        if (frm.doc.pin_code) {
            frm.add_custom_button(__('Copy PIN: {0}', [frm.doc.pin_code]), function() {
                frappe.utils.copy_to_clipboard(frm.doc.pin_code);
                frappe.show_alert({ message: __('PIN copied to clipboard!'), indicator: 'green' });
            });
        }

        // Active state buttons
        if (frm.doc.status === 'Active') {
            frm.add_custom_button(__('Push to Doors'), function() {
                frm.call({
                    method: 'sync_to_devices',
                    doc: frm.doc,
                    freeze: true,
                    freeze_message: __('Syncing visitor pass to terminals...'),
                    callback: function(r) {
                        if (r.message) {
                            frappe.msgprint({
                                title: __('Sync Result'),
                                indicator: r.message.status === 'success' ? 'green' : 'orange',
                                message: r.message.message
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Revoke Pass'), function() {
                frappe.confirm(
                    __('Revoke this pass and immediately lock out visitor <b>{0}</b>?', [frm.doc.visitor_name]),
                    function() {
                        frm.call({
                            method: 'revoke_from_devices',
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __('Revoking pass on door terminals...'),
                            callback: function(r) {
                                if (r.message) {
                                    frappe.msgprint({
                                        title: __('Pass Revoked'),
                                        indicator: 'orange',
                                        message: r.message.message
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }, __('Actions'));
        } else {
            // Reactivate button for revoked or expired passes
            frm.add_custom_button(__('Reactivate Pass'), function() {
                frm.set_value('status', 'Active');
                frm.set_value('valid_to', frappe.datetime.add_hours(frappe.datetime.now_datetime(), 8));
                frm.save().then(() => {
                    frm.call('sync_to_devices');
                });
            }, __('Actions'));
        }

        // Dashboard Alert
        let color = 'gray';
        if (frm.doc.status === 'Active') color = 'green';
        else if (frm.doc.status === 'Revoked') color = 'red';

        frm.dashboard.set_headline_alert(
            __('Pass Status: <b>{0}</b> | Temporary PIN: <b style="font-size:1.1em; letter-spacing:1px;">{1}</b> | Valid Until: {2}', [
                frm.doc.status,
                frm.doc.pin_code || __('None'),
                frm.doc.valid_to || __('Unset')
            ]),
            color
        );
    }
});
