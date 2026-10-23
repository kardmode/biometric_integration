// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on("UNIS Attendance Importer", {
	onload: function(frm) {
		if (!frm.doc.import_settings) {
			frm.set_value("import_settings", "Dry Run (Preview & Validate Only)");
		}
		if (!frm.doc.single_punch_handling) {
			frm.set_value("single_punch_handling", "Skip & Report in Error Log");
		}
		frm.set_value("only_show_errors", 1);
	},

	refresh: function(frm) {
		frm.disable_save();
		frm.page.set_title(__("UNIS Attendance Importer"));

		// 1. Setup Drag & Drop File Uploader passing current form settings
		let $wrapper = $(frm.fields_dict.upload_html.wrapper).empty();
		new frappe.ui.FileUploader({
			wrapper: $wrapper,
			method: "biometric_integration.biometric_integration.doctype.unis_attendance_importer.unis_attendance_importer.upload",
			args: {
				params: JSON.stringify({
					import_settings: frm.doc.import_settings || "Dry Run (Preview & Validate Only)",
					single_punch_handling: frm.doc.single_punch_handling || "Skip & Report in Error Log",
					default_company: frm.doc.default_company || ""
				})
			},
			on_success: function(file_doc) {
				let mode = frm.doc.import_settings;
				let indicator = mode.includes("Dry Run") ? "orange" : "blue";
				let msg = mode.includes("Dry Run")
					? __("Dry Run Preview started. Simulating import & checking for errors...")
					: __("File uploaded. Processing UNIS Attendance...");

				frappe.show_alert({
					message: msg,
					indicator: indicator
				});
			}
		});

		// 2. Setup Real-time Import Progress & Log Display
		frm.events.setup_realtime_listener(frm);
	},

	setup_realtime_listener: function(frm) {
		let $log_wrapper = $(frm.fields_dict.import_log.wrapper);

		frappe.realtime.off("import_unis_attendance");
		frappe.realtime.on("import_unis_attendance", function(data) {
			if (data.progress && data.total && !data.messages) {
				frappe.show_progress(__("Processing UNIS Attendance"), data.progress, data.total);
				if (data.progress === data.total) {
					frappe.hide_progress();
				}
			} else if (data.messages || data.summary_html) {
				frappe.hide_progress();
				$log_wrapper.empty();

				if (data.summary_html) {
					$log_wrapper.append(data.summary_html);
				}

				let messages = data.messages || [];
				let only_errors = frm.doc.only_show_errors;

				if (only_errors) {
					messages = messages.filter(msg => 
						msg.includes("Error") || 
						msg.includes("Warning") || 
						msg.includes("Flagged") || 
						msg.includes("Skipped") || 
						msg.includes("text-danger") || 
						msg.includes("text-warning")
					);
				}

				if (messages.length > 0) {
					let rows_html = messages.map(msg => `<tr><td>${msg}</td></tr>`).join("");
					$log_wrapper.append(`
						<div style="max-height: 500px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 6px;">
							<table class="table table-bordered table-striped" style="margin-bottom: 0;">
								<thead>
									<tr><th>${__("Detailed Logs & Validation Items ({0} items)", [messages.length])}</th></tr>
								</thead>
								<tbody>
									${rows_html}
								</tbody>
							</table>
						</div>
					`);
				} else if (only_errors) {
					$log_wrapper.append(`
						<div class="alert alert-success">
							<b>${__("No Errors Found!")}</b> ${__("All records processed and matched successfully without warnings.")}
						</div>
					`);
				}
			}
		});
	}
});
