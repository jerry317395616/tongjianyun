const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../tongjianyun/page/tongjianyun_recipe_workbench/tongjianyun_recipe_workbench.js'), 'utf8');

async function fixture() {
    const dialogs = [], calls = [];
    const button = {prop(k,v) {this[k]=v; return this;}, text(v) {this.label=v; return this;}};
    const errorBox = {text(v) {this.message=v;}};
    let start = async () => ({message:{status:'queued'}});
    const frappe = {pages:{'tongjianyun-recipe-workbench':{}}, utils:{escape_html:String}, msgprint() {},
        call: async options => {
            calls.push(options);
            if (options.method.endsWith('.start')) return start();
            return {message:{scope:{company:'School',warehouse:'W'}, revision:'R1', unmatched:0, meals:[{count:null}]}};
        }, ui:{Dialog:class {
            constructor(options) {Object.assign(this,options); this.$wrapper={find:()=>errorBox}; dialogs.push(this);}
            show() {} hide() {this.hidden=true;} get_primary_btn() {return button;}
        }}
    };
    const context=vm.createContext({frappe, console});
    vm.runInContext(source+'\nthis.Page=TongjianyunRecipePage;',context);
    const controller=Object.create(context.Page.prototype);
    controller.state={selectedRecipe:'RECIPE'};
    controller.refreshExecution=()=>{};
    await controller.executeRecipe();
    return {dialog:dialogs[0],calls,button,errorBox,setStart(fn) {start=fn;}};
}

test('opening or not confirming facts never starts financial work',async()=>{
    const f=await fixture();
    await f.dialog.primary_action({facts:0});
    assert.equal(f.calls.length,1);
    assert.ok(f.calls[0].method.endsWith('.inspect'));
});

test('double confirmation enqueues once and preserves zero people',async()=>{
    const f=await fixture();
    let resolve;
    f.setStart(()=>new Promise(r=>{resolve=r;}));
    const pending=f.dialog.primary_action({facts:1, fallback_count:0, include_history:1});
    await f.dialog.primary_action({facts:1, fallback_count:0});
    assert.equal(f.calls.filter(x=>x.method.endsWith('.start')).length,1);
    assert.equal(f.calls[1].args.fallback_count,0);
    resolve({message:{status:'queued'}});
    await pending;
    assert.equal(f.dialog.hidden,true);
});

test('enqueue error stays visible and restores confirmation control',async()=>{
    const f=await fixture();
    f.setStart(async()=>{throw new Error('queue unavailable');});
    await f.dialog.primary_action({facts:1, fallback_count:20});
    assert.match(f.errorBox.message,/queue unavailable/);
    assert.equal(f.button.disabled,false);
    assert.equal(f.dialog.hidden,undefined);
});
