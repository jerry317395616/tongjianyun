const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(process.argv[2], 'utf8');
const start = source.indexOf('    procurementDayRows(');
const end = source.indexOf('    async openProcurement()', start);
const context = {Object, Set, String, MEAL_LABELS: {breakfast:'早餐', lunch:'午餐', dinner:'晚餐'}};
vm.createContext(context);
vm.runInContext('this.Page = class {' + source.slice(start, end) + '}', context);
const page = new context.Page();
const meals = [
    {date:'2026-09-07', slot:'lunch', key:'2026-09-07:lunch', count:null},
    {date:'2026-09-09', slot:'breakfast', key:'2026-09-09:breakfast', count:0},
    {date:'2026-09-09', slot:'lunch', key:'2026-09-09:lunch', count:20},
    {date:'2026-09-10', slot:'lunch', key:'2026-09-10:lunch', count:null},
];
const days = page.procurementDayRows(meals);
assert.equal(days.length, 3);
assert.equal(days[1].breakfast, '0');
assert.equal(days[2].lunch, '');
page.fillProcurementCounts(meals, days, 30, false, '2026-09-09');
let values = page.procurementMealCounts(meals, days);
assert.equal(values['2026-09-07:lunch'], '');
assert.equal(values['2026-09-09:breakfast'], '0');
assert.equal(values['2026-09-09:lunch'], '20');
assert.equal(values['2026-09-10:lunch'], '30');
assert.equal(days[2].dinner, undefined);
page.fillProcurementCounts(meals, days, 10, true, '2026-09-09');
values = page.procurementMealCounts(meals, days);
assert.equal(values['2026-09-07:lunch'], '10');
assert.equal(values['2026-09-10:lunch'], '30');
assert.equal(Object.keys(values).length, meals.length);
assert(!source.includes('if (!values.confirmed)'));
assert(source.includes('食材明细与高级设置（通常无需操作）'));
console.log('Simplified procurement checks passed: daily rows, round trip, missing vs zero, non-overwrite, history scope, nonexistent meals');
