/** Submit a synthetic image through the actual native composer. */
import { chromium } from '/home/zyd/frappe/deepseek-harness/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
let raw=''; for await(const chunk of process.stdin) raw+=chunk;
const data=JSON.parse(raw);
const browser=await chromium.launch({executablePath:'/snap/bin/chromium',headless:true});
try {
  const context=await browser.newContext();
  const split=data.cookie.indexOf('=');
  await context.addCookies([{name:data.cookie.slice(0,split),value:data.cookie.slice(split+1),domain:'harness.myyr.top',path:'/',secure:true,httpOnly:true,sameSite:'Strict'}]);
  const page=await context.newPage();
  const errors=[];page.on('pageerror',()=>errors.push('pageerror'));
  await page.goto('https://harness.myyr.top/native/');
  await page.getByRole('button').filter({hasText:'新会话'}).first().click({timeout:20000});
  await page.getByRole('button',{name:'选择工作区',exact:true}).click();
  await page.getByText('童健云',{exact:true}).last().click();
  await page.waitForResponse(response=>new URL(response.url()).pathname==='/native/view' && response.status()===200,{timeout:20000});
  await page.evaluate(png=>{
    const transfer=new DataTransfer();
    transfer.items.add(new File([Uint8Array.from(atob(png),c=>c.charCodeAt(0))],'synthetic-red.png',{type:'image/png'}));
    document.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
  },data.png);
  await page.waitForFunction(()=>[...document.images].some(image=>image.alt==='synthetic-red.png' && image.naturalWidth>0),{},{timeout:10000});
  await page.locator('[contenteditable=true]').fill('What is the dominant color? Reply with only the color name. Do not use tools.');
  const responsePromise=page.waitForResponse(response=>new URL(response.url()).pathname==='/employee/session/prompt',{timeout:95000});
  await page.locator('[contenteditable=true]').press('Enter');
  const response=await responsePromise;
  if(response.status()!==200)throw new Error('Image prompt HTTP '+response.status());
  await page.getByText(/^red[.!]?$/i).first().waitFor({timeout:15000});
  const sessionId=response.request().postDataJSON().sessionId;
  const view=await page.evaluate(async sessionId=>(await fetch('/native/view',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sessionId,maxMessages:50})})).json(),sessionId);
  const digest=JSON.stringify(view).match(/sha256:[a-f0-9]{64}/)?.[0];
  if(!digest)throw new Error('No durable image reference');
  const read=await page.evaluate(async value=>{
    const response=await fetch('/native/attachment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
    const result=await response.json();return {status:response.status,hasData:typeof result.data==='string' && result.data.length>0};
  },{sessionId,attachmentId:digest});
  if(read.status!==200 || !read.hasData || errors.length)throw new Error('Image read or browser failure');
  console.log(JSON.stringify({passed:true,sessionId,attachmentId:digest,modelRecognizedRed:true,nativeComposer:true,ownedRead:true}));
}catch(error){console.log(JSON.stringify({passed:false,error:error.message.slice(0,200)}));process.exitCode=1;}
finally{await browser.close();}
