(() => {
    const profileType = "Tongjianyun Food Nutrition Profile";

    function ingredientFields(editable) {
        const fields = frappe.get_meta(profileType).fields;
        const nutrients = fields.findIndex(df => df.fieldname === "nutrients_section");
        const details = fields.findIndex(df => ["source_section", "review_section"].includes(df.fieldname));
        return fields.slice(nutrients, details).map(df => ({
            fieldname: df.fieldname, fieldtype: df.fieldtype, label: df.label,
            description: df.fieldname === "nutrients_section"
                ? "统一按每 100 克可食部填写。没有数据请留空。" : df.description,
            read_only: !editable,
        }));
    }

    async function ingredient(frm) {
        const $content = frm.fields_dict.custom_tjy_nutrition_preview?.$wrapper;
        if (!$content) return;
        if (!frappe.model.can_read(profileType)) {
            $content.empty().text("当前账号无权查看营养档案。");
            return;
        }

        const item = frm.doc;
        const fresh = frm.is_new();
        const token = Symbol();
        $content.data("tjy-nutrition-editor", token).empty().text("正在加载营养成分…");
        const active = () => frm.doc === item && $content.data("tjy-nutrition-editor") === token;

        async function render(result, revise = false) {
            if (!active()) return;
            const {draft, approved} = result;
            const record = draft || approved;
            const editable = !fresh && !result.disabled &&
                (draft ? draft.writable : result.can_create && (!approved || revise));
            const note = fresh ? "先保存食材，再填写营养值。"
                : draft ? "待审核 · 当前显示草稿" + (approved ? "，食谱计算使用已审核版本。" : "。")
                : approved && !revise ? "已审核 · " + approved.name
                : editable ? "填写后可保存为营养档案草稿。" : "暂无营养档案。";
            item.custom_tjy_nutrition_status = result.status || item.custom_tjy_nutrition_status;
            frm.refresh_field("custom_tjy_nutrition_status");
            $content.empty();
            const $actions = $("<div>", {class: "d-flex align-items-center flex-wrap mb-2"})
                .appendTo($content);
            $("<span>", {class: "text-muted mr-2", role: "status"}).text(note).appendTo($actions);
            const button = (label, action, primary = false) => $("<button>", {
                type: "button", class: "btn btn-sm mr-2 " + (primary ? "btn-primary" : "btn-default"),
            }).text(label).on("click", action).appendTo($actions);

            const group = new frappe.ui.FieldGroup({
                body: $("<div>", {class: "tjy-ingredient-nutrition-form"}).appendTo($content),
                fields: ingredientFields(editable), no_submit_on_enter: true,
            });
            group.make();
            if (record) await group.set_values(record.values);
            if (!active()) return;

            if (editable) {
                const $save = button("保存营养草稿", async () => {
                    const input = group.get_values(false, true);
                    if (!input) return;
                    const payload = Object.fromEntries(result.editable_fields.map(key => [key, input[key] ?? ""]));
                    $save.prop("disabled", true);
                    try {
                        const {message} = await frappe.call({
                            method: "tongjianyun.food_nutrition.save_ingredient_profile", type: "POST",
                            args: {item_code: item.name, values: JSON.stringify(payload),
                                name: draft?.name, modified: draft?.modified},
                            freeze: true,
                        });
                        if (active()) {
                            await render(message);
                            frappe.show_alert({message: "营养档案草稿已保存", indicator: "green"});
                        }
                    } finally {
                        $save.prop("disabled", false);
                    }
                }, true);
            } else if (approved && !draft && !revise && result.can_create) {
                button("新建版本", () => render(result, true));
            }
            if (revise) button("取消", () => render(result));
            if (record) {
                $("<a>", {class: "btn btn-default btn-sm",
                    href: frappe.utils.get_form_link(profileType, record.name)})
                    .text("档案详情").appendTo($actions);
            }
        }

        try {
            const [, response] = await Promise.all([
                frappe.model.with_doctype(profileType),
                fresh ? null : frappe.call({
                    method: "tongjianyun.food_nutrition.ingredient_editor", type: "GET",
                    args: {item_code: item.name},
                }),
            ]);
            await render(response?.message || {});
        } catch {
            if (active()) $content.empty().text("暂时无法读取营养成分。");
        }
    }

    frappe.tjy_ingredient_nutrition = ingredient;
})();
