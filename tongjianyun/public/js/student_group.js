frappe.ui.form.on('Student Group', {
  onload(frm) {
    set_direct_student_query(frm)
  },

  refresh(frm) {
    set_direct_student_query(frm)
  },
})

function set_direct_student_query(frm) {
  frm.set_query('student', 'students', () => ({
    query: 'tongjianyun.education_integration.fetch_students_for_group',
    filters: {
      student_group: frm.doc.name,
    },
  }))
}
