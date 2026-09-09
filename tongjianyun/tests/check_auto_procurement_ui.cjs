const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('    async autoMatchProcurementItems(');
const end = source.indexOf('    async resolveIngredients(', start);
async function run(states, prepared, fail = false) {
    const calls = [], messages = [];
    class Dialog {
        constructor() { this.fields_dict = {progress: {$wrapper: {text: x => messages.push(x)}}}; }
        show() {}
        hide() { if(this.onhide) this.onhide(); }
    }
    const context = {Date, Object, Promise, setTimeout: f => f(), frappe: {
        ui: {Dialog}, msgprint: x => messages.push(x), show_alert: x => messages.push(x.message),
        call: async ({method}) => {
            calls.push(method);
            if(fail) throw Error('network');
            return {message: method.endsWith('.prepare') ? prepared : states.shift()};
        },
    }};
    vm.createContext(context);
    vm.runInContext('this.Page = class {' + source.slice(start, end) + '}', context);
    const result = await new context.Page().autoMatchProcurementItems('recipe', 'company');
    return {result, calls, messages};
}
(async () => {
    const prepared = {ingredients: [{key:'a', item_code:'ITEM'}]};
    const done = await run([{status:'queued'}, {status:'running'}, {status:'completed'}], prepared);
    assert.strictEqual(done.result, prepared);
    assert.strictEqual(done.calls.filter(x => x.endsWith('auto_match_items')).length, 1);
    assert.strictEqual(done.calls.at(-1), 'tongjianyun.recipe_procurement.prepare');
    for(const status of ['failed', 'blocked', 'stale']) {
        const outcome = await run([{status}], prepared);
        assert.strictEqual(outcome.result, null);
        assert(!outcome.calls.some(x => x.endsWith('.prepare')));
    }
    const partial = await run([{status:'partial', unresolved:[{key:'b', reason:'需确认用途'}]}], {ingredients:[{key:'b', item_code:''}]});
    assert.strictEqual(partial.result.ingredients[0].basis, '需确认用途');
    assert.strictEqual((await run([], prepared, true)).result, null);
    assert(!source.includes('首次出现的食材：快速新建物料'));
    console.log('UI controller checks passed: completion, active polling, errors, stale state, partial reasons, removed manual creation');
})();
