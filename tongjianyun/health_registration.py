"""Monthly health declarations: unknown is never equivalent to explicitly none."""
import hashlib
import frappe
from frappe.utils import getdate, now_datetime

DOCTYPE = 'Tongjianyun Student Health'
ROLE = 'Tongjianyun Health Manager'
STATES = ('未登记', '明确无', '已登记', '待核实')

def access():
    user = frappe.session.user
    if user == 'Guest' or not frappe.db.get_value('User', user, 'enabled'):
        raise frappe.PermissionError('请使用已启用的健康管理账号')
    if user != 'Administrator' and ROLE not in frappe.get_roles(user):
        raise frappe.PermissionError('需要专属健康管理权限')

def month_date(value):
    if not value:
        frappe.throw('请选择月份')
    return getdate(value).replace(day=1)

def record_name(student, month):
    return 'HEALTH-' + hashlib.sha256((student + '|' + str(month_date(month))).encode()).hexdigest()[:24]

def validate_declaration(doc):
    if doc.get('review_status') not in ('待核对', '已核对'):
        frappe.throw('核对状态无效')
    for state_key, text_key in [('history_state', 'medical_history'), ('allergy_state', 'allergy_history')]:
        state = doc.get(state_key)
        value = str(doc.get(text_key) or '').strip()
        if state not in STATES:
            frappe.throw('健康登记状态无效')
        if state == '明确无' and value:
            frappe.throw('明确无不能同时填写病史或过敏内容')
        if state == '已登记' and not value:
            frappe.throw('已登记必须填写原始说明')
    if doc.get('review_status') == '已核对':
        if any(doc.get(k) not in ('明确无', '已登记') for k in ('history_state', 'allergy_state')):
            frappe.throw('未登记或待核实的资料不能标为已核对')
        if not str(doc.get('information_source') or '').strip():
            frappe.throw('请填写信息来源，例如家长确认')

def validate(doc):
    access()
    doc.month = month_date(doc.month)
    old = doc.get_doc_before_save()
    if old and any(str(old.get(k)) != str(doc.get(k)) for k in ('student', 'student_group', 'month')):
        frappe.throw('不能更改历史记录的学生、班级或月份')
    if old and old.review_status == '已核对' and not str(doc.change_reason or '').strip():
        frappe.throw('修改已核对资料需填写原因')
    student = frappe.get_doc('Student', doc.student)
    student.check_permission('read')
    group = frappe.get_doc('Student Group', doc.student_group)
    group.check_permission('read')
    if not old and not any(r.student == student.name and r.active for r in group.students):
        frappe.throw('学生不在该班级的启用名单中')
    if not old:
        doc.student_name = student.student_name
        doc.gender = student.gender
    else:
        doc.student_name = old.student_name
        doc.gender = old.gender
    validate_declaration(doc)
    if doc.review_status == '已核对':
        doc.confirmed_by = frappe.session.user
        doc.confirmed_at = now_datetime()
    else:
        doc.confirmed_by = None
        doc.confirmed_at = None

@frappe.whitelist()
def roster(group, month):
    access()
    month = month_date(month)
    doc = frappe.get_doc('Student Group', group)
    doc.check_permission('read')
    current = {r.student: r for r in frappe.get_list(DOCTYPE, filters={'student_group': group, 'month': month}, fields=['*'], limit_page_length=0)}
    students = {r.student: r.student_name for r in doc.students if r.active}
    students.update({r.student: r.student_name for r in current.values()})
    rows = []
    for student, name in students.items():
        if student in current:
            row = dict(current[student])
            row['inherited'] = False
        else:
            sd = frappe.get_doc('Student', student)
            sd.check_permission('read')
            if not sd.enabled:
                continue
            previous = frappe.get_list(DOCTYPE, filters={'student': student, 'month': ['<', month]}, fields=['*'], order_by='month desc', limit_page_length=1)
            row = {k: previous[0].get(k) for k in ('history_state', 'medical_history', 'allergy_state', 'allergy_history', 'contact_phone', 'information_source')} if previous else {}
            row.update(student=student, student_name=name, gender=sd.gender, name=None, modified=None, review_status='待核对', inherited=bool(previous))
        row.setdefault('history_state', '未登记')
        row.setdefault('allergy_state', '未登记')
        rows.append(row)
    return {'month': str(month), 'rows': rows}

@frappe.whitelist(methods=['POST'])
def save_registration(payload):
    access()
    data = frappe.parse_json(payload)
    if not isinstance(data, dict):
        frappe.throw('登记数据无效')
    name = record_name(data.get('student', ''), data.get('month'))
    if frappe.db.exists(DOCTYPE, name):
        doc = frappe.get_doc(DOCTYPE, name)
        doc.check_permission('write')
        if str(doc.modified) != str(data.get('modified')):
            frappe.throw('资料已变化，请刷新后重新核对')
    else:
        doc = frappe.new_doc(DOCTYPE)
        doc.student = data.get('student')
        doc.student_group = data.get('student_group')
        doc.month = month_date(data.get('month'))
    for key in ('history_state', 'medical_history', 'allergy_state', 'allergy_history', 'contact_phone', 'information_source', 'review_status', 'change_reason'):
        doc.set(key, data.get(key))
    doc.save()
    return {'name': doc.name, 'modified': str(doc.modified)}
