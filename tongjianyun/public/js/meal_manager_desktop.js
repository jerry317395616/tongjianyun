// The role is decided in the server boot hook. Frappe's Desktop Icons renderer
// can replay an old per-user layout, so use its Apps renderer for this role.
if (window.frappe?.boot?.tongjianyun_meal_manager === true) {
    frappe.boot.desktop_page = "Apps";
}
