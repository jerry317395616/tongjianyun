import {OBJECTS, objectFor, PAGE_SIZE, workRoute, objectBadge, visibleSelection} from './objects.js?v=teacher-entry-20260923-1';
import {STATUS, COLORS, MEALS, LOG_TYPES, esc as h, mealSelections, mealTotals, timeLabel, hash, attendanceChanges} from './state.js?v=teacher-entry-20260923-1';

const $ = id => document.getElementById(id);
const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const dialog = $('business-dialog');
const desk = (type, name = '', filters = {}) => `/desk/${type}${name ? '/' + encodeURIComponent(name) : ''}${Object.keys(filters).length ? '?' + new URLSearchParams(filters) : ''}`;
let data = null, scene = null, sequence = 0, dialogSequence = 0, writing = false, dirty = false, ready = false, currentView = 'room';
let toastTimer, scenePromise, activeAction = null, selectedIds = new Set(), pickSession = null, scenePicking = false;
const sceneCard = document.querySelector('.scene-card');
function clearSelection() { selectedIds.clear(); pickSession=null; scenePicking=false; scene?.setSelection([]); sceneCard.classList.remove('selecting'); dialog.classList.remove('scene-picking'); $('selection-context').textContent=''; }
function syncSelection() {
  selectedIds=new Set(visibleSelection([...selectedIds],pickSession?.rows||[]));
  scene?.setSelection([...selectedIds]);
  $('selection-context').textContent=pickSession?` / 已选 ${selectedIds.size} 人`:'';
  const count=$('scene-selection-count');if(count)count.textContent=selectedIds.size;
  if(scenePicking){$('context-title').textContent=`场景多选 · 已选 ${selectedIds.size} 人`;$('context-detail').textContent='点击名册形象选择，再在面板中应用并确认保存。';}
}
function toggleScenePicking() {
  if(!pickSession||writing)return;
  scenePicking=!scenePicking;sceneCard.classList.toggle('selecting',scenePicking);dialog.classList.toggle('scene-picking',scenePicking);
  const button=$('toggle-scene-picking');if(button){button.classList.toggle('selection-on',scenePicking);button.setAttribute('aria-pressed',String(scenePicking));button.textContent=scenePicking?'结束场景多选':'在场景里选学生';}
  syncSelection();if(!scenePicking)updateContext();
}
function selectStudent(id) {
  if(!ready||writing)return;
  if(scenePicking&&pickSession){if(!pickSession.rows.some(r=>r.student===id))return;selectedIds.has(id)?selectedIds.delete(id):selectedIds.add(id);pickSession.onChange();scene?.focusStudent(id);syncSelection();return;}
  openProfile(id);
}
function updateContext() {
  const object=objectFor(activeAction);
  $('context-title').textContent=object?object.title:'点一个物件，开始今天的工作';
  $('context-detail').textContent=object?object.hint:'门口点名 · 餐桌核餐 · 黑板看课表 · 阅读角记成长';
}
function pageChanged({page,total,size}) {
  $('scene-pager').hidden=total<=size;
  $('people-page').textContent=`名册形象 ${total?page*size+1:0}—${Math.min((page+1)*size,total)} / ${total}`;
  $('people-prev').disabled=page===0;$('people-next').disabled=(page+1)*size>=total;
}


function toast(text, error = false) {
  $('toast').textContent = text; $('toast').classList.toggle('error', error); $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 9000 : 4500);
}
function message(error) {
  return String(error?.message || '操作未完成，请刷新后核对数据。').slice(0, 600);
}
async function api(method, args = {}, write = false) {
  const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`/api/method/${method}${write ? '' : '?' + new URLSearchParams(args)}`, {
      method: write ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      headers: {'Accept': 'application/json', ...(write ? {'Content-Type':'application/json', 'X-Frappe-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content} : {})},
      ...(write ? {body: JSON.stringify(args)} : {}),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.exc) {
      let detail = response.status === 403 ? '没有操作权限或登录状态已失效，请重新登录后重试。' : '服务未完成操作，请刷新后核对。';
      try { const values = JSON.parse(body._server_messages || '[]'); if (values.length) { const item = typeof values[0] === 'string' ? JSON.parse(values[0]) : values[0]; detail = new DOMParser().parseFromString(item.message, 'text/html').body.textContent; } } catch (_) { /* No tracebacks or raw HTML shown. */ }
      throw new Error(detail);
    }
    return body.message;
  } catch (error) {
    if (error.name === 'AbortError' || error instanceof TypeError) throw new Error(write ? '网络中断，保存结果尚未确认。请先刷新核对，勿直接重复提交。' : '班级数据读取失败，请检查网络后点击刷新。');
    throw error;
  } finally { clearTimeout(timeout); }
}
const call = (method, args, write = false) => api(`tongjianyun.classroom.${method}`, args, write);
const workspace = new URLSearchParams(location.search).get('workspace') || '';
const scope = () => ({student_group: data.group.name, day: data.day, workspace: data.workspace || workspace});
const empty = (title, text = '') => `<div class="empty-block"><strong>${h(title)}</strong>${h(text)}</div>`;
const status = child => `<span class="row-status"><i class="dot ${h(child.status)}"></i>${h(STATUS[child.status])}</span>`;
const avatar = child => {
  const n=hash(child.student), hair=['#625044','#4e4036','#7b5942'][n%3], shirt=['#91b9ac','#d6a497','#a4b8d0','#d4bf83'][n%4];
  // Generic illustration, not a biometric photo or an inference about this child.
  return `<span class="avatar" style="--status:${COLORS[child.status] || COLORS.Unknown};background:${['#e6f0e9','#f7e7db','#e8edf8','#f5e4e6'][n%4]}"><svg viewBox="0 0 64 64" aria-hidden="true"><path d="M11 64Q12 45 32 45T53 64" fill="${shirt}"/>${n%3===0?`<circle cx="14" cy="22" r="8" fill="${hair}"/><circle cx="50" cy="22" r="8" fill="${hair}"/>`:''}<ellipse cx="32" cy="28" rx="17" ry="19" fill="#edc4a3"/><path d="M15 30Q10 7 31 8Q55 6 49 30L45 18Q33 24 23 17L19 29Z" fill="${hair}"/><ellipse cx="25" cy="30" rx="3.4" ry="4.1" fill="#493c35"/><ellipse cx="39" cy="30" rx="3.4" ry="4.1" fill="#493c35"/><circle cx="24" cy="29" r="1.1" fill="white"/><circle cx="38" cy="29" r="1.1" fill="white"/><ellipse cx="21" cy="36" rx="3" ry="1.6" fill="#e6a593"/><ellipse cx="43" cy="36" rx="3" ry="1.6" fill="#e6a593"/><path d="M28 38Q32 42 36 38" fill="none" stroke="#a5725e" stroke-width="1.7" stroke-linecap="round"/></svg></span>`;
};
function studentButton(child, index) {
  return `<button class="student-mini" data-student-index="${index}" title="查看${h(child.student_name)}">${avatar(child)}<strong>${h(child.student_name)}</strong><small>${h(STATUS[child.status])}</small></button>`;
}
function setPageMessage(text = '', error = false) {
  $('page-message').textContent = text; $('page-message').classList.toggle('error', error); $('page-message').hidden = !text;
}
async function load({automatic = false} = {}) {
  if (writing || (automatic && (dialog.open || document.hidden))) return;
  const request = ++sequence;
  ready = false;
  const group = $('class-select').value || new URLSearchParams(location.search).get('class') || '';
  const day = $('day-input').value || '';
  if (data?.group && (group !== data.group.name || day !== data.day)) $('dashboard').hidden = true;
  if (!automatic) { $('refresh').disabled = true; setPageMessage('正在读取班级记录…'); }
  try {
    const result = await call('get_overview', {student_group: group, day, workspace});
    if (request !== sequence) return;
    data = result;
    $('class-select').innerHTML = result.groups.map(g => `<option value="${h(g.name)}">${h(g.student_group_name || g.name)}</option>`).join('') || '<option value="">暂无可管理班级</option>';
    $('class-select').disabled = !result.groups.length;
    $('day-input').value = result.day;
    $('user-name').textContent = result.user_label;
    document.body.classList.toggle('teacher-workspace',result.workspace==='teacher');
    $('workspace-label').textContent=result.workspace==='teacher'?'教师 · 我的班级':'班级 3D 工作台';
    $('teacher-empty').hidden=!!result.group;
    if (!result.group) {
      $('dashboard').hidden = true; $('class-title').textContent = '尚未分配可管理班级';
      $('class-subtitle').textContent = '请由管理员核对教师与班级的关联及读取权限。';
      setPageMessage(result.workspace==='teacher'?'本人尚无可见任教班级，请核对员工、在岗教师与启用班级的关联。':'本账号暂无可见班级，不会展示其他班级或示例学生。'); return;
    }
    $('class-select').value = result.group.name;
    $('dashboard').hidden = false;
    render();
    ready = true;
    setPageMessage(result.capabilities.future ? '当前为未来日期：仅查看课表和预计用餐，不可登记实际出勤、实际就餐或成长记录。' : '');
    history.replaceState(null, '', '/tongjianyun-classroom?' + new URLSearchParams({class: result.group.name, day: result.day, workspace: result.workspace || workspace}));
    if (!scenePromise) {
      scenePromise = import('./scene.js?v=teacher-entry-20260923-1').then(({ClassroomScene}) => {
        scene = new ClassroomScene($('scene-canvas'), $('scene-labels'), {
          onStudent: id => selectStudent(id), onAction: action => act(action), onFailure: () => fallback(), onPage: pageChanged,
          onMotion: enabled => {const b=$('motion-toggle');if(b){b.setAttribute('aria-pressed',String(enabled));b.classList.toggle('active',enabled);b.title=enabled?'关闭装饰动画（非实时活动）':'开启装饰动画（遵循减少动态效果设置）';}},
        });
        if (data?.group) {scene.setStudents(data.attendance.students);scene.setBusinessData(data);}
        $('scene-loading').hidden = true;
      }).catch(() => fallback());
    } else if (scene) {scene.setStudents(result.attendance.students);scene.setBusinessData(result);}
  } catch (error) {
    if (request !== sequence) return;
    ready = false;
    setPageMessage(message(error) + (data ? ' 当前显示的上次数据不可作为最新状态；请刷新后再操作。' : ''), true);
    // Never leave another class visible after a failed class switch.
    if (data?.group && (group !== data.group.name || day !== data.day)) { $('dashboard').hidden = true; data = null; }
  } finally { if (request === sequence) $('refresh').disabled = false; }
}
function fallback() { $('scene-loading').hidden=true;$('scene-fallback').hidden=false;sceneCard.classList.add('no-webgl');$('scene-labels').hidden=true; }

function render() {
  const c=data.attendance.counts;
  $('class-title').textContent=data.group.label;
  $('class-subtitle').textContent=`${c.total} 名可见在册幼儿 · 点击物件办理业务，状态来自已有登记`;
  $('task-count').textContent=workRoute(data).filter(s=>s.needsAttention).length || '';
  $('sync-time').textContent=`业务读取 ${data.generated_at.slice(11,19)} · 可见时60秒刷新`;
  $('scene-note').textContent=`场景、人物姿态与动画均为示意，非真实活动或定位${c.total>PAGE_SIZE?' · 每页'+PAGE_SIZE+'人，可翻页查看全部名册':''}`;
  const preview=$('daily-preview');if(preview)preview.innerHTML=workRoute(data).slice(0,4).map(s=>`<button data-action="${s.action}"><span>${h(s.title)}</span><small>${h(s.state)}</small></button>`).join('');
  updateContext();renderSearch();
}
function renderSearch() {
  const term=$('scene-search').value.trim().toLowerCase(),box=$('search-results');
  if(!term||!data?.group){box.hidden=true;$('scene-search').setAttribute('aria-expanded','false');return;}
  const objects=OBJECTS.filter(o=>(o.title+o.label+o.hint).toLowerCase().includes(term));
  const children=data.attendance.students.map((r,i)=>[r,i]).filter(([r])=>(r.student_name+' '+r.student).toLowerCase().includes(term));
  box.innerHTML=objects.map(o=>`<button data-action="${o.action}">${icon(o.icon)}<span><strong>${h(o.label)}</strong><small>${h(o.title)}</small></span><span class="search-type">物件</span></button>`).join('')+children.slice(0,40).map(([r,i])=>`<button data-search-student="${i}">${avatar(r)}<span><strong>${h(r.student_name)}</strong><small>${h(STATUS[r.status])}</small></span><span class="search-type">学生</span></button>`).join('')+(children.length>40?'<button data-action="roster">结果较多，打开完整名册筛选 →</button>':'');
  if(!box.innerHTML)box.innerHTML=empty('没有匹配的可见学生或物件');
  box.hidden=false;$('scene-search').setAttribute('aria-expanded','true');
}
function closeSearch(){ $('search-results').hidden=true;$('scene-search').setAttribute('aria-expanded','false');$('scene-search').blur(); }
function openObjects() {
  openDialog('教室里的所有业务物件',`<div class="notice">每个物件都对应一个现有业务入口。键盘、搜索和降级模式提供相同功能；模型位置仅为示意。</div><div class="object-grid">${OBJECTS.map(o=>`<button class="object-tile" style="--tile-color:${o.tint}" data-action="${o.action}" data-registry-id="${o.id}">${icon(o.icon)}<span><strong>${h(o.label)}</strong><small>${h(o.title)}</small><small class="object-badge">${h(objectBadge(o.action,data))}</small></span></button>`).join('')}</div>`);
}
function openWorkflow() {
  const c=data.attendance.counts,steps=workRoute(data);
  openDialog('教师的一日工作',`<div class="notice">这是一条工作路线，不是自动考核。进入一个物件、查看课表或打开记录，均不会把业务标为已完成。当前使用当前启用名册查看所选日期记录。</div><div class="fact-grid"><div class="fact-tile">可见在册<strong>${c.total}</strong></div><div class="fact-tile">已登记到园<strong>${data.attendance.available?c.Present:'—'}</strong></div></div>${steps.map((s,i)=>`<section class="route-step ${s.needsAttention?'needs-attention':''}"><span class="step-number">${i+1}</span><div class="step-info"><h3>${h(s.title)}</h3><p>${h(s.note)}</p><span class="pill">${h(s.state)}</span></div><button class="secondary" data-action="${s.action}">前往物件 →</button></section>`).join('')}<p class="card-footnote">午休和美工仅提供人工观察入口；未接入定位、睡眠识别、家长即时聊天或环境传感器。</p>`);
}
function scheduleHTML(rows, links) {
  if (!data.schedule.available) return empty('暂无课表查看权限');
  if (!rows.length) return empty('当天尚无已登记课表', '不以示例活动代替班级真实安排。');
  return rows.map(r => `<div class="schedule-row"><span class="schedule-time">${h(timeLabel(r.from_time))}</span><i class="schedule-dot"></i><div class="schedule-title">${links ? `<a class="business-link" href="${h(desk('course-schedule', r.name))}">${h(r.title || r.course)} ↗</a><br><small>${h(r.room)} · ${h(timeLabel(r.from_time))}—${h(timeLabel(r.to_time))}</small>` : h(r.title || r.course)}</div></div>`).join('');
}
function logHTML(r) {
  const child = data.attendance.students.find(s => s.student === r.student);
  return `<div class="record-snippet"><strong>${h(child?.student_name || '学生')} <span class="pill">${h(LOG_TYPES[r.type] || '记录')}</span></strong><p>${h(r.log)}</p></div>`;
}
function openDialog(title, content, {wide = true} = {}) {
  ++dialogSequence;dirty=false;clearSelection();
  $('dialog-title').textContent=title;
  $('dialog-kicker').textContent=`${data.group.label} · ${data.day}`;
  $('object-context').textContent=objectFor(activeAction)?.title || '场景内办理';
  $('dialog-content').innerHTML=content;
  dialog.style.width='';dialog.classList.remove('expanded');
  if(!dialog.open)dialog.show();
  sceneCard.classList.add('panel-open');
  $('dialog-content').scrollTop=0;
  $('dialog-close').focus({preventScroll:true});
  return dialogSequence;
}
function closedPanel(){clearSelection();sceneCard.classList.remove('panel-open');updateContext();}
function closeDialog() {
  if(writing)return false;
  if(dirty&&!window.confirm('有尚未保存的修改，确认返回场景并放弃这些修改？'))return false;
  dirty=false;++dialogSequence;dialog.close();closedPanel();return true;
}
async function save(request, success) {
  if (writing) return;
  writing = true;
  const controls = [...dialog.querySelectorAll('button,input,select,textarea')].map(el => [el, el.disabled]);
  controls.forEach(([el]) => { el.disabled = true; });
  dialog.querySelectorAll('.inline-error').forEach(el => el.remove());
  try {
    await request();dirty=false;++dialogSequence;dialog.close();closedPanel();toast(success);await loadAfterWrite();
  } catch (error) {
    const box = document.createElement('p'); box.className = 'inline-error'; box.setAttribute('role','alert'); box.textContent = message(error); $('dialog-content').appendChild(box); box.scrollIntoView({block:'nearest'});
  } finally { writing = false; controls.forEach(([el, disabled]) => { el.disabled = disabled; }); }
}
async function loadAfterWrite() { writing = false; await load(); writing = true; }

function openRoster(leaveOnly = false) {
  openDialog(leaveOnly ? '请假与缺勤' : '学生名册', `<div class="notice">本班启用且当前账号可见的学生。点击姓名进入学生业务卡片，头像为通用名册标识。</div><div class="modal-toolbar"><input id="roster-filter" type="search" placeholder="搜索学生姓名" aria-label="搜索学生姓名"><select id="status-filter" aria-label="按出勤状态筛选"><option value="">全部状态</option>${Object.entries(STATUS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div><div class="table-wrap"><table><thead><tr><th>学生</th><th>名册序号</th><th>已登记状态</th><th>数据来源</th></tr></thead><tbody id="roster-body"></tbody></table></div><p class="card-footnote">请假撤销、返校等操作仍使用原请假业务流程。</p>`);
  const renderRows = () => {
    const term = $('roster-filter').value.trim(), filter = $('status-filter').value;
    $('roster-body').innerHTML = data.attendance.students.map((r,i) => [r,i]).filter(([r]) => r.student_name.includes(term) && (!filter || r.status === filter) && (!leaveOnly || ['Absent','Leave'].includes(r.status))).map(([r,i]) => `<tr><td><button class="person-link" data-student-index="${i}">${h(r.student_name)}</button></td><td>${h(r.roll_number || '—')}</td><td>${status(r)}</td><td>${r.leave_record ? `<a class="business-link" href="${h(desk('student-leave-application', r.leave_record))}">请假记录 ↗</a>` : h(r.source)}</td></tr>`).join('') || '<tr><td colspan="4">当前筛选没有匹配学生。</td></tr>';
  };
  $('roster-filter').addEventListener('input', renderRows); $('status-filter').addEventListener('change', renderRows); renderRows();
}
function openProfile(id) {
  if (!data?.group || writing || !ready) return;
  const child = data.attendance.students.find(r => r.student === id); if (!child) return;
  if (dirty && !window.confirm('切换学生将放弃尚未保存的修改，继续吗？')) return;
  activeAction='roster';scene?.setActiveAction('roster');updateContext();scene?.focusStudent(id);
  const index = data.attendance.students.indexOf(child);
  openDialog('学生业务卡片', `<div class="profile-header">${avatar(child)}<div><h3>${h(child.student_name)}</h3><p>${h(data.group.label)} · 名册虚拟形象</p></div></div><div class="profile-fact"><span>当日登记状态</span>${status(child)}</div><div class="profile-fact"><span>数据来源</span><strong>${h(child.source)}</strong></div><div class="profile-fact"><span>记录更新时间</span>${h(String(child.modified||'').slice(0,19) || '暂无记录')}</div><div class="profile-fact"><span>实际座位 / 实时位置</span>未接入</div><div class="profile-actions"><button class="primary" id="profile-attendance">核对出勤</button><button class="secondary" id="profile-record">记录成长</button><button class="secondary" id="profile-meals">核对用餐</button><button class="secondary" id="profile-contact">家园联系</button></div>${child.leave_record ? `<a class="business-link" href="${h(desk('student-leave-application',child.leave_record))}">打开原请假记录 ↗</a>` : ''}<div class="notice">头像、服饰及场景位置仅用于交互，不表示孩子的真实外貌、情绪、活动或健康状况。</div>`, {wide:false});
  $('profile-attendance').onclick = () => {activeAction='attendance';scene?.focusObject('attendance');updateContext();openAttendance(index);};
  $('profile-record').onclick=()=>{activeAction='records';scene?.focusObject('records');openRecords(index);};
  $('profile-meals').onclick=()=>{activeAction='meals';scene?.focusObject('meals');openMeals(child.student);};
  $('profile-contact').onclick=()=>{activeAction='contact';scene?.focusObject('contact');openContact(child.student);};
}
function openAttendance(singleIndex = null) {
  const context = scope(), snapshot = data.attendance, editable = data.capabilities.attendance_write;
  const rows = singleIndex === null ? snapshot.students : [snapshot.students[singleIndex]];
  const edits = {};
  openDialog('考勤点名', `<div class="notice${editable ? '' : ' warning'}">${editable ? '仅保存您明确选择的变更；待点名不会自动计入到园。请假须填写原因，已有请假需在原流程撤销或标记返校。' : `当前为只读：${data.capabilities.future ? '未来日期不可登记实际出勤' : data.capabilities.attendance_lock ? '当日膳食汇总' + h(data.capabilities.attendance_lock) + '，请先在原流程重新核对' : '当前账号不具备考勤编辑权限'}。`}</div><div class="selection-bar"><button class="secondary" id="toggle-scene-picking" aria-pressed="false">在场景里选学生</button><strong>已选 <span id="scene-selection-count">0</span> 人</strong><select id="selected-attendance-status" aria-label="选中学生的出勤状态"><option value="Present">到园</option><option value="Absent">缺勤</option><option value="Leave">请假</option></select><input id="selected-leave-reason" maxlength="1000" placeholder="批量请假原因（请假时必填）" aria-label="批量请假原因"><button class="secondary" id="apply-selected-attendance" ${editable?'':'disabled'}>应用到选中学生</button><span class="selection-hint">先勾选名册或点选场景形象；应用只是修改草稿，保存后才写入。</span></div><div class="modal-toolbar"><strong>${rows.length} 名学生</strong><span class="spacer"></span><button class="secondary" id="mark-pending" ${editable ? '' : 'disabled'}>将待点名标为到园</button></div><div class="table-wrap"><table><thead><tr><th>选择</th><th>学生</th><th>原登记</th><th>本次核对</th><th>请假原因</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td><input type="checkbox" class="attendance-select" data-row="${i}" aria-label="选择${h(r.student_name)}"></td><td>${h(r.student_name)}</td><td>${status(r)}</td><td><select class="attendance-value" data-row="${i}" aria-label="${h(r.student_name)}出勤状态" ${editable ? '' : 'disabled'}>${Object.entries(STATUS).map(([k,v])=>`<option value="${k}" ${k===r.status ? 'selected' : ''} ${k==='Unknown' && r.status!=='Unknown' ? 'disabled' : ''}>${v}</option>`).join('')}</select></td><td><input class="attendance-reason" data-row="${i}" aria-label="${h(r.student_name)}请假原因" placeholder="请假时必填" maxlength="1000" ${editable ? '' : 'disabled'}></td></tr>`).join('')}</tbody></table></div><div class="form-actions"><span id="attendance-changes" class="muted">暂无变更</span><button class="primary" id="save-attendance" disabled>保存点名变更</button></div>`);
  const update = () => {
    rows.forEach((r,i) => { const statusValue = dialog.querySelector(`.attendance-value[data-row="${i}"]`).value; const reason = dialog.querySelector(`.attendance-reason[data-row="${i}"]`); reason.disabled = !editable || statusValue !== 'Leave'; edits[r.student] = {status:statusValue,leave_reason:reason.value}; });
    const changes = attendanceChanges(rows, edits); dirty = !!changes.length;
    $('attendance-changes').textContent = changes.length ? `待保存 ${changes.length} 条变更，保存后同步原考勤业务` : '暂无变更';
    $('save-attendance').disabled = !editable || !changes.length;
  };
  dialog.querySelectorAll('.attendance-value,.attendance-reason').forEach(el=>el.addEventListener('input',update));
  $('mark-pending').onclick = () => {
    const pending = rows.filter(r=>r.status==='Unknown');
    if (!pending.length) return toast('当前名单没有待点名学生。');
    if (!window.confirm(`确认已逐一核实这 ${pending.length} 名待点名学生到园？此操作不会修改已登记请假或缺勤的学生。`)) return;
    rows.forEach((r,i)=>{if(r.status==='Unknown') dialog.querySelector(`.attendance-value[data-row="${i}"]`).value='Present';}); update();
  };
  pickSession={rows,onChange:()=>{dialog.querySelectorAll('.attendance-select').forEach(el=>{el.checked=selectedIds.has(rows[+el.dataset.row].student);el.closest('tr').classList.toggle('selected-row',el.checked);});}};
  dialog.querySelectorAll('.attendance-select').forEach(el=>el.onchange=()=>{const id=rows[+el.dataset.row].student;el.checked?selectedIds.add(id):selectedIds.delete(id);pickSession.onChange();syncSelection();});
  $('toggle-scene-picking').onclick=toggleScenePicking;
  $('apply-selected-attendance').onclick=()=>{
    if(!selectedIds.size)return toast('请先从场景或名册选择学生。');
    const status=$('selected-attendance-status').value,reason=$('selected-leave-reason').value.trim();
    if(status==='Leave'&&!reason)return toast('请填写批量请假的原因。',true);
    rows.forEach((r,i)=>{if(selectedIds.has(r.student)){dialog.querySelector(`.attendance-value[data-row="${i}"]`).value=status;dialog.querySelector(`.attendance-reason[data-row="${i}"]`).value=reason;}});update();
  };
  $('save-attendance').onclick = () => {
    const changes = attendanceChanges(rows, edits);
    if (changes.some(r=>r.status==='Unknown')) return toast('请明确选择到园、请假或缺勤。',true);
    if (changes.some(r=>r.status==='Leave'&&!r.leave_reason.trim())) return toast('请填写每名请假学生的请假原因。',true);
    save(()=>call('save_attendance',{...context,changes,revision:snapshot.revision},true),'点名已保存并同步原业务记录');
  };
  update();
}

async function openMeals(studentId = null) {
  const context = scope(), editable = data.capabilities.meals_write, future = data.capabilities.future;
  const generation = openDialog('核对班级各餐人数', empty('正在读取班级就餐明细…'));
  try {
    const result = await call('get_meals',context);
    if (!dialog.open || generation !== dialogSequence) return;
    const rows = mealSelections(result.record.students || []);
    $('dialog-content').innerHTML = `<div class="notice">预计安排不等于实际就餐。请逐人核对五个餐次；确认实际表示这些餐次均已核实，不会自动改写学生考勤。${future ? '未来日期只能保存预计安排。' : ''}</div>${!editable ? '<div class="notice warning">当前账号权限或锁定状态仅允许查看。</div>' : ''}<div class="selection-bar"><button class="secondary" id="toggle-scene-picking" aria-pressed="false">在场景里选学生</button><strong>已选 <span id="scene-selection-count">0</span> 人</strong><span class="selection-hint">场景选择与下面名册勾选联动；预计与实际仍按原流程分别保存。</span></div><div class="modal-toolbar"><strong>${h(result.record.status)} · ${rows.length} 人</strong><span class="spacer"></span><select id="bulk-meal" aria-label="批量调整餐次">${MEALS.map(([k,l])=>`<option value="${k}">${l}</option>`).join('')}</select><select id="bulk-state" aria-label="批量就餐状态">${['就餐','不就餐','不供餐'].map(s=>`<option>${s}</option>`).join('')}</select><button class="secondary" id="apply-meal" ${editable ? '' : 'disabled'}>应用到选中学生</button></div><div class="table-wrap"><table class="meal-table"><thead><tr><th><input type="checkbox" id="select-all-meals" aria-label="选择全部学生"></th><th>学生</th>${MEALS.map(([,l])=>`<th>${l}</th>`).join('')}</tr></thead><tbody>${rows.map((r,i)=>`<tr><td><input type="checkbox" class="meal-select" data-row="${i}" aria-label="选择${h(r.student_name)}"></td><td>${h(r.student_name)}</td>${MEALS.map(([k,l])=>`<td><select class="meal-value" data-row="${i}" data-meal="${k}" aria-label="${h(r.student_name)}${l}" ${editable?'':'disabled'}>${['就餐','不就餐','不供餐'].map(v=>`<option ${r[k]===v?'selected':''}>${v}</option>`).join('')}</select></td>`).join('')}</tr>`).join('')}</tbody><tfoot><tr><td colspan="2">本次核对人数</td>${MEALS.map(([k])=>`<td id="meal-total-${k}"></td>`).join('')}</tr></tfoot></table></div><label class="form-field" style="margin-top:15px"><span>修改原因（修改已确认记录时必填）</span><textarea id="meal-reason" rows="2" maxlength="1000" ${editable?'':'disabled'}></textarea></label><div class="form-actions"><span class="muted">${h(result.revision ? '以已保存班级安排为起点' : '尚无已保存安排；当前为原规则的预计值，请先核对')}</span><button class="secondary" id="save-meal-plan" ${editable&&rows.length&&result.record.status!=='已确认'?'':'disabled'}>保存预计</button><button class="primary green" id="confirm-meals" ${editable&&rows.length&&!future?'':'disabled'}>确认五餐实际情况</button></div>`;
    const totals = () => {const counts=mealTotals(rows); MEALS.forEach(([k])=>{$(`meal-total-${k}`).textContent=counts[k]+' 人';});};
    dialog.querySelectorAll('.meal-value').forEach(el=>el.onchange=()=>{rows[+el.dataset.row][el.dataset.meal]=el.value;dirty=true;totals();});
    $('meal-reason').oninput=()=>{dirty=true;};
    pickSession={rows,onChange:()=>{dialog.querySelectorAll('.meal-select').forEach(el=>{el.checked=selectedIds.has(rows[+el.dataset.row].student);el.closest('tr').classList.toggle('selected-row',el.checked);});}};
    $('toggle-scene-picking').onclick=toggleScenePicking;
    dialog.querySelectorAll('.meal-select').forEach(el=>el.onchange=()=>{const id=rows[+el.dataset.row].student;el.checked?selectedIds.add(id):selectedIds.delete(id);pickSession.onChange();syncSelection();});
    $('select-all-meals').onchange=()=>{selectedIds=new Set($('select-all-meals').checked?rows.map(r=>r.student):[]);pickSession.onChange();syncSelection();};
    if(studentId&&rows.some(r=>r.student===studentId)){selectedIds.add(studentId);pickSession.onChange();scene?.focusStudent(studentId);syncSelection();}
    $('apply-meal').onclick=()=>{
      const selected=[...dialog.querySelectorAll('.meal-select:checked')]; if(!selected.length)return toast('请先勾选需要调整的学生。');
      const meal=$('bulk-meal').value, value=$('bulk-state').value;
      selected.forEach(el=>{rows[+el.dataset.row][meal]=value;dialog.querySelector(`.meal-value[data-row="${el.dataset.row}"][data-meal="${meal}"]`).value=value;});dirty=true;totals();
    };
    const commit=confirm=>{
      const reason=$('meal-reason').value.trim();
      if(result.record.status==='已确认'&&!reason)return toast('修改已确认记录必须填写原因。',true);
      if(confirm&&!window.confirm('确认已经核对本班五个餐次的实际就餐情况？尚未发生的餐次不应提前确认。'))return;
      save(()=>call('save_meals',{...context,students:rows,revision:result.revision,confirm:confirm?1:0,change_reason:reason},true),confirm?'本班五餐实际情况已确认':'预计安排已保存，尚未确认实际就餐');
    };
    $('save-meal-plan').onclick=()=>commit(false);$('confirm-meals').onclick=()=>commit(true);totals();
  }catch(error){if(generation===dialogSequence)$('dialog-content').innerHTML=`<div class="notice error">${h(message(error))}</div>`;}
}

function openRecords(studentIndex = null, area = null) {
  const context = scope(), canCreate = data.capabilities.log_create;
  const areaLabels={reading:'阅读角',art:'美工区',rest:'午休区'};
  openDialog(area?areaLabels[area]+' · 人工观察':'记录孩子的成长', `<div class="notice">只记录教师实际观察，不生成情绪评分或能力排名。保存至现有 Student Log，不写入医疗资料。${area ? h(areaLabels[area])+'只是记录入口，不代表自动识别到此活动或位置。' : ''}</div><form id="record-form"><div class="form-grid"><label class="form-field"><span>学生</span><select name="student" required ${canCreate?'':'disabled'}>${data.attendance.students.map((r,i)=>`<option value="${h(r.student)}" ${i===studentIndex?'selected':''}>${h(r.student_name)}</option>`).join('')}</select></label><label class="form-field"><span>记录类型</span><select name="record_type" ${canCreate?'':'disabled'}>${Object.entries(LOG_TYPES).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><label class="form-field wide"><span>今天发生了什么？</span><textarea name="content" rows="4" required maxlength="2000" placeholder="写下具体的活动、孩子的表现与教师的支持…" ${canCreate?'':'disabled'}></textarea></label></div><div class="form-actions"><span class="muted">${canCreate?'与现有学生档案关联，最多2000字':'当前无创建权限，或所选日期尚未到来'}</span><button class="primary" ${canCreate&&data.attendance.students.length?'':'disabled'}>保存成长记录</button></div></form><h3 style="font-size:14px;margin:22px 0 12px">当日已登记记录（最近20条）</h3><div class="record-list">${data.logs.available ? data.logs.rows.map(logHTML).join('') || empty('还没有当日记录') : empty('暂无记录读取权限')}</div>`);
  $('record-form').oninput=()=>{dirty=true;};
  const observationPrefix=area?'观察入口：'+areaLabels[area]+'（教师手动记录，非自动监测）\n':'';
  $('record-form').querySelector('textarea').maxLength=2000-observationPrefix.length;
  $('record-form').onsubmit=event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget));if(area)values.content='观察入口：'+areaLabels[area]+'（教师手动记录，非自动监测）\n'+values.content;save(()=>call('add_record',{...context,...values},true),'成长记录已保存到学生日志');};
}
function openSchedule() {
  openDialog('黑板 · 当天课堂安排',`<div class="notice">读取本班当天的真实 Course Schedule。安排的时间不代表活动已发生，当前不新增课程完成状态。</div>${data.schedule.available?(data.schedule.rows.map(r=>`<section class="schedule-details"><h3>${h(r.title||r.course||'课程安排')}</h3><p>${h(timeLabel(r.from_time))}—${h(timeLabel(r.to_time))} · ${h(r.room||'未指定教室')}</p><p>状态：已排课（计划）</p><button class="secondary" data-action="records">记录实际课堂观察</button></section>`).join('')||empty('当天尚无已登记课表')):empty('暂无课表读取权限')}<details style="margin-top:20px"><summary class="muted">专业排课与原流程</summary><p class="card-footnote">课程新增、调整与冲突检查沿用原排课模块，不将计划误写为执行记录。</p><a class="business-link" target="_blank" rel="noopener" href="${h(desk('course-schedule','',{student_group:data.group.name,schedule_date:data.day}))}">在新页打开原排课模块 ↗</a></details>`,{wide:false});
}
function openContact(studentId = null) {
  openDialog('家园联系', `<div class="notice">沿用现有学生档案中的监护人资料。班级即时消息尚未接入，本页不展示模拟聊天或未经授权的联系电话。</div><div class="table-wrap"><table><thead><tr><th>学生</th><th>现有业务入口</th></tr></thead><tbody>${data.attendance.students.filter(r=>!studentId||r.student===studentId).map(r=>`<tr><td>${h(r.student_name)}</td><td><a class="business-link" target="_blank" rel="noopener" href="${h(desk('student',r.student))}">打开受权限控制的原档案 ↗</a></td></tr>`).join('')}</tbody></table></div>`);
}
async function openHealth() {
  const context = scope();
  if(!data.capabilities.health){openDialog('健康资料受权限保护',empty('需要专属健康管理权限','请联系园内获授权的健康管理人员核对，本页不扩大原有访问范围。'),{wide:false});return;}
  const generation=openDialog('本月健康登记',empty('正在读取受保护的健康资料…'));
  try{
    const result=await call('get_health',context);if(!dialog.open||generation!==dialogSequence)return;
    const renderRows=()=>{
      $('dialog-content').innerHTML=`<div class="notice">${h(result.month.slice(0,7))} · 仅展示当前可见班级学生。未登记不等于无过敏；沿用上月资料须重新核对。健康信息不在3D场景中公开展示。</div><div class="table-wrap"><table><thead><tr><th>学生</th><th>既往病史</th><th>过敏史</th><th>核对状态</th><th>操作</th></tr></thead><tbody>${result.rows.map((r,i)=>`<tr><td>${h(r.student_name)}</td><td>${h(r.history_state||'未登记')}</td><td>${h(r.allergy_state||'未登记')}</td><td>${h(r.inherited?'沿用上月 · 待核对':r.review_status||'待核对')}</td><td><button class="text-button edit-health" data-row="${i}">核对 / 修改</button></td></tr>`).join('')}</tbody></table></div>`;
      dialog.querySelectorAll('.edit-health').forEach(el=>el.onclick=()=>edit(result.rows[+el.dataset.row]));
    };
    const edit=r=>{
      const field=(name,label,value,type='text')=>`<label class="form-field"><span>${label}</span><input name="${name}" type="${type}" value="${h(value||'')}" maxlength="1000"></label>`;
      const state=(name,label)=>`<label class="form-field"><span>${label}</span><select name="${name}">${['未登记','明确无','已登记','待核实'].map(v=>`<option ${v===(r[name]||'未登记')?'selected':''}>${v}</option>`).join('')}</select></label>`;
      $('dialog-content').innerHTML=`<div class="notice">正在核对 ${h(r.student_name)} 的 ${h(result.month.slice(0,7))} 资料。只登记已获授权的原始说明，不做诊断。${r.inherited?'当前内容沿用历史资料，尚未完成本月核对。':''}</div><form id="health-form"><div class="form-grid">${state('history_state','既往病史状态')}${field('medical_history','既往病史原始说明',r.medical_history)}${state('allergy_state','过敏史状态')}${field('allergy_history','过敏史原始说明',r.allergy_history)}${field('contact_phone','联系电话（人工核对）',r.contact_phone,'tel')}${field('information_source','信息来源（如家长确认）',r.information_source)}<label class="form-field"><span>核对状态</span><select name="review_status"><option ${r.review_status!=='已核对'?'selected':''}>待核对</option><option ${r.review_status==='已核对'?'selected':''}>已核对</option></select></label>${field('change_reason','修改已核对资料的原因','')}</div><div class="form-actions"><button type="button" class="secondary" id="health-back">返回名单</button><button class="primary green">保存本月登记</button></div></form>`;
      $('health-form').oninput=()=>{dirty=true;};
      $('health-back').onclick=()=>{if(dirty&&!window.confirm('放弃尚未保存的健康资料修改？'))return;dirty=false;renderRows();};
      $('health-form').onsubmit=event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget));save(()=>call('save_health',{...context,payload:{...values,student:r.student,modified:r.modified}},true),'本月健康资料已保存');};
    };renderRows();
  }catch(error){if(generation===dialogSequence)$('dialog-content').innerHTML=`<div class="notice error">${h(message(error))}</div>`;}
}

function act(action) {
  if(!data?.group)return toast('请先选择有权限的班级。');
  if(!ready)return toast('请等待数据读取完成，或刷新后再操作。');
  if(writing)return;
  const functions={overview:()=>closeDialog(),objects:openObjects,workflow:openWorkflow,roster:()=>openRoster(),leave:()=>openRoster(true),attendance:()=>openAttendance(),meals:()=>openMeals(),records:()=>openRecords(null,'reading'),art:()=>openRecords(null,'art'),rest:()=>openRecords(null,'rest'),schedule:openSchedule,health:openHealth,contact:()=>openContact()};
  if(!functions[action])return;
  if(dirty&&!window.confirm('切换物件会放弃尚未保存的修改，继续吗？'))return;
  dirty=false;closeSearch();activeAction=action;scene?.focusObject(action);updateContext();
  document.querySelectorAll('.scene-actions [data-action]').forEach(el=>el.classList.toggle('active',el.dataset.action===action));
  functions[action]();
}
document.addEventListener('click',event=>{
  const legacy=event.target.closest('a[href^="/desk/"]');if(legacy&&dialog.contains(legacy)){legacy.target='_blank';legacy.rel='noopener';}
  const action=event.target.closest('[data-action]');if(action){act(action.dataset.action);return;}
  const searchStudent=event.target.closest('[data-search-student]');if(searchStudent&&data?.group){const id=data.attendance.students[+searchStudent.dataset.searchStudent]?.student;closeSearch();selectStudent(id);return;}
  const student=event.target.closest('[data-student-index]');if(student&&data?.group){selectStudent(data.attendance.students[+student.dataset.studentIndex]?.student);return;}
  const view=event.target.closest('[data-view]');if(view){currentView=view.dataset.view;scene?.setView(currentView);document.querySelectorAll('[data-view]').forEach(el=>{const active=el.dataset.view===currentView;el.classList.toggle('active',active);el.setAttribute('aria-pressed',active);});}
  if(!event.target.closest('.search-shell'))closeSearch();
});
$('dialog-close').onclick=closeDialog;
dialog.addEventListener('cancel',event=>{event.preventDefault();closeDialog();});
dialog.addEventListener('close',()=>{if(!dialog.open&&!writing){dirty=false;++dialogSequence;closedPanel();}});
$('dialog-expand').onclick=()=>{dialog.classList.toggle('expanded');};
$('scene-search').oninput=renderSearch;
$('scene-search').onkeydown=event=>{if(event.key==='ArrowDown'){event.preventDefault();$('search-results').querySelector('button')?.focus();}};
document.addEventListener('keydown',event=>{
  const editing=/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)||event.target.isContentEditable;
  if(event.key==='Escape'){if(!$('search-results').hidden){closeSearch();return;}if(dialog.open){event.preventDefault();closeDialog();}}
  if(event.key==='/'&&!editing){event.preventDefault();$('scene-search').focus();}
  if(event.key==='?'&&!editing){event.preventDefault();act('objects');}
});
function changeContext(element) {
  const old=element.id==='class-select'?data?.group?.name:data?.day;
  if(writing||(dirty&&!window.confirm('切换班级或日期将放弃当前尚未保存的修改，继续吗？'))){if(old)element.value=old;return;}
  dirty=false;if(dialog.open)closeDialog();clearSelection();activeAction=null;scene?.setActiveAction(null);scene?.setPage(0);closeSearch();load();
}
$('class-select').onchange=()=>changeContext($('class-select'));
$('day-input').onchange=()=>{if($('day-input').value)changeContext($('day-input'));};
$('refresh').onclick=()=>{if(writing)return;if(dialog.open&&!closeDialog())return;load();};
$('reset-view').onclick=()=>{scene?.setView(currentView);};
$('people-prev').onclick=()=>scene?.setPage((scene?.page||0)-1);
$('people-next').onclick=()=>scene?.setPage((scene?.page||0)+1);
$('label-toggle').onclick=()=>{const hidden=sceneCard.classList.toggle('scene-labels-hidden');$('label-toggle').setAttribute('aria-pressed',String(!hidden));$('label-toggle').classList.toggle('active',!hidden);};
$('motion-toggle').onclick=()=>{if(scene)scene.setMotion(!scene.motionEnabled);};
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(_){toast('浏览器未允许全屏，仍可使用全部班级功能。');}};
const refreshTimer=setInterval(()=>load({automatic:true}),60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load({automatic:true});});
window.addEventListener('beforeunload',event=>{if(dirty||writing){event.preventDefault();event.returnValue='';}});
window.addEventListener('pagehide',()=>{clearInterval(refreshTimer);scene?.dispose();});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
const initial=new URLSearchParams(location.search);if(initial.get('day')&&/^\d{4}-\d{2}-\d{2}$/.test(initial.get('day')))$('day-input').value=initial.get('day');
load();
