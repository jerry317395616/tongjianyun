/* Browser-only acceptance with synthetic children. No live API writes or login bypass.
 * Uses the already-installed Chromium and Debian ws package; no application deps.
 */
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process');const WebSocket=require('ws');
const ROOT=path.resolve(__dirname,'../..');
const CHROME=process.env.CLASSROOM_TEST_CHROME||'/home/zyd/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux/headless_shell';
const OUT=process.env.CLASSROOM_TEST_OUTPUT||'/tmp/tongjianyun-classroom-review';fs.mkdirSync(OUT,{recursive:true});
const wait=ms=>new Promise(r=>setTimeout(r,ms));
let students=Array.from({length:28},(_,i)=>({student:'DEMO-'+(i+1),student_name:'示例幼儿'+String(i+1).padStart(2,'0'),roll_number:i+1,status:i<24?'Present':i===24?'Leave':i===25?'Absent':'Unknown',modified:'2026-09-23 08:30:00',source:i<26?'演示考勤':'尚无登记'}));
let logs=[],revision=1,mealActual=null;const requests=[],errors=[];
function model(group,day){
  day=day||'2026-09-23';group=group||'DEMO-CLASS';const counts={Present:0,Absent:0,Leave:0,Unknown:0,total:students.length};students.forEach(s=>counts[s.status]++);counts.rate=Math.round(counts.Present/students.length*1000)/10;
  return {groups:[{name:'DEMO-CLASS',student_group_name:'小太阳班 · 演示'},{name:'DEMO-OTHER',student_group_name:'彩虹班 · 演示'}],group:{name:group,label:group==='DEMO-CLASS'?'小太阳班 · 演示':'彩虹班 · 演示'},day,today:'2026-09-23',generated_at:'2026-09-23 10:24:00',user_label:'演示老师',scene:{mode:'illustrative',location_connected:false},attendance:{available:true,students,counts,revision:String(revision)},capabilities:{attendance_write:day<='2026-09-23',meals_write:true,log_create:day<='2026-09-23',health:true,future:day>'2026-09-23'},health:{available:true,month:'2026-09-01',total:28,registered:26,unregistered:2,pending:1},meals:{available:true,status:mealActual?'已确认':'待确认',has_plan:true,expected:{lunch_count:26},actual:mealActual,source:'班级已保存安排'},schedule:{available:true,rows:[{name:'DEMO-SCHEDULE',title:'绘本里的秋天（演示）',course:'绘本阅读',from_time:'9:00:00',to_time:'9:30:00',room:'示例教室'},{name:'DEMO-ART',title:'创意美工（演示）',from_time:'10:00:00',to_time:'10:30:00',room:'示例教室'}]},logs:{available:true,rows:logs}};
}
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/method/')){
    let raw='';for await(const chunk of req)raw+=chunk;const args=req.method==='POST'?JSON.parse(raw||'{}'):Object.fromEntries(url.searchParams);const method=url.pathname.split('/').pop();requests.push({method,write:req.method==='POST'});let result;
    if(method==='tongjianyun.classroom.get_overview')result=model(args.student_group,args.day);
    else if(method==='tongjianyun.classroom.save_attendance'){assert.equal(args.revision,String(revision));args.changes.forEach(c=>{students=students.map(s=>s.student===c.student?{...s,status:c.status}:s);});revision++;result={saved:args.changes.length};}
    else if(method==='tongjianyun.classroom.add_record'){logs.unshift({name:'DEMO-LOG',student:args.student,type:args.record_type,date:args.day,log:args.content});result={name:'DEMO-LOG'};}
    else if(method==='tongjianyun.student_meals.get_class_meals')result={revision:'meal-1',record:{status:'待确认',students:students.map(s=>({student:s.student,student_name:s.student_name,...Object.fromEntries(['breakfast','morning_snack','lunch','afternoon_snack','dinner'].flatMap(k=>[[k,k==='dinner'?'不供餐':'未确认'],[k+'_expected',k==='dinner'?0:1]]))}))}};
    else if(method==='tongjianyun.student_meals.save_class_meals'){assert.equal(args.students.length,28);if(args.confirm)mealActual={lunch_count:args.students.filter(s=>s.lunch==='就餐').length};result={ok:true};}
    else if(method==='tongjianyun.classroom.get_health')result={month:'2026-09-01',rows:[{student:'DEMO-1',student_name:'示例幼儿01',history_state:'未登记',allergy_state:'未登记',review_status:'待核对',modified:null}]};
    else if(method==='tongjianyun.classroom.save_health'){assert.equal(args.payload.student,'DEMO-1');result={name:'DEMO-HEALTH'};}
    else{res.writeHead(404);res.end('{}');return;}
    res.setHeader('Content-Type','application/json');res.end(JSON.stringify({message:result}));return;
  }
  let file;
  if(url.pathname==='/tongjianyun-classroom'){res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(path.join(ROOT,'tongjianyun/www/tongjianyun-classroom.html'),'utf8').replace('{{ csrf_token | e }}','synthetic-test-csrf'));return;}
  if(url.pathname.startsWith('/assets/tongjianyun/'))file=path.join(ROOT,'tongjianyun/public',decodeURIComponent(url.pathname.slice('/assets/tongjianyun/'.length)));
  if(!file||!file.startsWith(path.join(ROOT,'tongjianyun/public')+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
  res.setHeader('Content-Type',({'.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
});
class CDP{
  constructor(url){this.id=0;this.pending=new Map();this.ws=new WebSocket(url);this.ready=new Promise(r=>this.ws.once('open',r));this.ws.on('message',b=>{const m=JSON.parse(b);if(m.id){const p=this.pending.get(m.id);if(p){this.pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text+': '+(m.params.exceptionDetails.exception?.description||''));});}
  async send(method,params={},sessionId){await this.ready;return new Promise((resolve,reject)=>{const id=++this.id;this.pending.set(id,{resolve,reject});this.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});}
}
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const port=server.address().port;const profile=fs.mkdtempSync(path.join(os.tmpdir(),'tjy-classroom-browser-'));
  // Only a throwaway profile and synthetic loopback data; no user session is loaded.
  const browser=spawn(CHROME,['--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
  let diagnostic='';const wsURL=await new Promise((resolve,reject)=>{const timeout=setTimeout(()=>reject(Error('Browser did not start: '+diagnostic.slice(-500))),15000);browser.stderr.on('data',b=>{diagnostic+=b.toString();const match=diagnostic.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match){clearTimeout(timeout);resolve(match[1]);}});browser.once('error',reject);});
  const cdp=new CDP(wsURL);let session;
  try{
    const target=await cdp.send('Target.createTarget',{url:'about:blank'});session=(await cdp.send('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;
    const send=(m,p={})=>cdp.send(m,p,session);await send('Page.enable');await send('Runtime.enable');
    const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value;};
    const until=async expression=>{for(let i=0;i<100;i++){if(await evaluate(expression))return;await wait(200);}throw Error('Timed out: '+expression);};
    const click=selector=>evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const close=()=>click('#dialog-close');
    await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url:`http://127.0.0.1:${port}/tongjianyun-classroom`});
    await until(`!!document.querySelector('#scene-canvas canvas') && document.querySelector('#scene-loading').hidden && !document.querySelector('#dashboard').hidden`);await wait(1000);
    assert.equal(await evaluate(`document.querySelector('#scene-fallback').hidden`),true);
    assert.equal(await evaluate(`document.querySelectorAll('#class-select option').length`),2);
    await evaluate('window.confirm=()=>true');
    const shot=async filename=>{const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(OUT,filename),Buffer.from(r.data,'base64'));};
    assert.equal(await evaluate(`document.querySelectorAll('#scene-labels [data-object-id]').length`),11);
    assert.equal(await evaluate(`!!document.querySelector('.sidenav') || !!document.querySelector('.right-column')`),false);
    await shot('desktop.png');
    await click('#scene-labels [data-action="workflow"]');await until(`document.querySelectorAll('.route-step').length===5`);
    assert.equal(await evaluate(`document.querySelector('#business-dialog').getAttribute('aria-modal')`),'false');
    await shot('workflow.png');await close();
    await click('.scene-actions [data-action="objects"]');await until(`document.querySelectorAll('[data-registry-id]').length===11`);await close();
    await click('#scene-labels [data-action="attendance"]');await until(`!!document.querySelector('#toggle-scene-picking')`);
    await click('#toggle-scene-picking');
    // Exercise real raycasting, not only DOM buttons. Project the first child's
    // head using this illustrative camera, then dispatch a canvas-host tap.
    await evaluate(`(async()=>{const T=await import('/assets/tongjianyun/campus/vendor/three.module.js');const host=document.querySelector('#scene-canvas'),r=host.getBoundingClientRect(),aspect=r.width/r.height,span=Math.max(12.8,19/aspect);const camera=new T.OrthographicCamera(-span*aspect/2,span*aspect/2,span/2,-span/2,.1,120);camera.position.set(12.8,11.6,20.5);camera.zoom=1.08;camera.lookAt(-6.7*.13,.8,4.5*.12);camera.updateProjectionMatrix();camera.updateMatrixWorld();const point=new T.Vector3(-4+Math.cos(Math.PI/8)*1.10,1.095,-1.25+Math.sin(Math.PI/8)*1.10).project(camera);const init={bubbles:true,clientX:r.left+(point.x+1)*r.width/2,clientY:r.top+(1-point.y)*r.height/2,pointerId:1};host.dispatchEvent(new PointerEvent('pointerdown',init));host.dispatchEvent(new PointerEvent('pointerup',init));})()`);
    await until(`document.querySelector('#scene-selection-count')?.textContent==='1'`);
    assert.equal(await evaluate(`document.querySelectorAll('.attendance-select:checked').length`),1);
    await shot('scene-selection.png');await click('#toggle-scene-picking');await close();
    assert.equal(requests.filter(r=>r.write).length,0,'Selecting a scene child must never write');
    await click('#scene-labels [data-action="attendance"]');await until(`!!document.querySelector('#mark-pending')`);await click('#mark-pending');await click('#save-attendance');await until(`!document.querySelector('#business-dialog').open && !document.querySelector('#page-message').textContent`);assert.equal(students.filter(s=>s.status==='Present').length,26);
    await click('#scene-labels [data-action="meals"]');await until(`!!document.querySelector('#confirm-meals')`);await click('.meal-select[data-row="0"]');assert.equal(await evaluate(`document.querySelector('#scene-selection-count').textContent`),'1');await click('#dialog-expand');await shot('meals.png');await click('#confirm-meals');await until(`!document.querySelector('#business-dialog').open`);assert.equal(mealActual.lunch_count,28);await wait(500);
    await click('#scene-labels [data-action="records"]');await until(`!!document.querySelector('#record-form')`);await evaluate(`document.querySelector('#record-form textarea').value='隔离浏览器验收记录，不写入真实学生';document.querySelector('#record-form').requestSubmit()`);await until(`!document.querySelector('#business-dialog').open`);assert.equal(logs.length,1);await wait(500);
    await click('#scene-labels [data-action="health"]');await until(`!!document.querySelector('.edit-health')`);await click('.edit-health');await until(`!!document.querySelector('#health-form')`);await close();
    for(const action of ['art','rest']){await click('#scene-labels [data-action="'+action+'"]');await until(`!!document.querySelector('#record-form')`);assert(await evaluate(`document.querySelector('#dialog-title').textContent.includes('人工观察')`));await close();}
    await click('#scene-labels [data-action="schedule"]');await until(`document.querySelectorAll('.schedule-details').length===2`);await close();
    await click('#scene-labels [data-action="leave"]');await until(`document.querySelector('#dialog-title').textContent==='请假与缺勤'`);await close();
    await click('#scene-labels [data-action="contact"]');await until(`document.querySelector('#dialog-title').textContent==='家园联系'`);await close();
    await click('#scene-labels [data-action="records"]');await until(`!!document.querySelector('#record-form')`);
    await evaluate(`document.querySelector('#record-form textarea').value='未保存草稿';document.querySelector('#record-form textarea').dispatchEvent(new Event('input',{bubbles:true}));window.confirm=()=>false;`);
    await click('#scene-labels [data-action="schedule"]');assert(await evaluate(`!!document.querySelector('#record-form')`),'Dirty draft was discarded');
    await evaluate('window.confirm=()=>true');await close();
    await click('[data-view="top"]');await wait(350);await click('[data-view="room"]');await wait(350);
    await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await wait(500);assert(await evaluate(`document.documentElement.scrollWidth <= window.innerWidth+1`),'mobile horizontal overflow');await evaluate(`document.querySelector('#toast').hidden=true`);await shot('mobile.png');await click('#scene-labels [data-action="attendance"]');await until(`!!document.querySelector('#toggle-scene-picking')`);await click('#toggle-scene-picking');await wait(250);await shot('mobile-selection.png');await close();
    await evaluate(`const d=document.querySelector('#day-input');d.value='2026-09-24';d.dispatchEvent(new Event('change',{bubbles:true}));`);await until(`document.querySelector('#page-message').textContent.includes('未来日期')`);await click('#scene-labels [data-action="meals"]');await until(`!!document.querySelector('#confirm-meals')`);assert.equal(await evaluate(`document.querySelector('#confirm-meals').disabled`),true);await close();
    await evaluate(`const select=document.querySelector('#class-select');select.value='DEMO-OTHER';select.dispatchEvent(new Event('change',{bubbles:true}));`);await until(`document.querySelector('#class-title').textContent.includes('彩虹班')`);
    students=Array.from({length:80},(_,i)=>({student:'LARGE-DEMO-'+i,student_name:'合成名单'+i,status:'Unknown',source:'尚无登记'}));
    await click('#refresh');await until(`document.querySelector('#scene-canvas').dataset.totalStudents==='80' && document.querySelector('#scene-canvas').dataset.renderedStudents==='48'`);
    assert.equal(await evaluate(`document.querySelector('#scene-note').textContent.includes('48人')`),true);await click('#people-next');await until(`document.querySelector('#scene-canvas').dataset.studentPage==='1' && document.querySelector('#scene-canvas').dataset.renderedStudents==='32'`);
    await click('#scene-labels [data-action="roster"]');await until(`document.querySelectorAll('#roster-body tr').length===80`);await close();
    await evaluate(`document.querySelector('#scene-canvas canvas').dispatchEvent(new Event('webglcontextlost',{cancelable:true}))`);
    assert.equal(await evaluate(`document.querySelector('#scene-fallback').hidden`),false);
    await click('#scene-labels [data-action="roster"]');await until(`document.querySelectorAll('#roster-body tr').length===80`);await close();
    await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1050,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate(`location.pathname`),'/tongjianyun-classroom','Core business must not navigate away');
    assert.equal(errors.length,0,errors.join('\n'));console.log(JSON.stringify({passed:true,checks:['11 scene-first business objects','real avatar raycast selection','selection does not write','shared meal selection','workflow uses facts','art/rest manual observation','unsaved draft protection','all 80 avatars paginated','Three.js WebGL rendering','desktop screenshot','attendance interaction/save (synthetic)','five-meal confirmation (synthetic)','growth record save (synthetic)','health permission UI','room/top view','mobile no horizontal overflow','future actual confirmation disabled','class switching','80-student roster with explicit 48-avatar cap','WebGL failure keeps roster functional'],api_calls:requests.length,screenshots:OUT,browser_exceptions:errors.length}));
  }finally{
    const exited=new Promise(resolve=>browser.once('exit',resolve));
    await cdp.send('Browser.close').catch(()=>{});cdp.ws.close();
    if(browser.exitCode===null&&browser.signalCode===null){await Promise.race([exited,wait(3000)]);if(browser.exitCode===null&&browser.signalCode===null){browser.kill();await Promise.race([exited,wait(3000)]);}}
    server.close();
    // Chromium may finish writing its *throwaway* cache after Browser.close.
    // Wait for exit and retry deletion instead of racing its cache directory.
    fs.rmSync(profile,{recursive:true,force:true,maxRetries:8,retryDelay:250});
  }
})().catch(error=>{console.error(error.stack);server.close();process.exit(1);});
