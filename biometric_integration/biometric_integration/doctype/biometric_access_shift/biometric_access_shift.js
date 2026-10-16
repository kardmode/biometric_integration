// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on('Biometric Access Shift', {
    refresh(frm) {
        // Quick Action 1: Populate Week Schedule
        frm.add_custom_button(__('Populate Week Schedule'), function() {
            open_populate_week_dialog(frm);
        }, __('Actions'));

        // Quick Action 2: Copy Row to Days
        frm.add_custom_button(__('Copy Row to Other Days'), function() {
            open_copy_row_dialog(frm);
        }, __('Actions'));
    }
});

frappe.ui.form.on('Biometric Door Schedule Item', {
    schedule_items_add(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        const all_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

        // Find existing days in current grid
        const existing_days = (frm.doc.schedule_items || [])
            .map(r => r.day_of_week)
            .filter(Boolean);

        // Pick next unused day, or Monday
        let next_day = 'Monday';
        for (let d of all_days) {
            if (!existing_days.includes(d)) {
                next_day = d;
                break;
            }
        }

        frappe.model.set_value(cdt, cdn, 'day_of_week', next_day);
        if (!row.start_time) {
            frappe.model.set_value(cdt, cdn, 'start_time', '09:00:00');
        }
        if (!row.end_time) {
            frappe.model.set_value(cdt, cdn, 'end_time', '17:00:00');
        }
    }
});


function open_populate_week_dialog(frm) {
    const all_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
    const mon_sat = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

    const d = new frappe.ui.Dialog({
        title: __('Populate Week Schedule'),
        fields: [
            {
                fieldname: 'preset',
                fieldtype: 'Select',
                label: __('Quick Day Preset'),
                options: 'Weekdays (Mon - Fri)\nMonday to Saturday\nAll 7 Days (Mon - Sun)\nCustom Selection',
                default: 'Weekdays (Mon - Fri)',
                onchange() {
                    const val = d.get_value('preset');
                    if (val === 'Weekdays (Mon - Fri)') {
                        d.set_value('days', weekdays);
                    } else if (val === 'Monday to Saturday') {
                        d.set_value('days', mon_sat);
                    } else if (val === 'All 7 Days (Mon - Sun)') {
                        d.set_value('days', all_days);
                    }
                }
            },
            {
                fieldname: 'days',
                fieldtype: 'MultiCheck',
                label: __('Select Days'),
                options: all_days.map(d => ({ label: d, value: d, checked: weekdays.includes(d) })),
                reqd: 1
            },
            { fieldtype: 'Section Break', label: __('Shift 1 Hours (Morning / Standard)') },
            {
                fieldname: 'start_time',
                fieldtype: 'Time',
                label: __('Start Time'),
                default: '09:00:00',
                reqd: 1
            },
            {
                fieldname: 'end_time',
                fieldtype: 'Time',
                label: __('End Time'),
                default: '17:00:00',
                reqd: 1
            },
            { fieldtype: 'Section Break', label: __('Optional Split Shift (Afternoon Window)') },
            {
                fieldname: 'enable_split',
                fieldtype: 'Check',
                label: __('Add Second Split Window (e.g. 16:00 to 19:00)')
            },
            {
                fieldname: 'split_start_time',
                fieldtype: 'Time',
                label: __('Second Start Time'),
                default: '16:00:00',
                depends_on: 'eval:doc.enable_split'
            },
            {
                fieldname: 'split_end_time',
                fieldtype: 'Time',
                label: __('Second End Time'),
                default: '19:00:00',
                depends_on: 'eval:doc.enable_split'
            },
            { fieldtype: 'Section Break' },
            {
                fieldname: 'clear_existing',
                fieldtype: 'Check',
                label: __('Clear existing schedule rows first'),
                default: 1
            }
        ],
        primary_action_label: __('Add Schedule Rows'),
        primary_action(values) {
            let selected_days = values.days || [];
            if (typeof selected_days === 'string') {
                selected_days = selected_days.split(',').map(s => s.trim()).filter(Boolean);
            }
            if (!selected_days || selected_days.length === 0) {
                frappe.msgprint(__('Please select at least one day.'));
                return;
            }

            if (values.clear_existing) {
                frm.clear_table('schedule_items');
            }

            const day_order = {
                'Monday': 1, 'Tuesday': 2, 'Wednesday': 3, 'Thursday': 4,
                'Friday': 5, 'Saturday': 6, 'Sunday': 7
            };
            selected_days.sort((a, b) => (day_order[a] || 0) - (day_order[b] || 0));

            for (let day of selected_days) {
                // Add Shift 1
                const row1 = frm.add_child('schedule_items');
                row1.day_of_week = day;
                row1.start_time = values.start_time;
                row1.end_time = values.end_time;

                // Add Shift 2 if split enabled
                if (values.enable_split && values.split_start_time && values.split_end_time) {
                    const row2 = frm.add_child('schedule_items');
                    row2.day_of_week = day;
                    row2.start_time = values.split_start_time;
                    row2.end_time = values.split_end_time;
                }
            }

            frm.refresh_field('schedule_items');
            d.hide();
            frappe.show_alert({
                message: __('Added schedule for {0} day(s)!', [selected_days.length]),
                indicator: 'green'
            });
        }
    });

    d.show();
}


function open_copy_row_dialog(frm) {
    const rows = frm.doc.schedule_items || [];
    if (rows.length === 0) {
        frappe.msgprint(__('Please add at least one row to the schedule first.'));
        return;
    }

    const row_options = rows.map((r, idx) => {
        return `Row #${idx + 1}: ${r.day_of_week || 'Day'} (${r.start_time || ''} - ${r.end_time || ''})`;
    });

    const all_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

    const d = new frappe.ui.Dialog({
        title: __('Copy Row to Other Days'),
        fields: [
            {
                fieldname: 'source_row_label',
                fieldtype: 'Select',
                label: __('Source Row to Copy'),
                options: row_options.join('\n'),
                default: row_options[0],
                reqd: 1
            },
            {
                fieldname: 'target_days',
                fieldtype: 'MultiCheck',
                label: __('Copy Times to Target Days'),
                options: all_days.map(day => ({ label: day, value: day, checked: false })),
                reqd: 1
            }
        ],
        primary_action_label: __('Copy to Selected Days'),
        primary_action(values) {
            let target_days = values.target_days || [];
            if (typeof target_days === 'string') {
                target_days = target_days.split(',').map(s => s.trim()).filter(Boolean);
            }
            if (!target_days || target_days.length === 0) {
                frappe.msgprint(__('Please select at least one target day.'));
                return;
            }

            const selected_label = values.source_row_label;
            const match = selected_label.match(/Row #(\d+):/);
            const row_num = match ? parseInt(match[1], 10) - 1 : 0;
            const src = rows[row_num];

            if (!src) {
                frappe.msgprint(__('Source row not found.'));
                return;
            }

            for (let day of target_days) {
                const new_row = frm.add_child('schedule_items');
                new_row.day_of_week = day;
                new_row.start_time = src.start_time;
                new_row.end_time = src.end_time;
            }

            frm.refresh_field('schedule_items');
            d.hide();
            frappe.show_alert({
                message: __('Copied times to {0} day(s)!', [target_days.length]),
                indicator: 'green'
            });
        }
    });

    d.show();
}
