(() => {
  const esc = value => frappe.utils.escape_html(String(value ?? ""));
  frappe.ui.form.on("Production Plan", {
    refresh(frm) {
      const week = frm.doc.custom_meal_week;
      const historical = !week;
      if (historical && (!frm.doc.custom_is_meal_plan || !frm.doc.custom_meal_batch)) return;
      const filters = historical ? {plan_batch: frm.doc.custom_meal_batch} : {week_name: week};
      frm.set_intro(historical
        ? "历史生产计划草稿：仅保留每名幼儿带量；供餐人数待确认，配方计算基准1不代表实际供餐人数。"
        : `本餐计划供餐 ${Number(frm.doc.custom_meal_headcount || 0)} 人，人数来自教育在册名册；人均带量与总需求在周计划中核算。`, "blue");
      if (week) frm.add_custom_button("食谱周计划", () => frappe.set_route("Form", "Meal Planning Week", week));
      frm.add_custom_button("周食谱表", () => frappe.set_route("query-report", "Tongjianyun Weekly Menu", filters));
      frm.add_custom_button("食材需求明细", () => frappe.set_route("query-report", "Meal Ingredient Requirements", filters));
      const wrapper = frm.fields_dict.custom_meal_ingredients_html?.$wrapper;
      if (!wrapper) return;
      const name = frm.doc.name;
      wrapper.html("<p class='text-muted'>正在读取本餐食材需求…</p>");
      frappe.call({method: "tongjianyun.meal_planning.get_meal_ingredients", args: {plan_name: name}}).then(r => {
        if (frm.doc.name !== name) return;
        const rows = r.message?.rows || [];
        const cells = rows.map(x => `<tr><td>${esc(x.ingredient_name)}</td><td>${esc(x.per_child_qty)} ${esc(x.uom)}/人</td><td>${x.total_qty === null ? "人数待确认" : `${esc(x.total_qty)} ${esc(x.uom)}`}</td></tr>`).join("");
        const note = historical ? "历史供餐人数未确认；暂不计算备料总量。" : `计划人数 ${Number(frm.doc.custom_meal_headcount)} 人；非当天实际就餐记录。`;
        wrapper.html(`<strong>本餐食材带量与备料总量</strong><table class="table table-bordered"><thead><tr><th>食材</th><th>每名幼儿</th><th>本餐总量</th></tr></thead><tbody>${cells}</tbody></table><p class="text-muted small">${note}</p>`);
      }).catch(() => { if (frm.doc.name === name) wrapper.html("<p class='text-danger'>读取失败，请打开食材需求明细查看。</p>"); });
    }
  });
})();
