const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../tongjianyun/page/tongjianyun_recipe_workbench/tongjianyun_recipe_workbench.js'), 'utf8');

test('browse header has no secondary processing menu', () => {
    const header = source.slice(source.indexOf('    showBrowse()'), source.indexOf('    renderBrowseCell('));
    for (const label of ['更多处理', '食材物料匹配结果', '食材用途确认', 'erp-procurement']) assert.ok(!header.includes(label));
    assert.ok(header.includes('execute-recipe'));
});

for (const [status, stage, expected] of [['failed','食材匹配',true], ['interrupted','食材匹配',true], ['running','食材匹配',false], ['completed','完成',false], ['failed','校验人数与价格',false]]) {
    test(`${status}/${stage}: contextual recovery ${expected}`, async () => {
        const appended = [], handlers = {};
        const element = {length:1, html(){return this;}, text(){return this;}, prop(){return this;}, append(value){appended.push(value);return this;}, find(){return this;}, on(event, fn){handlers[event]=fn;return this;}};
        const frappe = {pages:{'tongjianyun-recipe-workbench':{}}, utils:{escape_html:String}, call:async()=>({message:{status,stage}})};
        const context = vm.createContext({frappe,clearTimeout(){},setTimeout(){}});
        vm.runInContext(source+'\nthis.Page=TongjianyunRecipePage;',context);
        const page=Object.create(context.Page.prototype);
        page.state={selectedRecipe:'R'};
        page.main={find:()=>element};
        await page.refreshExecution();
        assert.equal(appended.some(html=>html.includes('data-resolve-ingredients')),expected);
        assert.equal(Boolean(handlers.click),expected);
    });
}
