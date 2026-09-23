import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const text=await readFile(new URL('../public/classroom/objects.js',import.meta.url),'utf8');
const {OBJECTS,objectFor,PAGE_SIZE,studentPage,visibleSelection,workRoute,objectBadge}=await import('data:text/javascript;base64,'+Buffer.from(text).toString('base64'));
const cases=[];
function test(name,run){run();cases.push(name);}
const base=()=>({attendance:{available:true,counts:{Present:0,Absent:0,Leave:0,Unknown:3,total:3}},meals:{available:true,has_plan:false,actual:null},schedule:{available:true,rows:[]},health:{available:false},logs:{available:true,rows:[]}});
test('Every business object has a unique ID/action and finite anchor',()=>{
  assert.equal(OBJECTS.length,11);assert.equal(new Set(OBJECTS.map(o=>o.id)).size,11);assert.equal(new Set(OBJECTS.map(o=>o.action)).size,11);
  for(const o of OBJECTS){assert(o.label&&o.title&&o.hint);assert.equal(o.point.length,3);assert(o.point.every(Number.isFinite));assert.equal(objectFor(o.action).id,o.id);}
});
test('Search and scene share the same capability index',()=>assert.equal(objectFor('not-a-capability'),null));
test('24 detailed avatars per page, all 80 children reachable',()=>{const rows=Array.from({length:80},(_,i)=>({student:'S'+i}));assert.equal(PAGE_SIZE,24);assert.equal(studentPage(rows,'S23'),0);assert.equal(studentPage(rows,'S24'),1);assert.equal(studentPage(rows,'S79'),3);assert.equal(studentPage(rows,'OTHER'),null);});
test('Selections cannot retain foreign or duplicate IDs',()=>assert.deepEqual(visibleSelection(['S1','S1','OTHER'],[{student:'S1'}]),['S1']));
test('Unknown attendance stays actionable',()=>assert.equal(workRoute(base())[0].state,'3 人待点名'));
test('Empty roster does not imply attendance complete',()=>{const d=base();d.attendance.counts={total:0,Unknown:0};assert.equal(workRoute(d)[0].state,'暂无学生');});
test('Saved meal plan is not actual confirmation',()=>{const d=base();d.meals.has_plan=true;assert.equal(workRoute(d)[2].state,'预计已保存，实际待核对');assert(workRoute(d)[2].needsAttention);});
test('Actual zero meals is still an actual record, not missing',()=>{const d=base();d.meals.actual={lunch_count:0};assert.equal(workRoute(d)[2].needsAttention,false);});
test('Scheduled lessons are plans, never completed activity',()=>{const d=base();d.schedule.rows=[{}];assert.equal(workRoute(d)[1].state,'1 项已排课');assert(!workRoute(d)[1].needsAttention);});
test('Protected health counts never enter ordinary teacher route',()=>{const d=base();d.health={available:false,unregistered:99,pending:99};assert(!workRoute(d).some(s=>s.action==='health'));assert.equal(objectBadge('health',d),'专属权限');});
test('Health review uses permission-gated recorded facts',()=>{const d=base();d.health={available:true,unregistered:2,pending:1};assert.equal(workRoute(d).find(s=>s.action==='health').state,'3 人待核对');});
test('Logs are counts, not a quota or evaluation',()=>{const d=base();d.logs.rows=new Array(20).fill({});const s=workRoute(d).find(s=>s.action==='records');assert.equal(s.state,'20＋ 条当日记录');assert(!s.needsAttention);});
test('Rest area never claims sleep sensing',()=>assert.equal(objectBadge('rest',base()),'仅人工观察'));
test('Unavailable attendance is not advertised as a completed count',()=>{const d=base();d.attendance.available=false;assert.equal(objectBadge('attendance',d),'不可读取');});
console.log(JSON.stringify({passed:true,cases:cases.length,checks:cases}));
