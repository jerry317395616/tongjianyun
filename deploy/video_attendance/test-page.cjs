// Component smoke checks without a browser or any real employee data.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../../tongjianyun/tongjianyun/page/teacher_video_attendance/teacher_video_attendance.js'), 'utf8');
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function render(manager, data) {
  let html = '', methods = [], buttons = [];
  const root = {appendTo(){return this;}, html(s){html=s;return this;},find(){return {on(){}};}};
  const frappe = {pages:{'teacher-video-attendance':{}},session:{user:manager?'Administrator':'teacher-test'}, user_roles:[],
    utils:{escape_html:esc},datetime:{get_today:()=> '2026-09-16'},
    ui:{make_app_page:()=>({main:{},add_field(f){f.change();return {get_value:()=> '2026-09-16'};},set_primary_action(){},add_inner_button(label){buttons.push(label);}})},
    call: async args => {methods.push(args.method);return {message:data};}};
  vm.runInNewContext(source, {frappe,$:()=>root,setInterval(){},document:{hidden:false},window:{}});
  const wrapper = {};
  frappe.pages['teacher-video-attendance'].on_page_load(wrapper);
  await wrapper.video_refresh();
  return {html,methods,buttons};
}
(async()=>{
  const empty={devices:[],profiles:[],events:[],batches:[],batch_total:0,event_total:0};
  const admin=await render(true,empty);
  assert(admin.html.includes('暂无记录'));
  assert(admin.buttons.includes('下载采集程序'));
  const teacher=await render(false,[]);
  assert(teacher.methods[0].endsWith('.my_checkins'));
  assert(!teacher.buttons.includes('注册教师'));
  const hostile=await render(true,{...empty,events:[{name:'a',batch:'b',employee:'<img src=x onerror=alert(1)>',status:'Review',log_type:'IN'}]});
  assert(!hostile.html.includes('<img'));
  assert(hostile.html.includes('&lt;img'));
  console.log('3 page component checks passed (admin empty state, teacher isolation, HTML escaping)');
})().catch(e=>{console.error(e);process.exitCode=1;});
