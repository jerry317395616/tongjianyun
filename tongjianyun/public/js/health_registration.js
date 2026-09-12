window.tjyOpenHealthRegistration = function () {
    const esc = v => frappe.utils.escape_html(String(v ?? ''));
    let rows = [], group = '', month = '', generation = 0;
    const call = async (method, args) => (await frappe.call({method: 'tongjianyun.health_registration.' + method, args})).message;
    const d = new frappe.ui.Dialog({title: '幼儿健康登记', size: 'extra-large', fields: [
        {fieldtype:'HTML', options:'<p>只登记已获授权的健康资料；空白不代表无病史、无过敏。上月资料可沿用，但必须重新核对。当前仅开放给健康管理人员。</p>'},
        {fieldtype:'Link', fieldname:'group', label:'班级', options:'Student Group', reqd:1},
        {fieldtype:'Date', fieldname:'month', label:'月份（选择该月任意一天）', default:frappe.datetime.get_today(), reqd:1},
        {fieldtype:'Button', fieldname:'load', label:'查看本月登记', click:load},
        {fieldtype:'Button', fieldname:'print', label:'打印当前月份', click:print},
        {fieldtype:'HTML', fieldname:'rows'}
    ]});
    const box = () => d.fields_dict.rows.$wrapper;
    const display = (r, state, text) => r[state] === '已登记' || r[state] === '待核实' ? `${r[state]}：${r[text] || ''}` : r[state] || '未登记';
    const phone = p => p ? String(p).replace(/.(?=.{4})/g, '*') : '未登记';
    function table(printing=false) {
        return '<table class="table table-bordered"><thead><tr><th>姓名</th><th>性别</th><th>既往病史</th><th>过敏史</th><th>电话（脱敏）</th><th>状态</th>' + (printing?'':'<th>操作</th>') + '</tr></thead><tbody>' + rows.map((r,i) => `<tr><td>${esc(r.student_name)}</td><td>${esc(r.gender)}</td><td>${esc(display(r,'history_state','medical_history'))}</td><td>${esc(display(r,'allergy_state','allergy_history'))}</td><td>${esc(phone(r.contact_phone))}</td><td>${esc(r.inherited?'沿用上月·待核对':r.review_status)}</td>${printing?'':`<td><button type="button" class="btn btn-xs btn-default" data-health-row="${i}">核对 / 修改</button></td>`}</tr>`).join('') + '</tbody></table>';
    }
    async function load() {
        const values = d.get_values();
        if (!values) return;
        const request = ++generation;
        rows = []; box().text('正在读取…');
        try {
            const result = await call('roster', {group:values.group, month:values.month});
            if (request !== generation) return;
            group = values.group; month = result.month; rows = result.rows;
            box().html(`<p>${esc(group)} · ${esc(month.slice(0,7))} · ${rows.length} 人</p>` + table());
            box().find('[data-health-row]').on('click', function() { edit(rows[Number(this.dataset.healthRow)]); });
        } catch(e) { box().text('读取失败，请检查权限后重试。'); }
    }
    function edit(r) {
        const states = '未登记\n明确无\n已登记\n待核实';
        const editor = new frappe.ui.Dialog({title: '核对：' + r.student_name, fields: [
            {fieldtype:'Select',fieldname:'history_state',label:'既往病史状态',options:states,default:r.history_state || '未登记',reqd:1},
            {fieldtype:'Small Text',fieldname:'medical_history',label:'既往病史原始说明',default:r.medical_history || ''},
            {fieldtype:'Select',fieldname:'allergy_state',label:'过敏史状态',options:states,default:r.allergy_state || '未登记',reqd:1},
            {fieldtype:'Small Text',fieldname:'allergy_history',label:'过敏史原始说明',default:r.allergy_history || ''},
            {fieldtype:'Data',fieldname:'contact_phone',label:'联系电话（请核对）',default:r.contact_phone || ''},
            {fieldtype:'Small Text',fieldname:'information_source',label:'信息来源（如家长确认）',default:r.information_source || ''},
            {fieldtype:'Select',fieldname:'review_status',label:'核对状态',options:'待核对\n已核对',default:r.review_status || '待核对'},
            {fieldtype:'Small Text',fieldname:'change_reason',label:'修改已核对资料的原因'}
        ], primary_action_label:'保存本月登记', primary_action:async values => {
            editor.get_primary_btn().prop('disabled',true);
            try {
                await call('save_registration', {payload:JSON.stringify({...values,student:r.student,student_group:group,month,modified:r.modified})});
                editor.hide(); await load();
            } finally { editor.get_primary_btn().prop('disabled',false); }
        }});
        editor.show();
    }
    function print() {
        if (!rows.length) return frappe.msgprint('请先查看需要打印的月份');
        const w = window.open('', '_blank');
        if (!w) return frappe.msgprint('请允许浏览器打开打印窗口');
        w.opener = null;
        w.document.write('<!doctype html><html lang="zh"><meta charset="utf-8"><title>幼儿健康登记</title><style>body{font:14px sans-serif;padding:24px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #777;padding:8px;word-break:break-word}thead{display:table-header-group}</style><h2>幼儿健康登记表</h2><p>' + esc(group) + ' · ' + esc(month.slice(0,7)) + '</p>' + table(true) + '<p>沿用资料未经本月核对不视为已确认。请妥善保管本表。</p></html>');
        w.document.close(); w.focus(); w.print();
    }
    d.show();
};
