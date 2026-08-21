frappe.query_reports["Weekly Recipe Nutrition Analysis"] = {
    filters: [
        {
            fieldname: "recipe",
            label: __("Recipe"),
            fieldtype: "Link",
            options: "Tongjianyun Recipe",
            get_query: () => ({ filters: { is_deleted: 0 } }),
        },
        {
            fieldname: "standard_mode",
            label: "标准计算方式",
            fieldtype: "Select",
            options: "自动（按学生档案）\n手动估算",
            default: "自动（按学生档案）",
        },
        {
            fieldname: "student_groups",
            label: "统计班级（不选则全园）",
            fieldtype: "MultiSelectList",
            get_data: (txt) => frappe.db.get_link_options("Student Group", txt, { disabled: 0 }),
        },
        {
            fieldname: "age_group",
            label: "手动年龄口径",
            fieldtype: "Select",
            options: "4–5岁平均\n4岁\n5岁",
            default: "4–5岁平均",
        },
        {
            fieldname: "gender",
            label: "手动性别口径",
            fieldtype: "Select",
            options: "男女平均\n男\n女",
            default: "男女平均",
        },
        {
            fieldname: "garden_ratio",
            label: "园内供给目标",
            fieldtype: "Percent",
            default: 80,
        },
        {
            fieldname: "section",
            label: "报表内容",
            fieldtype: "Select",
            options: "全部\n营养素\n食物结构\n餐次结构",
            default: "全部",
        },
    ],

    onload(report) {
        report.page.add_inner_button("打开食谱计划", () => {
            frappe.set_route("tongjianyun-recipe-workbench");
        });
        report.page.add_inner_button("打开当前食谱", () => {
            const recipe = report.get_filter_value("recipe");
            if (!recipe) {
                frappe.msgprint("请先选择一份食谱。");
                return;
            }
            frappe.route_options = { recipe };
            frappe.set_route("tongjianyun-recipe-workbench");
        });

        if (!report.get_filter_value("recipe")) {
            frappe.db.get_list("Tongjianyun Recipe", {
                filters: { is_deleted: 0 },
                fields: ["name"],
                order_by: "modified desc",
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
        if (data?.section_header) {
            if (column.fieldname === "metric") {
                return `<span style="font-weight:700;color:var(--text-color);">${formatted}</span>`;
            }
            return "";
        }
        if (column.fieldname === "evaluation") {
            const text = String(data?.evaluation || "");
            let color = "var(--text-muted)";
            let background = "var(--subtle-fg)";
            if (["达标", "适宜", "接近目标"].includes(text)) {
                color = "#2b8a3e";
                background = "#ebfbee";
            } else if (["偏低", "偏高", "需调整", "需关注"].includes(text)) {
                color = "#c92a2a";
                background = "#fff5f5";
            } else if (["未记录", "数据不足"].includes(text)) {
                color = "#e67700";
                background = "#fff9db";
            }
            return `<span style="display:inline-block;padding:2px 8px;border-radius:999px;color:${color};background:${background};font-weight:600;">${frappe.utils.escape_html(text)}</span>`;
        }
        if (column.fieldname === "achievement_rate" && Number(data?.achievement_rate) < 80) {
            formatted = `<span style="color:#c92a2a;font-weight:600;">${formatted}</span>`;
        }
        return formatted;
    },
};
