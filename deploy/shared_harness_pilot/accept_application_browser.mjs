/** Actual browser confirmation; the private cookie arrives only over stdin. */
import { chromium } from '/home/zyd/frappe/deepseek-harness/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const data = JSON.parse(input);
let browser;
let stage = 'launch';
let page;
const requests = [], errors = [];
try {
  browser = await chromium.launch({ executablePath: '/snap/bin/chromium', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
  const split = data.cookie.indexOf('=');
  await context.addCookies([{ name: data.cookie.slice(0, split), value: data.cookie.slice(split + 1),
    domain: 'harness.myyr.top', path: '/', secure: true, httpOnly: true, sameSite: 'Strict' }]);
  page = await context.newPage();
  page.on('pageerror', () => errors.push('pageerror'));
  page.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (/^\/employee\/(status|session\/(page|capabilities|review|confirm)|chat\/(chat\.mjs|client\.mjs)?)$/.test(path))
      requests.push({ path, status: response.status() });
  });
  stage = 'navigate';
  await page.goto('https://harness.myyr.top/employee/chat/#' + data.sessionId);
  stage = 'review';
  const card = page.locator('.approval').filter({ hasText: data.preview_id });
  await card.waitFor({ timeout: 30000 });
  if (!await card.getByRole('button', { name: '确认执行', exact: true }).isDisabled()) throw new Error('consent missing');
  stage = 'confirm';
  await card.getByRole('checkbox').check();
  await card.getByRole('button', { name: '确认执行', exact: true }).click();
  await card.getByText('执行成功', { exact: true }).waitFor({ timeout: 30000 });
  await page.waitForFunction(() => document.getElementById('refresh').disabled === false);
  await page.screenshot({ path: '/home/zyd/frappe/backups/harness/application-preview-20260908/confirmation.png', fullPage: true });
  if (errors.length) throw new Error('browser page errors');
  console.log(JSON.stringify({ browser_passed: true, consent_required: true, receipt_visible: true }));
} catch {
  await page?.screenshot({ path: '/home/zyd/frappe/backups/harness/application-preview-20260908/browser-failure.png' }).catch(() => {});
  console.log(JSON.stringify({ browser_passed: false, stage, requests, page_errors: errors.length }));
  process.exitCode = 1;
} finally {
  await browser?.close();
}
