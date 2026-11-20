/** Actual native UI boot without printing login data. */
import { chromium } from '/home/zyd/frappe/deepseek-harness/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
const browser = await chromium.launch({ executablePath: '/snap/bin/chromium', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
const split = data.cookie.indexOf('=');
await context.addCookies([{ name: data.cookie.slice(0, split), value: data.cookie.slice(split + 1),
  domain: 'harness.myyr.top', path: '/', secure: true, httpOnly: true, sameSite: 'Strict' }]);
const page = await context.newPage();
const errors = [], failures = [];
const calls = [];
page.on('request', req => {
  const path = new URL(req.url()).pathname;
  if (path === '/native/view' || path === '/employee/session/prompt')
    calls.push({path,sessionId:req.postDataJSON()?.sessionId});
});
page.on('pageerror', error => errors.push(error.message.slice(0, 220)));
page.on('response', response => {
  if (response.status() >= 400) failures.push({ path: new URL(response.url()).pathname, status: response.status() });
});
try {
  await page.goto('https://harness.myyr.top/native/');
  await page.waitForTimeout(7000);
  await page.getByRole('button').filter({hasText:'新会话'}).first().click({timeout: 5000});
  await page.getByRole('button', {name:'选择工作区',exact:true}).click({timeout:5000});
  await page.getByText('童健云',{exact:true}).last().click({timeout:5000});
  await page.waitForTimeout(9000);
  await page.locator('[contenteditable=true]').fill('只回复“原生界面连接正常”。不要查询或修改业务数据。');
  await page.locator('[contenteditable=true]').press('Enter');
  await page.getByText(/^[“"]?原生界面连接正常[。！!]?[”"]?$/).waitFor({timeout:45000});
  await page.waitForTimeout(2000);
  if (await page.getByText('只回复“原生界面连接正常”。不要查询或修改业务数据。', {exact:true}).count() !== 1)
    throw new Error('Duplicate user echo');
  const sessionId = calls.find(row=>row.path.includes('prompt'))?.sessionId;
  if (!sessionId) throw new Error('No owned session');
  const commands = await page.evaluate(async sessionId => {
    const invoke = async (method, request) => {
      const response = await window.__DSH_TRANSPORT__.fetch('', {body:JSON.stringify({
        rpcId:crypto.randomUUID(),method,payload:{args:{request}},
      }),signal:new AbortController().signal});
      return (await response.json()).result;
    };
    return [await invoke('session/rename',{sessionId,title:'原生会话操作验收'}),
      await invoke('session/cancel',{sessionId})];
  },sessionId);
  if (commands.some(result=>!result.ok)) throw new Error('Owned command failed');
  await page.getByText('原生会话操作验收',{exact:true}).first().waitFor({timeout:10000});
  const currentModel = await page.evaluate(async()=>{
    const response=await fetch('/native/models');
    if(!response.ok)throw new Error('model catalog unavailable');
    return (await response.json()).default.model;
  });
  await page.getByRole('button').filter({hasText:currentModel}).last().click({timeout:10000});
  await page.waitForTimeout(500);
  await page.screenshot({ path: '/home/zyd/frappe/backups/harness/application-preview-20260908/native-ui.png' });
  if (errors.length || failures.length) throw new Error('Native browser errors');
  console.log(JSON.stringify({passed:true, uniqueUserEcho:true, modelReply:true, rename:true, cancelAcknowledged:true, modelSelectorOpened:true, errors, failures}));
} catch (error) {
  await page.screenshot({ path: '/home/zyd/frappe/backups/harness/application-preview-20260908/native-ui.png' });
  console.log(JSON.stringify({ passed:false, error:error.message.slice(0,200), errors, failures,
    prompts:calls.filter(row=>row.path.includes('prompt')), calls:calls.slice(-4) }));
  process.exitCode=1;
} finally { await browser.close(); }
