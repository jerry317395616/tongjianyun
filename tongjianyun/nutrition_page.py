"""Temporary browser-only viewer. No local storage, persistence or analytics."""
import json
import secrets


def render(report_id, csrf_token):
    nonce = secrets.token_urlsafe(24)
    html = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">
<title>临时AI食谱营养分析</title><style nonce="NONCE">
:root{font:100%/1.7 system-ui,sans-serif;color:CanvasText;background:Canvas;color-scheme:light dark}
body{margin:0}main{max-width:90rem;margin:auto;padding:1.5rem}h1{font-size:1.7rem}h2{font-size:1.25rem}
a{color:LinkText}button{font:inherit;background:ButtonFace;color:ButtonText;padding:.5rem .9rem;border:1px solid GrayText;border-radius:.35rem;cursor:pointer}
button:disabled{cursor:default}.actions{display:flex;gap:1rem;align-items:center;flex-wrap:wrap}.table{overflow-x:auto;margin:1rem 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{border:1px solid GrayText;padding:.5rem;text-align:left;vertical-align:top;min-width:6rem;overflow-wrap:anywhere}
th{font-weight:600}.notice{border:1px solid GrayText;border-radius:.4rem;padding:1rem}p,li{overflow-wrap:anywhere}a:focus-visible,button:focus-visible{outline:3px solid Highlight;outline-offset:3px}
</style><main><h1>临时AI食谱营养分析</h1>
<p class="notice">AI估算，仅供膳食安排参考。按每名幼儿计划配方毛重分析，未实测实际摄入。资料来自模型通用知识，未联网核验；区间、假设及缺项均由大模型给出。营养值不写入ERP或长期聊天记录。</p>
<p id="status" role="status" aria-live="polite">正在读取分析进度…</p><p id="expiry"></p>
<div class="actions"><a id="download" hidden>下载Excel</a><button id="refresh" type="button">刷新进度</button><button id="clear" type="button">立即清除临时结果</button></div>
<div id="report"></div></main><script nonce="NONCE">
'use strict';
const id='REPORT_ID', csrf=CSRF_TOKEN, base='/api/method/tongjianyun.weekly_nutrition_api.', status=document.getElementById('status'), root=document.getElementById('report');
let timer=null,expiryTimer=null,busy=false,done=false;
function expire(){done=true;clearTimeout(timer);root.replaceChildren();document.getElementById('download').hidden=true;status.textContent='临时结果已过期并清除，请重新生成。';}
const range=x=>x===null?'未知／未完整估算':x.map(n=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:3})).join('–');
function node(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.append(e);return e;}
function table(title,headers,rows){node('h2',title,root);const wrap=node('div',undefined,root);wrap.className='table';const t=node('table',undefined,wrap),h=node('tr',undefined,node('thead',undefined,t));headers.forEach(x=>{const th=node('th',x,h);th.scope='col';});const body=node('tbody',undefined,t);rows.forEach(row=>{const tr=node('tr',undefined,body);row.forEach(x=>node('td',String(x),tr));});}
async function load(){if(busy||done)return;busy=true;clearTimeout(timer);try{
const response=await fetch(base+'result?report_id='+id,{credentials:'same-origin',cache:'no-store',redirect:'error'});if(!response.ok)throw Error();const p=(await response.json()).message;if(!p?.ok)throw Error();
document.getElementById('expiry').textContent='临时结果有效至 '+new Date(p.expires_at*1000).toLocaleString('zh-CN')+'；过期后自动清除。下载到本机的文件由你保管。';clearTimeout(expiryTimer);expiryTimer=setTimeout(expire,Math.max(0,p.expires_at*1000-Date.now()));
if(p.status==='pending'){status.textContent='大模型正在分析，请稍候。';timer=setTimeout(load,4000);return;}
if(p.status!=='ready'){status.textContent='本次分析未成功。请返回膳食助手或食谱分析页重新生成。';return;}
const markup=document.createElement('template');markup.innerHTML=p.sheet_html;markup.content.querySelectorAll('style').forEach(e=>e.nonce='NONCE');root.replaceChildren(markup.content);
const a=document.getElementById('download');a.href=base+'download?report_id='+id;a.hidden=false;status.textContent='分析完成。预览和Excel使用同一份临时结果。';
}catch{root.replaceChildren();document.getElementById('download').hidden=true;status.textContent='结果已过期、食谱已变化、登录失效或服务暂时不可用。请重新登录后生成报告。';}finally{busy=false;}}
document.getElementById('refresh').onclick=load;
document.getElementById('clear').onclick=async()=>{try{const response=await fetch(base+'discard',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':csrf},body:JSON.stringify({report_id:id})});if(!response.ok)throw Error();done=true;clearTimeout(timer);root.replaceChildren();document.getElementById('download').hidden=true;status.textContent='临时结果已清除。';}catch{status.textContent='暂时无法清除；结果仍会在到期时自动清除。';}};
window.addEventListener('pagehide',()=>{clearTimeout(timer);root.replaceChildren();});window.addEventListener('pageshow',load);
</script></html>'''.replace('NONCE', nonce).replace('REPORT_ID', report_id).replace('CSRF_TOKEN', json.dumps(csrf_token).replace('<', '\\u003c'))
    return html, f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
