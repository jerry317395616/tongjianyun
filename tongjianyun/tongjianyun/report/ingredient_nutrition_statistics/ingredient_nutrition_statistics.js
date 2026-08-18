frappe.query_reports["Ingredient Nutrition Statistics"] = {
    filters: [
        {
            fieldname: "recipe",
            label: "食谱",
            fieldtype: "Link",
            options: "Tongjianyun Recipe",
            get_query: () => ({ filters: { is_deleted: 0 } }),
        },
        {
            fieldname: "meal_slot",
            label: "餐次",
            fieldtype: "Select",
            options: "全部\n早餐\n早点\n午餐\n午点\n晚餐",
            default: "全部",
        },
        {
            fieldname: "category",
            label: "食材分类",
            fieldtype: "Select",
            options: "全部\n细粮\n杂粮\n糕点\n干豆类\n豆制品\n非深色蔬菜\n深色蔬菜\n水果\n奶及奶制品\n蛋类\n肉类\n动物肝脏\n鱼虾水产\n糖类\n油脂及坚果\n饮用水",
            default: "全部",
        },
        {
            fieldname: "ingredient",
            label: "食材关键字",
            fieldtype: "Data",
        },
        {
            fieldname: "value_basis",
            label: "统计口径",
            fieldtype: "Select",
            options: "日均每人贡献\n周合计每人贡献\n每100克营养成分",
            default: "日均每人贡献",
        },
        {
            fieldname: "nutrient_scope",
            label: "营养指标",
            fieldtype: "Select",
            options: "全部指标\n核心指标",
            default: "全部指标",
        },
        {
            fieldname: "sort_by",
            label: "排序与图表",
            fieldtype: "Select",
            options: "能量\n蛋白质\n脂肪\n碳水化合物\n钙\n铁\n锌\n维生素A\n维生素C\n膳食纤维",
            default: "能量",
        },
    ],

    onload(report) {
        report.page.add_inner_button("打开当前食谱", () => {
            const recipe = report.get_filter_value("recipe");
            if (!recipe) {
                frappe.msgprint("请先选择一份食谱。");
                return;
            }
            frappe.route_options = { recipe };
            frappe.set_route("tongjianyun-recipe-workbench");
        });
        report.page.add_inner_button("周食谱营养分析", () => {
            frappe.set_route("weekly-recipe-nutrition-sheet");
        });

        if (!report.get_filter_value("recipe")) {
            frappe.db.get_list("Tongjianyun Recipe", {
                filters: { is_deleted: 0 },
                fields: ["name"],
                order_by: "week_start desc, modified desc",
                limit: 1,
            }).then((rows) => {
                if (rows.length && !report.get_filter_value("recipe")) {
                    report.set_filter_value("recipe", rows[0].name);
                }
            });
        }
    },

    formatter(value, row, column, data, defaultFormatter) {
        let formatted = defaultFormatter(value, row, column, data);
        if (column.fieldname === "ingredient") {
            return `<span style="font-weight:700;color:var(--text-color);">${formatted}</span>`;
        }
        if (column.fieldname === "category") {
            const text = frappe.utils.escape_html(String(data?.category || ""));
            return `<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#e9f7f1;color:#1f7a5a;font-weight:600;">${text}</span>`;
        }
        if (column.fieldtype === "Float" && Number(value || 0) === 0) {
            return '<span style="color:var(--text-muted);">0</span>';
        }
        if (["dishes", "data_basis"].includes(column.fieldname)) {
            return `<span style="color:var(--text-muted);">${formatted}</span>`;
        }
        return formatted;
    },
};
