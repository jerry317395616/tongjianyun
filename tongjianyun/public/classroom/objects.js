// One registry for physical hotspots, search, keyboard navigation and fallback.
// Coordinates describe an illustrative room, never a child's actual location.
export const OBJECTS = Object.freeze([
  {id:'arrival', action:'attendance', title:'门口点名台', label:'考勤点名', icon:'check', point:[-7.05,2.16,4.93], tint:'#59a080', hint:'核对到园、请假与缺勤'},
  {id:'cubbies', action:'roster', title:'学生储物柜', label:'学生名册', icon:'people', point:[6.84,2.08,5.04], tint:'#e8a343', hint:'完整名册与学生业务卡片'},
  {id:'leave_book', action:'leave', title:'请假登记簿', label:'请假与缺勤', icon:'note', point:[-4.02,1.50,5.07], tint:'#c29864', hint:'查看登记、核对请假'},
  {id:'board', action:'schedule', title:'教学黑板', label:'课堂安排', icon:'book', point:[.10,4.11,-5.37], tint:'#549dea', hint:'当天课表，仅表示计划'},
  {id:'dining', action:'meals', title:'班级餐桌', label:'五餐确认', icon:'meal', point:[3.45,2.25,.45], tint:'#58ad91', hint:'预计安排与实际分开核对'},
  {id:'reading', action:'records', title:'阅读帐篷', label:'成长记录', icon:'book', point:[-6.35,2.54,-2.10], tint:'#70ad88', hint:'记录教师实际观察', area:'reading'},
  {id:'art', action:'art', title:'美工画架', label:'美工观察', icon:'palette', point:[-5.20,2.24,2.03], tint:'#ac86d3', hint:'手动记录，不推断参与情况', area:'art'},
  {id:'rest', action:'rest', title:'午休小床', label:'午休观察', icon:'bed', point:[6.65,1.79,-2.56], tint:'#a78adb', hint:'仅人工观察，无睡眠监测', area:'rest'},
  {id:'health', action:'health', title:'健康资料柜', label:'健康核对', icon:'heart', point:[7.21,2.27,1.65], tint:'#de8587', hint:'专属权限，详情按需读取'},
  {id:'mailbox', action:'contact', title:'家园信箱', label:'家园联系', icon:'chat', point:[4.18,2.08,4.88], tint:'#6aa8d9', hint:'查看已授权监护人资料'},
  {id:'dayboard', action:'workflow', title:'教师工作板', label:'一日工作', icon:'check', point:[-3.75,2.53,-3.9], tint:'#659f85', hint:'按已有业务记录引导，不自动完成'},
]);
export const objectFor = action => OBJECTS.find(o => o.action === action) || null;
export const PAGE_SIZE = 24;
export function studentPage(rows, id) {
  const index = rows.findIndex(r => r.student === id);
  return index < 0 ? null : Math.floor(index / PAGE_SIZE);
}
export function visibleSelection(ids, rows) {
  const available = new Set(rows.map(r => r.student));
  return [...new Set(ids)].filter(id => available.has(id));
}
export function workRoute(data) {
  const a=data.attendance, m=data.meals, s=data.schedule, h=data.health, l=data.logs;
  const steps = [
    {action:'attendance', title:'先核对出勤', state:!a.available?'不可读取':a.counts.total===0?'暂无学生':a.counts.Unknown?`${a.counts.Unknown} 人待点名`:'名单均有登记', needsAttention:a.available&&a.counts.Unknown>0, note:'只统计已有登记，不表示实时位置。'},
    {action:'schedule', title:'查看课堂计划', state:!s.available?'不可读取':s.rows.length?`${s.rows.length} 项已排课`:'尚无课表', needsAttention:false, note:'计划不等于已经完成，不自动打勾。'},
    {action:'meals', title:'核对班级用餐', state:!m.available?'不可读取':m.actual?'已确认实际':m.has_plan?'预计已保存，实际待核对':'尚未保存预计', needsAttention:m.available&&!m.actual, note:'未发生的餐次不可提前确认实际。'},
    {action:'records', title:'留下真实观察', state:!l.available?'不可读取':`${l.rows.length}${l.rows.length===20?'＋':''} 条当日记录`, needsAttention:false, note:'记录数量不是教师完成率，不要求给每个孩子打分。'},
  ];
  if (h.available) steps.push({action:'health', title:'核对本月健康资料', state:`${h.unregistered+h.pending} 人待核对`, needsAttention:h.unregistered+h.pending>0, note:'仅获授权账号可见；不是实时健康监测。'});
  return steps;
}
export function objectBadge(action,data) {
  const step=workRoute(data).find(s=>s.action===action);
  if(step)return step.state;
  if(action==='roster')return `${data.attendance.counts.total} 名可见学生`;
  if(action==='leave')return data.attendance.available ? `请假 ${data.attendance.counts.Leave} · 缺勤 ${data.attendance.counts.Absent}` : '不可读取';
  if(action==='health')return '专属权限';
  if(action==='workflow')return `${workRoute(data).filter(s=>s.needsAttention).length} 项待核对`;
  if(action==='rest')return '仅人工观察';
  if(action==='art')return '记录实际观察';
  if(action==='contact')return '按权限查看';
  return '';
}
