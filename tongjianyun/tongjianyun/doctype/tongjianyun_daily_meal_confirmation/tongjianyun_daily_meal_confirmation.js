frappe.ui.form.on("Tongjianyun Daily Meal Confirmation", {
    refresh(frm) {
        if (frm.is_new()) {
            frm.set_intro("保存后可根据 Education 的班级、考勤和请假数据自动计算就餐人数。", "blue");
            return;
        }

        frm.add_custom_button("重新计算", async () => {
            const response = await frappe.call({
                method: "tongjianyun.daily_meals.recalculate_daily_meal",
                type: "POST",
                args: { name: frm.doc.name },
                freeze: true,
                freeze_message: "正在汇总班级、考勤和请假数据…",
            });
            frm.sync(response.message);
            frm.refresh();
        });

        if (frm.doc.status === "待确认") {
            frm.add_custom_button("确认人数", async () => {
                const response = await frappe.call({
                    method: "tongjianyun.daily_meals.confirm_daily_meal",
                    type: "POST",
                    args: { meal_date: frm.doc.meal_date },
                    freeze: true,
                    freeze_message: "正在确认当日就餐人数…",
                });
                frm.sync(response.message);
                frm.refresh();
            }).addClass("btn-primary");
        }
    },
});
