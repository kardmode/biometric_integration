// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.ui.form.on("UNIS Attendance Importer", {
	onload: function(frm) {
		frm.set_value("import_settings", "Update Existing Records");
		frm.set_value("only_show_errors", 1);
	},

	refresh: function(frm) {
		frm.disable_save();
		frm.page.set_title(__("UNIS Attendance Importer"));

		// 1. Setup Drag & Drop File Uploader
		let $wrapper = $(frm.fields_dict.upload_html.wrapper).empty();
		new frappe.ui.FileUploader({
			wrapper: $wrapper,
			method: "biometric_integration.biometric_integration.doctype.unis_attendance_importer.unis_attendance_importer.upload",
			on_success: function(file_doc) {
				frappe.show_alert({
					message: __("File uploaded. Processing UNIS Attendance..."),
					indicator: "blue"
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
			if (data.progress && data.total) {
				frappe.show_progress(__("Importing UNIS Attendance"), data.progress, data.total);
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
									<tr><th>${__("Detailed Logs & Notifications ({0} items)", [messages.length])}</th></tr>
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
