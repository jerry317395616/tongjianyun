const TJY_ATTENDANCE_STATUS_OPTIONS = [
    ["Present", "到园"],
    ["Absent", "缺勤"],
    ["Leave", "请假"],
];

function tjy_escape(value) {
    return frappe.utils.escape_html(String(value ?? ""));
}

function tjy_status_label(status) {
    return TJY_ATTENDANCE_STATUS_OPTIONS.find(([value]) => value === status)?.[1] || "到园";
}

function tjy_status_class(status) {
    return status === "Present" ? "text-success" : status === "Absent" ? "text-danger" : "text-warning";
}

function tjy_student_key(detail) {
    return `${detail.student_group}::${detail.student}`;
}

function tjy_open_student_attendance(frm) {
    let details = [];
    let classFilter = "";
    let statusFilter = "";
    let searchText = "";
    const changes = new Map();

    const dialog = new frappe.ui.Dialog({
        title: __("按班级管理学生缺勤"),
        size: "extra-large",
        fields: [
            {
                fieldname: "attendance_table",
                fieldtype: "HTML",
                label: "",
            },
        ],
        primary_action_label: __("保存变更"),
        primary_action: async () => {
            if (frm.doc.status !== "待确认") {
                frappe.msgprint(__("当前记录不是待确认状态，请先重新核对后再修改。"));
                return;
            }
            const payload = Array.from(changes.values());
            if (!payload.length) {
                frappe.show_alert({ message: __("没有需要保存的变更"), indicator: "blue" });
                return;
            }
            const invalid = payload.find((item) => item.status === "Leave" && !String(item.leave_reason || "").trim());
            if (invalid) {
                frappe.msgprint(__("标记请假时必须填写请假原因：{0}").replace("{0}", invalid.student));
                return;
            }
            await frappe.call({
                method: "tongjianyun.daily_meals.save_student_meal_attendance",
                type: "POST",
                args: {
                    meal_date: frm.doc.meal_date,
                    changes: JSON.stringify(payload),
                },
                freeze: true,
                freeze_message: __("正在保存学生缺勤并重新汇总…"),
            }).then((response) => {
                frm.sync(response.message.confirmation);
                dialog.hide();
                frm.refresh();
                frappe.show_alert({ message: __("学生缺勤已保存，班级人数已重新汇总"), indicator: "green" });
            });
        },
    });

    const $wrapper = dialog.fields_dict.attendance_table.$wrapper;

    function getCurrent(detail) {
        return changes.get(tjy_student_key(detail)) || {
            student_group: detail.student_group,
            student: detail.student,
            status: detail.attendance_status,
            leave_reason: detail.leave_reason || "",
        };
    }

    function filteredDetails() {
        const query = searchText.trim().toLowerCase();
        return details.filter((detail) => {
            const current = getCurrent(detail);
            const matchesClass = !classFilter || detail.student_group === classFilter;
            const matchesStatus = !statusFilter || current.status === statusFilter;
            const matchesSearch = !query
                || String(detail.student_name || "").toLowerCase().includes(query)
                || String(detail.student || "").toLowerCase().includes(query);
            return matchesClass && matchesStatus && matchesSearch;
        });
    }

    function render() {
        const classes = [];
        details.forEach((detail) => {
            if (!classes.some((item) => item.value === detail.student_group)) {
                classes.push({ value: detail.student_group, label: detail.class_name });
            }
        });
        const visible = filteredDetails();
        const readonly = frm.doc.status !== "待确认";
        const total = details.length;
        const counts = details.reduce((result, detail) => {
            const status = getCurrent(detail).status;
            result[status] = (result[status] || 0) + 1;
            return result;
        }, { Present: 0, Absent: 0, Leave: 0 });
        const classOptions = [
            `<option value="">全部班级</option>`,
            ...classes.map((item) => `<option value="${tjy_escape(item.value)}" ${item.value === classFilter ? "selected" : ""}>${tjy_escape(item.label)}</option>`),
        ].join("");
        const statusOptions = [
            `<option value="">全部状态</option>`,
            ...TJY_ATTENDANCE_STATUS_OPTIONS.map(([value, label]) => `<option value="${value}" ${value === statusFilter ? "selected" : ""}>${label}</option>`),
        ].join("");

        const rows = visible.map((detail) => {
            const current = getCurrent(detail);
            const statusOptionsHtml = TJY_ATTENDANCE_STATUS_OPTIONS.map(([value, label]) => (
                `<option value="${value}" ${value === current.status ? "selected" : ""}>${label}</option>`
            )).join("");
            const reason = current.leave_reason || detail.leave_reason || "";
            return `
                <tr data-student-key="${tjy_escape(tjy_student_key(detail))}">
                    <td>${tjy_escape(detail.group_roll_number || "")}</td>
                    <td><strong>${tjy_escape(detail.student_name)}</strong><br><small class="text-muted">${tjy_escape(detail.student)}</small></td>
                    <td><select class="form-control tjy-student-status" ${readonly ? "disabled" : ""}>${statusOptionsHtml}</select></td>
                    <td><input class="form-control tjy-leave-reason" value="${tjy_escape(reason)}" placeholder="请假原因" ${readonly || current.status !== "Leave" ? "disabled" : ""}></td>
                    <td class="${tjy_status_class(current.status)} tjy-meal-cell">${current.status === "Present" ? "早餐 · 午餐 · 午点" : "不就餐"}</td>
                    <td>${detail.leave_application ? `<small class="text-muted">${tjy_escape(detail.leave_application)}</small>` : "—"}</td>
                </tr>`;
        }).join("");

        $wrapper.html(`
            <style>
                .tjy-attendance-manager { padding: 4px 2px 8px; }
                .tjy-attendance-toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
                .tjy-attendance-toolbar .form-control { min-width:150px; max-width:220px; }
                .tjy-attendance-summary { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
                .tjy-attendance-summary span { padding:5px 10px; border-radius:14px; background:var(--bg-light-gray); font-size:12px; }
                .tjy-attendance-summary .present { color:var(--green-600); background:var(--green-50); }
                .tjy-attendance-summary .absent { color:var(--red-600); background:var(--red-50); }
                .tjy-attendance-summary .leave { color:var(--orange-600); background:var(--orange-50); }
                .tjy-attendance-table-wrap { max-height:520px; overflow:auto; border:1px solid var(--border-color); border-radius:8px; }
                .tjy-attendance-manager table { margin:0; font-size:12px; }
                .tjy-attendance-manager th { position:sticky; top:0; z-index:1; background:var(--bg-color); }
                .tjy-attendance-manager td, .tjy-attendance-manager th { vertical-align:middle !important; }
                .tjy-attendance-manager .tjy-meal-cell { min-width:130px; }
                .tjy-attendance-help { margin-top:8px; color:var(--text-muted); font-size:12px; }
            </style>
            <div class="tjy-attendance-manager">
                <div class="tjy-attendance-toolbar">
                    <select class="form-control tjy-class-filter">${classOptions}</select>
                    <select class="form-control tjy-status-filter">${statusOptions}</select>
                    <input class="form-control tjy-student-filter" value="${tjy_escape(searchText)}" placeholder="搜索学生姓名或编号">
                    <button class="btn btn-default btn-xs tjy-bulk-present" ${readonly ? "disabled" : ""}>当前结果标记到园</button>
                    <button class="btn btn-default btn-xs tjy-bulk-absent" ${readonly ? "disabled" : ""}>当前结果标记缺勤</button>
                </div>
                <div class="tjy-attendance-summary">
                    <span>在册 <strong>${total}</strong></span>
                    <span class="present">到园 <strong>${counts.Present}</strong></span>
                    <span class="absent">缺勤 <strong>${counts.Absent}</strong></span>
                    <span class="leave">请假 <strong>${counts.Leave}</strong></span>
                    ${readonly ? `<span>当前为${tjy_escape(frm.doc.status)}，只读查看</span>` : ""}
                </div>
                <div class="tjy-attendance-table-wrap">
                    <table class="table table-hover">
                        <thead><tr><th style="width:60px">序号</th><th>学生</th><th style="width:110px">出勤状态</th><th style="width:190px">请假原因</th><th>就餐结果</th><th>请假记录</th></tr></thead>
                        <tbody>${rows || `<tr><td colspan="6" class="text-center text-muted" style="padding:28px">没有符合条件的学生</td></tr>`}</tbody>
                    </table>
                </div>
                <div class="tjy-attendance-help">状态保存后会写入教育管理考勤/请假记录，并自动重算班级和全园就餐人数。已确认记录需先重新核对；已锁定记录不可修改。</div>
            </div>
        `);

        $wrapper.find(".tjy-class-filter").on("change", function () {
            classFilter = this.value;
            render();
        });
        $wrapper.find(".tjy-status-filter").on("change", function () {
            statusFilter = this.value;
            render();
        });
        $wrapper.find(".tjy-student-filter").on("input", function () {
            searchText = this.value;
            const cursor = this.selectionStart;
            render();
            const input = $wrapper.find(".tjy-student-filter").get(0);
            if (input) {
                input.focus();
                input.setSelectionRange(cursor, cursor);
            }
        });
        $wrapper.find(".tjy-student-status").on("change", function () {
            const row = $(this).closest("tr");
            const detail = details.find((item) => tjy_student_key(item) === row.data("student-key"));
            if (!detail) return;
            const current = getCurrent(detail);
            changes.set(tjy_student_key(detail), {
                student_group: detail.student_group,
                student: detail.student,
                status: this.value,
                leave_reason: current.leave_reason || "",
            });
            render();
        });
        $wrapper.find(".tjy-leave-reason").on("input", function () {
            const row = $(this).closest("tr");
            const detail = details.find((item) => tjy_student_key(item) === row.data("student-key"));
            if (!detail) return;
            const current = getCurrent(detail);
            changes.set(tjy_student_key(detail), {
                student_group: detail.student_group,
                student: detail.student,
                status: current.status,
                leave_reason: this.value,
            });
        });
        $wrapper.find(".tjy-bulk-present, .tjy-bulk-absent").on("click", function () {
            const status = $(this).hasClass("tjy-bulk-present") ? "Present" : "Absent";
            visible.forEach((detail) => {
                const current = getCurrent(detail);
                changes.set(tjy_student_key(detail), {
                    student_group: detail.student_group,
                    student: detail.student,
                    status,
                    leave_reason: current.leave_reason || "",
                });
            });
            render();
        });
    }

    dialog.show();
    $wrapper.html('<div class="text-center" style="padding:36px;color:var(--text-muted);">正在加载班级和学生…</div>');
    frappe.call({
        method: "tongjianyun.daily_meals.get_student_details",
        args: { meal_date: frm.doc.meal_date },
    }).then((response) => {
        details = response.message || [];
        render();
    }).catch((error) => {
        $wrapper.html(`<div class="text-danger" style="padding:30px">加载失败：${tjy_escape(error?.message || "请稍后重试")}</div>`);
    });
}

frappe.ui.form.on("Tongjianyun Daily Meal Confirmation", {
    refresh(frm) {
        if (frm.is_new()) {
            frm.set_intro("保存后可根据 Education 的班级、考勤和请假数据自动计算就餐人数。", "blue");
            return;
        }

        frm.add_custom_button("管理学生缺勤", () => tjy_open_student_attendance(frm));

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

        if (frm.doc.status === "已确认") {
            frm.add_custom_button("重新核对", async () => {
                const response = await frappe.call({
                    method: "tongjianyun.daily_meals.reopen_daily_meal",
                    type: "POST",
                    args: { name: frm.doc.name },
                    freeze: true,
                    freeze_message: "正在打开学生缺勤修改…",
                });
                frm.sync(response.message);
                frm.refresh();
            });
        }

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
