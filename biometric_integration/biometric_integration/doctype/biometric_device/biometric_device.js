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

        if (!frm.is_new() && frm.doc.enable_access_control) {
            frm.add_custom_button(__('Unlock Door'), function() {
                frappe.confirm(
                    __('Trigger remote unlock pulse on <b>{0}</b>?', [frm.doc.device_name || frm.doc.name]),
                    function() {
                        frappe.call({
                            method: 'unlock_door',
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __('Unlocking door...'),
                            callback: function(r) {
                                if (r.message && r.message.status === 'success') {
                                    frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-success');
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

            frm.add_custom_button(__('Sync Active Employees'), function() {
                frappe.confirm(
                    __('Sync all active employees to <b>{0}</b>?<br><br><small class="text-muted">Note: This safely registers IDs, names, PINs, and RFID cards. Existing face and fingerprint data on the terminal will <b>NOT</b> be overwritten.</small>', [frm.doc.name]),
                    function() {
                        frappe.call({
                            method: 'biometric_integration.biometric_integration.employee_sync.sync_all_active_employees_to_device',
                            args: { device_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __('Syncing all active employees to device...'),
                            callback: function(r) {
                                if (r.message) {
                                    frappe.msgprint({
                                        title: __('Employee Sync Complete'),
                                        indicator: 'green',
                                        message: r.message.message
                                    });
                                }
                            }
                        });
                    }
                );
            }, __('Actions'));


            if (frm.doc.enable_access_control) {
                frm.add_custom_button(__('Push Door Schedule'), function() {
                    frappe.confirm(
                        __('Push door schedule to <b>{0}</b>?', [frm.doc.name]),
                        function() {
                            frappe.call({
                                method: 'sync_door_schedule',
                                doc: frm.doc,
                                freeze: true,
                                freeze_message: __('Syncing door schedule to terminal...'),
                                callback: function(r) {
                                    if (r.message && r.message.status === 'success') {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }, __('Actions'));

                // Door Hardware Mode Controls
                frm.add_custom_button(__('Hold Open (Always Open)'), function() {
                    frappe.confirm(
                        __('Keep <b>{0}</b> permanently unlocked (Free Passage mode)?', [frm.doc.name]),
                        function() {
                            frappe.call({
                                method: 'set_door_mode',
                                doc: frm.doc,
                                args: { command: 'alwaysOpen' },
                                freeze: true,
                                callback: function(r) {
                                    if (r.message) {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    }
                                }
                            });
                        }
                    );
                }, __('Door Mode'));

                frm.add_custom_button(__('Lockdown (Always Closed)'), function() {
                    frappe.confirm(
                        __('Put <b>{0}</b> into lockdown (Lock permanently, denying access)?', [frm.doc.name]),
                        function() {
                            frappe.call({
                                method: 'set_door_mode',
                                doc: frm.doc,
                                args: { command: 'alwaysClose' },
                                freeze: true,
                                callback: function(r) {
                                    if (r.message) {
                                        frappe.show_alert({ message: r.message.message, indicator: 'orange' });
                                    }
                                }
                            });
                        }
                    );
                }, __('Door Mode'));

                frm.add_custom_button(__('Resume Normal Security'), function() {
                    frappe.confirm(
                        __('Clear manual hold/lockdown and resume normal scheduled security on <b>{0}</b>?', [frm.doc.name]),
                        function() {
                            frappe.call({
                                method: 'set_door_mode',
                                doc: frm.doc,
                                args: { command: 'resume' },
                                freeze: true,
                                callback: function(r) {
                                    if (r.message) {
                                        frappe.show_alert({ message: r.message.message, indicator: 'green' });
                                    }
                                }
                            });
                        }
                    );
                }, __('Door Mode'));
            }

            frm.add_custom_button(__('Fetch Enrolled User Count'), function() {
                frappe.call({
                    method: 'biometric_integration.biometric_integration.employee_sync.fetch_enrolled_user_count',
                    args: { device_name: frm.doc.name },
                    freeze: true,
                    callback: function(r) {
                        if (r.message && r.message.status === 'success') {
                            frappe.msgprint({
                                title: __('Enrolled Users Count'),
                                indicator: 'blue',
                                message: __('Device <b>{0}</b> currently has <b>{1}</b> enrolled persons.', [frm.doc.name, r.message.enrolled_users])
                            });
                        }
                    }
                });
            }, __('Actions'));
        }
    }
});

