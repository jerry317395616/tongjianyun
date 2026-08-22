frappe.ui.form.on("Tongjianyun Nutrition Rule Set", {
    refresh(frm) {
        if (frm.is_new()) return;

        frm.add_custom_button(__("试算对比"), () => {
            frappe.prompt(
                [{ fieldname: "recipe", label: __("食谱"), fieldtype: "Link", options: "Tongjianyun Recipe", reqd: 1 }],
                ({ recipe }) => frappe.call({
                    method: "tongjianyun.nutrition_rule_service.preview_rule_set",
                    args: { rule_set: frm.doc.name, recipe },
                    freeze: true,
                    freeze_message: __("正在试算营养规则…"),
                }).then(({ message }) => {
                    const rows = (message?.differences || []).map((row) =>
                        `<tr><td>${frappe.utils.escape_html(row.nutrient)}</td><td>${formatNumber(row.before)}</td><td>${formatNumber(row.after)}</td><td>${formatNumber(row.change_percent)}%</td></tr>`
                    ).join("");
                    frappe.msgprint({
                        title: __("营养规则试算结果"),
                        wide: true,
                        message: `<div class="table-responsive"><table class="table table-bordered"><thead><tr><th>${__("营养指标")}</th><th>${__("当前规则")}</th><th>${__("草稿规则")}</th><th>${__("变化率")}</th></tr></thead><tbody>${rows}</tbody></table></div>`,
                    });
                }),
                __("选择试算食谱"),
            );
        });

        if (frm.doc.status === "草稿") {
            frm.add_custom_button(__("提交审核"), () => callTransition(frm, "submit_rule_set"), __("规则流程"));
        }
        if (frm.doc.status === "待审核" && (frappe.user.has_role("System Manager") || frappe.user.has_role("Tongjianyun Administrator"))) {
            frm.add_custom_button(__("发布规则"), () => {
                frappe.confirm(__("发布后，新的营养分析将立即使用本规则。确定继续吗？"), () =>
                    callTransition(frm, "publish_rule_set", { confirmation: "确认发布" })
                );
            }, __("规则流程"));
        }
    },
});

function callTransition(frm, method, extra = {}) {
    return frappe.call({
        method: `tongjianyun.nutrition_rule_service.${method}`,
        args: { rule_set: frm.doc.name, ...extra },
        freeze: true,
    }).then(() => frm.reload_doc());
}

function formatNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number.toFixed(3).replace(/\.?0+$/, "") : "0";
}
