import frappe

MANAGER_ROLES = {"System Manager", "I-ONE Manager", "I-ONE Auditor"}
OPERATOR_ROLES = MANAGER_ROLES | {"I-ONE AI Operator"}


def _is_manager(user=None):
	user = user or frappe.session.user
	return bool(MANAGER_ROLES.intersection(frappe.get_roles(user)))


def _is_operator(user=None):
	user = user or frappe.session.user
	return bool(OPERATOR_ROLES.intersection(frappe.get_roles(user)))


def _escape(value):
	return frappe.db.escape(value)


def owner_query(user=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return ""
	return f"`owner` = {_escape(user)}"


def owner_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return True
	return doc.owner == user


def owner_user_query(user=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return ""
	return f"`owner_user` = {_escape(user)}"


def owner_user_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return True
	return doc.owner_user == user or doc.owner == user


def approval_query(user=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return ""
	user_sql = _escape(user)
	return f"(`owner` = {user_sql} or `requested_by` = {user_sql} or `approver` = {user_sql})"


def approval_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return True
	return user in {doc.owner, doc.requested_by, doc.approver}


def experience_query(user=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return ""
	return f"(`status` = '已发布' or `owner` = {_escape(user)} or `author_user` = {_escape(user)})"


def experience_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return True
	if permission_type == "read" and doc.status == "已发布":
		return True
	return user in {doc.owner, doc.author_user}


def achievement_query(user=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return ""
	return f"`user` = {_escape(user)}"


def achievement_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return True
	return permission_type == "read" and doc.user == user


def user_query(user=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return ""
	return f"`user` = {_escape(user)}"


def user_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if _is_operator(user):
		return True
	return doc.user == user
