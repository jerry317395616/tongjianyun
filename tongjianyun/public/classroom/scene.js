import * as THREE from 'three';
import {OrbitControls} from '/assets/tongjianyun/campus/vendor/OrbitControls.js';
import {OBJECTS, objectFor, PAGE_SIZE, studentPage, objectBadge} from './objects.js?v=scene-v1-20260923-1';
import {hash, COLORS, STATUS} from './state.js?v=scene-v1-20260923-1';

// Procedural, generic room. No photographs, inferred activity or position telemetry.
export class ClassroomScene {
  constructor(host, labels, callbacks) {
    this.host=host;this.labels=labels;this.callbacks=callbacks;this.materials=new Map();this.geometries=new Map();this.textures=[];this.tags=[];this.students=new Map();this.frame=null;this.disposed=false;this.page=0;this.rows=[];this.selection=new Set();this.rings=new Map();this.activeAction=null;
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#f0e9db');
    this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,1.6));this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.06;
    host.appendChild(this.renderer.domElement);this.renderer.domElement.style.touchAction='none';
    this.camera=new THREE.OrthographicCamera(-10,10,7,-7,.1,120);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=true;this.controls.dampingFactor=.12;this.controls.minZoom=.7;this.controls.maxZoom=2.5;this.controls.maxPolarAngle=Math.PI/2-.1;this.controls.minPolarAngle=.04;
    this.controls.addEventListener('change',()=>this.invalidate());
    this.scene.add(new THREE.HemisphereLight('#fffaf0','#b1c3bb',1.7));
    const sun=new THREE.DirectionalLight('#fff2d4',2.7);sun.position.set(-8,16,9);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-13,right:13,top:13,bottom:-13,near:.5,far:55});sun.shadow.normalBias=.05;sun.shadow.bias=-.0002;this.scene.add(sun);
    const fill=new THREE.DirectionalLight('#dfedff',.65);fill.position.set(8,7,-6);this.scene.add(fill);
    this.room=new THREE.Group();this.scene.add(this.room);this.people=new THREE.Group();this.scene.add(this.people);
    this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();this.buildRoom();this.buildBusinessObjects();this.setView('room');
    this.down=e=>{this.pointerStart={x:e.clientX,y:e.clientY};};
    this.up=e=>{if(!this.pointerStart||Math.hypot(e.clientX-this.pointerStart.x,e.clientY-this.pointerStart.y)>6)return;this.pick(e);};
    this.lost=e=>{e.preventDefault();this.callbacks.onFailure();};
    this.move=e=>this.hover(e);this.leave=()=>{this.host.style.cursor='';};host.addEventListener('pointermove',this.move);host.addEventListener('pointerleave',this.leave);host.addEventListener('pointerdown',this.down);host.addEventListener('pointerup',this.up);this.renderer.domElement.addEventListener('webglcontextlost',this.lost);
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(host);this.visible=()=>{if(!document.hidden)this.invalidate();};document.addEventListener('visibilitychange',this.visible);this.resize();
  }
  material(color,roughness=.8){const key=color+':'+roughness;if(!this.materials.has(key))this.materials.set(key,new THREE.MeshStandardMaterial({color,roughness}));return this.materials.get(key);}
  geometry(key,create){if(!this.geometries.has(key))this.geometries.set(key,create());return this.geometries.get(key);}
  mesh(parent,geo,color,x,y,z){const obj=new THREE.Mesh(geo,this.material(color));obj.position.set(x,y,z);obj.castShadow=true;obj.receiveShadow=true;parent.add(obj);return obj;}
  box(parent,x,y,z,w,h,d,color,round=0){
    const geo=this.geometry(`b:${w}:${h}:${d}:${round}`,()=>{
      if(!round)return new THREE.BoxGeometry(w,h,d);
      const r=Math.min(round,w/3,h/3,d/3),shape=new THREE.Shape();
      shape.moveTo(-w/2+r,-h/2);shape.lineTo(w/2-r,-h/2);shape.quadraticCurveTo(w/2,-h/2,w/2,-h/2+r);shape.lineTo(w/2,h/2-r);shape.quadraticCurveTo(w/2,h/2,w/2-r,h/2);shape.lineTo(-w/2+r,h/2);shape.quadraticCurveTo(-w/2,h/2,-w/2,h/2-r);shape.lineTo(-w/2,-h/2+r);shape.quadraticCurveTo(-w/2,-h/2,-w/2+r,-h/2);
      const g=new THREE.ExtrudeGeometry(shape,{depth:d-2*r,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:r*.48,bevelThickness:r,curveSegments:3});g.translate(0,0,-(d-2*r)/2);return g;
    });return this.mesh(parent,geo,color,x,y,z);
  }
  sphere(parent,x,y,z,r,color,scale=null){const m=this.mesh(parent,this.geometry('s:'+r,()=>new THREE.SphereGeometry(r,16,12)),color,x,y,z);if(scale)m.scale.set(...scale);return m;}
  cylinder(parent,x,y,z,r,h,color,r2=r){return this.mesh(parent,this.geometry(`c:${r}:${h}:${r2}`,()=>new THREE.CylinderGeometry(r2,r,h,20)),color,x,y,z);}
  limb(parent,a,b,r,color){const start=new THREE.Vector3(...a),end=new THREE.Vector3(...b);const m=this.cylinder(parent,0,0,0,r,start.distanceTo(end),color);m.position.copy(start.clone().add(end).multiplyScalar(.5));m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),end.sub(start).normalize());return m;}
  torus(parent,x,y,z,r,tube,color,arc=Math.PI*2){return this.mesh(parent,this.geometry(`t:${r}:${tube}:${arc}`,()=>new THREE.TorusGeometry(r,tube,7,32,arc)),color,x,y,z);}
  rug(x,z,w,d,color){return this.box(this.room,x,.025,z,w,.028,d,color,.08);}
  tag(title,subtitle,point,action){
    const object=objectFor(action),el=document.createElement('button');el.type='button';el.className='scene-label';el.dataset.action=action;el.dataset.objectId=object?.id||action;el.style.setProperty('--object-color',object?.tint||'#7c9f8f');el.setAttribute('aria-label',title+'：'+subtitle);
    const strong=document.createElement('strong');strong.textContent=title;el.appendChild(strong);const detail=document.createElement('span');detail.className='object-state';detail.textContent=subtitle;el.appendChild(detail);this.labels.appendChild(el);this.tags.push({el,point:new THREE.Vector3(...point),action,detail});
  }
  buildBusinessObjects(){
    const make=action=>{const g=new THREE.Group();g.userData.action=action;this.room.add(g);return g;};
    const arrival=make('attendance');this.box(arrival,-6.7,.65,4.5,1.1,1.3,.5,'#ccbc95',.07);this.box(arrival,-6.7,1.4,4.47,1.0,.72,.10,'#77a8b8',.07);this.box(arrival,-6.7,1.41,4.55,.81,.53,.025,'#fbf7e9',.035);this.sign(arrival,-6.7,1.4,4.58,.71,.42,(ctx,w,h)=>{ctx.fillStyle='#487b85';ctx.font='bold 185px "Noto Sans CJK SC",sans-serif';ctx.textAlign='center';ctx.fillText('点名',w/2,h*.7);});
    const book=make('leave');this.box(book,-4.2,.55,4.65,1.3,.12,.8,'#ceaf83',.05);for(const dx of[-.5,.5])this.box(book,-4.2+dx,.25,4.65,.08,.5,.55,'#cfb589');this.box(book,-4.2,.7,4.65,.73,.14,.54,'#d5a78c',.035);this.box(book,-4.2,.79,4.65,.62,.025,.48,'#f8efdb');
    const mail=make('contact');this.box(mail,2.9,.62,4.85,.13,1.24,.13,'#bd9c76');this.box(mail,2.9,1.28,4.85,.77,.60,.45,'#d5a29b',.07);this.box(mail,2.9,1.4,5.10,.43,.065,.024,'#a0706b',.02);this.box(mail,2.9,1.13,5.10,.28,.20,.03,'#fff1da',.02);this.sphere(mail,3.12,1.18,5.13,.025,'#b38554');
    const rest=make('rest');this.box(rest,6.5,.20,4.70,2.05,.28,1.0,'#d4b890',.075);this.box(rest,6.5,.41,4.70,1.92,.25,.93,'#e6e2db',.13);this.box(rest,6.75,.57,4.70,1.28,.12,.86,'#a4b8d0',.07);this.box(rest,5.84,.58,4.70,.38,.14,.69,'#fcf2dc',.09);for(const x of[5.48,7.52])this.box(rest,x,.42,4.70,.10,.7,1.03,'#d4b890',.04);
    const board=make('workflow');this.box(board,-3.2,1.63,-4.35,1.0,1.15,.14,'#b69b77',.055);this.box(board,-3.2,1.65,-4.25,.82,.95,.025,'#fff1cd',.035);this.box(board,-3.2,.48,-4.35,.12,.9,.12,'#c2ab86');this.box(board,-3.2,.07,-4.35,.8,.12,.5,'#c2ab86');this.sign(board,-3.2,1.67,-4.22,.72,.72,(ctx,w,h)=>{ctx.fillStyle='#70886c';ctx.textAlign='center';ctx.font='bold 150px "Noto Sans CJK SC",sans-serif';ctx.fillText('一日工作',w/2,h*.32);ctx.fillStyle='#e0d2b1';for(let i=0;i<3;i++){ctx.fillRect(130,h*.48+i*115,70,70);ctx.fillRect(250,h*.50+i*115,580,25);}});
    OBJECTS.forEach(o=>this.tag(o.label,o.hint,o.point,o.action));
    this.highlight=this.torus(this.room,0,.055,0,.7,.028,'#549ed4');this.highlight.rotation.x=-Math.PI/2;this.highlight.visible=false;
  }
  setBusinessData(data){this.tags.forEach(t=>{t.detail.textContent=objectBadge(t.action,data);t.el.setAttribute('aria-label',objectFor(t.action).title+'：'+t.detail.textContent);});this.invalidate();}
  setActiveAction(action){this.activeAction=action;const object=objectFor(action);this.tags.forEach(t=>{const active=t.action===action;t.el.classList.toggle('active',active);t.el.setAttribute('aria-pressed',String(active));});this.highlight.visible=!!object;if(object)this.highlight.position.set(object.point[0],.055,object.point[2]);this.invalidate();}
  focusObject(action){const object=objectFor(action);if(!object)return;this.setActiveAction(action);this.controls.target.set(object.point[0]*.13,.8,object.point[2]*.12);this.controls.update();this.invalidate();}
  setSelection(ids){this.selection=new Set(ids);this.rings.forEach((ring,id)=>{ring.material=this.material(this.selection.has(id)?'#428bda':COLORS[this.students.get(id).child.status]||COLORS.Unknown);ring.scale.setScalar(this.selection.has(id)?1.25:1);});this.invalidate();}
  setPage(page){const count=Math.max(1,Math.ceil(this.rows.length/PAGE_SIZE));this.page=Math.min(count-1,Math.max(0,page));this.signature=null;this.renderPeople();}
  sign(parent,x,y,z,w,h,draw){const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=Math.round(1024*h/w);draw(canvas.getContext('2d'),canvas.width,canvas.height);const tex=new THREE.CanvasTexture(canvas);tex.colorSpace=THREE.SRGBColorSpace;tex.anisotropy=4;this.textures.push(tex);const mat=new THREE.MeshBasicMaterial({map:tex,transparent:true});this.materials.set('sign:'+this.textures.length,mat);const g=this.geometry(`plane:${w}:${h}`,()=>new THREE.PlaneGeometry(w,h));const mesh=new THREE.Mesh(g,mat);mesh.position.set(x,y,z);parent.add(mesh);return mesh;}
  plant(parent,x,y,z,size=1){
    this.cylinder(parent,x,y+.22*size,z,.22*size,.44*size,'#d9b598',.29*size);this.cylinder(parent,x,y+.44*size,z,.255*size,.02*size,'#7e7258');
    for(let i=0;i<5;i++){const angle=i*2.4;const end=[x+Math.sin(angle)*.32*size,y+(.75+i*.11)*size,z+Math.cos(angle)*.25*size];this.limb(parent,[x,y+.35*size,z],end,.018*size,'#88a578');const leaf=this.sphere(parent,...end,.22*size,i%2?'#9fb587':'#7eaa89',[.6,1.45,.5]);leaf.rotation.z=Math.sin(angle)*.55;}
  }
  shelf(x,z,w=2.6,h=1.25,action='roster'){
    const group=new THREE.Group();group.position.set(x,0,z);group.userData.action=action;this.room.add(group);
    this.box(group,0,h/2,0,w,h,.54,'#cbac85',.04);this.box(group,0,h/2,.28,w-.14,h-.16,.05,'#f3e0bd');
    for(let row=0;row<2;row++)for(let col=0;col<3;col++){
      const xx=-w/2+(col+.5)*w/3,yy=.12+row*h/2;this.box(group,xx,yy,0,w/3,.065,.62,'#edd3a9');
      if(row===0){this.box(group,xx,yy+.22,.12,w/3-.13,.34,.43,['#b1c9be','#dcae96','#aebfd2'][col],.045);this.box(group,xx,yy+.25,.35,.18,.045,.025,'#f6f1e1',.012);}
      else for(let j=0;j<5;j++){const book=this.box(group,xx-.24+j*.115,yy+.25,.09,.08,.40+j%2*.09,.32,['#9eafbc','#d4ad82','#bcc398','#d7a6a0','#a5bdaf'][j]);book.rotation.z=(j===0?-.13:0);}
    }
    for(let i=1;i<3;i++)this.box(group,-w/2+i*w/3,h/2,.035,.07,h,.56,'#edd3a9');return group;
  }
  chair(parent,x,z,angle){const group=new THREE.Group();group.position.set(x,0,z);group.rotation.y=angle;parent.add(group);
    this.box(group,0,.43,0,.47,.09,.45,'#e3c18e',.04);this.box(group,0,.73,-.2,.47,.40,.08,'#c9d8bb',.055);
    for(const dx of[-.18,.18])for(const dz of[-.16,.16])this.cylinder(group,dx,.23,dz,.035,.46,'#c7a777');return group;
  }
  buildRoom(){
    const p=this.room;
    this.box(p,0,-.2,0,16.5,.4,11.6,'#d8c4a5',.25);this.box(p,0,.005,0,16,.025,11,'#e4c89f');
    for(let i=0;i<28;i++)this.box(p,-7.75+i*.56,.025,0,.543,.014,10.94,['#e5cdab','#ecd5b4','#e8d0ae','#e1c5a0'][i%4]);
    for(let i=0;i<28;i++)for(let j=0;j<3;j++)this.box(p,-7.75+i*.56,.035,-3.5+j*3.5+(i%2)*.8,.54,.009,.014,'#d6b98e');
    this.box(p,0,2.05,-5.45,16.3,4.1,.22,'#f3edda',.025);this.box(p,-8,2.05,0,.22,4.1,11,'#f0ecdd',.025);
    this.box(p,0,.44,-5.27,16,.87,.12,'#d3deca');this.box(p,-7.85,.44,0,.12,.87,11,'#d3deca');
    this.box(p,0,.91,-5.17,16,.09,.1,'#cab68d');this.box(p,-7.75,.91,0,.1,.09,11,'#cab68d');
    // Three large windows; their exterior is also illustrative.
    for(const z of[-3.45,0,3.45]){
      this.box(p,-7.82,2.65,z,.04,2.45,2.72,'#b7d7dc');
      for(const dz of[-1.43,1.43])this.box(p,-7.61,2.65,z+dz,.32,2.7,.15,'#fcf8eb');
      for(const yy of[1.28,4.00])this.box(p,-7.59,yy,z,.36,.13,2.99,'#fdfaf0');
      this.box(p,-7.5,1.27,z,.65,.11,3.15,'#dfc29b');
      this.box(p,-7.59,2.65,z,.18,2.65,.09,'#fcf8eb');this.box(p,-7.59,2.65,z,.18,.08,2.80,'#fcf8eb');
      this.sphere(p,-7.78,1.80,z-.8,.56,'#9cbca5',[.06,1,1]);this.sphere(p,-7.78,2.04,z-.35,.70,'#a8c5af',[.06,1,1]);
      this.plant(p,-7.38,1.32,z+.8,.46);
      for(const dz of[-1.57,1.57])for(let j=0;j<3;j++)this.box(p,-7.4,2.67,z+dz+j*.07,.14,2.5,.1,'#efe4ca',.035);
    }
    const board=new THREE.Group();board.userData.action='schedule';p.add(board);
    this.box(board,-.35,2.61,-5.16,5.1,1.85,.12,'#ba9470',.05);this.box(board,-.35,2.63,-5.07,4.86,1.60,.09,'#5e8072',.05);
    this.sign(board,-.35,2.63,-5.00,4.5,1.38,(ctx,w,hh)=>{
      ctx.fillStyle='#f7ecd4';ctx.textAlign='center';ctx.font='600 72px "Noto Sans CJK SC","Microsoft YaHei",sans-serif';ctx.fillText('一起玩 · 一起学',w/2,hh*.43);ctx.font='38px "Noto Sans CJK SC",sans-serif';ctx.fillStyle='#d7e0c7';ctx.fillText('每一天，都有小小的成长',w/2,hh*.75);
      ctx.strokeStyle='#e3c67b';ctx.lineWidth=6;ctx.beginPath();ctx.arc(100,100,30,0,Math.PI*2);ctx.stroke();for(let i=0;i<8;i++){const a=i*Math.PI/4;ctx.beginPath();ctx.moveTo(100+Math.cos(a)*42,100+Math.sin(a)*42);ctx.lineTo(100+Math.cos(a)*54,100+Math.sin(a)*54);ctx.stroke();}
    });
    this.box(board,-.35,1.70,-4.97,5.2,.08,.28,'#cfb288');
    // Pastel rainbow and a small clock, without a fabricated current time.
    for(let i=0;i<4;i++){const arc=this.torus(p,-5.8,3.03,-5.25,.85-i*.13,.055,['#d9a89a','#e2c58e','#b2c6ac','#a8c5ce'][i],Math.PI);arc.castShadow=false;}
    this.cylinder(p,4.15,3.32,-5.23,.35,.045,'#ceb591').rotation.x=Math.PI/2;
    this.sign(p,4.15,3.32,-5.18,.64,.64,(ctx,w,hh)=>{ctx.fillStyle='#fbf7e8';ctx.beginPath();ctx.arc(w/2,hh/2,w*.46,0,Math.PI*2);ctx.fill();ctx.fillStyle='#829480';ctx.textAlign='center';ctx.font='bold 170px sans-serif';ctx.fillText('✿',w/2,hh*.70);});
    this.shelf(-5.45,-4.69,3.5,1.16,'roster');this.plant(p,-6.6,1.18,-4.60,.65);
    for(let i=0;i<4;i++)this.box(p,-5.5+i*.4,1.37,-4.56,.30,.38,.30,['#dacaa0','#b2c9b4','#d9a899','#a6bdcf'][i],.045);
    // A house-shaped reading nook, book display, rug and a cuddly bear.
    const nook=new THREE.Group();nook.userData.action='records';p.add(nook);this.rug(5.3,-3.5,3.65,2.65,'#c4d6b6');
    this.box(nook,5.5,1.3,-5.1,2.7,2.6,.25,'#d6c39c',.045);this.box(nook,5.5,1.38,-4.90,2.4,2.3,.10,'#b4c6ad',.055);
    for(const x of[4.12,6.88])this.box(nook,x,1.35,-4.48,.14,2.7,.90,'#e1c798');
    this.limb(nook,[4.03,2.7,-4.18],[5.5,3.6,-4.18],.095,'#d8b991');this.limb(nook,[5.5,3.6,-4.18],[6.96,2.7,-4.18],.095,'#d8b991');
    this.box(nook,5.5,.43,-4.40,2.55,.32,1.05,'#eedfc3',.15);this.box(nook,5.5,.70,-4.8,2.45,.42,.22,'#efe3cd',.12);
    for(const [x,c] of[[4.65,'#dcbca2'],[5.4,'#bfcfae'],[6.2,'#e1c881']]){const cushion=this.box(nook,x,.88,-4.62,.6,.52,.18,c,.13);cushion.rotation.z=(x-5.5)*.12;}
    this.shelf(3.4,-4.60,1.25,1.45,'records');
    this.sphere(nook,6.4,.53,-3.9,.25,'#c6a277',[1,1.3,.8]);this.sphere(nook,6.4,.92,-3.9,.23,'#c6a277');
    for(const dx of[-.15,.15])this.sphere(nook,6.4+dx,1.10,-3.9,.08,'#c6a277');this.sphere(nook,6.4,.87,-3.70,.10,'#e5cdab');
    for(const dx of[-.07,.07])this.sphere(nook,6.4+dx,.96,-3.695,.019,'#5a4a39');this.sphere(nook,6.4,.90,-3.603,.025,'#5a4a39');
    // Six activity tables double as business hotspots, not surveyed seats.
    this.tablePositions=[];
    for(let row=0;row<2;row++)for(let col=0;col<3;col++){
      const x=-4+col*3.6,z=-1.25+row*3.5;this.tablePositions.push([x,z]);
      const table=new THREE.Group();table.userData.action='meals';p.add(table);
      for(const angle of[.8,2.3,3.9,5.5])this.cylinder(table,x+Math.cos(angle)*.57,.37,z+Math.sin(angle)*.57,.055,.74,'#c9a875');
      this.cylinder(table,x,.78,z,.85,.11,'#edcf9f');this.cylinder(table,x,.84,z,.81,.022,'#f5dfb9');
      if(row===1&&col===1){for(const dx of[-.37,.35]){this.cylinder(table,x+dx,.875,z,.16,.028,'#f6f6df');this.sphere(table,x+dx,.91,z,.08,'#e2a978',[1,.65,1]);}this.cylinder(table,x,.94,z+.25,.09,.17,'#a3c9bc');}
      else{this.box(table,x-.15,.88,z,.44,.02,.31,'#fbf9e8');const paper=this.box(table,x+.3,.88,z+.22,.36,.02,.27,'#f8f7e3');paper.rotation.y=.4;this.cylinder(table,x+.25,.95,z-.25,.08,.19,['#c0d09e','#9fbec2','#d4afa0'][col]);for(let j=0;j<4;j++)this.cylinder(table,x+.21+j*.025,1.10,z-.25,.008,.22,['#c9907b','#a5ba8a','#d6bb66','#8fa6bc'][j]);}
      for(let i=0;i<8;i++){const angle=i*Math.PI/4+Math.PI/8,xx=x+Math.cos(angle)*1.10,zz=z+Math.sin(angle)*1.10;this.chair(p,xx,zz,Math.atan2(x-xx,z-zz));}
    }
    // Art station, storage and authorised health-record entry.
    const easel=new THREE.Group();easel.userData.action='art';p.add(easel);for(const x of[6.0,7.0])this.limb(easel,[x,0,-.8],[x,1.8,-1],.045,'#cfaf7d');this.box(easel,6.5,1.25,-.92,1.35,1.25,.08,'#e4c490',.04);this.box(easel,6.5,1.28,-.86,1.15,1.05,.02,'#fff8e6');
    this.sign(easel,6.5,1.3,-.84,1,1,(ctx,w,hh)=>{ctx.lineWidth=48;['#d9a294','#e5c875','#a5c6aa','#97b9c9'].forEach((c,i)=>{ctx.strokeStyle=c;ctx.beginPath();ctx.arc(w/2,hh*.72,w*.35-i*52,Math.PI,0);ctx.stroke();});ctx.fillStyle='#d9e5c4';ctx.fillRect(90,hh*.76,w-180,35);});
    const cabinet=this.shelf(-6.65,3.80,1.7,1.1,'roster');cabinet.rotation.y=.10;
    const health=this.shelf(6.55,2.95,1.8,1.2,'health');this.plant(health,0,1.21,0,.60);
    this.rug(6.65,.90,1.7,1.25,'#d8d3bc');for(let i=0;i<5;i++)this.box(p,6.2+i*.2,.10,.8+(i%2)*.15,.16,.16,.16,['#d7b16c','#95bfc0','#cba394','#a9be90','#a8b3cc'][i],.018);
    this.plant(p,-7.1,0,-1.8,1.15);this.plant(p,7.2,0,-3.8,.95);
    // A decorative teacher avatar, clearly separate from staff attendance.
    const teacher=this.character('teacher','#91b49c',true);teacher.position.set(.15,0,-3.5);teacher.rotation.y=.15;teacher.scale.setScalar(1.40);p.add(teacher);
    // Soft hanging cloud light and bunting on the back wall.
    this.limb(p,[-4.8,4.65,-2.8],[-4.8,3.87,-2.8],.015,'#b8b29d');
    for(const [dx,r] of[[-.35,.3],[0,.43],[.37,.31]])this.sphere(p,-4.8+dx,3.84,-2.8,r,'#fff5d8',[1,.70,.78]);
    for(let i=0;i<10;i++){const xx=-2.55+i*.52;const flag=this.mesh(p,this.geometry('flag',()=>new THREE.ConeGeometry(.16,.28,3)),['#c9ac9c','#acc2a3','#d9c180','#acc5cc'][i%4],xx,3.83,-5.09);flag.rotation.z=Math.PI;flag.rotation.y=Math.PI/2;}
  }
  character(id,shirt=null,standing=false){
    const n=hash(id),group=new THREE.Group(),skin=['#edc09b','#e4b491','#edc7aa','#d7a882'][n%4],hair=['#635043','#514338','#71523b'][n%3];
    shirt=shirt||['#94b9af','#d7a497','#a5b7cf','#d5c38c','#b8c5a0','#c2b0cd'][n%6];
    this.box(group,0,.65,0,.31,.33,.24,shirt,.055);this.cylinder(group,0,.87,0,.062,.10,skin);
    this.sphere(group,0,1.08,.015,.245,skin,[1,1.07,.94]);
    const cap=this.mesh(group,this.geometry('haircap',()=>new THREE.SphereGeometry(.252,18,12,0,Math.PI*2,0,1.43)),hair,0,1.095,.005);cap.scale.z=.97;
    for(const [x,y] of[[-.125,1.25],[-.01,1.29],[.125,1.255]]){const bang=this.sphere(group,x,y,.151,.105,hair,[.85,.65,.72]);bang.rotation.z=x*2;}
    for(const dx of[-1,1]){
      this.sphere(group,dx*.245,1.085,.015,.05,skin,[.65,1,1]);
      this.sphere(group,dx*.087,1.10,.227,.045,'#fff8eb',[.85,1.15,.42]);this.sphere(group,dx*.087,1.10,.244,.028,'#3f3734',[.83,1.1,.65]);this.sphere(group,dx*.082,1.112,.260,.008,'#fffdfa');
      this.sphere(group,dx*.144,1.012,.219,.032,'#e6a58f',[1,.55,.3]);
      this.limb(group,[dx*.175,.77,0],[dx*.235,.54,.15],.054,shirt);this.sphere(group,dx*.236,.51,.17,.061,skin);
      if(standing){this.limb(group,[dx*.09,.5,0],[dx*.10,.15,.04],.071,'#6a7d7b');}else{this.limb(group,[dx*.09,.48,0],[dx*.10,.31,.18],.071,'#718597');this.limb(group,[dx*.10,.31,.18],[dx*.10,.15,.24],.06,'#718597');}
      this.box(group,dx*.105,.115,standing?.085:.28,.14,.12,.23,'#f3ebd9',.035);
    }
    const smile=this.torus(group,0,1.003,.247,.042,.008,'#9e6555',Math.PI);smile.rotation.z=Math.PI;
    this.sphere(group,0,1.048,.251,.026,skin,[.75,.75,1]);
    if(n%3===0)for(const dx of[-1,1]){this.sphere(group,dx*.28,1.20,.006,.108,hair,[1,.86,1]);this.sphere(group,dx*.24,1.25,.06,.033,'#dba69f');}
    return group;
  }
  setStudents(rows){
    const signature=rows.map(r=>r.student+':'+r.student_name+':'+r.status).join('|');if(signature===this.signature)return;this.signature=signature;this.rows=rows;this.page=Math.min(this.page,Math.max(0,Math.ceil(rows.length/PAGE_SIZE)-1));this.renderPeople();
  }
  renderPeople(){
    this.people.clear();this.students.clear();this.rings.clear();if(this.selectedTag){this.selectedTag.remove();this.selectedTag=null;}
    this.rows.slice(this.page*PAGE_SIZE,(this.page+1)*PAGE_SIZE).forEach((child,i)=>{
      const table=this.tablePositions[i%6],angle=Math.floor(i/6)*Math.PI/4+Math.PI/8;
      const x=table[0]+Math.cos(angle)*1.10,z=table[1]+Math.sin(angle)*1.10;
      const group=this.character(child.student);group.position.set(x,.015,z);group.rotation.y=Math.atan2(table[0]-x,table[1]-z);group.userData.student=child.student;this.people.add(group);
      const ring=this.torus(group,0,.045,0,.34,.022,COLORS[child.status]||COLORS.Unknown);ring.rotation.x=-Math.PI/2;this.rings.set(child.student,ring);this.students.set(child.student,{group,child});
    });this.setSelection([...this.selection]);this.host.dataset.renderedStudents=String(this.students.size);this.host.dataset.totalStudents=String(this.rows.length);this.host.dataset.studentPage=String(this.page);this.callbacks.onPage?.({page:this.page,total:this.rows.length,size:PAGE_SIZE});this.invalidate();
  }
  focusStudent(id){
    const page=studentPage(this.rows,id);if(page===null)return;if(page!==this.page)this.setPage(page);
    const entry=this.students.get(id);if(!entry)return;if(this.selectedTag)this.selectedTag.remove();const el=document.createElement('button');el.type='button';el.onclick=()=>this.callbacks.onStudent(id);el.className='scene-label student-label';const name=document.createElement('strong');name.textContent=entry.child.student_name;el.appendChild(name);el.appendChild(document.createTextNode(STATUS[entry.child.status]||'待点名'));this.labels.appendChild(el);this.selectedTag=el;this.selectedPoint=entry.group.position.clone().add(new THREE.Vector3(0,1.65,0));this.invalidate();
  }
  hit(event){const rect=this.host.getBoundingClientRect();this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);this.raycaster.setFromCamera(this.pointer,this.camera);const hits=this.raycaster.intersectObjects([this.people,this.room],true);for(const hit of hits){let target=hit.object;while(target){if(target.userData.student||target.userData.action)return target.userData;target=target.parent;}if(hit.object.geometry?.type!=='PlaneGeometry')break;}return null;}
  hover(event){if(event.buttons)return;const target=this.hit(event);this.renderer.domElement.style.cursor=target?'pointer':'grab';}
  pick(event){const target=this.hit(event);if(target?.student)this.callbacks.onStudent(target.student);else if(target?.action)this.callbacks.onAction(target.action);}
  setView(view){this.view=view;this.camera.zoom=view==='top'?1:1.08;this.controls.target.set(0,.85,0);this.camera.position.set(...(view==='top'?[0,27,.001]:[12.8,11.6,20.5]));this.camera.updateProjectionMatrix();this.controls.update();this.invalidate();}
  resize(){if(this.disposed)return;const w=this.host.clientWidth,h=this.host.clientHeight;if(!w||!h)return;const aspect=w/h,span=Math.max(12.8,19/aspect);this.camera.left=-span*aspect/2;this.camera.right=span*aspect/2;this.camera.top=span/2;this.camera.bottom=-span/2;this.camera.updateProjectionMatrix();this.renderer.setSize(w,h,false);this.invalidate();}
  project(el,point){const p=point.clone().project(this.camera);el.hidden=p.z< -1||p.z>1||Math.abs(p.x)>1||Math.abs(p.y)>1;if(!el.hidden){el.style.left=(p.x+1)/2*this.host.clientWidth+'px';el.style.top=(1-p.y)/2*this.host.clientHeight+'px';}}
  layoutTags(){
    const boxes=[],width=this.host.clientWidth,height=this.host.clientHeight,small=width<700;
    // Stable, deterministic collision avoidance. No label is silently removed:
    // every operation remains reachable from the object index and keyboard.
    [...this.tags].sort((a,b)=>(b.action===this.activeAction)-(a.action===this.activeAction)).forEach(t=>{
      this.project(t.el,t.point);if(t.el.hidden)return;const w=t.el.offsetWidth,h=t.el.offsetHeight;
      let x=parseFloat(t.el.style.left),y=parseFloat(t.el.style.top);const original=y;
      x=Math.max(w/2+8,Math.min(width-w/2-8,x));y=Math.max(small?110:140,Math.min(height-105,y));
      for(let tries=0;tries<8;tries++){
        const b={left:x-w/2-3,right:x+w/2+3,top:y-h-4,bottom:y+6};
        if(!boxes.some(p=>b.left<p.right&&b.right>p.left&&b.top<p.bottom&&b.bottom>p.top)){boxes.push(b);break;}
        y+=h+9;if(y>height-105){y=Math.max(h+110,original-h-12);x=Math.min(width-w/2-8,x+w*.7);}
      }
      t.el.style.left=x+'px';t.el.style.top=y+'px';t.el.dataset.shifted=String(Math.abs(y-original)>20);
    });
  }
  invalidate(){if(this.frame!==null||this.disposed||document.hidden)return;this.frame=requestAnimationFrame(()=>{this.frame=null;if(this.disposed)return;this.controls.update();this.renderer.render(this.scene,this.camera);this.layoutTags();if(this.selectedTag)this.project(this.selectedTag,this.selectedPoint);});}
  dispose(){if(this.disposed)return;this.disposed=true;if(this.frame!==null)cancelAnimationFrame(this.frame);this.resizeObserver.disconnect();this.host.removeEventListener('pointermove',this.move);this.host.removeEventListener('pointerleave',this.leave);this.host.removeEventListener('pointerdown',this.down);this.host.removeEventListener('pointerup',this.up);document.removeEventListener('visibilitychange',this.visible);this.renderer.domElement.removeEventListener('webglcontextlost',this.lost);this.controls.dispose();this.geometries.forEach(g=>g.dispose());this.materials.forEach(m=>m.dispose());this.textures.forEach(t=>t.dispose());this.renderer.dispose();this.labels.replaceChildren();}
}
