/* Full browser acceptance with synthetic records and loopback-only server.
 * Does not load personal sessions, real pupils or production write APIs.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),http=require('node:http'),path=require('node:path'),os=require('node:os');
const {spawn}=require('node:child_process'),WebSocket=require('ws');
const ROOT=path.resolve(__dirname,'../..'),PUBLIC=path.join(ROOT,'tongjianyun/public');
const CHROME=process.env.CLASSROOM_TEST_CHROME||'/home/zyd/.cache/ms-playwright/chromium_headless_shell-1228/chrome-linux/headless_shell';
const OUT=process.env.MEAL_SCENE_OUTPUT||'/tmp/tjy-meal-scene-review';fs.mkdirSync(OUT,{recursive:true});
const delay=ms=>new Promise(r=>setTimeout(r,ms));
let confirmed=false,demandCreated=false,createdRecipe=null,createdPayload=null,createdCount=0,createdRevision='rev2',editUpdates=0;const calls=[],errors=[],checks=[];
const meals=['breakfast','morning_snack','lunch','afternoon_snack','dinner'];
const kids=Array.from({length:4},(_,i)=>({student:'SYN-'+i,student_name:'合成幼儿'+(i+1),...Object.fromEntries(meals.flatMap(k=>[[k,k==='dinner'?'不供餐':'未确认'],[k+'_expected',k==='dinner'?0:1]]))}));
const recipe={name:'SYN-RECIPE',title:'秋日食谱 · 验收演示',workflow_status:'已发布',week_start:'2026-09-21',week_end:'2026-09-25',modified:'rev1'};
function overview(args){
  const day=args.day||'2026-09-23',meal=args.meal||'lunch';
  return {day,meal,today:'2026-09-23',generated_at:'2026-09-23 16:00:00',user_label:'演示膳食管理员',
    recipes:{available:true,rows:[recipe,...(createdRecipe?[createdRecipe]:[])].filter(row=>day>=row.week_start&&day<=row.week_end),has_more:false},
    plans:{available:true,rows:[{group:'SYN-C1',label:'示例一班',record:'SYN-CM',has_plan:true,confirmed,expected:4,actual:confirmed?4:null,status:confirmed?'已确认':'待确认'},
      {group:'SYN-C2',label:'示例二班',has_plan:false,confirmed:false,expected:null,actual:null,status:'尚未保存预计'}],
      summary:{visible_groups:2,planned_groups:1,confirmed_groups:confirmed?1:0,expected:null,actual:null,confirmed_subtotal:confirmed?4:null,scope_label:'当前可见班级 · 合成数据'}},
    orders:{available:true,rows:[{name:'SYN-PO',supplier_name:'示例供应商',company:'示例园',transaction_date:'2026-09-23',status:'To Receive',docstatus:1,grand_total:160,currency:'CNY'}],has_more:false,doctype:'Purchase Order',date_field:'transaction_date',start:'2026-09-17',end:day,note:'合成订单，不是真实采购记录'},
    receipts:{available:true,rows:[],has_more:false,doctype:'Purchase Receipt',date_field:'posting_date',start:'2026-09-17',end:day,note:'所选日期向前七日，无合成收货单'},
    capabilities:{recipe:true,recipe_write:true,recipe_create:true,procurement:true,order:true,receipt:true,stock:true,meals:true,meals_write:true},
    unconnected:['加工执行记录','配送签收','温度传感器','留样消毒记录','特殊餐执行闭环'],scene:{mode:'illustrative',telemetry:false,workflow_order_not_completion:true}};
}
function payload(){
  const slots=[['breakfast','早餐','小米粥'],['morningSnack','早点','水果'],['lunch','午餐','田园时蔬'],['snack','午点','点心'],['dinner','晚餐','杂粮饭']];
  const days=Array.from({length:5},(_,i)=>{
    const date=new Date(Date.parse(recipe.week_start+'T00:00:00Z')+i*86400000).toISOString().slice(0,10);
    return {date,day:['周一','周二','周三','周四','周五'][i],portions:slots.filter(([slot])=>!(i===1&&slot==='dinner')).map(([slot,label,dish])=>({slot,label,dishes:i===2&&slot==='lunch'?['田园时蔬','米饭']:[dish],dishIngredientRows:i===2&&slot==='lunch'?[{dishName:'米饭',ingredient:'大米（示例）',amount:40,unit:'g'},{dishName:'田园时蔬',ingredient:'青菜（示例）',amount:60,unit:'g'}]:[]}))};
  });
  return {recipe:{recipeId:'SYN-RECIPE',title:recipe.title,workflowStatus:'已发布',weekStart:recipe.week_start,weekEnd:recipe.week_end},days};
}
const server=http.createServer(async(req,res)=>{
  try{
    const u=new URL(req.url,'http://localhost');
    if(u.pathname==='/tongjianyun-meal-scene'){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end(fs.readFileSync(path.join(ROOT,'tongjianyun/www/tongjianyun-meal-scene.html'),'utf8').replace('{{ csrf_token | e }}','synthetic-csrf'));}
    if(u.pathname.startsWith('/desk/')){res.setHeader('Content-Type','text/html; charset=utf-8');return res.end('<h1>原专业模块 · 合成验收占位</h1><p>该测试页不会提交任何生产单据。</p>');}
    if(u.pathname.startsWith('/api/method/')){
      if(u.pathname==='/api/method/upload_file'){for await(const _ of req){}calls.push({method:'upload_file',write:true,args:{private:true}});res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({message:{file_url:'/private/files/synthetic-week.xlsx'}}));}
      let raw='';for await(const b of req)raw+=b;const args=req.method==='POST'?JSON.parse(raw||'{}'):Object.fromEntries(u.searchParams);const method=u.pathname.split('.').pop();calls.push({method,write:req.method==='POST',args});let result;
      if(method==='get_overview')result=overview(args);
      else if(method==='get_recipes')result={available:true,rows:[...(createdRecipe?[createdRecipe]:[]),recipe],has_more:false};
      else if(method==='get_recipe')result=args.recipe===createdRecipe?.name?{name:createdRecipe.name,revision:createdRevision,payload:createdPayload,edit:{mode:'update',reason:'普通草稿可直接修改'}}:{name:recipe.name,revision:'rev1',payload:payload(),edit:{mode:'copy',reason:'已发布食谱只生成修订草稿'}};
      else if(method==='start_recipe_import')result={import_id:'synthetic-import'};
      else if(method==='get_recipe_import_status')result={status:'completed',progress:100,message:'识别完成',result:{payload:payload(),warnings:['合成提醒：请核对午餐食材。'],summary:{day_count:5}}};
      else if(method==='create_recipe_draft'){assert.equal(args.payload.recipe.workflowStatus,'草稿');if(createdCount===1)assert.equal(args.import_id,'synthetic-import');createdCount++;createdPayload=structuredClone(args.payload);createdPayload.recipe.recipeId='SYN-CREATED-'+createdCount;createdPayload.recipe.workflowStatus='草稿';createdRevision='rev2';createdRecipe={name:'SYN-CREATED-'+createdCount,title:createdPayload.recipe.title,workflow_status:'草稿',week_start:createdPayload.recipe.weekStart,week_end:createdPayload.recipe.weekEnd,modified:createdRevision};result={name:createdRecipe.name,title:createdRecipe.title,status:'草稿',sync:{recipe:createdRecipe.name,status:'blocked'}};}
      else if(method==='save_recipe_edit'){
        if(args.recipe===recipe.name){assert.equal(args.revision,'rev1');createdCount++;createdPayload=structuredClone(args.payload);createdPayload.recipe.recipeId='SYN-CREATED-'+createdCount;createdPayload.recipe.workflowStatus='草稿';createdRevision='rev2';createdRecipe={name:'SYN-CREATED-'+createdCount,title:createdPayload.recipe.title,workflow_status:'草稿',week_start:createdPayload.recipe.weekStart,week_end:createdPayload.recipe.weekEnd,modified:createdRevision};result={name:createdRecipe.name,title:createdRecipe.title,status:'草稿',mode:'copy',source:recipe.name};}
        else {assert.equal(args.recipe,createdRecipe.name);assert.equal(args.revision,createdRevision);createdPayload=structuredClone(args.payload);createdPayload.recipe.workflowStatus='草稿';createdRevision='rev3';createdRecipe.title=createdPayload.recipe.title;createdRecipe.modified=createdRevision;editUpdates++;result={name:createdRecipe.name,title:createdRecipe.title,status:'草稿',mode:'update',source:createdRecipe.name};}
      }
      else if(method==='nutrition')result={recipe:{title:recipe.title},nutrients:{energy:700,protein:20,calcium:250},evaluations:{energy:{status:'估算参考',garden_target:720}},rule:{},standard_label:'合成估算基准',garden_ratio:80,conclusion:'合成结果，不是生产营养结论。',basis:'分类代表值估算，不是实测摄入量。'};
      else if(method==='get_documents')result=args.kind==='receipt'?overview(args).receipts:overview(args).orders;
      else if(method==='get_stock')result={warehouses:[{name:'SYN-WH',company:'示例园'}],warehouse:'SYN-WH',rows:[{item_code:'SYN-RICE',item_name:'大米（示例）',actual_qty:28,projected_qty:34,ordered_qty:6,stock_uom:'Kg'},{item_code:'SYN-MILK',item_name:'牛奶（示例）',actual_qty:10,projected_qty:10,ordered_qty:0,stock_uom:'L'}],has_more:false,generated_at:'2026-09-23 16:00:00',basis:'当前账面库存，非实物盘点，不同单位不合计。'};
      else if(method==='recipe_trace')result={impact:{requests:demandCreated?[{name:'SYN-MR',docstatus:0}]:[],message:'不覆盖原单'},note:'仅业务关联，不是全链路溯源。'};
      else if(method==='prepare_demand')result={scope:{company:'示例园',warehouse:'SYN-WH'},prepared:{meals:[{key:'2026-09-23:lunch',date:'2026-09-23',slot:'lunch',count:4,basis:'合成班级预计，非实际就餐'}],ingredients:[{key:'RICE',ingredient:'大米（示例）',source_uom:'g',item_code:'SYN-RICE',uom:'g',factor:1,basis:'同名候选需核对'}]},impact:{requests:[],message:'无现有需求'}};
      else if(method==='preview_demand')result={company:'示例园',warehouse:'SYN-WH',token:'syn-token',lines:[{schedule_date:'2026-09-23',item_code:'SYN-RICE',item_name:'大米（示例）',qty:.16,uom:'Kg',rate:4}]};
      else if(method==='create_demand'){assert.equal(args.confirmed,1);assert.equal(args.token,'syn-token');assert.equal(args.meals['2026-09-23:lunch'],4);demandCreated=true;result={name:'SYN-MR',existing:false};}
      else if(method==='get_meals')result={record:{status:confirmed?'已确认':'待确认',students:kids},revision:'cm-v1',editable:true};
      else if(method==='save_meals'){assert.equal(args.students.length,4);assert.equal(args.revision,'cm-v1');assert.equal(args.confirm,1);confirmed=true;result={saved:true};}
      else throw Error('Unexpected endpoint '+method);
      res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({message:result}));
    }
    const file=u.pathname.startsWith('/assets/tongjianyun/')?path.resolve(PUBLIC,decodeURIComponent(u.pathname.slice('/assets/tongjianyun/'.length))):null;
    if(!file||!file.startsWith(PUBLIC+path.sep)||!fs.existsSync(file)){res.writeHead(404);return res.end();}
    res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));
  }catch(e){errors.push(e.message);res.writeHead(500);res.end('{}');}
});
class CDP{
  constructor(url){this.id=0;this.pending=new Map();this.ws=new WebSocket(url);this.ready=new Promise((r,j)=>{this.ws.once('open',r);this.ws.once('error',j);});this.ws.on('message',raw=>{const m=JSON.parse(raw);if(m.id){const p=this.pending.get(m.id);if(!p)return;this.pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(m.error.message)):p.resolve(m.result);}else if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);});}
  async send(method,params={},sessionId){await this.ready;return new Promise((resolve,reject)=>{const id=++this.id,timer=setTimeout(()=>{this.pending.delete(id);reject(Error('CDP timed out '+method));},45000);this.pending.set(id,{resolve,reject,timer});this.ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));});}
}
(async()=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'tjy-meal-flow-browser-'));let browser,cdp;
  try{
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    browser=spawn(CHROME,['--no-sandbox','--disable-dev-shm-usage','--use-angle=swiftshader','--enable-unsafe-swiftshader','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:['ignore','ignore','pipe']});
    let output='';const socket=await new Promise((r,j)=>{const t=setTimeout(()=>j(Error('Browser startup timed out')),15000);browser.stderr.on('data',b=>{output+=b;const m=output.match(/DevTools listening on (ws:\/\/\S+)/);if(m){clearTimeout(t);r(m[1]);}});browser.once('error',j);});
    cdp=new CDP(socket);const target=await cdp.send('Target.createTarget',{url:'about:blank'}),session=(await cdp.send('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;
    const send=(m,p={})=>cdp.send(m,p,session);await send('Page.enable');await send('Runtime.enable');
    const run=async expression=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;};
    const until=async(expression,label)=>{for(let i=0;i<150;i++){if(await run(expression))return;await delay(200);}throw Error('Timed out '+(label||expression));};
    const click=s=>run(`document.querySelector(${JSON.stringify(s)}).click()`),close=()=>click('#close-panel');
    const shot=async name=>{const s=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(OUT,name),Buffer.from(s.data,'base64'));};
    const check=(name,value)=>{assert(value,name);checks.push(name);};
    await send('Emulation.setDeviceMetricsOverride',{width:1680,height:1050,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:`http://127.0.0.1:${server.address().port}/tongjianyun-meal-scene`});
    await until(`!!document.querySelector('#render-status') && document.querySelector('#render-status').hidden && document.querySelector('#message').hidden && !!document.querySelector('#canvas canvas')`,'initial scene');await delay(600);
    check('WebGL scene renders',await run(`document.querySelector('#fallback').hidden`));
    check('eight physical stations and ordered buttons',await run(`document.querySelectorAll('.scene-tag').length===8&&document.querySelectorAll('#flow-nav button').length===8`));
    check('partial confirmations display unknown not false totals',await run(`document.querySelector('#facts').textContent.includes('待核对')`));
    const metrics=await run(`({...document.querySelector('#canvas').dataset})`);check('batched static draw-call budget',Number(metrics.drawCalls)<1500);
    await shot('desktop-overview.png');
    await run(`window.confirm=()=>true`);
    // Pointer event hits actual geometry, independent of the HTML tag.
    await run(`(async()=>{const T=await import('/assets/tongjianyun/campus/vendor/three.module.js'),host=document.querySelector('#canvas'),r=host.getBoundingClientRect(),span=Math.max(23,39/(r.width/r.height)),camera=new T.OrthographicCamera(-span*r.width/r.height/2,span*r.width/r.height/2,span/2,-span/2,.1,180);camera.position.set(3.7,29,32);camera.lookAt(0,0,0);camera.updateProjectionMatrix();camera.updateMatrixWorld();const p=new T.Vector3(-10,3.12,-3.84).project(camera),ev={bubbles:true,isPrimary:true,clientX:r.left+(p.x+1)*r.width/2,clientY:r.top+(1-p.y)*r.height/2,pointerId:1};host.dispatchEvent(new PointerEvent('pointerdown',ev));host.dispatchEvent(new PointerEvent('pointerup',ev));})()`);
    await until(`document.querySelector('#panel').open&&document.querySelector('.recipe-week-grid')`,'geometry picking');check('actual building raycast opens business',true);
    check('single covering recipe opens full five-by-five week directly',await run(`document.querySelectorAll('.recipe-week-cell').length===25&&document.querySelector('.recipe-week-cell.selected')?.dataset.calendarDay==='2026-09-23'`));
    await shot('recipe-week-calendar.png');
    await click('[data-calendar-day="2026-09-22"][data-calendar-slot="dinner"]');check('missing meal is clearly unplanned',await run(`document.querySelector('#recipe-calendar-preview').textContent.includes('尚未编排')`));
    await click('[data-calendar-day="2026-09-23"][data-calendar-slot="lunch"]');check('calendar selection restores current lunch without changing global context',await run(`document.querySelector('#recipe-calendar-preview').textContent.includes('田园时蔬')&&document.querySelector('#day').value==='2026-09-23'`));
    await click('[data-sub="nutrition"]');await until(`document.querySelectorAll('.metric').length===7`);check('nutrition labels weekly estimates explicitly',await run(`document.querySelector('#panel-body').textContent.includes('整周营养估算')`));
    await click('[data-sub="recipe-back"]');await until(`!!document.querySelector('.recipe-week-grid')`);check('nutrition returns to selected week calendar',await run(`document.querySelector('.recipe-week-cell.selected')?.dataset.calendarSlot==='lunch'`));
    check('published recipe offers scene-native revision',await run(`document.querySelector('[data-sub="recipe-edit"]')?.textContent.includes('修订')`));
    await click('[data-sub="recipe-edit"]');await until(`!!document.querySelector('#draft-title')`);
    check('published editor is clearly an independent copy',await run(`document.querySelector('#panel-body').textContent.includes('原记录不变')&&!document.querySelector('iframe.professional')`));
    await shot('published-revision-editor.png');
    check('opening published revision does not write',calls.filter(c=>c.method==='save_recipe_edit').length===0);
    await click('[data-sub="draft-cancel"]');await until(`!!document.querySelector('.recipe-week-grid')`);await close();
    for(const id of ['receipt','stock','kitchen','dispatch','trace']){await click('#flow-nav [data-step="'+id+'"]');await until(`!document.querySelector('#panel-body').textContent.includes('正在读取')`);await delay(180);check('station '+id+' loads',await run(`document.querySelector('#panel').open`));if(id==='stock')await shot('stock-panel.png');if(id==='kitchen')check('kitchen does not claim actual processing',await run(`document.querySelector('#panel-body').textContent.includes('不是加工执行')`));await close();}
    check('viewing eight stations never writes',calls.filter(c=>c.write).length===0);
    await click('#flow-nav [data-step="purchase"]');await until(`!!document.querySelector('#new-demand')`);await click('#new-demand');await until(`!!document.querySelector('#preview-demand')`);
    await run(`const input=document.querySelector('.demand-count');input.value='4';input.dispatchEvent(new Event('input',{bubbles:true}));window.confirm=()=>false;`);
    await click('#flow-nav [data-step="stock"]');check('dirty draft survives refused navigation',await run(`!!document.querySelector('#preview-demand')`));
    await run('window.confirm=()=>true');await click('#preview-demand');await until(`!!document.querySelector('#create-demand')`);await shot('demand-preview.png');
    await click('#create-demand');await until(`!!document.querySelector('[data-native="request"][data-doc="SYN-MR"]')`);check('only explicit demand draft writes',demandCreated&&calls.filter(c=>c.write).length===1);await close();
    await click('#flow-nav [data-step="dining"]');await until(`!!document.querySelector('[data-meal-group]')`);await click('[data-meal-group]');await until(`!!document.querySelector('#meal-confirm')`);
    await click('.meal-select');check('student selection does not save',calls.filter(c=>c.write).length===1);await click('#meal-confirm');await until(`!document.querySelector('#meal-confirm')&&document.querySelector('#message').hidden`);check('actual meal uses original explicit adapter',confirmed);await close();
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('[data-sub="recipe-edit"]')`);check('recipe edit no longer opens the original module',await run(`!document.querySelector('[data-native="recipe"]')&&!document.querySelector('iframe.professional')`));await close();
    await click('[data-view="top"]');await delay(250);await shot('top-view.png');await click('[data-view="overview"]');
    await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await delay(600);
    check('mobile has no page horizontal overflow',await run(`document.documentElement.scrollWidth<=innerWidth+1`));await run(`document.querySelector('#toast').hidden=true`);await shot('mobile-overview.png');
    await click('#flow-nav [data-step="dispatch"]');await until(`!!document.querySelector('[data-meal-group]')`);await shot('mobile-panel.png');await close();
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('.recipe-week-grid')`);check('mobile recipe week remains inside panel without page overflow',await run(`document.documentElement.scrollWidth<=innerWidth+1&&document.querySelector('.recipe-week-scroll').scrollWidth>0`));check('mobile week calendar explains horizontal scrolling',await run(`getComputedStyle(document.querySelector('.recipe-week-swipe')).display!=='none'`));await shot('mobile-recipe-week-calendar.png');await close();
    await run(`const day=document.querySelector('#day');day.value='2026-09-24';day.dispatchEvent(new Event('change',{bubbles:true}));`);await until(`document.querySelector('#message').hidden&&location.search.includes('2026-09-24')`);
    await click('#flow-nav [data-step="dining"]');await until(`!!document.querySelector('[data-meal-group]')`);await click('[data-meal-group]');await until(`!!document.querySelector('#meal-confirm')`);check('future actual confirmation disabled',await run(`document.querySelector('#meal-confirm').disabled`));await close();
    await run(`document.querySelector('#day').value='2026-09-28';document.querySelector('#day').dispatchEvent(new Event('change',{bubbles:true}));`);await until(`document.querySelector('#message').hidden&&location.search.includes('2026-09-28')`);
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('.recipe-week-grid')`);check('date without recipe opens empty week calendar directly',await run(`document.querySelectorAll('.recipe-week-cell.unplanned').length===25&&document.querySelector('#panel-body').textContent.includes('不代表其他日期也未编排')&&!document.querySelector('iframe.professional')`));await shot('empty-recipe-week-calendar.png');
    await click('[data-sub="recipe-library"]');await until(`!!document.querySelector('[data-recipe="SYN-RECIPE"]')`);await click('[data-recipe="SYN-RECIPE"]');await until(`!!document.querySelector('.recipe-week-grid')`);check('other-week recipe stays preview with date mismatch warning',await run(`document.querySelector('#panel-body').textContent.includes('不覆盖顶部所选业务日期')&&document.querySelector('#day').value==='2026-09-28'`));await close();
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('[data-sub="recipe-new"]')`);await click('[data-sub="recipe-new"]');await until(`!!document.querySelector('#draft-title')`);check('new recipe opens scene-native five-by-five editor',await run(`document.querySelectorAll('[data-draft-day]').length===25&&!document.querySelector('iframe.professional')`));await shot('new-recipe-editor.png');await run(`document.querySelector('#panel-body').scrollTop=1000`);await shot('new-recipe-editor-details.png');await run(`document.querySelector('#panel-body').scrollTop=0`);
    await run(`(()=>{const title=document.querySelector('#draft-title'),dish=document.querySelector('#draft-dishes');title.value='本周合成草稿';dish.value=['米饭','清炒时蔬'].join(String.fromCharCode(10));dish.dispatchEvent(new Event('input',{bubbles:true}));})()`);await click('#draft-add-ingredient');
    await run(`(()=>{const row=document.querySelector('.draft-ingredient-row');row.querySelector('[data-field="dish"]').value='米饭';row.querySelector('[data-field="ingredient"]').value='大米';row.querySelector('[data-field="amount"]').value='40';row.querySelector('[data-field="unit"]').value='g';})()`);
    check('editing does not save before explicit draft button',calls.filter(c=>c.method==='create_recipe_draft').length===0);
    await click('#draft-save');await until(`!!document.querySelector('.recipe-week-grid')&&!document.querySelector('#draft-title')`);check('scene-native create saves a draft then returns to week',createdCount===1&&await run(`document.querySelector('#panel-body').textContent.includes('本周合成草稿')&&document.querySelector('#panel-body').textContent.includes('米饭')`));await close();
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('[data-sub="recipe-import"]')`);await click('[data-sub="recipe-import"]');await until(`!!document.querySelector('#recipe-import-file')`);
    await run(`(()=>{const transfer=new DataTransfer();transfer.items.add(new File(['synthetic workbook'],'week.xlsx',{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));document.querySelector('#recipe-import-file').files=transfer.files;})()`);await click('#recipe-import-start');await until(`!!document.querySelector('#draft-title')&&document.querySelector('#panel-body').textContent.includes('Excel 识别结果')`);
    check('import previews inside scene with warnings before saving',await run(`document.querySelector('#panel-body').textContent.includes('合成提醒')&&!document.querySelector('iframe.professional')`)&&createdCount===1);await shot('import-recipe-review.png');
    await run(`(()=>{document.querySelector('#draft-title').value='导入后校对的食谱';document.querySelector('#draft-dishes').value='番茄炒蛋';})()`);
    await click('#draft-save');await until(`!!document.querySelector('.recipe-week-grid')&&!document.querySelector('#draft-title')`);check('imported recipe saved only as reviewed draft',createdCount===2&&createdPayload.recipe.workflowStatus==='草稿'&&createdPayload.recipe.title==='导入后校对的食谱'&&createdPayload.days[0].portions.find(p=>p.slot==='lunch').dishes[0]==='番茄炒蛋'&&calls.some(c=>c.method==='upload_file'&&c.args.private));await close();
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('[data-sub="recipe-edit"]')`);await click('[data-sub="recipe-edit"]');await until(`!!document.querySelector('#draft-title')`);
    check('existing draft edits inside the week calendar',await run(`document.querySelectorAll('[data-draft-day]').length===25&&document.querySelector('#draft-save').textContent.includes('修改')&&!document.querySelector('iframe.professional')`));
    await shot('existing-draft-editor.png');
    await run(`document.querySelector('#draft-dishes').value=['番茄炒蛋','杂粮饭'].join(String.fromCharCode(10))`);await click('#draft-save');await until(`!!document.querySelector('.recipe-week-grid')&&!document.querySelector('#draft-title')`);
    check('draft edit saves the same identity with revision guard',editUpdates===1&&createdCount===2&&createdPayload.days[0].portions.find(p=>p.slot==='lunch').dishes.includes('杂粮饭'));
    await close();
    await click('#flow-nav [data-step="recipe"]');await until(`!!document.querySelector('[data-sub="recipe-library"]')`);await click('[data-sub="recipe-library"]');await until(`!!document.querySelector('[data-recipe="SYN-RECIPE"]')`);
    await click('[data-recipe="SYN-RECIPE"]');await until(`!!document.querySelector('[data-sub="recipe-edit"]')`);await click('[data-sub="recipe-edit"]');await until(`!!document.querySelector('#draft-title')`);
    await run(`document.querySelector('#draft-title').value='已发布食谱的合成修订'`);await click('#draft-save');await until(`!!document.querySelector('.recipe-week-grid')&&!document.querySelector('#draft-title')`);
    check('published revision creates a new draft without overwriting source',createdCount===3&&createdRecipe.name==='SYN-CREATED-3'&&recipe.workflow_status==='已发布'&&calls.filter(c=>c.method==='save_recipe_edit').length===2);
    await close();
    await run(`document.querySelector('#canvas canvas').dispatchEvent(new Event('webglcontextlost',{cancelable:true}))`);check('WebGL loss gives ordinary equivalent actions',await run(`!document.querySelector('#fallback').hidden`));
    await click('#flow-nav [data-step="stock"]');await until(`!!document.querySelector('#stock-warehouse')`);check('stock works without WebGL',true);
    check('no automatic financial endpoints',calls.every(c=>!['start','create_purchase','complete_purchase_cycle'].includes(c.method)));
    check('no uncaught browser exceptions',errors.length===0);
    console.log(JSON.stringify({passed:true,checks,metrics,api_calls:calls.length,synthetic_writes:calls.filter(c=>c.write).map(c=>c.method),screenshots:OUT,browser_exceptions:errors}));
  }finally{
    if(cdp){const exited=browser.exitCode===null?new Promise(r=>browser.once('exit',r)):Promise.resolve();await cdp.send('Browser.close').catch(()=>{});cdp.ws.close();await Promise.race([exited,delay(3000)]);}
    if(browser&&browser.exitCode===null){browser.kill();await delay(500);}server.close();fs.rmSync(profile,{recursive:true,force:true,maxRetries:8,retryDelay:250});
  }
})().catch(e=>{console.error(JSON.stringify({passed:false,error:e.stack,checks,exceptions:errors}));server.close();process.exit(1);});
