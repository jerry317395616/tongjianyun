from __future__ import annotations

import datetime

import frappe

ID_NUMBER_FIELDNAME = "id_number"
ID_NUMBER_LABEL = "身份证号"
ID_NUMBER_FIELDTYPE = "Data"
ID_NUMBER_LENGTH = 18
ID_NUMBER_INSERT_AFTER = "student_mobile_number"


def install() -> None:
    """通过 Custom Field 给 Student 添加身份证号字段。

    此函数在 bench migrate 的 after_migrate 阶段被调用。
    如果 Custom Field 已存在则跳过，幂等安全。
    """
    _ensure_id_number_field()


def _ensure_id_number_field() -> None:
    """如果 Student 上还没有 id_number 的 Custom Field，就创建它。"""
    if frappe.db.exists("Custom Field", {
        "dt": "Student",
        "fieldname": ID_NUMBER_FIELDNAME,
    }):
        return

    custom_field = frappe.new_doc("Custom Field")
    custom_field.dt = "Student"
    custom_field.module = "Tongjianyun"
    custom_field.fieldname = ID_NUMBER_FIELDNAME
    custom_field.label = ID_NUMBER_LABEL
    custom_field.fieldtype = ID_NUMBER_FIELDTYPE
    custom_field.len = ID_NUMBER_LENGTH
    custom_field.insert_after = ID_NUMBER_INSERT_AFTER
    custom_field.read_only = 0
    custom_field.hidden = 0
    custom_field.permlevel = 0
    custom_field.ignore_user_permissions = 0
    custom_field.allow_on_submit = 0
    custom_field.no_copy = 0
    custom_field.is_system_generated = 1
    custom_field.insert(ignore_permissions=True)


def validate_id_number(id_number: str) -> str | None:
    """校验 18 位身份证号格式。

    规则：
    1. 长度必须为 18
    2. 前 6 位为行政区划码（数字）
    3. 接下来 8 位为出生日期（YYYYMMDD）
    4. 接下来 3 位为顺序码（数字）
    5. 最后 1 位为校验码（数字或 X）
    6. 出生日期不能晚于今天
    7. 出生日期不能早于 1900-01-01

    :param id_number: 身份证号字符串
    :return: 合法时返回 None，不合法时返回错误信息
    """
    if not id_number:
        return None

    id_number = id_number.strip()

    # 1. 长度
    if len(id_number) != 18:
        return "身份证号必须为 18 位"

    # 2. 前 17 位为数字
    if not id_number[:17].isdigit():
        return "身份证号前 17 位必须为数字"

    # 3. 最后一位为数字或 X/x
    if not (id_number[17].isdigit() or id_number[17] in ("X", "x")):
        return "身份证号第 18 位必须为数字或 X"

    # 4. 日期合法性
    year = int(id_number[6:10])
    month = int(id_number[10:12])
    day = int(id_number[12:14])

    try:
        dob = datetime.date(year, month, day)
    except ValueError:
        return "身份证号中的出生日期不合法"

    today = datetime.date.today()
    if dob > today:
        return "身份证号中的出生日期不能晚于今天"
    if dob.year < 1900:
        return "身份证号中的出生日期不能早于 1900 年"

    return None
