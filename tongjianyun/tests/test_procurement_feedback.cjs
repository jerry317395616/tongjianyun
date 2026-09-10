// Regression checks for the real async review action; no server requests or writes.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../tongjianyun/page/tongjianyun_recipe_workbench/tongjianyun_recipe_workbench.js'), 'utf8');

async function reviewFixture() {
    const dialogs = [], calls = [];
    const input = {value: '0.02', dataset: {priceKey: 'key', label: '西芹', uom: 'g', qty: '1650'}, focus() {}, scrollIntoView() {}};
    function element() {
        return {value: '', disabled: false, text(value) { this.value = value; return this; },
            removeClass() {return this;}, addClass() {return this;}, prependTo(footer) {footer.status = this; return this;},
            prop(key, value) {this[key] = value; return this;}, closest() {return this;}, find() {return this;}};
    }
    const plan = {token:'preview', transaction_date:'2026-09-10', price_precision:2, price_currency:'CNY',
        lines:[{price_key:'key', item_code:'CELERY', item_name:'西芹', uom:'g', qty:1650, unit_price:0.02, schedule_date:'2026-09-10'}]};
    const prepared = {ingredients:[{key:'mapped', item_code:'CELERY', factor:1, uom:'g'}],
        meals:[{key:'2026-09-10:lunch', date:'2026-09-10', slot:'lunch'}], as_of_date:'2026-09-10'};
    let complete = async () => {throw {status:500};};
    const frappe = {pages:{'tongjianyun-recipe-workbench':{}}, msgprint() {},
        utils:{escape_html: String, get_form_link:(dt,name)=>name},
        call: async (options) => {
            const method = options.method.split('.').pop();
            calls.push(method);
            if (method === 'create_purchase') return {message: await complete()};
            return {message: {revision_impact:{}, default_scope:{company:'School', warehouse:'W'}, prepare:prepared, preview:plan}[method]};
        },
        ui:{Dialog: class {
            constructor(options) {
                Object.assign(this,options); this.footer = {}; this.button = element();
                this.$wrapper = {on() {}, find(selector) {return selector === '.tjy-procurement-price' ? {each(fn) {fn.call(input);}} : element();}};
                dialogs.push(this);
            }
            show() {} hide() {this.hidden = true;} get_primary_btn() {return this.button;}
        }},
    };
    const context = vm.createContext({frappe, $:element, console, flt:(n,p)=>Math.round(n * 10**p)/10**p});
    vm.runInContext(source + '\nthis.Page = TongjianyunRecipePage; this.errorMessage = procurementErrorMessage;', context);
    const controller = Object.create(context.Page.prototype);
    controller.state = {selectedRecipe:'R'};
    controller.procurementDayRows = () => [];
    controller.procurementMealCounts = () => ({'2026-09-10:lunch':'33'});
    await controller.openProcurement();
    await dialogs[0].primary_action({ingredients:prepared.ingredients, meal_days:[], include_history:0});
    return {review:dialogs[1], input, calls, context, setComplete(fn) {complete = fn;}};
}

test('tiny price shows an inline error without requesting procurement', async () => {
    const fixture = await reviewFixture();
    fixture.input.value = '0.000003';
    await fixture.review.primary_action();
    assert.match(fixture.review.footer.status.value, /西芹.*过小.*为 0/);
    assert.equal(fixture.calls.includes('create_purchase'), false);
});

test('HTTP failure is caught, prices preserved and retry enabled', async () => {
    const fixture = await reviewFixture();
    fixture.setComplete(async () => {throw {status:417, responseJSON:{_server_messages:JSON.stringify([JSON.stringify({message:'西芹采购价过小'})])}};});
    await fixture.review.primary_action();
    assert.match(fixture.review.footer.status.value, /采购闭环未完成.*西芹采购价过小/);
    assert.equal(fixture.input.value, '0.02');
    assert.equal(fixture.review.button.disabled, false);
    assert.equal(fixture.review.procurementSubmitting, false);
});

test('in-flight duplicate click is ignored and success closes review', async () => {
    const fixture = await reviewFixture();
    let finish;
    fixture.setComplete(() => new Promise(resolve => {finish = resolve;}));
    const pending = fixture.review.primary_action();
    assert.equal(fixture.review.button.disabled, true);
    assert.match(fixture.review.footer.status.value, /正在保存单价/);
    await fixture.review.primary_action();
    assert.equal(fixture.calls.filter(method => method === 'create_purchase').length, 1);
    finish({purchase_orders:['PO'], purchase_receipts:['PR'], purchase_invoices:['PI'], payment_entries:['PE']});
    await pending;
    assert.equal(fixture.review.hidden, true);
    assert.equal(fixture.review.button.disabled, false);
});
