/* Student-level meals: one class, exceptions only, explicit actual confirmation. */
(() => {
    const meals = [["breakfast", "早餐"], ["morning_snack", "早点"], ["lunch", "午餐"], ["afternoon_snack", "午点"], ["dinner", "晚餐"]];
    const esc = value => frappe.utils.escape_html(String(value ?? ""));
    async function open(frm) {
        let data, rows = [], dirty = false, loading = true;
        const dialog = new frappe.ui.Dialog({
            title: "确认学生就餐人数", size: "extra-large",
            fields: [
                {fieldname: "day", fieldtype: "Date", label: "日期", default: frm.doc.meal_date || frappe.datetime.get_today(), reqd: 1, onchange: () => load()},
                {fieldname: "group", fieldtype: "Select", label: "班级", reqd: 1, onchange: () => load()},
                {fieldname: "meal_table", fieldtype: "HTML"},
                {fieldname: "reason", fieldtype: "Small Text", label: "修改原因（修改已确认记录时填写）"}
            ],
            primary_action_label: "确认实际人数",
            primary_action: () => save(true),
            secondary_action_label: "保存预计人数",
            secondary_action: () => save(false)
        });
        const wrapper = dialog.fields_dict.meal_table.$wrapper;
        async function load() {
            if (loading || !dialog.get_value("group") || !dialog.get_value("day")) return;
            if (dirty && !window.confirm("切换日期或班级将丢弃尚未保存的修改，继续吗？")) {
                loading = true;
                await dialog.set_value("day", data.record.meal_date);
                await dialog.set_value("group", data.record.student_group);
                loading = false;
                return;
            }
            loading = true;
            dialog.get_primary_btn().prop("disabled", true);
            wrapper.text("正在加载学生名单…");
            try {
                const response = await frappe.call({method: "tongjianyun.student_meals.get_class_meals", args: {meal_date: dialog.get_value("day"), student_group: dialog.get_value("group")}});
                data = response.message;
                rows = (data.record.students || []).map(row => {
                    const result = {student: row.student, student_name: row.student_name, attendance_hint: row.attendance_hint};
                    meals.forEach(([key]) => { result[key] = row[key] === "不供餐" ? "不供餐" : row[key] === "已就餐" ? "就餐" : row[key] === "未就餐" ? "不就餐" : row[key + "_expected"] ? "就餐" : "不就餐"; });
                    return result;
                });
                dirty = false;
                dialog.set_value("reason", "");
                render();
            } catch (error) {
                data = null;
                wrapper.text("加载失败，请关闭后重试；未保存任何人数。");
            } finally { loading = false; }
        }
        function render() {
            const future = dialog.get_value("day") > frappe.datetime.get_today();
            dialog.get_primary_btn().prop("disabled", !rows.length || future);
            const absent = rows.filter(row => meals.some(([key]) => row[key] === "不就餐")).length;
            wrapper.html(`<div class="alert alert-info">只需标记不就餐的学生；全天、上午、下午可批量设置。预计安排不是实际就餐，点击“确认实际人数”表示已核对本班当天各餐实际情况。${future ? "未来日期仅可保存预计人数。" : ""}</div>
                <p>状态：${esc(data.record.status)} · 本班 ${rows.length} 人 · 有不就餐餐次 ${absent} 人</p>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
                    <select class="form-control tjy-meal-range" style="width:150px"><option value="all">全天</option><option value="am">上午（早餐、早点）</option><option value="pm">下午（午点、晚餐）</option>${meals.map(([key,label]) => `<option value="${key}">${label}</option>`).join("")}</select>
                    <button class="btn btn-default tjy-meal-bulk" data-state="不就餐">选中学生不就餐</button>
                    <button class="btn btn-default tjy-meal-bulk" data-state="就餐">恢复就餐</button>
                    <button class="btn btn-default tjy-meal-bulk" data-state="不供餐">该餐不提供</button>
                </div>
                <div style="max-height:440px;overflow:auto"><table class="table table-bordered"><thead><tr><th><input type="checkbox" class="tjy-meal-all" aria-label="选中全部学生"></th><th>学生</th>${meals.map(([,label])=>`<th>${label}</th>`).join("")}</tr></thead><tbody>
                ${rows.map((row,index)=>`<tr><td><input type="checkbox" class="tjy-meal-select" data-index="${index}" aria-label="选择${esc(row.student_name)}"></td><td>${esc(row.student_name || row.student)}<br><small>${row.attendance_hint === "Absent" ? "考勤参考：缺勤" : row.attendance_hint === "Leave" ? "考勤参考：请假" : "请核对实际就餐"}</small></td>${meals.map(([key,label])=>`<td><select class="form-control tjy-meal-value" data-index="${index}" data-meal="${key}" aria-label="${esc(row.student_name)}${label}">${["就餐","不就餐","不供餐"].map(value=>`<option ${value===row[key]?"selected":""}>${value}</option>`).join("")}</select></td>`).join("")}</tr>`).join("") || '<tr><td colspan="7">本班暂无启用学生。请先补齐学生档案并分配班级，不能以预计数字替代学生记录。</td></tr>'}
                </tbody><tfoot><tr><td colspan="2">本次核对人数</td>${meals.map(([key])=>`<td>${rows.filter(row=>row[key]==="就餐").length} 人</td>`).join("")}</tr></tfoot></table></div>
                <small>不就餐不等于缺勤，不会自动修改教育考勤或产生退费。上午/下午快捷项不包含午餐，请单独核对午餐。已提交采购、收货、发票和付款不会被改写。</small>`);
            wrapper.find(".tjy-meal-all").on("change", function () { wrapper.find(".tjy-meal-select").prop("checked", this.checked); });
            wrapper.find(".tjy-meal-value").on("change", function () { rows[Number(this.dataset.index)][this.dataset.meal] = this.value; dirty = true; render(); });
            wrapper.find(".tjy-meal-bulk").on("click", function () {
                const indexes = wrapper.find(".tjy-meal-select:checked").map((_,el)=>Number(el.dataset.index)).get();
                if (!indexes.length) return frappe.msgprint("请先勾选学生；如全班不供某餐，可勾选表头选择全班。");
                const range = wrapper.find(".tjy-meal-range").val();
                const keys = range === "all" ? meals.map(([key])=>key) : range === "am" ? ["breakfast","morning_snack"] : range === "pm" ? ["afternoon_snack","dinner"] : [range];
                indexes.forEach(index=>keys.forEach(key=> { if (this.dataset.state === "不供餐" || rows[index][key] !== "不供餐" || range === key) rows[index][key]=this.dataset.state; }));
                dirty = true; render();
            });
        }
        async function save(confirm) {
            if (loading || !data || !rows.length) return;
            if (data.record.status === "已确认" && !String(dialog.get_value("reason") || "").trim()) return frappe.msgprint("请填写修改原因，系统会保留原人数及本次变更记录。");
            loading = true;
            try {
                await frappe.call({method: "tongjianyun.student_meals.save_class_meals", type: "POST", freeze: true, freeze_message: "正在保存并汇总人数…", args: {meal_date: dialog.get_value("day"), student_group: dialog.get_value("group"), students: JSON.stringify(rows), revision: data.revision, confirm: confirm ? 1 : 0, change_reason: dialog.get_value("reason") || ""}});
                dirty = false;
                frappe.show_alert({message: confirm ? "本班实际人数已确认" : "预计人数已保存，尚未确认实际就餐", indicator: "green"});
                dialog.hide();
                if (!frm.is_new()) await frm.reload_doc();
            } finally { loading = false; }
        }
        dialog.show();
        loading = true;
        try {
            const response = await frappe.call({method: "tongjianyun.student_meals.get_class_meals"});
            const groups = response.message.groups;
            dialog.set_df_property("group", "options", groups.map(g=>({label:g.label,value:g.name})));
            if (groups.length) await dialog.set_value("group", groups[0].name);
            else wrapper.text("没有可操作的班级，请联系管理员分配教师与班级。");
        } finally { loading = false; }
        await load();
    }
    frappe.ui.form.on("Tongjianyun Daily Meal Confirmation", {
        refresh(frm) {
            frm.remove_custom_button("确认人数");
            frm.remove_custom_button("管理学生缺勤");
            frm.add_custom_button("按学生确认就餐", () => open(frm)).addClass("btn-primary");
            frm.set_intro("未完成各班确认时，汇总仅为预计参考。请点击“按学生确认就餐”，只标记例外后确认本班实际人数。", "blue");
        }
    });
})();
