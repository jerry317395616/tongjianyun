frappe.pages["teacher-video-attendance"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: "教师视频考勤", single_column: true });
  const api = "tongjianyun.video_attendance.api.";
  const esc = (v) => frappe.utils.escape_html(String(v ?? ""));
  const manager = frappe.session.user === "Administrator" || frappe.user_roles.includes("System Manager");
  const $body = $('<div class="tjy-video"></div>').appendTo(page.main);
  let busy = false;
  let date;
  date = page.add_field({ fieldtype: "Date", fieldname: "day", label: "日期", default: frappe.datetime.get_today(), change: () => { if (date) refresh(); } });
  page.set_primary_action("刷新", () => refresh(), "refresh");
  page.add_inner_button("业务工作台", () => frappe.set_route("tongjianyun-workbench"));
  if (manager) {
    page.add_inner_button("下载采集程序", () => window.open("/assets/tongjianyun/downloads/tongjianyun-video-collector-20260916-v1.zip", "_blank", "noopener"));
    page.add_inner_button("设备设置", () => frappe.set_route("List", "Tongjianyun Video Device"));
    page.add_inner_button("注册教师", () => enroll());
  }
  const call = async (method, args = {}) => (await frappe.call({ method: api + method, args })).message;
  const labels = { Uploading: "上传中", Queued: "待分析", Processing: "分析中", "Needs Setup": "待配置",
    Review: "待核实", "No Match": "无可靠匹配", Failed: "处理失败", Expired: "已过期", Approved: "已核实", Rejected: "已排除" };
  function table(headers, rows) {
    return `<div class="tjy-table"><table><thead><tr>${headers.map(x => `<th>${esc(x)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}" class="text-muted">暂无记录</td></tr>`}</tbody></table></div>`;
  }
  async function refresh() {
    if (busy) return;
    busy = true;
    try {
      if (!manager) {
        const rows = await call("my_checkins", { day: date.get_value() });
        $body.html(`<div class="tjy-notice">这里只显示本人已记录的打卡。视频未拍到不代表缺勤；如需补卡，请使用 HRMS 考勤申请。</div>` +
          table(["时间", "方向", "状态"], rows.map(r => [esc(r.time), esc(r.log_type === "IN" ? "签到" : "签退"), esc(r.skip_auto_attendance ? "待考勤核验" : "已进入考勤处理")])));
        return;
      }
      const data = await call("overview", { day: date.get_value() });
      $body.html(`<div class="tjy-notice"><strong>试运行 · 人工核实模式</strong><p>连续采集 → 分段上传 → 视频分析 → 核实候选 → 员工打卡。当前不自动认定缺勤、不影响工资。识别分数不是正确率；单目视频尚未验证活体。</p></div>
        <div class="tjy-cards"><div><span>已登记设备</span><b>${data.devices.length}</b></div><div><span>在线设备</span><b>${data.devices.filter(d => d.online).length}</b></div><div><span>已授权教师档案</span><b>${data.profiles.filter(p => p.active && p.consent).length}</b></div><div><span>当天视频片段</span><b>${data.batch_total}</b></div></div>
        <h4>采集设备</h4>` + table(["点位", "方向", "连接", "采集状态", "待上传", "最后心跳"], data.devices.map(d => [esc(d.title || d.name), esc(d.direction), esc(d.online ? "在线" : "未连接 / 离线"), esc(d.health || "尚未安装采集程序"), esc(d.pending), esc(d.last_seen)])) +
        `<h4>识别候选 <small>共 ${data.event_total} 条，显示最近 200 条；没有候选不代表缺勤</small></h4>` + table(["教师编号", "拍摄时间", "配置方向", "状态", "操作"], data.events.map(e => [esc(e.employee), esc(e.occurred_at), esc(e.log_type), esc(labels[e.status] || e.status), e.status === "Review" ? `<button class="btn btn-xs btn-default" data-review="${esc(e.name)}">核实</button> <button class="btn btn-xs btn-default" data-video="${esc(e.batch)}">查看视频</button>` : esc(e.checkin || "—")])) +
        `<h4>上传与分析进度 <small>共 ${data.batch_total} 段，显示最近 100 段</small></h4>` + table(["拍摄时间", "设备", "进度", "说明", "操作"], data.batches.map(b => [esc(b.started_at), esc(b.camera), esc(labels[b.status] || b.status) + (b.status === "Uploading" ? ` ${Math.floor(100 * b.received / b.size)}%` : ""), esc(b.detail), ["Failed", "Needs Setup"].includes(b.status) && !b.video_deleted ? `<button class="btn btn-xs btn-default" data-retry="${esc(b.name)}">重试</button>` : "—"])) +
        `<h4>教师识别授权</h4>` + table(["员工编号", "授权状态", "操作"], data.profiles.map(p => [esc(p.employee), esc(p.active && p.consent ? "已启用" : "已停用"), p.active ? `<button class="btn btn-xs btn-default" data-revoke="${esc(p.name)}">撤回并删除模板</button>` : "—"])));
      $body.find("[data-retry]").on("click", async function () { await call("retry_batch", { batch: this.dataset.retry }); refresh(); });
      $body.find("[data-review]").on("click", function () { review(this.dataset.review); });
      $body.find("[data-video]").on("click", function () { window.open(`/api/method/${api}download_video?batch=${encodeURIComponent(this.dataset.video)}`, "_blank", "noopener"); });
      $body.find("[data-revoke]").on("click", function () { const profile = this.dataset.revoke; frappe.confirm("停止识别并删除当前模板？历史考勤不会删除。", async () => { await call("revoke_profile", { profile }); refresh(); }); });
    } finally { busy = false; }
  }
  function review(event) {
    const dialog = new frappe.ui.Dialog({ title: "核实视频考勤候选", fields: [
      { fieldtype: "HTML", options: "<p>请核对视频中的本人、日期及进出方向。批准后仅生成待考勤核验的员工打卡，不自动生成出勤或工资。</p>" },
      { fieldtype: "Select", fieldname: "action", label: "处理", options: "批准\n排除", default: "排除", reqd: 1 },
      { fieldtype: "Small Text", fieldname: "reason", label: "核实说明", reqd: 1 },
      { fieldtype: "Check", fieldname: "confirmed", label: "我已核实实际本人、拍摄时间和进出方向" }
    ], primary_action_label: "保存核实结果", primary_action: async (values) => {
      dialog.get_primary_btn().prop("disabled", true);
      try { await call("review_event", { event, ...values, action: values.action === "批准" ? "approve" : "reject" }); dialog.hide(); refresh(); }
      finally { dialog.get_primary_btn().prop("disabled", false); }
    }});
    dialog.show();
  }
  function enroll() {
    const dialog = new frappe.ui.Dialog({ title: "注册教师识别档案", fields: [
      { fieldtype: "Link", fieldname: "employee", label: "在职员工", options: "Employee", reqd: 1, get_query: () => ({ filters: { status: "Active" } }) },
      { fieldtype: "HTML", fieldname: "photo", options: '<p>请选择一张仅含该教师清晰正脸的照片（小于 4 MB）。原图用于生成模板后即删除。</p><input type="file" accept="image/jpeg,image/png" class="tjy-enroll-file">' },
      { fieldtype: "Small Text", fieldname: "consent_note", label: "授权记录编号、日期及说明", reqd: 1 },
      { fieldtype: "Check", fieldname: "confirmed", label: "已取得本人对识别及远端处理的单独同意，并提供非刷脸方式", reqd: 1 }
    ], primary_action_label: "生成识别模板", primary_action: async (values) => {
      const file = dialog.$wrapper.find(".tjy-enroll-file")[0].files[0];
      if (!file || file.size > 4 * 1024 * 1024) return frappe.msgprint("请选择小于 4 MB 的清晰照片");
      dialog.get_primary_btn().prop("disabled", true);
      try {
        const encoded = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(",")[1]); reader.onerror = reject; reader.readAsDataURL(file); });
        await call("enroll", { ...values, image_base64: encoded }); dialog.hide(); refresh();
      } finally { dialog.get_primary_btn().prop("disabled", false); }
    }});
    dialog.show();
  }
  wrapper.video_refresh = refresh;
  wrapper.video_timer = setInterval(() => { if (frappe.get_route()[0] === "teacher-video-attendance" && !document.hidden) refresh().catch(() => {}); }, 15000);
};
frappe.pages["teacher-video-attendance"].on_page_show = function (wrapper) { wrapper.video_refresh?.(); };
