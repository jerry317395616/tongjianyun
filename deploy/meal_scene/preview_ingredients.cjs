/* Read-only loopback fixture for browser acceptance. No production sessions or data.
 * Run `node deploy/meal_scene/preview_ingredients.cjs`, then use the printed URL.
 * All non-GET requests are refused, including chat sends and file uploads.
 */
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),publicRoot=path.join(root,'tongjianyun/public');
const slots=['breakfast','morningSnack','lunch','snack','dinner'];
const payload={recipe:{recipeId:'DEMO-WEEK',title:'验收示例食谱',weekStart:'2026-09-21',weekEnd:'2026-09-25',workflowStatus:'草稿'},days:Array.from({length:5},(_,i)=>({date:'2026-09-'+(21+i),portions:slots.map((slot,index)=>({slot,dishes:index===2?['米饭','鱼香肉丝','清炒西兰花','番茄鸡蛋汤']:index===0?['小米粥','奶香馒头']:index===1?['苹果']:index===3?['纯牛奶']:['杂粮饭','清炒时蔬'],dishIngredientRows:index===2?[{dishName:'米饭',ingredient:'大米',amount:40+i,unit:'g'},{dishName:'鱼香肉丝',ingredient:'猪肉',amount:30,unit:'g'},{dishName:'鱼香肉丝',ingredient:'胡萝卜',amount:20,unit:'g'},{dishName:'清炒西兰花',ingredient:'西兰花',amount:50,unit:'g'},{dishName:'番茄鸡蛋汤',ingredient:'番茄',amount:30,unit:'g'},{dishName:'番茄鸡蛋汤',ingredient:'鸡蛋',amount:15,unit:'g'}]:index===3?[{dishName:'纯牛奶',ingredient:'牛奶',amount:150,unit:'ml'}]:[]}))}))};
const recipe={name:'DEMO-WEEK',title:'验收示例食谱',workflow_status:'草稿',week_start:'2026-09-21',week_end:'2026-09-25'};
const server=http.createServer((req,res)=>{
  res.setHeader('Cache-Control','no-store');
  if(req.method!=='GET'){res.writeHead(405);return res.end('Read-only acceptance fixture');}
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/tongjianyun-meal-scene'){
    res.setHeader('Content-Type','text/html; charset=utf-8');
    return res.end(fs.readFileSync(path.join(root,'tongjianyun/www/tongjianyun-meal-scene.html'),'utf8').replace('{{ csrf_token | e }}','synthetic-not-a-credential'));
  }
  if(url.pathname.startsWith('/assets/tongjianyun/')){
    const asset=path.resolve(publicRoot,url.pathname.slice('/assets/tongjianyun/'.length));
    if(!asset.startsWith(publicRoot+path.sep)||!fs.existsSync(asset)||!fs.statSync(asset).isFile()){res.writeHead(404);return res.end();}
    res.setHeader('Content-Type',({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[path.extname(asset)]||'application/octet-stream');
    return res.end(fs.readFileSync(asset));
  }
  let message;
  if(url.pathname==='/api/method/tongjianyun.meal_scene.get_overview'){
    const day=url.searchParams.get('day')||'2026-09-23',meal=url.searchParams.get('meal')||'lunch';
    message={day,meal,user_label:'验收示例账号',recipes:{available:true,rows:day>=recipe.week_start&&day<=recipe.week_end?[recipe]:[]},capabilities:{recipe:true,recipe_write:true}};
  }else if(url.pathname==='/api/method/tongjianyun.meal_scene.get_recipe')message={name:recipe.name,payload,edit:{mode:'update'}};
  else if(url.pathname==='/api/method/tongjianyun.meal_chat.get_chat_access')message={allowed:true};
  else if(url.pathname==='/api/method/tongjianyun.meal_chat.get_conversation')message={tasks:[]};
  else{res.writeHead(404);return res.end();}
  res.setHeader('Content-Type','application/json');res.end(JSON.stringify({message}));
});
server.listen(0,'127.0.0.1',()=>console.log(`http://127.0.0.1:${server.address().port}/tongjianyun-meal-scene?day=2026-09-23&meal=lunch`));
