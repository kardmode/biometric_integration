// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on('Biometric Device', {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.webhook_endpoint_url) {
            frm.add_custom_button(__('Copy Push URL'), function() {
                frappe.utils.copy_to_clipboard(frm.doc.webhook_endpoint_url);
                frappe.show_alert({ message: __('Push URL copied to clipboard!'), indicator: 'green' });
            });
        }

        if (!frm.is_new() && frm.doc.ip && frm.doc.username) {
            frm.add_custom_button(__('Test Connection'), function() {
                frappe.call({
                    method: 'biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.check_device_connection',
                    args: { device_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Testing connection...'),
                    callback: function(r) {
                        const res = r.message || {};
                        const indicator = res.status === 'success' ? 'green' : 'red';
                        frappe.msgprint({
                            title: res.status === 'success' ? __('Connection Successful') : __('Connection Failed'),
                            indicator: indicator,
                            message: `<div><b>${res.message}</b><br><small>${res.details || ''}</small></div>`
                        });
                        frm.reload_doc();
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Fetch Hardware Info'), function() {
                frappe.call({
                    method: 'biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.fetch_device_info',
                    args: { device_name: frm.doc.name },
                    freeze: true,
                    callback: function(r) {
                        if (r.message) {
                            frappe.show_alert({ message: r.message.message, indicator: 'green' });
                            frm.reload_doc();
                        }
                    }
                });
            }, __('Actions'));

            frm.add_custom_button(__('Sync Logs'), function() {
                const d = new frappe.ui.Dialog({
                    title: __('Sync Attendance from ' + frm.doc.name),
                    fields: [
                        { label: __('From Date'), fieldname: 'from_date', fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1 },
                        { label: __('From Time'), fieldname: 'from_time', fieldtype: 'Time', default: '00:00:00', reqd: 1 },
                        { fieldtype: 'Column Break' },
                        { label: __('To Date'), fieldname: 'to_date', fieldtype: 'Date', default: frappe.datetime.get_today(), reqd: 1 },
                        { label: __('To Time'), fieldname: 'to_time', fieldtype: 'Time', default: '23:59:59', reqd: 1 }
                    ],
                    primary_action_label: __('Sync Now'),
                    primary_action(values) {
                        d.hide();
                        values.device_name = frm.doc.name;
                        frappe.call({
                            method: 'biometric_integration.biometric_integration.doctype.biometric_device.biometric_device.sync_device_attendance',
                            args: values,
                            freeze: true,
                            freeze_message: __('Syncing device logs...'),
                            callback: function(r) {
                                if (r.message) {
                                    frappe.msgprint({
                                        title: __('Sync Result'),
                                        indicator: 'green',
                                        message: r.message
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                });
                d.show();
            }, __('Actions'));
        }
    }
});
