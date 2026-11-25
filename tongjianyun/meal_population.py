"""Private education roster helpers for meal planning; no public student identifiers.

The normal read path uses only current Education documents. Legacy tables are
read exclusively by the explicit, one-time migration helper. Callers own the
transaction and must authorize their enclosing operation; nothing is whitelisted.
"""

# ruff: noqa: RUF001
import datetime as dt
import hashlib
import json

import frappe

STUDENT_BATCH_FIELD = "custom_student_batch"
STUDENT_BATCH_CUSTOM_FIELD = {
	"dt": "Student",
	"fieldname": STUDENT_BATCH_FIELD,
	"label": "在读班级",
	"fieldtype": "Link",
	"options": "Student Batch Name",
	"insert_after": "enabled",
	"in_list_view": 1,
	"in_standard_filter": 1,
	"description": "教育管理当前归班；食谱按有效在册学生计算预计人数，实际就餐须另行确认。",
}


def _fail(message, permission=False):
	frappe.throw(message, frappe.PermissionError if permission else frappe.ValidationError)


def _date(value, label):
	if isinstance(value, dt.datetime):
		return value.date()
	if isinstance(value, dt.date):
		return value
	try:
		return dt.date.fromisoformat(str(value))
	except TypeError, ValueError:
		_fail(f"{label}必须为有效日期。")


def _flag(value):
	return value is True or value == 1 or value == "1"


def _rows(doctype, fields):
	return [dict(row) for row in frappe.get_all(doctype, fields=fields, limit_page_length=0)]


def _unique(rows, label):
	result = {}
	for row in rows:
		name = row.get("name")
		if not name or name in result:
			_fail(f"{label}存在空标识或重复记录，请先核对教育资料。")
		result[name] = row
	return result


def _company(company):
	if not isinstance(company, str) or not company.strip():
		_fail("请明确选择供餐公司。")
	companies = _rows("Company", ["name"])
	if company not in _unique(companies, "公司"):
		_fail("供餐公司不存在。")
	return companies


def _period(company, meal_date, academic_year=None, academic_term=None):
	years = _rows("Academic Year", ["name", "year_start_date", "year_end_date", "company"])
	terms = _rows("Academic Term", ["name", "academic_year", "term_start_date", "term_end_date", "company"])
	_unique(years, "学年")
	_unique(terms, "学期")

	def includes(row, start, end):
		return (
			row.get(start)
			and row.get(end)
			and _date(row[start], "学年学期开始日期") <= meal_date <= _date(row[end], "学年学期结束日期")
		)

	def company_matches(row):
		return not row.get("company") or row["company"] == company

	years = [
		row
		for row in years
		if (not academic_year or row["name"] == academic_year)
		and company_matches(row)
		and includes(row, "year_start_date", "year_end_date")
	]
	if len(years) != 1:
		_fail("供餐日期必须唯一对应一个有效学年，请核对日期、公司和学年。")
	year = years[0]
	terms = [
		row
		for row in terms
		if (not academic_term or row["name"] == academic_term)
		and row.get("academic_year") == year["name"]
		and company_matches(row)
		and includes(row, "term_start_date", "term_end_date")
	]
	if len(terms) != 1:
		_fail("供餐日期必须唯一对应所选学年的一个有效学期，请核对教育学期。")
	return year, terms[0]


def _students(lock=False, require_batch=True):
	has_field = frappe.get_meta("Student").has_field(STUDENT_BATCH_FIELD)
	if require_batch and not has_field:
		_fail("教育学生尚未配置在读班级字段，请先完成归班迁移。")
	fields = ["name", "enabled", "alumni", "docstatus", "joining_date", "date_of_leaving"]
	if has_field:
		fields.append(STUDENT_BATCH_FIELD)
	if lock:
		# Fixed, module-owned field names; no user-controlled SQL identifiers.
		return [
			dict(row)
			for row in frappe.db.sql(
				"SELECT "
				+ ",".join(f"`{field}`" for field in fields)
				+ " FROM tabStudent ORDER BY name FOR UPDATE",
				as_dict=True,
			)
		]
	return _rows("Student", fields)


def _batches(lock=False):
	fields = ["name", "company", "disabled", "start_date", "end_date"]
	if lock:
		return [
			dict(row)
			for row in frappe.db.sql(
				"SELECT name,company,disabled,start_date,end_date "
				"FROM `tabStudent Batch Name` ORDER BY name FOR UPDATE",
				as_dict=True,
			)
		]
	return _rows("Student Batch Name", fields)


def _active(student, meal_date):
	if not _flag(student.get("enabled")) or _flag(student.get("alumni")) or student.get("docstatus") == 2:
		return False
	joining = _date(student["joining_date"], "学生入园日期") if student.get("joining_date") else None
	leaving = _date(student["date_of_leaving"], "学生离园日期") if student.get("date_of_leaving") else None
	if joining and leaving and leaving < joining:
		_fail("学生入退园日期存在倒置，请先核对教育资料。")
	# Leaving date is the first day no longer enrolled.
	return (not joining or joining <= meal_date) and (not leaving or leaving > meal_date)


def _build_snapshot(company, meal_date, year, term, students, batches):
	student_map = _unique(students, "学生")
	batch_map = _unique(batches, "班级")
	classes = {}
	roster = []
	for student in student_map.values():
		if not _active(student, meal_date):
			continue
		batch_name = student.get(STUDENT_BATCH_FIELD)
		if not batch_name or batch_name not in batch_map:
			_fail("有效在册学生存在缺班或无效班级链接，无法可靠区分公司，请先完善教育归班。")
		batch = batch_map[batch_name]
		if not batch.get("company"):
			_fail("在册学生关联班级尚未明确公司，无法可靠计算供餐人数。")
		if batch["company"] != company:
			continue
		if _flag(batch.get("disabled")):
			_fail("有效在册学生仍关联已停用班级，请先核对归班。")
		start = _date(batch["start_date"], "班级开始日期") if batch.get("start_date") else None
		end = _date(batch["end_date"], "班级结束日期") if batch.get("end_date") else None
		if start and end and end < start:
			_fail("班级起止日期存在倒置，请先核对教育资料。")
		if (start and meal_date < start) or (end and meal_date > end):
			_fail("有效在册学生关联班级在供餐日尚未开始或已经结束，请核对归班。")
		classes[batch_name] = classes.get(batch_name, 0) + 1
		roster.append((student["name"], batch_name))
	if not roster:
		_fail("所选公司和日期没有有效在册学生，不能生成零人数食谱。")
	fingerprint = json.dumps(
		[company, meal_date.isoformat(), year["name"], term["name"], sorted(roster)],
		ensure_ascii=False,
		separators=(",", ":"),
	)
	return {
		"total": len(roster),
		"classes": [{"student_batch": name, "count": classes[name]} for name in sorted(classes)],
		"roster_hash": hashlib.sha256(fingerprint.encode()).hexdigest(),
		"as_of": dt.datetime.now(dt.UTC).isoformat(),
		"basis": "教育学生在册预计人数（非实际出勤或就餐确认）",
		"academic_year": year["name"],
		"academic_term": term["name"],
	}


def get_population_snapshot(company, meal_date, academic_year=None, academic_term=None):
	"""Return aggregate expected enrollment only; never read legacy group tables."""
	_company(company)
	meal_date = _date(meal_date, "供餐日期")
	year, term = _period(company, meal_date, academic_year, academic_term)
	return _build_snapshot(company, meal_date, year, term, _students(), _batches())


def _legacy_mapping(students, batches, groups, members, academic_year, academic_term):
	student_map = _unique(students, "学生")
	batch_map = _unique(batches, "班级")
	group_map = _unique(groups, "旧班级")
	selected = {
		name: row
		for name, row in group_map.items()
		if row.get("academic_year") == academic_year
		and row.get("academic_term") == academic_term
		and not _flag(row.get("disabled"))
		and row.get("docstatus") != 2
	}
	if not selected:
		_fail("指定学年学期没有可核验的旧班级，归班迁移已停止。")
	targets = {}
	for name, row in selected.items():
		target = row.get("batch") or name
		if target not in batch_map or _flag(batch_map[target].get("disabled")):
			_fail("旧班级没有唯一对应的现行启用班级，归班迁移已停止。")
		if target in targets.values():
			_fail("多个旧班级指向同一现行班级，归班迁移已停止。")
		targets[name] = target
	mapping = {}
	for member in members:
		if not _flag(member.get("active")):
			continue
		parent = member.get("parent")
		if parent not in group_map or member.get("parenttype") != "Student Group":
			_fail("旧归班关系存在孤儿或错误父记录，归班迁移已停止。")
		if parent not in selected:
			continue
		student = member.get("student")
		if student not in student_map or student in mapping:
			_fail("旧归班关系存在孤儿学生或重复归班，归班迁移已停止。")
		target = targets[parent]
		current = student_map[student].get(STUDENT_BATCH_FIELD)
		if current and current != target:
			_fail("现行学生归班与旧关系冲突，迁移只填空字段，不覆盖已有归班。")
		mapping[student] = target
	if not mapping:
		_fail("旧班级没有可迁移学生，归班迁移已停止。")
	return mapping, targets, selected


def migrate_legacy_student_batches(company, academic_year, academic_term, dry_run=True):
	"""One-time migration, default read-only; caller must commit explicitly.

	Writing requires System Manager and an actual boolean False. Validate the
	entire source before writing; use a savepoint so failures never leave a
	partially applied batch in the caller's transaction.
	"""
	if not isinstance(dry_run, bool):
		_fail("dry_run 必须是明确的布尔值，默认仅检查不写入。")
	if not dry_run and "System Manager" not in frappe.get_roles():
		_fail("只有系统管理员可以执行一次性学生归班迁移。", permission=True)
	companies = _company(company)
	years = _unique(_rows("Academic Year", ["name", "company", "year_start_date", "year_end_date"]), "学年")
	terms = _unique(
		_rows("Academic Term", ["name", "academic_year", "company", "term_start_date", "term_end_date"]),
		"学期",
	)
	if (
		academic_year not in years
		or academic_term not in terms
		or terms[academic_term].get("academic_year") != academic_year
	):
		_fail("归班迁移的学年学期不匹配。")
	# Validate the selected period without assuming it is today's academic term.
	reference_date = _date(terms[academic_term].get("term_start_date"), "学期开始日期")
	year, term = _period(company, reference_date, academic_year, academic_term)
	students = _students(lock=not dry_run, require_batch=not dry_run)
	batches = _batches(lock=not dry_run)
	for doctype in ("Student Group", "Student Group Student"):
		if not frappe.db.table_exists(doctype):
			_fail("旧教育归班来源表不存在，迁移已停止；正常人数查询无需这些表。")
	groups = [
		dict(row)
		for row in frappe.db.sql(
			"SELECT name,disabled,docstatus,academic_year,academic_term,batch,program FROM `tabStudent Group`",
			as_dict=True,
		)
	]
	members = [
		dict(row)
		for row in frappe.db.sql(
			"SELECT student,active,parent,parenttype FROM `tabStudent Group Student`", as_dict=True
		)
	]
	mapping, targets, selected = _legacy_mapping(
		students, batches, groups, members, academic_year, academic_term
	)
	batch_map = _unique(batches, "班级")
	programs = _unique(_rows("Program", ["name", "company"]), "教育项目")
	period_companies = {row["company"] for row in (year, term) if row.get("company")}
	sole_company = {row["name"] for row in companies} == {company}
	all_groups_declared = True
	for group_name, group in selected.items():
		declared_companies = set(period_companies)
		program = group.get("program")
		if program and program not in programs:
			_fail("旧班级关联教育项目不存在，无法核实公司归属。")
		if program and programs[program].get("company"):
			declared_companies.add(programs[program]["company"])
		target = targets[group_name]
		if batch_map[target].get("company"):
			declared_companies.add(batch_map[target]["company"])
		if declared_companies - {company}:
			_fail("学年学期、项目或班级存在跨公司归属冲突，迁移已停止。")
		if not declared_companies:
			all_groups_declared = False
			if not sole_company:
				_fail("多公司站点的旧教育来源未明确公司，不允许推断归属。")
	proof = "education_company_links" if all_groups_declared else "single_company_site"
	student_updates = []
	batch_updates = [name for name in sorted(targets.values()) if not batch_map[name].get("company")]
	for student in students:
		if student["name"] in mapping and not student.get(STUDENT_BATCH_FIELD):
			student_updates.append((student["name"], mapping[student["name"]]))
		if student["name"] in mapping:
			student[STUDENT_BATCH_FIELD] = mapping[student["name"]]
	for name in batch_updates:
		batch_map[name]["company"] = company
	# Missing/currently ambiguous students fail before the first write. This is a
	# term-start enrollment baseline, not a historical attendance reconstruction.
	snapshot = _build_snapshot(company, reference_date, year, term, students, list(batch_map.values()))
	result = {
		"dry_run": dry_run,
		"company": company,
		"academic_year": academic_year,
		"academic_term": academic_term,
		"mapped_students": len(mapping),
		"student_fields_to_fill": len(student_updates),
		"batch_companies_to_fill": len(batch_updates),
		"classes": snapshot["classes"],
		"company_basis": proof,
	}
	if dry_run:
		return result
	savepoint = "meal_student_batch_migration"
	frappe.db.savepoint(savepoint)
	try:
		for name in batch_updates:
			frappe.db.set_value("Student Batch Name", name, "company", company)
		for name, batch in student_updates:
			frappe.db.set_value("Student", name, STUDENT_BATCH_FIELD, batch)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return result
