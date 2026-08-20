frappe.ui.form.on('Student Group', {
  onload(frm) {
    set_direct_student_query(frm)
  },

  refresh(frm) {
    set_direct_student_query(frm)
    add_student_import_button(frm)
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

function add_student_import_button(frm) {
  if (frm.is_new() || frm.doc.disabled || !frm.perm[0]?.write) {
    return
  }

  frm.add_custom_button('导入学生', () => show_student_import_dialog(frm))
}

function show_student_import_dialog(frm) {
  const group_name = frm.doc.student_group_name || frm.doc.name
  const template_url =
    '/api/method/tongjianyun.student_group_import.download_student_import_template' +
    `?student_group=${encodeURIComponent(frm.doc.name)}`

  const dialog = new frappe.ui.Dialog({
    title: `导入学生到“${group_name}”`,
    fields: [
      {
        fieldtype: 'HTML',
        options: `
          <div class="mb-3 text-muted">
            本次文件中的学生将统一加入 <strong>${frappe.utils.escape_html(group_name)}</strong>。
            <a class="ml-2" href="${template_url}" target="_blank">下载导入模板</a>
          </div>`,
      },
      {
        fieldname: 'file_url',
        fieldtype: 'Attach',
        label: '学生文件',
        reqd: 1,
        description: '支持 .xlsx、.xls 和 .csv；新增学生至少填写“学生姓名”。',
      },
      {
        fieldname: 'update_existing',
        fieldtype: 'Check',
        label: '更新已存在的学生档案',
        default: 1,
      },
      {
        fieldname: 'allow_transfer',
        fieldtype: 'Check',
        label: '允许从同学年其他班级转入',
        description: '未勾选时，已在其他班级的学生会作为冲突行跳过。',
        default: 0,
      },
    ],
    primary_action_label: '开始导入',
    async primary_action(values) {
      dialog.disable_primary_action()
      try {
        const response = await frappe.call({
          method: 'tongjianyun.student_group_import.import_students_to_group',
          args: {
            student_group: frm.doc.name,
            file_url: values.file_url,
            update_existing: values.update_existing,
            allow_transfer: values.allow_transfer,
          },
          freeze: true,
          freeze_message: '正在导入学生…',
        })
        dialog.hide()
        await frm.reload_doc()
        show_student_import_result(response.message || {})
      } finally {
        dialog.enable_primary_action()
      }
    },
  })

  dialog.show()
}

function show_student_import_result(result) {
  const errors = result.errors || []
  const summary = `
    <div class="mb-3">
      共处理 ${result.total_rows || 0} 行；
      新建档案 ${result.created || 0} 个，更新档案 ${result.updated || 0} 个，
      加入班级 ${result.added_to_group || 0} 人，已在本班 ${result.already_in_group || 0} 人，
      转班 ${result.transferred || 0} 人，失败 ${errors.length} 行。
    </div>`

  let error_table = ''
  if (errors.length) {
    const rows = errors
      .slice(0, 100)
      .map(
        (error) => `
          <tr>
            <td>${frappe.utils.escape_html(String(error.row || ''))}</td>
            <td>${frappe.utils.escape_html(error.student_name || '')}</td>
            <td>${frappe.utils.escape_html(error.message || '')}</td>
          </tr>`
      )
      .join('')
    error_table = `
      <div class="text-danger mb-2">以下行未导入：</div>
      <div style="max-height: 320px; overflow: auto;">
        <table class="table table-bordered table-sm">
          <thead><tr><th>Excel 行号</th><th>学生姓名</th><th>原因</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`
  }

  frappe.msgprint({
    title: errors.length ? '学生导入完成（部分数据需处理）' : '学生导入完成',
    indicator: errors.length ? 'orange' : 'green',
    message: summary + error_table,
    wide: Boolean(errors.length),
  })
}
