frappe.ui.form.on("Student", {
    id_number: function (frm) {
        var id = frm.doc.id_number || "";
        if (!id) return;

        id = $.trim(id);

        // 长度校验
        if (id.length !== 18) {
            frm.set_value("id_number", "");
            frappe.throw(__("身份证号必须为 18 位"));
            return;
        }

        // 格式正则校验：前 17 位数字 + 第 18 位数字或 X
        if (!/^\d{17}[\dXx]$/.test(id)) {
            frm.set_value("id_number", "");
            frappe.throw(__("身份证号格式不正确"));
            return;
        }

        // 日期部分提取
        var year = parseInt(id.substring(6, 10), 10);
        var month = parseInt(id.substring(10, 12), 10);
        var day = parseInt(id.substring(12, 14), 10);

        // 日期合法性
        var dob = new Date(year, month - 1, day);
        if (
            dob.getFullYear() !== year ||
            dob.getMonth() !== month - 1 ||
            dob.getDate() !== day
        ) {
            frm.set_value("id_number", "");
            frappe.throw(__("身份证号中的出生日期不合法"));
            return;
        }

        var today = new Date();
        today.setHours(0, 0, 0, 0);
        if (dob > today) {
            frm.set_value("id_number", "");
            frappe.throw(__("身份证号中的出生日期不能晚于今天"));
            return;
        }
    },
});
