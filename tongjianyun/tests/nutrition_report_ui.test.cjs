const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const code=readFileSync(path.join(__dirname,'../tongjianyun/report/weekly_recipe_nutrition_analysis/weekly_recipe_nutrition_analysis.js'),'utf8');
const name='Weekly Recipe Nutrition Analysis';
function fixture(){
 const buttons={},events={},timers=new Map();let timerId=0,route=['query-report',name],fetches=0,resolveResult;
 const nodes={};function node(selector){return nodes[selector]??={value:selector==='.tjy-inline-sheet'?'BLANK':'',html(v){if(v===undefined)return this.value;this.value=v;return this;},text(v){this.value=v;return this;},css(){return this;},hide(){this.hidden=true;return this;}};}
 const report={data:[{week_name:'June'}],filters:{week_name:'June'},$report_message:{find:node,css(){return this;}},$report:node('report'),
 get_filter_value(k){return this.filters[k];},async set_filter_value(values){Object.assign(this.filters,values);},async refresh(){this.refreshes=(this.refreshes||0)+1;},
 page:{set_title(){},add_inner_button(label,click){const b={click,disabled:false,prop(k,v){this[k]=v;return this;}};buttons[label]=b;return b;}}};
 const frappe={query_reports:{},query_report:report,get_route:()=>route,utils:{escape_html:String},router:{on:(key,fn)=>events[key]=fn},db:{get_list:async()=>[]},
 call:async({method})=>({message:method.endsWith('generate')?{report_id:'a'.repeat(64),expires_at:Date.now()/1000+900}:{ok:true}}),msgprint(){},show_alert(){},set_route(){}};
 const context={frappe,__:s=>s,window:{addEventListener:(key,fn)=>events[key]=fn,location:{assign:url=>events.download=url}},fetch:()=>{fetches++;return new Promise(resolve=>resolveResult=resolve);},
 setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id),Date,console};
 vm.runInNewContext(code,context);const settings=frappe.query_reports[name];
 return {buttons,events,nodes,node,report,settings,timers,setRoute:r=>route=r,fetches:()=>fetches,
 ready:()=>resolveResult({ok:true,json:async()=>({message:{status:'ready',sheet_html:'READY',expires_at:Date.now()/1000+900}})}),pending:()=>resolveResult({ok:true,json:async()=>({message:{status:'pending'}})})};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const f=fixture();await f.settings.onload(f.report);f.settings.after_refresh(f.report);
 assert.equal(f.nodes.report.hidden,true);assert.equal(f.buttons['下载带量分析Excel'].disabled,true);
 const job=f.buttons['生成AI营养分析'].click();await tick();assert.equal(f.fetches(),1);
 f.ready();await job;assert.equal(f.node('.tjy-inline-sheet').value,'READY');assert.equal(f.buttons['下载带量分析Excel'].disabled,false);
 f.buttons['下载带量分析Excel'].click();assert.ok(f.events.download.endsWith('a'.repeat(64)));
 const expiry=[...f.timers.values()].find(t=>t.delay>10000);expiry.fn();assert.equal(f.node('.tjy-inline-sheet').value,'BLANK');assert.equal(f.buttons['下载带量分析Excel'].disabled,true);
 const g=fixture();await g.settings.onload(g.report);g.settings.after_refresh(g.report);
 const stale=g.buttons['生成AI营养分析'].click();await tick();g.report.filters.week_start='2026-10-26';await g.settings.filters[0].on_change(g.report);
 g.ready();await stale;assert.equal(g.node('.tjy-inline-sheet').value,'BLANK');assert.equal(g.report.filters.week_name,'');assert.equal(g.buttons['下载带量分析Excel'].disabled,true);
 const h=fixture();await h.settings.onload(h.report);h.settings.after_refresh(h.report);
 const leaving=h.buttons['生成AI营养分析'].click();await tick();h.setRoute(['List','Employee']);h.events.change();h.ready();await leaving;
 assert.equal(h.node('.tjy-inline-sheet').value,'BLANK');assert.equal(h.buttons['打印带量分析'].disabled,true);
 console.log('UI lifecycle passed: inline result, download, expiry, source switch, route leave.');
})().catch(error=>{console.error(error);process.exitCode=1;});
