import * as THREE from 'three';
import {OrbitControls} from '/assets/tongjianyun/campus/vendor/OrbitControls.js';
import {VisualKit} from '/assets/tongjianyun/classroom/visual-kit.js?v=refined-20260923-1';
import {STEPS,stepBadge} from './state.js?v=meal-flow-20260923-1';

// Presentation only. No network calls, account identity, counters or business writes.
export class MealScene {
  constructor(host,labels,callbacks){
    Object.assign(this,{host,labels,callbacks,disposed:false,frame:null,tags:[],lastHover:0});
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#eaf0e5');
    this.renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,innerWidth<760?1.25:1.6));
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.04;
    this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;this.renderer.shadowMap.autoUpdate=false;
    host.appendChild(this.renderer.domElement);this.k=new VisualKit(this.renderer);
    this.scene.add(new THREE.HemisphereLight('#fff8e7','#a9b6a3',1.45));
    const sun=new THREE.DirectionalLight('#fff1d3',2.8);sun.position.set(-15,25,14);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-24,right:24,top:22,bottom:-22,near:.5,far:75});sun.shadow.normalBias=.035;this.scene.add(sun);
    const fill=new THREE.DirectionalLight('#ddeffc',.6);fill.position.set(12,12,-5);this.scene.add(fill);
    this.camera=new THREE.OrthographicCamera(-20,20,13,-13,.1,180);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=true;this.controls.dampingFactor=.17;this.controls.minZoom=.7;this.controls.maxZoom=2.5;this.controls.minPolarAngle=.06;this.controls.maxPolarAngle=Math.PI/2-.25;
    this.controlChange=()=>this.invalidate();this.controls.addEventListener('change',this.controlChange);
    this.root=new THREE.Group();this.scene.add(this.root);this.build();this.releaseBatch=this.k.batch(this.root);
    this.highlight=this.k.ring(this.scene,0,.09,0,2.9,.028,'#f9c867');this.highlight.rotation.x=-Math.PI/2;this.highlight.visible=false;this.highlight.castShadow=false;
    this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();
    STEPS.forEach(step=>this.tag(step));
    this.down=e=>{if(e.isPrimary!==false)this.pointerStart=[e.clientX,e.clientY];};
    this.up=e=>{if(this.pointerStart&&Math.hypot(e.clientX-this.pointerStart[0],e.clientY-this.pointerStart[1])<6){const id=this.hit(e);if(id)this.callbacks.onSelect(id);}this.pointerStart=null;};
    this.move=e=>{if(e.buttons||performance.now()-this.lastHover<80)return;this.lastHover=performance.now();this.renderer.domElement.style.cursor=this.hit(e)?'pointer':'grab';};
    this.cancel=()=>{this.pointerStart=null;};
    this.lost=e=>{e.preventDefault();this.contextLost=true;if(this.frame!==null)cancelAnimationFrame(this.frame);this.frame=null;this.callbacks.onFailure();};
    host.addEventListener('pointerdown',this.down);host.addEventListener('pointerup',this.up);host.addEventListener('pointermove',this.move);host.addEventListener('pointercancel',this.cancel);this.renderer.domElement.addEventListener('webglcontextlost',this.lost);
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(host);
    this.visible=()=>{if(!document.hidden)this.invalidate();};document.addEventListener('visibilitychange',this.visible);
    this.setView('overview');this.resize();this.renderer.shadowMap.needsUpdate=true;host.dataset.version='meal-flow-20260923-1';
  }
  box(p,x,y,z,w,h,d,c,r=.04,kind='wood'){return this.k.box(p,x,y,z,w,h,d,c,r,kind);}
  text(p,x,y,z,w,h,text,color='#467462',key=text){
    return this.k.sign(p,x,y,z,w,h,'meal-text:'+key,(c,W,H)=>{
      c.fillStyle=color;c.textAlign='center';c.textBaseline='middle';c.font=`600 ${Math.min(H*.65,W/(text.length+.7))}px "Noto Sans CJK SC","Microsoft YaHei",sans-serif`;c.fillText(text,W/2,H/2,W*.95);
    });
  }
  plant(p,x,z,size=.7,y=0){const k=this.k;k.cyl(p,x,y+.17*size,z,.20*size,.34*size,'#d6b18a',.23*size);for(let i=0;i<5;i++){const a=i*2.4;k.limb(p,[x,y+.25*size,z],[x+Math.sin(a)*.20*size,y+(.6+i*.03)*size,z+Math.cos(a)*.18*size],.012*size,'#719271');const leaf=k.ball(p,x+Math.sin(a)*.18*size,y+(.57+i*.06)*size,z+Math.cos(a)*.18*size,.17*size,['#a7bf8c','#8baa7c'][i%2],[.6,1.5,.5]);leaf.rotation.z=Math.sin(a)*.6;}}
  tree(x,z,s=1){const p=this.root,k=this.k;k.cyl(p,x,.62*s,z,.085*s,1.25*s,'#b09a70');for(const [dx,dy,dz,r] of [[0,1.75,0,.64],[-.34,1.43,.05,.45],[.29,1.58,.15,.46]])k.ball(p,x+dx*s,dy*s,z+dz*s,r*s,'#a4bd8d',[.91,1.17,.87]);k.shadow(p,x,z,1.8*s,1.4*s,.12);}
  shelf(p,x,z,w=1.7){const k=this.k;this.box(p,x,.65,z,w,1.25,.50,'#d8bd8e');for(let i=0;i<3;i++){this.box(p,x,.12+i*.41,z+.27,w-.10,.055,.63,'#edd7ae');for(let j=0;j<4;j++){this.box(p,x-w*.34+j*w*.23,.29+i*.4,z+.13,w*.18,.28,.37,['#a9c6b1','#e5c18f','#c7bfd1','#c7d59f'][j],.015,'matte');}}}
  table(p,x,z,w=1.7,d=.8){this.box(p,x,.91,z,w,.12,d,'#d0dfe0',.04,'metal');for(const dx of [-w*.42,w*.42])for(const dz of [-d*.36,d*.36])this.k.cyl(p,x+dx,.45,z+dz,.032,.9,'#a7bec0',.032,'metal');}
  screen(p,x,y,z,w=1.5,h=1,title=''){this.box(p,x,y,z,w,h,.11,'#6c998b');this.box(p,x,y,z+.07,w-.10,h-.11,.025,'#dfede0',.012,'matte');if(title)this.text(p,x,y+h*.29,z+.09,w*.87,h*.18,title,'#487765');for(let i=0;i<3;i++){this.box(p,x+w*.04,y+h*.05-i*h*.18,z+.10,w*.66,.018,.018,'#b5cbb6',0,'matte');this.k.ball(p,x-w*.37,y+h*.05-i*h*.18,z+.105,.025,'#92b49a',[1,1,.5]);}}
  tray(p,x,y,z){const k=this.k;this.box(p,x,y,z,.47,.038,.34,'#fcf3df',.014,'ceramic');this.box(p,x-.11,y+.032,z,.14,.013,.25,'#fff9ea',.009,'ceramic');for(let i=0;i<5;i++){const a=i*1.3;k.ball(p,x+.08+Math.cos(a)*.06,y+.055,z+Math.sin(a)*.08,.037,['#bdc986','#ddac64','#88b17e'][i%3],[1,.7,1]);}}
  chef(p,x,z,angle=0,shirt='#f7f2e4',child=false){
    const k=this.k,g=k.group(p,null,[x,0,z]);g.rotation.y=angle;const head=k.group(g,null,[0,1.34,0]);
    k.ball(head,0,0,0,.285,'#f1c59e',[1,1.04,.92],'skin');k.ball(head,0,.13,-.06,.288,'#75533b',[1,.75,.82],'hair');
    for(const sign of [-1,1]){k.ball(head,sign*.105,.01,.247,.045,'#4c3d31',[.8,1.05,.42],'eye');k.ball(head,sign*.105-.009,.025,.265,.010,'#fffaec',[1,1,.4]);k.ball(head,sign*.18,-.073,.205,.036,'#dea18d',[1,.5,.3],'skin');}
    k.curve(head,[[-.055,-.14,.227],[0,-.157,.249],[.055,-.14,.227]],.008,'#a77359','skin');
    k.ball(g,0,.86,0,.225,shirt,[1,1.35,.79],'fabric');this.box(g,0,.81,.155,.26,.37,.042,child?'#cfb888':'#a2c5b0',.02,'fabric');
    for(const s of [-1,1]){k.limb(g,[s*.12,.64,0],[s*.13,.13,.04],.075,child?'#c2b393':'#7d9193','fabric');this.box(g,s*.13,.10,.10,.18,.12,.28,'#f7eedb',.035,'matte');k.limb(g,[s*.19,1.01,0],[s*.28,.77,.12],.065,shirt,'fabric');k.limb(g,[s*.28,.77,.12],[s*.22,.88,.32],.050,shirt,'fabric');k.ball(g,s*.22,.88,.33,.06,'#efc59d',[1,.9,.8],'skin');}
    if(!child){k.cyl(head,0,.28,0,.282,.15,'#fffaf0',.27,'fabric');for(let i=0;i<5;i++){const a=i*Math.PI*2/5;k.ball(head,Math.cos(a)*.14,.43,Math.sin(a)*.12,.17,'#fffaf0',[1,1.02,.95],'fabric');}}else g.scale.setScalar(.70);
    return g;
  }
  cart(p,x,z,color='#9cc7bb'){
    const k=this.k,g=k.group(p,null,[x,0,z]);for(const y of [.22,.62,1.03])this.box(g,0,y,0,.85,.06,.61,color,.026,'metal');
    for(const xx of [-.37,.37])for(const zz of [-.24,.24]){k.cyl(g,xx,.66,zz,.02,1.25,'#a5b6b3',.02,'metal');const wheel=k.cyl(g,xx,.095,zz,.074,.043,'#627273',.074,'matte');wheel.rotation.z=Math.PI/2;}
    this.tray(g,-.20,1.085,0);this.tray(g,.21,1.085,0);return g;
  }
  building(step){
    const k=this.k,g=k.group(this.root,step.id,[step.point[0],0,step.point[2]]);
    this.box(g,0,.05,0,5.75,.13,4.75,'#d7d5bf',.06,'matte');this.box(g,0,.16,0,5.5,.15,4.4,'#f3ecda',.06);
    // Open-front dollhouse cutaway, not a surveyed floor plan.
    this.box(g,0,1.61,-1.91,5.55,2.85,.14,'#faf1df',.015,'matte');this.box(g,-2.70,1.53,-.25,.13,2.7,3.4,'#e8e9d6',.015,'matte');
    for(const x of [-2.67,2.67])this.box(g,x,1.65,1.88,.13,3.0,.17,'#f4e7cb',.02);
    this.box(g,0,3.11,-1.86,5.8,.21,.72,'#f7ecd8',.06);for(const x of [-2.74,2.74])this.box(g,x,3.11,0,.28,.21,4.35,'#f7ecd8',.03);this.box(g,0,3.22,-1.90,4.65,.11,.52,'#c1d0c5',.03,'metal');
    // Remove the middle roof visually: broad skylight strip lets light into the kitchen.
    this.box(g,0,3.12,1.96,5.83,.11,.21,'#f6efd9');this.box(g,0,3.03,2.10,5.30,.06,.025,step.color,.008,'matte');
    this.text(g,0,2.64,-1.81,3.9,.32,step.title,step.color,'wall-'+step.id);
    this.box(g,-1.97,1.87,-1.805,1.08,.72,.027,'#b9d8d8',.015,'matte');this.box(g,-1.97,1.87,-1.77,.035,.73,.023,'#fffbed',0);this.box(g,-1.97,1.87,-1.76,1.1,.035,.023,'#fffbed',0);
    this.plant(g,-2.38,1.83,.7);this.plant(g,2.40,1.83,.7);
    this.text(g,0,.32,2.40,4.8,.20,step.number<5?'计划与供给准备':'执行参考与结果核对','#a89c7f','row-'+(step.number<5));
    return g;
  }
  stationDetails(step,g){
    const k=this.k,id=step.id;
    if(id==='recipe'){
      this.screen(g,.45,1.75,-1.72,2.7,1.28,'每周食谱');
      for(let d=0;d<5;d++)for(let m=0;m<3;m++)this.box(g,-.54+d*.48,1.9-m*.24,-1.58,.36,.17,.02,['#c8d9ac','#e6c48f','#b6d3d0'][m],.01,'matte');
      this.table(g,.1,.55,2.7,.87);this.tray(g,-.5,1,.55);this.tray(g,.4,1,.55);this.chef(g,-1.50,.60,-.35);this.shelf(g,1.6,-.8,1.15);
      this.screen(g,-1.40,1.13,1.48,.7,.5,'配方');
    }else if(id==='purchase'){
      this.shelf(g,-1.65,-1.23,1.65);this.screen(g,.42,1.92,-1.73,2.6,.85,'采购需求 → 订单');this.table(g,.25,.15,2.2,1.1);
      for(let x=0;x<3;x++)this.box(g,-.37+x*.40,1.01,.22,.28,.035,.41,'#fff8e4',.005,'matte');
      this.screen(g,.76,1.32,.30,.63,.47,'需求');this.chef(g,-1.2,.70,.4);this.box(g,1.9,.50,.75,.83,.65,.67,'#debd84');this.box(g,1.9,.84,.75,.86,.06,.70,'#eed5a7');
    }else if(id==='receipt'){
      this.table(g,.15,.45,2.5,1.05);this.box(g,-.40,1.06,.45,.65,.20,.51,'#b8ceca',.026,'metal');this.screen(g,-.40,1.34,.33,.50,.35,'核对');
      for(const [x,z] of [[1,-.9],[1.85,-.7],[1.9,.4]]){this.box(g,x,.50,z,.68,.72,.64,'#dfc194');this.box(g,x,.85,z,.71,.05,.67,'#f0d7a4');}
      this.chef(g,-1.25,.80,.32);this.screen(g,-1.3,1.93,-1.7,1.3,.72,'原收货单');
    }else if(id==='stock'){
      this.shelf(g,-1.5,-1.08,1.8);this.shelf(g,.58,-1.08,1.8);this.shelf(g,1.52,.6,1.6);
      for(let i=0;i<3;i++){this.box(g,-.78+i*.56,.33,1.10,.43,.39,.49,'#dbbc88');k.ball(g,-.78+i*.56,.57,1.10,.18,['#abc280','#debd70','#db9f85'][i],[1,.6,1]);}
      this.chef(g,-1.3,.83,.3);this.screen(g,-1.35,1.13,1.28,.48,.4,'库存');
    }else if(id==='kitchen'){
      this.box(g,0,2.16,-.93,3.1,.55,1.1,'#cad8d7',.05,'metal');this.box(g,0,2.61,-1.0,.55,.44,.55,'#c5d6d5',.015,'metal');
      this.table(g,0,-.74,3.3,1.15);
      for(const x of [-1,0,1]){k.cyl(g,x,1.16,-.8,.32,.41,'#d0d9d3',.35,'metal');k.cyl(g,x,1.40,-.8,.35,.04,'#e2e7dc',.35,'metal');k.ball(g,x,1.44,-.8,.04,'#97aaa0');}
      this.table(g,.1,1.16,2.4,.8);this.tray(g,.2,1.25,1.16);this.chef(g,-1.55,.88,.35);this.chef(g,1.42,.34,-.30);this.shelf(g,-2.1,-.6,.9);
    }else if(id==='dispatch'){
      this.screen(g,0,1.95,-1.72,2.3,.9,'班级配餐参考');this.cart(g,-1.2,.4);this.cart(g,.05,.9);this.cart(g,1.4,.25);
      for(const [x,z,c] of [[-1.2,.4,'#8dbaa7'],[.05,.9,'#d9b78d'],[1.4,.25,'#adc4d5']]){this.box(g,x,.75,z+.37,.44,.17,.02,c,.01,'matte');this.text(g,x,.75,z+.39,.4,.10,'按班核对','#fffcef');}
      this.chef(g,-1.8,1.3,.25);
    }else if(id==='dining'){
      for(const x of [-.95,1.05]){k.cyl(g,x,.60,.20,.70,.10,'#ebcd9c',.70);for(const dx of [-.45,.45]){k.cyl(g,x+dx,.3,.20,.03,.6,'#cdb689');this.tray(g,x+dx*.55,.68,.20);}for(const s of [-1,1]){const child=this.chef(g,x+s*.53,.65,s<0?.5:-.5,['#edba7c','#aacbc4'][s===1?0:1],true);child.position.y=.025;}}
      this.screen(g,0,1.97,-1.72,2.1,.78,'预计 ≠ 实际');this.chef(g,2.05,.7,-.4);this.shelf(g,-1.55,-1.22,1.7);
    }else{
      this.screen(g,0,1.85,-1.70,3.5,1.3,'原始单据 · 可核对');this.table(g,.1,.25,2.6,.95);
      for(const x of [-.72,.02,.75]){this.screen(g,x,1.28,.28,.63,.42,'记录');this.box(g,x,.95,.28,.39,.035,.27,'#ebf0e5',.01,'matte');}
      this.chef(g,-1.60,.84,.25);this.shelf(g,1.92,-.5,1.0);
    }
  }
  arrow(x,z,angle,color='#fffdf1'){
    const p=this.k.group(this.root,null,[x,.086,z]);p.rotation.y=angle;
    this.box(p,0,0,-.12,.12,.018,.53,color,0,'matte');
    for(const sign of [-1,1]){const m=this.box(p,sign*.115,0,.12,.105,.018,.34,color,0,'matte');m.rotation.y=-sign*.75;}
  }
  build(){
    const p=this.root,k=this.k;
    this.box(p,0,-.45,0,31.5,.65,23.8,'#d1ccb2',.20);this.box(p,0,-.008,0,31.2,.045,23.45,'#bdcfa9',.02,'matte');
    // One unambiguous serpentine path: 1→2→3→4, down to 5, then 6→7→8.
    this.box(p,0,.043,-2.55,26.3,.065,1.32,'#9ebdbf',.02,'matte');this.box(p,13.12,.043,2.53,1.32,.065,11.45,'#9ebdbf',.02,'matte');this.box(p,0,.043,7.6,26.3,.065,1.32,'#9ebdbf',.02,'matte');
    for(const x of [-7,-.02,6.65,11.5])this.arrow(x,-2.55,Math.PI/2);
    this.arrow(13.12,1,0);this.arrow(13.12,5,0);
    for(const x of [9,6.65,0,-6.65,-11.5])this.arrow(x,7.6,-Math.PI/2);
    // Small entry apron, no invented real-world geography or driving telemetry.
    this.box(p,0,.08,10.15,7.5,.14,2.0,'#e7dcc2',.09);this.box(p,0,.66,10.35,4.40,1.0,.40,'#d7c4a1',.13);
    this.text(p,0,.77,10.58,4.0,.30,'从食谱到餐桌','#7c8667','park-title');this.text(p,0,.42,10.58,3.8,.16,'八个业务站点 · 同一份真实记录','#908d76','park-subtitle');
    STEPS.forEach(step=>{const group=this.building(step);this.stationDetails(step,group);});
    // Quiet school silhouette behind the business stations.
    const school=k.group(p,null,[0,0,-10.5]);this.box(school,0,1.05,0,10.4,2.1,1.35,'#edddbe',.06);this.box(school,0,2.20,0,10.7,.22,1.55,'#dda885',.05);
    for(let i=0;i<8;i++)this.box(school,-4.4+i*1.25,1.25,.69,.72,.94,.028,'#b2d1d1',.025,'matte');this.box(school,0,1.10,.78,2.0,2.1,.18,'#f2e7cb');this.text(school,0,1.98,.89,1.7,.32,'童健云','#81977d');
    for(const x of [-14.2,-11.8,-7.7,-4.8,5.8,8.1,11.8,14.2])this.tree(x,-10.6,.75+(Math.abs(x)%3)*.09);
    for(const x of [-14.6,14.6])for(const z of [-5,-1,3,8.8])this.tree(x,z,.68);
    // Sparse repeated foliage, batched per material, leaves the flow readable.
    for(const step of STEPS)for(const s of [-1,1]){const x=step.point[0]+s*2.2,z=step.point[2]+2.7;this.box(p,x,.15,z,.95,.28,.52,'#e1d7bd');for(let i=0;i<3;i++)k.ball(p,x-.3+i*.3,.42,z,.20,'#b4c593',[1,.8,.85]);}
    for(const x of [-6.65,0,6.65]){this.tree(x,1.4,.66);this.plant(p,x,9,.8);}
    this.renderer.shadowMap.needsUpdate=true;
  }
  tag(step){const el=document.createElement('button');el.type='button';el.className='scene-tag';el.dataset.step=step.id;el.style.setProperty('--tint',step.color);const num=document.createElement('span');num.textContent=step.number;const copy=document.createElement('div');const title=document.createElement('b');title.textContent=step.title;const detail=document.createElement('small');detail.textContent=step.subtitle;copy.append(title,detail);el.append(num,copy);this.labels.appendChild(el);this.tags.push({el,detail,point:new THREE.Vector3(...step.point),step});}
  setData(data){this.tags.forEach(t=>{t.detail.textContent=stepBadge(t.step.id,data);t.el.setAttribute('aria-label',`${t.step.number} ${t.step.title}：${t.detail.textContent}`);});this.invalidate();}
  focus(id){const s=STEPS.find(s=>s.id===id);this.tags.forEach(t=>{t.el.classList.toggle('active',t.step.id===id);t.el.setAttribute('aria-pressed',String(t.step.id===id));});this.highlight.visible=!!s;if(s)this.highlight.position.set(s.point[0],.09,s.point[2]);this.invalidate();}
  hit(event){const r=this.host.getBoundingClientRect();if(!r.width||!r.height)return null;this.pointer.set((event.clientX-r.left)/r.width*2-1,1-(event.clientY-r.top)/r.height*2);this.raycaster.setFromCamera(this.pointer,this.camera);for(const hit of this.raycaster.intersectObjects([this.root],true)){let obj=hit.object;while(obj){if(obj.userData.action)return obj.userData.action;obj=obj.parent;}if(!hit.object.material.transparent)return null;}return null;}
  setView(view){this.view=view;this.camera.position.set(...(view==='top'?[0,42,.001]:[3.7,29,32]));this.controls.target.set(0,0,0);this.camera.zoom=1;this.camera.updateProjectionMatrix();this.controls.update();this.invalidate();}
  resize(){if(this.disposed)return;const w=this.host.clientWidth,h=this.host.clientHeight;if(!w||!h)return;const ratio=w/h,small=w<760,span=Math.max(small?22:23,(small?34:39)/ratio);this.camera.left=-span*ratio/2;this.camera.right=span*ratio/2;this.camera.top=span/2;this.camera.bottom=-span/2;this.camera.updateProjectionMatrix();this.renderer.setSize(w,h,false);this.invalidate();}
  project(){const w=this.host.clientWidth,h=this.host.clientHeight,boxes=[];this.tags.forEach(t=>{const p=t.point.clone().project(this.camera);t.el.hidden=Math.abs(p.x)>1.2||Math.abs(p.y)>1.2||p.z>1||p.z< -1;if(t.el.hidden)return;const tw=t.el.offsetWidth,th=t.el.offsetHeight;let x=(p.x+1)*w/2,y=(1-p.y)*h/2;const margin=w<760?6:185;x=Math.max(margin+tw/2,Math.min(w-tw/2-8,x));y=Math.max(w<760?140:160,Math.min(h-130,y));for(let i=0;i<6;i++){const b={l:x-tw/2,r:x+tw/2,t:y-th,b:y+6};if(!boxes.some(a=>b.l<a.r&&b.r>a.l&&b.t<a.b&&b.b>a.t)){boxes.push(b);break;}y+=th+8;if(y>h-126)y-=2*(th+8);}t.el.style.left=x+'px';t.el.style.top=y+'px';});}
  invalidate(){if(this.frame!==null||this.disposed||this.contextLost||document.hidden)return;this.frame=requestAnimationFrame(()=>{this.frame=null;if(this.disposed||this.contextLost)return;this.controls.update();this.renderer.render(this.scene,this.camera);this.project();Object.assign(this.host.dataset,{drawCalls:String(this.renderer.info.render.calls),triangles:String(this.renderer.info.render.triangles)});});}
  dispose(){if(this.disposed)return;this.disposed=true;if(this.frame!==null)cancelAnimationFrame(this.frame);this.resizeObserver.disconnect();this.host.removeEventListener('pointerdown',this.down);this.host.removeEventListener('pointerup',this.up);this.host.removeEventListener('pointermove',this.move);this.host.removeEventListener('pointercancel',this.cancel);this.renderer.domElement.removeEventListener('webglcontextlost',this.lost);document.removeEventListener('visibilitychange',this.visible);this.controls.dispose();this.releaseBatch();this.k.dispose();this.renderer.dispose();this.renderer.domElement.remove();this.labels.replaceChildren();}
}
