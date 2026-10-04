// Copyright (c) 2026, NDV and contributors
// For license information, please see license.txt

frappe.pages['door-control'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __('Door & Shutter Control'),
        single_column: true
    });

    page.add_inner_button(__('Refresh Doors'), function() {
        render_doors(page);
    }, 'refresh');

    render_doors(page);
};

function render_doors(page) {
    let $parent = $(page.body);
    $parent.empty();

    let $container = $(`
        <div class="door-control-container" style="max-width: 900px; margin: 20px auto; padding: 0 15px;">
            <div class="row" id="door-cards-list">
                <div class="col-sm-12 text-center text-muted" style="padding: 40px;">
                    <i class="fa fa-spinner fa-spin fa-2x"></i>
                    <p style="margin-top: 10px;">${__("Loading accessible doors...")}</p>
                </div>
            </div>
        </div>
    `).appendTo($parent);

    frappe.call({
        method: "biometric_integration.biometric_integration.api.get_accessible_doors",
        callback: function(r) {
            let $list = $container.find("#door-cards-list");
            $list.empty();

            let doors = r.message || [];
            if (doors.length === 0) {
                $list.html(`
                    <div class="col-sm-12 text-center text-muted" style="padding: 40px; background: var(--card-bg); border-radius: 8px;">
                        <i class="fa fa-lock fa-3x" style="opacity: 0.3; margin-bottom: 15px;"></i>
                        <h4>${__("No Accessible Doors Found")}</h4>
                        <p>${__("No active doors with mobile unlock permission are currently configured.")}</p>
                    </div>
                `);
                return;
            }

            doors.forEach(door => {
                let isShutter = door.door_type === "Roller Shutter Gate";
                let btnLabel = isShutter ? __("Cycle / Toggle Shutter") : __("Tap to Unlock");
                let btnIcon = isShutter ? "fa-arrow-circle-up" : "fa-unlock-alt";
                let btnClass = isShutter ? "btn-warning" : "btn-primary";

                let badgeHtml = "";
                if (door.current_state === "Closed") {
                    badgeHtml = `<span class="indicator-pill green" style="font-size: 12px; padding: 4px 10px;">${__("Closed")}</span>`;
                } else if (door.current_state === "Open") {
                    badgeHtml = `<span class="indicator-pill orange" style="font-size: 12px; padding: 4px 10px;">${__("Open")}</span>`;
                } else if (door.current_state === "Held-Open Alert") {
                    badgeHtml = `<span class="indicator-pill red" style="font-size: 12px; padding: 4px 10px;">${__("HELD OPEN ALERT")}</span>`;
                } else {
                    badgeHtml = `<span class="indicator-pill grey" style="font-size: 12px; padding: 4px 10px;">${__("Unknown")}</span>`;
                }

                let cardHtml = $(`
                    <div class="col-md-6 col-sm-12" style="margin-bottom: 20px;">
                        <div class="card" style="border: 1px solid var(--border-color); border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); background: var(--card-bg); overflow: hidden;">
                            <div class="card-body" style="padding: 20px;">
                                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                                    <div>
                                        <h4 style="margin: 0 0 5px 0; font-weight: 600;">${door.door_name}</h4>
                                        <p class="text-muted" style="margin: 0; font-size: 13px;">
                                            <i class="fa fa-map-marker"></i> ${door.location || __("Factory")} • ${door.door_type}
                                        </p>
                                    </div>
                                    <div>${badgeHtml}</div>
                                </div>
                                <div style="margin-top: 20px;">
                                    <button class="btn ${btnClass} btn-block btn-lg trigger-door-btn" style="height: 52px; font-size: 16px; font-weight: 600; border-radius: 8px;">
                                        <i class="fa ${btnIcon}" style="margin-right: 8px;"></i> ${btnLabel}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                `);

                // Button click handler
                cardHtml.find(".trigger-door-btn").on("click", function() {
                    let $btn = $(this);
                    $btn.prop("disabled", true).html(`<i class="fa fa-spinner fa-spin"></i> ${__("Signaling...")}`);

                    let method = isShutter 
                        ? "biometric_integration.biometric_integration.api.trigger_access_shutter"
                        : "biometric_integration.biometric_integration.api.unlock_access_door";

                    frappe.call({
                        method: method,
                        args: { door_name: door.name },
                        callback: function(res) {
                            if (res.message && res.message.status === "success") {
                                frappe.show_alert({
                                    message: res.message.message,
                                    indicator: "green"
                                }, 5);
                                $btn.html(`<i class="fa fa-check"></i> ${__("Triggered!")}`).removeClass("btn-primary btn-warning").addClass("btn-success");
                                setTimeout(() => {
                                    $btn.prop("disabled", false).html(`<i class="fa ${btnIcon}"></i> ${btnLabel}`).removeClass("btn-success").addClass(btnClass);
                                    render_doors(page);
                                }, 3000);
                            } else {
                                $btn.prop("disabled", false).html(`<i class="fa ${btnIcon}"></i> ${btnLabel}`);
                            }
                        },
                        error: function() {
                            $btn.prop("disabled", false).html(`<i class="fa ${btnIcon}"></i> ${btnLabel}`);
                        }
                    });
                });

                $list.append(cardHtml);
            });
        }
    });
}
