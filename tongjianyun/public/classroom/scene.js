import * as THREE from 'three';
import {OrbitControls} from '/assets/tongjianyun/campus/vendor/OrbitControls.js';
import {OBJECTS,objectFor,PAGE_SIZE,studentPage,objectBadge} from './objects.js?v=refined-20260923-1';
import {COLORS,STATUS} from './state.js?v=refined-20260923-1';
import {VisualKit} from './visual-kit.js?v=refined-20260923-1';
import {createCharacter} from './characters.js?v=refined-20260923-1';
import {buildRefinedRoom} from './room.js?v=refined-20260923-1';
import {ROOM_VIEW,slotFor,VISUAL_PAGE_SIZE} from './visual-layout.js?v=refined-20260923-1';

/** Presentation-only renderer. This module never fetches or writes business data. */
export class ClassroomScene {
  constructor(host,labels,callbacks) {
    if(PAGE_SIZE!==VISUAL_PAGE_SIZE)throw new Error('Roster and illustration page sizes must agree');
    Object.assign(this,{host,labels,callbacks,frame:null,disposed:false,contextLost:false,page:0,rows:[],selection:new Set(),students:new Map(),rings:new Map(),rigs:[],tags:[],activeAction:null,labelsDirty:true});
    this.scene=new THREE.Scene();this.scene.background=new THREE.Color('#efe6d5');
    this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'low-power'});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,window.innerWidth<700?1.25:1.65));
    this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.ACESFilmicToneMapping;this.renderer.toneMappingExposure=1.04;
    this.renderer.shadowMap.enabled=true;this.renderer.shadowMap.type=THREE.PCFSoftShadowMap;this.renderer.shadowMap.autoUpdate=false;
    host.appendChild(this.renderer.domElement);this.renderer.domElement.style.touchAction='none';
    this.kit=new VisualKit(this.renderer);
    this.scene.add(new THREE.HemisphereLight('#fffaf0','#9e9985',1.40));
    const sun=new THREE.DirectionalLight('#fff0d1',3.15);sun.position.set(-6,15,9);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);
    Object.assign(sun.shadow.camera,{left:-15,right:15,top:15,bottom:-15,near:1,far:55});sun.shadow.normalBias=.035;sun.shadow.bias=-.00006;this.scene.add(sun);
    const fill=new THREE.DirectionalLight('#e9f3ff',.70);fill.position.set(5,8,15);this.scene.add(fill);
    this.camera=new THREE.OrthographicCamera(-10,10,7,-7,.1,120);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=true;this.controls.dampingFactor=.16;this.controls.minZoom=.65;this.controls.maxZoom=3;this.controls.maxPolarAngle=Math.PI/2-.13;this.controls.minPolarAngle=.04;
    this.controlChange=()=>{this.labelsDirty=true;this.invalidate();};this.controls.addEventListener('change',this.controlChange);
    this.roomModel=buildRefinedRoom(this.kit);this.room=this.roomModel.root;this.scene.add(this.room);
    this.people=new THREE.Group();this.people.name='visible-roster-illustrations';this.scene.add(this.people);
    this.teacher=createCharacter(this.kit,'decorative-teacher',{teacher:true,pose:'stand'});
    const t=this.roomModel.teacher;this.teacher.root.position.set(t.x,0,t.z);this.teacher.root.rotation.y=t.angle;this.teacher.root.userData.action='workflow';this.scene.add(this.teacher.root);
    this.leaders=document.createElementNS('http://www.w3.org/2000/svg','svg');this.leaders.classList.add('scene-leaders');this.leaders.setAttribute('aria-hidden','true');labels.appendChild(this.leaders);
    OBJECTS.forEach(o=>this.tag(o));
    this.highlight=this.kit.ring(this.scene,0,.074,0,.60,.024,'#68a9c8');this.highlight.rotation.x=-Math.PI/2;this.highlight.castShadow=false;this.highlight.visible=false;
    this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();this.setView('room');
    this.down=e=>{this.pointerStart={x:e.clientX,y:e.clientY};};
    this.up=e=>{if(this.pointerStart&&Math.hypot(e.clientX-this.pointerStart.x,e.clientY-this.pointerStart.y)<6)this.pick(e);this.pointerStart=null;};
    this.move=e=>this.hover(e);this.leave=()=>{this.renderer.domElement.style.cursor='grab';};
    this.lost=e=>{e.preventDefault();this.contextLost=true;clearInterval(this.motionTimer);if(this.frame!==null)cancelAnimationFrame(this.frame);this.frame=null;this.callbacks.onFailure();};
    host.addEventListener('pointerdown',this.down);host.addEventListener('pointerup',this.up);host.addEventListener('pointermove',this.move);host.addEventListener('pointerleave',this.leave);this.renderer.domElement.addEventListener('webglcontextlost',this.lost);
    this.motionPreference=window.matchMedia('(prefers-reduced-motion: reduce)');
    this.motionEnabled=!this.motionPreference.matches&&window.innerWidth>=700;
    this.preferenceChange=()=>this.setMotion(!this.motionPreference.matches&&window.innerWidth>=700);this.motionPreference.addEventListener('change',this.preferenceChange);
    this.visibility=()=>{if(!document.hidden){this.labelsDirty=true;this.invalidate();}};document.addEventListener('visibilitychange',this.visibility);
    this.motionTimer=setInterval(()=>this.animate(),90);
    this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(host);this.resize();
    host.dataset.sceneVersion='refined-20260923-1';host.dataset.motionEnabled=String(this.motionEnabled);this.callbacks.onMotion?.(this.motionEnabled);
  }
  tag(object) {
    const el=document.createElement('button');el.type='button';el.className='scene-label';el.dataset.action=object.action;el.dataset.objectId=object.id;el.style.setProperty('--object-color',object.tint);
    const badge=document.createElement('span');badge.className='object-icon';badge.setAttribute('aria-hidden','true');
    // Symbol identifiers originate only from the static object registry.
    badge.innerHTML=`<svg><use href="#i-${object.icon}"/></svg>`;
    const text=document.createElement('span');text.className='object-copy';const strong=document.createElement('strong');strong.textContent=object.label;const detail=document.createElement('span');detail.className='object-state';detail.textContent=object.hint;text.append(strong,detail);el.append(badge,text);
    const leader=document.createElementNS('http://www.w3.org/2000/svg','line');leader.setAttribute('stroke',object.tint);this.leaders.appendChild(leader);
    el.setAttribute('aria-label',object.title+'：'+object.hint);this.labels.appendChild(el);this.tags.push({el,detail,leader,action:object.action,point:new THREE.Vector3(...object.point)});
  }
  setBusinessData(data) {
    this.tags.forEach(t=>{t.detail.textContent=objectBadge(t.action,data);t.el.setAttribute('aria-label',objectFor(t.action).title+'：'+t.detail.textContent);});
    this.roomModel.updateClass(data.group?.label);this.labelsDirty=true;this.invalidate();
  }
  setActiveAction(action) {
    this.activeAction=action;const object=objectFor(action);
    this.tags.forEach(t=>{t.el.classList.toggle('active',t.action===action);t.el.setAttribute('aria-pressed',String(t.action===action));});
    this.highlight.visible=!!object;if(object)this.highlight.position.set(object.point[0],.074,object.point[2]);this.labelsDirty=true;this.invalidate();
  }
  focusObject(action) {
    const object=objectFor(action);if(!object)return;this.setActiveAction(action);
    this.controls.target.set(object.point[0]*.09,1.0,object.point[2]*.08);this.controls.update();this.invalidate();
  }
  setStudents(rows) {
    const signature=rows.map(r=>r.student+':'+r.student_name+':'+r.status).join('|');if(signature===this.signature)return;
    this.signature=signature;this.rows=rows;this.page=Math.min(this.page,Math.max(0,Math.ceil(rows.length/PAGE_SIZE)-1));this.renderPeople();
  }
  renderPeople() {
    this.rigs.forEach(r=>r.dispose());this.rigs=[];this.people.clear();this.students.clear();this.rings.clear();this.clearStudentLabel();
    this.rows.slice(this.page*PAGE_SIZE,(this.page+1)*PAGE_SIZE).forEach((child,i)=>{
      const slot=slotFor(i),rig=createCharacter(this.kit,child.student,{pose:slot.pose});
      const group=rig.root;group.position.set(slot.x,.02,slot.z);group.rotation.y=slot.angle;group.userData.student=child.student;
      this.people.add(group);this.rigs.push(rig);
      // A visible ring encodes only the existing attendance record. Poses never do.
      const ring=this.kit.ring(group,0,.053,0,.39,.022,COLORS[child.status]||COLORS.Unknown);ring.rotation.x=-Math.PI/2;ring.castShadow=false;ring.receiveShadow=false;this.rings.set(child.student,ring);this.students.set(child.student,{group,child,rig});
      const shadow=this.kit.shadow(this.people,slot.x,slot.z,1.12,.98,.20);shadow.userData.keepSeparate=true;
    });
    this.setSelection(this.selection);this.host.dataset.renderedStudents=String(this.students.size);this.host.dataset.totalStudents=String(this.rows.length);this.host.dataset.studentPage=String(this.page);
    this.callbacks.onPage?.({page:this.page,total:this.rows.length,size:PAGE_SIZE});this.renderer.shadowMap.needsUpdate=true;this.labelsDirty=true;this.invalidate();
  }
  setPage(page) {
    const count=Math.max(1,Math.ceil(this.rows.length/PAGE_SIZE));this.page=Math.min(count-1,Math.max(0,Number.isFinite(page)?Math.floor(page):0));this.signature=null;this.renderPeople();
  }
  setSelection(ids) {
    this.selection=new Set(ids);this.rings.forEach((ring,id)=>{const active=this.selection.has(id);ring.material=this.kit.material(active?'#459de3':COLORS[this.students.get(id).child.status]||COLORS.Unknown);ring.scale.setScalar(active?1.20:1);});this.invalidate();
  }
  clearStudentLabel(){this.selectedTag?.remove();this.selectedTag=null;this.focusedStudent=null;}
  focusStudent(id) {
    const page=studentPage(this.rows,id);if(page===null)return;if(page!==this.page)this.setPage(page);
    const entry=this.students.get(id);if(!entry)return;this.clearStudentLabel();this.focusedStudent=id;
    const el=document.createElement('button');el.type='button';el.className='scene-label student-label';el.onclick=()=>this.callbacks.onStudent(id);
    const name=document.createElement('strong');name.textContent=entry.child.student_name;el.append(name,document.createTextNode(STATUS[entry.child.status]||'待点名'));this.labels.appendChild(el);this.selectedTag=el;this.selectedPoint=entry.group.position.clone().add(new THREE.Vector3(0,2.06,0));
    this.labelsDirty=true;this.invalidate();
  }
  setView(view) {
    this.view=view;this.camera.zoom=view==='top'?1:view==='close'?1.55:ROOM_VIEW.zoom;
    this.controls.target.set(...ROOM_VIEW.target);this.camera.position.set(...(view==='top'?[0,28,.001]:view==='close'?[7.5,8.7,21]:ROOM_VIEW.eye));this.camera.updateProjectionMatrix();this.controls.update();this.labelsDirty=true;this.invalidate();
  }
  setMotion(enabled) {
    // OS reduced-motion remains authoritative, even after a manual toggle.
    this.motionEnabled=!!enabled&&!this.motionPreference.matches;
    if(!this.motionEnabled){this.rigs.forEach(r=>r.animate(0,false));this.teacher.animate(0,false);this.invalidate();}
    this.host.dataset.motionEnabled=String(this.motionEnabled);this.callbacks.onMotion?.(this.motionEnabled);
  }
  animate() {
    if(this.disposed||this.contextLost||document.hidden||!this.motionEnabled||this.host.clientWidth===0)return;
    this.host.dataset.animationTicks=String((Number(this.host.dataset.animationTicks)||0)+1);
    const seconds=performance.now()/1000;this.teacher.animate(seconds);
    this.rigs.forEach((rig,index)=>{rig.animate(seconds,index<6||this.students.get(this.focusedStudent)?.rig===rig);});this.invalidate();
  }
  hit(event) {
    const rect=this.host.getBoundingClientRect();if(!rect.width||!rect.height||this.contextLost)return null;
    this.pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);this.raycaster.setFromCamera(this.pointer,this.camera);
    for(const hit of this.raycaster.intersectObjects([this.people,this.room,this.teacher.root],true)) {
      let target=hit.object;while(target){if(target.userData.student||target.userData.action)return target.userData;target=target.parent;}
      if(hit.object.geometry?.type!=='PlaneGeometry')break;
    }
    return null;
  }
  hover(event){if(event.buttons)return;const now=performance.now();if(now-(this.lastHover||0)<70)return;this.lastHover=now;this.renderer.domElement.style.cursor=this.hit(event)?'pointer':'grab';}
  pick(event){const target=this.hit(event);if(target?.student)this.callbacks.onStudent(target.student);else if(target?.action)this.callbacks.onAction(target.action);}
  resize() {
    if(this.disposed)return;const w=this.host.clientWidth,h=this.host.clientHeight;if(!w||!h)return;
    const aspect=w/h,span=Math.max(ROOM_VIEW.vertical,ROOM_VIEW.horizontal/aspect);this.camera.left=-span*aspect/2;this.camera.right=span*aspect/2;this.camera.top=span/2;this.camera.bottom=-span/2;this.camera.updateProjectionMatrix();this.renderer.setSize(w,h,false);this.labelsDirty=true;this.invalidate();
  }
  project(el,point) {
    const p=point.clone().project(this.camera);el.hidden=p.z< -1||p.z>1||Math.abs(p.x)>1||Math.abs(p.y)>1;
    if(!el.hidden){el.style.left=(p.x+1)/2*this.host.clientWidth+'px';el.style.top=(1-p.y)/2*this.host.clientHeight+'px';}
  }
  layoutTags() {
    const boxes=[],width=this.host.clientWidth,height=this.host.clientHeight,small=width<700;
    [...this.tags].sort((a,b)=>(b.action===this.activeAction)-(a.action===this.activeAction)).forEach(t=>{
      this.project(t.el,t.point);t.leader.style.display='none';if(t.el.hidden)return;
      const w=t.el.offsetWidth,h=t.el.offsetHeight;let x=parseFloat(t.el.style.left),y=parseFloat(t.el.style.top);const original=y,originalX=x;
      x=Math.max(w/2+8,Math.min(width-w/2-8,x));y=Math.max(small?110:135,Math.min(height-(small?145:140),y));
      for(let tries=0;tries<12;tries++) {
        const b={left:x-w/2-5,right:x+w/2+5,top:y-h-5,bottom:y+5};
        if(!boxes.some(p=>b.left<p.right&&b.right>p.left&&b.top<p.bottom&&b.bottom>p.top)){boxes.push(b);break;}
        y+=h+10;if(y>height-(small?145:140)){y=Math.max(h+105,original-h-17);x=Math.min(width-w/2-8,x+w*.58);}
      }
      t.el.style.left=x+'px';t.el.style.top=y+'px';t.el.dataset.shifted=String(Math.abs(y-original)>22);
      if(Math.hypot(x-originalX,y-original)>24){t.leader.style.display='';t.leader.setAttribute('x1',String(originalX));t.leader.setAttribute('y1',String(original));t.leader.setAttribute('x2',String(x));t.leader.setAttribute('y2',String(y>original?y-h:y));}
    });
    if(this.selectedTag)this.project(this.selectedTag,this.selectedPoint);
  }
  invalidate() {
    if(this.frame!==null||this.disposed||this.contextLost||document.hidden)return;
    this.frame=requestAnimationFrame(()=>{
      this.frame=null;if(this.disposed||this.contextLost)return;
      this.controls.update();this.renderer.render(this.scene,this.camera);
      if(this.labelsDirty){this.layoutTags();this.labelsDirty=false;}
      this.host.dataset.drawCalls=String(this.renderer.info.render.calls);this.host.dataset.triangles=String(this.renderer.info.render.triangles);this.host.dataset.geometryCount=String(this.renderer.info.memory.geometries);
    });
  }
  dispose() {
    if(this.disposed)return;this.disposed=true;clearInterval(this.motionTimer);if(this.frame!==null)cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();this.controls.removeEventListener('change',this.controlChange);this.controls.dispose();
    this.host.removeEventListener('pointerdown',this.down);this.host.removeEventListener('pointerup',this.up);this.host.removeEventListener('pointermove',this.move);this.host.removeEventListener('pointerleave',this.leave);this.renderer.domElement.removeEventListener('webglcontextlost',this.lost);
    document.removeEventListener('visibilitychange',this.visibility);this.motionPreference.removeEventListener('change',this.preferenceChange);
    this.rigs.forEach(r=>r.dispose());this.teacher.dispose();this.roomModel.dispose();this.kit.dispose();this.renderer.dispose();this.renderer.domElement.remove();this.labels.replaceChildren();
  }
}
