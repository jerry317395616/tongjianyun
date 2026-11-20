from __future__ import annotations

import csv
import os
import re
from collections import defaultdict
from io import StringIO

import frappe
from frappe.utils import cint, cstr, getdate
from frappe.utils.xlsxutils import (
    build_xlsx_response,
    read_xls_file_from_attached_file,
    read_xlsx_file_from_attached_file,
)


MAX_IMPORT_ROWS = 2000

TEMPLATE_HEADERS = [
    "学生编号（已有学生选填）",
    "学生姓名*",
    "性别",
    "出生日期",
    "手机号码",
    "邮箱",
    "入学日期",
    "启用",
]

HEADER_ALIASES = {
    "student_id": (
        "学生编号",
        "学生编号已有学生选填",
        "学号",
        "studentid",
        "studentnumber",
    ),
    "student_name": ("学生姓名", "姓名", "studentname", "firstname"),
    "gender": ("性别", "gender"),
    "date_of_birth": ("出生日期", "生日", "dateofbirth", "birthday"),
    "student_mobile_number": (
        "手机号码",
        "手机号",
        "联系电话",
        "学生手机号",
        "studentmobilenumber",
        "mobile",
    ),
    "student_email_id": ("邮箱", "学生邮箱", "studentemailaddress", "email"),
    "joining_date": ("入学日期", "joiningdate"),
    "enabled": ("启用", "是否启用", "enabled"),
}


@frappe.whitelist()
def download_student_import_template(student_group: str):
    group = frappe.get_doc("Student Group", student_group)
    group.check_permission("read")
    build_xlsx_response(
        [TEMPLATE_HEADERS], f"{group.student_group_name or group.name}学生导入模板"
    )


@frappe.whitelist()
def import_students_to_group(
    student_group: str,
    file_url: str,
    update_existing: int | str = 1,
    allow_transfer: int | str = 0,
):
    """Create/update Student records and add them to one Student Group.

    The selected Student Group is the single source of class context, so a
    class column is intentionally not required in every spreadsheet row.
    """
    group = frappe.get_doc("Student Group", student_group)
    group.check_permission("write")
    frappe.has_permission("Student", "read", throw=True)
    frappe.has_permission("Student", "create", throw=True)

    if group.disabled:
        frappe.throw("停用的班级不能导入学生。")
    if not group.academic_year:
        frappe.throw("请先为班级设置学年。")

    parsed_rows = _read_import_rows(file_url)
    update_existing = cint(update_existing)
    allow_transfer = cint(allow_transfer)

    current_members = {row.student: row for row in group.students if row.student}
    current_active_count = sum(cint(row.active) for row in group.students)
    assignments = _get_other_group_assignments(group)
    planned_student_ids: set[str] = set()
    planned_transfers: set[tuple[str, str]] = set()
    group_changed = False

    result = {
        "total_rows": len(parsed_rows),
        "created": 0,
        "updated": 0,
        "added_to_group": 0,
        "already_in_group": 0,
        "transferred": 0,
        "errors": [],
    }

    for row_number, values in parsed_rows:
        save_point = f"student_group_import_{row_number}"
        frappe.db.savepoint(save_point)
        try:
            student, is_new = _get_or_create_student(
                values, update_existing=update_existing
            )

            if student.name in planned_student_ids:
                raise ValueError("同一文件中出现重复学生。")
            if not cint(student.enabled):
                raise ValueError("学生档案已停用，请先启用后再加入班级。")

            member = current_members.get(student.name)
            needs_class_seat = not member or not cint(member.active)
            if (
                needs_class_seat
                and group.max_strength
                and current_active_count >= cint(group.max_strength)
            ):
                raise ValueError(f"班级人数已达到上限 {group.max_strength} 人。")

            other_groups = assignments.get(student.name, [])
            if other_groups and not allow_transfer:
                raise ValueError(f"该学生已在班级：{'、'.join(other_groups)}。")

            if other_groups:
                for other_group in other_groups:
                    other_doc = frappe.get_doc("Student Group", other_group)
                    other_doc.check_permission("write")
                    planned_transfers.add((student.name, other_group))

            if member:
                if not cint(member.active):
                    member.active = 1
                    current_active_count += 1
                    group_changed = True
                    result["added_to_group"] += 1
                else:
                    result["already_in_group"] += 1
            else:
                member = group.append(
                    "students",
                    {
                        "student": student.name,
                        "student_name": student.student_name,
                        "active": 1,
                    },
                )
                current_members[student.name] = member
                current_active_count += 1
                group_changed = True
                result["added_to_group"] += 1

            planned_student_ids.add(student.name)
            result["created" if is_new else "updated"] += 1
            frappe.db.release_savepoint(save_point)
        except Exception as exc:
            frappe.db.rollback(save_point=save_point)
            frappe.clear_messages()
            result["errors"].append(
                {
                    "row": row_number,
                    "student_name": _cell_text(values.get("student_name")),
                    "message": cstr(exc) or "导入失败",
                }
            )

    if planned_transfers:
        transfer_docs = {}
        for student, other_group in planned_transfers:
            other_doc = transfer_docs.setdefault(
                other_group, frappe.get_doc("Student Group", other_group)
            )
            other_doc.check_permission("write")
            for row in other_doc.students:
                if row.student == student and cint(row.active):
                    row.active = 0
                    result["transferred"] += 1
        for other_doc in transfer_docs.values():
            other_doc.save()

    if group_changed:
        group.save()

    return result


def _read_import_rows(file_url: str) -> list[tuple[int, dict]]:
    if not file_url:
        frappe.throw("请上传学生文件。")

    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_doc.check_permission("read")
    extension = os.path.splitext(file_doc.file_name or file_url)[1].lower()
    content = file_doc.get_content()

    if extension == ".xlsx":
        rows = read_xlsx_file_from_attached_file(fcontent=content, read_only=True)
    elif extension == ".xls":
        rows = read_xls_file_from_attached_file(content)
    elif extension == ".csv":
        if isinstance(content, bytes):
            content = content.decode("utf-8-sig")
        rows = list(csv.reader(StringIO(content)))
    else:
        frappe.throw("仅支持 .xlsx、.xls 或 .csv 文件。")

    header_index = next(
        (
            index
            for index, row in enumerate(rows[:20])
            if any(not _is_blank(cell) for cell in row)
        ),
        None,
    )
    if header_index is None:
        frappe.throw("导入文件中没有数据。")

    header_map = _build_header_map(rows[header_index])
    if (
        "student_name" not in header_map.values()
        and "student_id" not in header_map.values()
    ):
        frappe.throw("导入文件必须包含“学生姓名”列；更新已有学生时也可使用“学生编号”。")

    parsed_rows = []
    for index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        values = {
            fieldname: row[column] if column < len(row) else None
            for column, fieldname in header_map.items()
        }
        if any(not _is_blank(value) for value in values.values()):
            parsed_rows.append((index, values))

    if not parsed_rows:
        frappe.throw("导入文件中没有学生数据。")
    if len(parsed_rows) > MAX_IMPORT_ROWS:
        frappe.throw(f"一次最多导入 {MAX_IMPORT_ROWS} 名学生。")
    return parsed_rows


def _build_header_map(headers) -> dict[int, str]:
    aliases = {
        _normalize_header(alias): fieldname
        for fieldname, names in HEADER_ALIASES.items()
        for alias in names
    }
    header_map = {}
    used_fields = set()
    for index, header in enumerate(headers):
        fieldname = aliases.get(_normalize_header(header))
        if not fieldname:
            continue
        if fieldname in used_fields:
            frappe.throw(f"导入文件中存在重复列：{_cell_text(header)}。")
        header_map[index] = fieldname
        used_fields.add(fieldname)
    return header_map


def _get_or_create_student(values: dict, *, update_existing: bool):
    student_name = _cell_text(values.get("student_name"))
    student_id = _cell_text(values.get("student_id"))
    email = _cell_text(values.get("student_email_id"))
    mobile = _cell_text(values.get("student_mobile_number"))
    birth_date = _date_value(values.get("date_of_birth"), "出生日期")

    existing_name = None
    if student_id:
        if not frappe.db.exists("Student", student_id):
            raise ValueError(
                f"学生编号 {student_id} 不存在；新增学生请将学生编号留空。"
            )
        existing_name = student_id
    elif email:
        existing_name = frappe.db.get_value(
            "Student", {"student_email_id": email}, "name"
        )

    if not existing_name and student_name:
        filters = {"student_name": student_name}
        if birth_date:
            filters["date_of_birth"] = birth_date
        elif mobile:
            filters["student_mobile_number"] = mobile
        matches = frappe.get_list(
            "Student",
            filters=filters,
            pluck="name",
            limit_page_length=3,
        )
        if len(matches) > 1:
            raise ValueError("存在多名同名学生，请填写学生编号或出生日期。")
        if matches:
            existing_name = matches[0]

    is_new = not existing_name
    if is_new:
        if not student_name:
            raise ValueError("新增学生必须填写学生姓名。")
        student = frappe.new_doc("Student")
    else:
        student = frappe.get_doc("Student", existing_name)
        student.check_permission("write")

    if is_new or update_existing:
        if student_name:
            student.first_name = student_name
        if birth_date:
            student.date_of_birth = birth_date
        if mobile:
            student.student_mobile_number = mobile
        if email:
            student.student_email_id = email

        joining_date = _date_value(values.get("joining_date"), "入学日期")
        if joining_date:
            student.joining_date = joining_date

        gender = _gender_value(values.get("gender"))
        if gender:
            student.gender = gender

        if "enabled" in values and not _is_blank(values.get("enabled")):
            student.enabled = _check_value(values.get("enabled"))
        elif is_new:
            student.enabled = 1

        student.save()

    return student, is_new


def _get_other_group_assignments(group) -> dict[str, list[str]]:
    active_groups = frappe.get_all(
        "Student Group",
        filters={
            "academic_year": group.academic_year,
            "disabled": 0,
            "name": ["!=", group.name],
        },
        pluck="name",
    )
    if not active_groups:
        return {}

    assignments = defaultdict(list)
    for row in frappe.get_all(
        "Student Group Student",
        filters={
            "parent": ["in", active_groups],
            "parenttype": "Student Group",
            "active": 1,
        },
        fields=["student", "parent"],
    ):
        assignments[row.student].append(row.parent)
    return dict(assignments)


def _normalize_header(value) -> str:
    return re.sub(r"[\s*()（）_\-]+", "", _cell_text(value)).lower()


def _cell_text(value) -> str:
    if _is_blank(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return cstr(value).strip()


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _date_value(value, label: str):
    if _is_blank(value):
        return None
    try:
        return getdate(value)
    except Exception as exc:
        raise ValueError(f"{label}格式不正确：{_cell_text(value)}。") from exc


def _gender_value(value) -> str | None:
    raw_value = _cell_text(value)
    if not raw_value:
        return None
    aliases = {
        "男": "Male",
        "男性": "Male",
        "male": "Male",
        "女": "Female",
        "女性": "Female",
        "female": "Female",
    }
    gender = aliases.get(raw_value.lower(), raw_value)
    if not frappe.db.exists("Gender", gender):
        raise ValueError(f"系统中不存在性别：{raw_value}。")
    return gender


def _check_value(value) -> int:
    normalized = _cell_text(value).lower()
    if normalized in {"1", "是", "启用", "yes", "true", "y"}:
        return 1
    if normalized in {"0", "否", "停用", "no", "false", "n"}:
        return 0
    raise ValueError(f"启用列的值无法识别：{_cell_text(value)}。")
