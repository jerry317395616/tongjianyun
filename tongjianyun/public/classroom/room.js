import * as THREE from 'three';
import {ILLUSTRATIVE_SLOTS} from './visual-layout.js?v=refined-20260923-1';

const WOOD='#e0b780',EDGE='#cfa06c',CREAM='#faf2e3',SAGE='#a9bf94';
const BOOKS=['#bbca9b','#96bcc4','#dfa298','#e2bc7a','#b8acd0','#9eb595'];
const FONT='"Noto Sans CJK SC","Microsoft YaHei",sans-serif';

function star(c,x,y,r,color) {
  c.fillStyle=color;c.beginPath();for(let i=0;i<10;i++){const a=-Math.PI/2+i*Math.PI/5,rr=i%2?r*.46:r;i?c.lineTo(x+Math.cos(a)*rr,y+Math.sin(a)*rr):c.moveTo(x+Math.cos(a)*rr,y+Math.sin(a)*rr);}c.closePath();c.fill();
}
function plant(k,p,x,y,z,scale=1) {
  const g=k.group(p,null,[x,y,z]);g.scale.setScalar(scale);
  k.cyl(g,0,.19,0,.20,.38,'#e6c5a1',.27,'ceramic');k.cyl(g,0,.39,0,.245,.025,'#79634b');
  for(let i=0;i<7;i++) {
    const a=i*2.4,height=.65+i*.087,xx=Math.sin(a)*.30,zz=Math.cos(a)*.24;
    k.curve(g,[[0,.3,0],[xx*.35,height*.75,zz*.35],[xx,height,zz]],.013,'#76956a');
    const leaf=k.ball(g,xx,height,zz,.16,i%2?'#92b274':'#6f9a6d',[.68,1.70,.36]);leaf.rotation.set(.3, a,Math.sin(a)*.6);
  }
  return g;
}
function book(k,p,x,y,z,color,height=.37,angle=0) {
  const g=k.group(p,null,[x,y,z]);g.rotation.z=angle;
  k.box(g,0,height/2,0,.09,height,.27,color,.01,'matte');k.box(g,.051,height/2,.01,.01,height-.037,.222,'#fff2dc',.003,'matte');
  k.box(g,0,height*.77,.143,.061,.018,.005,'#f8efd6',0,'matte');return g;
}
function shelf(k,p,x,z,w=2.6,action='roster',rows=2) {
  const g=k.group(p,action,[x,0,z]),h=rows*.54+.13;
  k.box(g,0,h/2,-.12,w,h,.12,'#d4b58b');
  for(const side of [-1,1])k.box(g,side*(w/2-.035),h/2,0,.11,h+.09,.62,WOOD);
  for(let j=0;j<=rows;j++)k.box(g,0,.09+j*.54,.025,w+.08,.09,.71,WOOD);
  const cells=Math.max(2,Math.round(w/.75));
  for(let i=1;i<cells;i++)k.box(g,-w/2+i*w/cells,h/2,0,.07,h,.62,WOOD);
  for(let j=0;j<rows;j++)for(let i=0;i<cells;i++) {
    const xx=-w/2+(i+.5)*w/cells,yy=.14+j*.54;
    if(j===0&&i%2===0) {
      k.box(g,xx,yy+.18,.09,w/cells-.17,.32,.48,BOOKS[(i+1)%6],.04,'fabric');
      k.box(g,xx,yy+.20,.338,.17,.065,.014,'#fcf3de',.013,'matte');
    } else for(let b=0;b<4;b++)book(k,g,xx-.19+b*.105,yy,0,BOOKS[(i+b+j)%6],.31+(b%3)*.03,b===0?-.08:0);
  }
  k.shadow(p,x,z,w+.5,.95,.22);return g;
}
function bear(k,p,x,y,z,s=.6) {
  const g=k.group(p,null,[x,y,z]);g.scale.setScalar(s);
  k.ball(g,0,.32,0,.25,'#c9a075',[1,1.24,.8],'fabric');k.ball(g,0,.70,.025,.25,'#c9a075',[1,1.02,.87],'fabric');
  for(const a of [-1,1]){k.ball(g,a*.18,.91,.01,.09,'#c9a075',[1,1,.6],'fabric');k.ball(g,a*.18,.91,.06,.053,'#e5cba7',[1,1,.5],'fabric');k.ball(g,a*.25,.40,.01,.105,'#c9a075',[.75,1.48,.75],'fabric');k.ball(g,a*.155,.1,.16,.12,'#c9a075',[1,.7,1.2],'fabric');k.ball(g,a*.088,.74,.232,.020,'#423429',[1,1,.5],'eye');}
  k.ball(g,0,.64,.245,.104,'#ead4ac',[1,.76,.52],'fabric');k.ball(g,0,.674,.299,.035,'#68503d',[1,.6,.4]);k.box(g,0,.47,.24,.20,.07,.027,'#b3c2a2',.025,'fabric');
  return g;
}
function chair(k,p,s) {
  if(s.cushion)return;
  const g=k.group(p,null,[s.x,0,s.z]);g.rotation.y=s.angle;
  k.box(g,0,.54,0,.58,.10,.58,WOOD,.06);
  for(const x of [-.22,.22])for(const z of [-.22,.22])k.limb(g,[x,.52,z],[x*1.1,.04,z*1.1],.039,EDGE,'wood');
  for(const x of [-.23,.23])k.limb(g,[x,.50,-.23],[x,.99,-.26],.036,WOOD,'wood');
  k.box(g,0,.89,-.262,.54,.32,.083,'#cbd7b4',.07);
  k.box(g,0,.887,-.215,.16,.037,.007,'#f0e6c7',.008,'matte');
}
function table(k,p,x,z,action,r=1.13) {
  const g=k.group(p,action,[x,0,z]);k.shadow(p,x,z,r*2.9,r*2.7,.25);
  for(let i=0;i<4;i++){const a=Math.PI/4+i*Math.PI/2;k.limb(g,[Math.cos(a)*r*.69,.99,Math.sin(a)*r*.69],[Math.cos(a)*r*.75,.06,Math.sin(a)*r*.75],.065,EDGE,'wood');}
  k.cyl(g,0,.99,0,r,.14,WOOD);k.cyl(g,0,1.068,0,r-.035,.026,'#f0d7aa');return g;
}
function crayonCup(k,p,x,y,z) {
  k.cyl(p,x,y+.12,z,.099,.24,'#9dbeb5',.115,'ceramic');
  for(let i=0;i<6;i++){const a=i*1.07;const crayon=k.cyl(p,x+Math.cos(a)*.053,y+.29,z+Math.sin(a)*.045,.011,.28,BOOKS[i],.011,'matte');crayon.rotation.z=(i-2.5)*.05;}
}
function paintingTexture(k,index) {
  return k.texture('child-art-'+index,(c,w,h)=>{
    c.fillStyle='#fff7e7';c.fillRect(0,0,w,h);
    if(index%3===0){for(let i=0;i<4;i++){c.strokeStyle=BOOKS[i];c.lineWidth=27;c.beginPath();c.arc(w*.5,h*.67,w*.36-i*28,Math.PI,0);c.stroke();}c.fillStyle='#bfce9a';c.fillRect(40,h*.73,w-80,9);}
    else if(index%3===1){c.fillStyle='#ecc36f';c.beginPath();c.arc(w*.7,h*.27,40,0,Math.PI*2);c.fill();c.fillStyle='#abc5a0';c.beginPath();c.moveTo(0,h);c.quadraticCurveTo(w*.3,h*.2,w,h);c.fill();c.fillStyle='#9dbbca';c.fillRect(w*.27,h*.46,w*.3,h*.36);c.fillStyle='#d9a391';c.beginPath();c.moveTo(w*.23,h*.47);c.lineTo(w*.43,h*.27);c.lineTo(w*.61,h*.47);c.fill();}
    else{for(let i=0;i<5;i++){const x=60+i*82,yy=h*.40+(i%2)*40;c.strokeStyle='#8cac7b';c.lineWidth=7;c.beginPath();c.moveTo(x,h*.88);c.lineTo(x,yy);c.stroke();for(let j=0;j<6;j++){c.fillStyle=BOOKS[i%6];c.beginPath();c.ellipse(x+Math.cos(j*Math.PI/3)*22,yy+Math.sin(j*Math.PI/3)*22,20,14,j*Math.PI/3,0,Math.PI*2);c.fill();}c.fillStyle='#e6bb56';c.beginPath();c.arc(x,yy,12,0,Math.PI*2);c.fill();}}
  },512,384);
}

/** Warm classroom with separate reading, art, dining, rest and welcome areas. */
export function buildRefinedRoom(k) {
  const p=new THREE.Group();p.name='refined-room';
  k.box(p,0,-.20,0,16.6,.43,12.05,'#ccac86',.18);
  // Individually jointed boards use a shared generated grain, not hundreds of images.
  const shades=['#e8c291','#edc99b','#e3ba85','#eac699'];
  for(let col=0;col<27;col++)for(let row=0;row<4;row++) {
    const x=-7.98+col*.613,z=-4.51+row*2.98;
    k.box(p,x,.027,z,.587,.039,2.945,shades[(col*3+row)%4],.005);
  }
  k.box(p,0,2.43,-5.91,16.65,4.85,.18,CREAM,.02,'matte');
  k.box(p,-8.25,2.43,0,.17,4.85,12,CREAM,.02,'matte');
  k.box(p,0,.44,-5.76,16.4,.90,.1,'#d6dfc3',.01,'wood');
  for(let i=0;i<32;i++)k.box(p,-7.95+i*.513,.44,-5.692,.024,.90,.015,'#c9d4b9',0,'matte');
  k.box(p,0,.92,-5.64,16.42,.09,.15,'#e2c291');k.box(p,0,.10,-5.63,16.42,.13,.13,'#d6b88d');
  k.box(p,0,4.83,-5.68,16.5,.22,.38,'#d8b082',.03);k.box(p,-8.00,4.83,0,.38,.22,12,'#d8b082',.03);
  const sky=k.texture('window-garden',(c,w,h)=>{
    const grad=c.createLinearGradient(0,0,0,h);grad.addColorStop(0,'#d8edf0');grad.addColorStop(.7,'#f3f4df');grad.addColorStop(1,'#c9d8ab');c.fillStyle=grad;c.fillRect(0,0,w,h);
    for(let i=0;i<18;i++){const x=(i*137)%w,yy=h*.74+Math.sin(i*1.9)*h*.12;c.fillStyle=i%2?'#b1c8a1':'#c7d6af';c.beginPath();c.arc(x,yy,36+(i%3)*18,0,Math.PI*2);c.fill();}
  },512,768);
  for(let i=0;i<4;i++) {
    const z=-4.35+i*2.9;
    k.plane(p,-8.147,2.91,z,2.62,3.07,sky,[0,Math.PI/2,0]);
    for(const zz of [z-1.38,z,z+1.38])k.box(p,-7.995,2.91,zz,.27,3.29,.095,'#fff7e9',.014);
    for(const yy of [1.25,2.91,4.55])k.box(p,-7.995,yy,z,.29,.10,2.90,'#fff7e9',.014);
    k.box(p,-7.80,1.21,z,.71,.125,2.95,'#e3bf8e',.035);
    for(const s of [-1,1])for(let j=0;j<4;j++) {
      const curtain=k.cyl(p,-7.84,2.89,z+s*(1.37+j*.065),.07,3.26,'#eee0c2',.055,'fabric');curtain.scale.x=.60;
    }
    plant(k,p,-7.66,1.29,z+.63,.50);
  }
  const glow=k.texture('window-light',(c,w,h)=>{const g=c.createLinearGradient(0,0,w,0);g.addColorStop(0,'rgba(255,244,206,0)');g.addColorStop(.18,'rgba(255,247,218,.65)');g.addColorStop(.83,'rgba(255,249,227,.4)');g.addColorStop(1,'rgba(255,250,230,0)');c.fillStyle=g;c.fillRect(0,0,w,h);},128);
  for(let i=0;i<4;i++)k.plane(p,-3.85,.064,-3.9+i*2.75,7.1,1.75,glow,[-Math.PI/2,0,-.26],.38);
  // Dynamic class title is drawn from the real group label, never a mock student list.
  const blackboard=k.group(p,'schedule');
  k.box(blackboard,.10,3.04,-5.54,6.85,2.26,.18,'#c79c68',.065);k.box(blackboard,.10,3.06,-5.415,6.60,2.01,.06,'#466553',.035,'matte');
  let currentTitle='一起玩 · 一起学';
  const drawBoard=(c,w,h,title)=>{
    c.clearRect(0,0,w,h);c.fillStyle='#fff2ca';c.textAlign='center';c.font=`500 65px ${FONT}`;c.fillText(title.length>15?title.slice(0,15)+'…':title,w*.53,h*.39,w*.72);
    c.font=`32px ${FONT}`;c.fillStyle='#e6ead1';c.fillText('让每个孩子，都闪闪发光',w*.53,h*.66);c.font=`21px ${FONT}`;c.fillStyle='#c6d8b6';c.fillText('有爱 · 有趣 · 一起成长',w*.53,h*.84);
    c.strokeStyle='#f1cd6f';c.lineWidth=4;c.beginPath();c.arc(w*.095,h*.4,31,0,Math.PI*2);c.stroke();for(let i=0;i<8;i++){const a=i*Math.PI/4;c.beginPath();c.moveTo(w*.095+Math.cos(a)*42,h*.4+Math.sin(a)*42);c.lineTo(w*.095+Math.cos(a)*56,h*.4+Math.sin(a)*56);c.stroke();}
  };
  const boardTexture=k.texture('live-class-title',(c,w,h)=>drawBoard(c,w,h,currentTitle),1024,320);
  k.plane(blackboard,.1,3.09,-5.373,6.3,1.86,boardTexture);
  k.box(blackboard,.1,1.87,-5.26,6.92,.10,.38,WOOD);
  for(let i=0;i<4;i++)k.cyl(blackboard,-.7+i*.2,1.947,-5.16,.021,.13,['#fff0da','#d9b580','#c6d7b9','#cda9b4'][i],.021,'matte').rotation.z=Math.PI/2;
  shelf(k,p,-.7,-5.18,4.95,'schedule',2);
  // Shelves above the board, plants and hanging bunting.
  k.box(p,.1,4.36,-5.42,7.1,.09,.57,WOOD);
  for(const x of [-2.85,-.65,2.91])plant(k,p,x,4.42,-5.41,.39);
  bear(k,p,1.35,4.43,-5.39,.37);bear(k,p,1.82,4.43,-5.39,.29);
  for(let i=0;i<8;i++)book(k,p,-1.97+i*.12,4.42,-5.40,BOOKS[i%6],.26+(i%2)*.045);
  for(let i=0;i<9;i++) {
    const x=-2.5+i*.62,yy=4.02-Math.sin(i/8*Math.PI)*.11;
    const g=k.geometry('bunting',()=>new THREE.ConeGeometry(.11,.22,3));const m=k.mesh(p,g,BOOKS[i%6],[x,yy,-5.31]);m.rotation.z=Math.PI;
  }
  // Reading corner: fabric tent, fairy lights, beanbags and faced-out books.
  const reading=k.group(p,'records');shelf(k,reading,-5.25,-5.16,3.02,'records',2);
  const tent=k.group(reading,null,[-6.6,0,-3.12]);
  const polePoints=[[-1,0,-.74],[1,0,-.74],[-1,0,.78],[1,0,.78]];
  for(const point of polePoints)k.limb(tent,point,[.06,2.77,-.12],.042,WOOD,'wood');
  const cloth=k.material('#f3e7cb','fabric');cloth.side=THREE.DoubleSide;
  for(const [a,b] of [[polePoints[0],polePoints[1]],[polePoints[0],polePoints[2]],[polePoints[1],polePoints[3]]]) {
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute([...a,...b,.06,2.59,-.12],3));geo.setAttribute('uv',new THREE.Float32BufferAttribute([0,0,1,0,.5,1],2));geo.computeVertexNormals();k.geometries.set('tent:'+k.geometries.size,geo);k.mesh(tent,geo,cloth);
  }
  const glowMat=k.material('#fff1b8','ceramic');glowMat.emissive=new THREE.Color('#f0c879');glowMat.emissiveIntensity=.45;
  for(let i=0;i<11;i++){const t=i/10;k.ball(tent,-.98+1.03*t,.10+2.49*t,.77-.84*t,.030,glowMat);}
  for(const slot of ILLUSTRATIVE_SLOTS.filter(s=>s.cushion)) {
    const bean=k.ball(reading,slot.x,.28,slot.z,.43,'#afbf8e',[1.53,.84,1.30],'fabric');bean.rotation.y=.3;
    k.ball(reading,slot.x-.10,.56,slot.z-.27,.37,'#a6b981',[1.10,1,.65],'fabric');k.shadow(reading,slot.x,slot.z,1.5,1.3,.30);
  }
  bear(k,reading,-7.13,.26,-2.20,.66);plant(k,reading,-7.31,0,-.4,.95);
  for(let i=0;i<3;i++){const b=k.box(reading,-5.37+i*.34,.23,-.24,.29,.40,.055,BOOKS[i],.018,'matte');b.rotation.x=-.14;}
  // Teaching and dining furniture are separate physical business objects.
  const central=table(k,p,-.85,-1.45,'records',1.21);
  for(let i=0;i<4;i++){const a=i*Math.PI/2,x=Math.cos(a)*.55,z=Math.sin(a)*.55;k.plane(central,x,1.097,z,.47,.37,paintingTexture(k,i),[-Math.PI/2,0,a]);}
  crayonCup(k,central,0,1.09,0);
  const dining=table(k,p,3.45,.45,'meals',.99);
  for(let i=0;i<5;i++) {
    const a=i*Math.PI*2/5,x=Math.cos(a)*.63,z=Math.sin(a)*.63;
    k.cyl(dining,x,1.103,z,.21,.033,'#fff8e3',.22,'ceramic');const rim=k.ring(dining,x,1.124,z,.186,.012,'#d6dfba');rim.rotation.x=Math.PI/2;
    k.ball(dining,x-.07,1.147,z,.067,'#eee1b2',[1,.47,1]);
    for(let j=0;j<3;j++)k.ball(dining,x+.055+(j%2)*.038,1.162,z-.05+j*.03,.037,['#8ca564','#e6b361','#98b671'][j],[1,.72,1]);
  }
  k.cyl(dining,0,1.19,0,.12,.22,'#b2c9c5',.14,'ceramic');
  // Arts: broad table, papers, jars, palette and hand-painted easel.
  const art=k.group(p,'art',[-5.20,0,2.03]);k.box(art,0,.99,0,3.07,.13,1.22,WOOD,.085);
  for(const x of [-1.27,1.27])for(const z of [-.43,.43])k.limb(art,[x,.95,z],[x*1.05,.06,z*1.1],.060,EDGE,'wood');
  for(let i=0;i<4;i++)k.plane(art,-1.05+i*.70,1.067,(i%2?-.16:.14),.58,.44,paintingTexture(k,i),[-Math.PI/2,0,.10*i]);
  for(const x of [-.75,.78])crayonCup(k,art,x,1.067,-.09);
  k.cyl(art,.03,1.092,.15,.18,.038,'#f0dfb9',.18,'ceramic');
  for(let i=0;i<5;i++){const a=i*Math.PI*2/5;k.ball(art,.03+Math.cos(a)*.12,1.12,.15+Math.sin(a)*.12,.032,BOOKS[i],[1,.24,1]);}
  for(let i=0;i<4;i++)k.cyl(art,-1.10+i*.22,1.18,-.29,.07,.21,BOOKS[i],.072,'ceramic');
  k.shadow(p,-5.2,2.03,3.8,2.1,.29);
  const easel=k.group(p,'art',[-7.3,0,1.42]);
  for(const x of [-.43,.43])k.limb(easel,[x,0,.18],[x*.5,2.23,-.1],.039,WOOD,'wood');k.limb(easel,[0,0,-.55],[0,2.23,-.1],.039,WOOD,'wood');
  k.box(easel,0,1.45,0,1.06,1.20,.09,WOOD);k.plane(easel,0,1.45,.055,.93,1.07,paintingTexture(k,2));k.box(easel,0,.90,.12,1.17,.08,.23,WOOD);
  // Chairs belong to the decorative layout; no extra fake pupils are generated.
  ILLUSTRATIVE_SLOTS.filter(s=>s.seated).forEach(s=>chair(k,p,s));
  // A woven sun rug leaves a clear centre-front circulation area.
  const rugTexture=k.texture('sun-rug',(c,w,h)=>{
    c.clearRect(0,0,w,h);c.fillStyle='#f2dfb7';c.beginPath();c.arc(w/2,h/2,w*.476,0,Math.PI*2);c.fill();
    for(let i=0;i<210;i++){const a=i*Math.PI*2/210;c.strokeStyle=i%2?'#d3b883':'#e1c99b';c.lineWidth=1.5;c.beginPath();c.moveTo(w/2+Math.cos(a)*w*.46,h/2+Math.sin(a)*h*.46);c.lineTo(w/2+Math.cos(a)*w*.482,h/2+Math.sin(a)*h*.482);c.stroke();}
    c.strokeStyle='#cbb080';c.lineWidth=2;c.setLineDash([5,7]);c.beginPath();c.arc(w/2,h/2,w*.425,0,Math.PI*2);c.stroke();c.setLineDash([]);
    c.fillStyle='#e7bd60';c.beginPath();c.arc(w/2,h*.38,w*.13,0,Math.PI*2);c.fill();
    for(let i=0;i<10;i++){const a=i*Math.PI/5;c.save();c.translate(w/2+Math.cos(a)*w*.205,h*.38+Math.sin(a)*w*.205);c.rotate(a);c.fillStyle='#e0b460';c.beginPath();c.ellipse(0,0,27,10,0,0,Math.PI*2);c.fill();c.restore();}
    c.fillStyle='#7d694c';for(const dx of [-1,1]){c.beginPath();c.arc(w/2+dx*34,h*.38-11,6,0,Math.PI*2);c.fill();}c.strokeStyle='#8c6a48';c.lineWidth=5;c.beginPath();c.arc(w/2,h*.38+5,27,.2,Math.PI-.2);c.stroke();
    c.font=`bold 51px ${FONT}`;c.fillStyle='#a67e48';c.textAlign='center';c.fillText('一起长大',w/2,h*.715);c.font=`27px ${FONT}`;c.fillText('有爱 · 有趣 · 有光',w/2,h*.785);
  },1024);
  k.plane(p,-.3,.07,3.63,4.15,4.15,rugTexture,[-Math.PI/2,0,0]);
  // Rest area: empty beds and toy bear, not fabricated sleeping attendance.
  const rest=k.group(p,'rest');
  const quiltTex=k.texture('quilt-stars',(c,w,h)=>{c.fillStyle='#b9cedb';c.fillRect(0,0,w,h);for(let i=0;i<25;i++)star(c,35+(i%5)*102,40+Math.floor(i/5)*100,12,'#f8edce');c.strokeStyle='#a7bfcb';c.lineWidth=1;for(let i=0;i<w;i+=64){c.beginPath();c.moveTo(i,0);c.lineTo(i,h);c.stroke();c.beginPath();c.moveTo(0,i);c.lineTo(w,i);c.stroke();}},512);
  const quilt=k.material('#ffffff','fabric').clone();quilt.map=quiltTex;k.materials.set('quilt-material',quilt);
  for(const [x,z] of [[4.87,-3.93],[6.72,-3.93],[6.72,-1.48]]) {
    const bed=k.group(rest,null,[x,0,z]);k.shadow(rest,x,z,1.8,2.8,.27);
    k.box(bed,0,.31,0,1.34,.26,2.03,WOOD,.06);k.box(bed,0,.53,0,1.22,.24,1.91,'#f5e8d7',.09,'fabric');
    k.box(bed,0,.67,.34,1.245,.18,1.23,quilt,.07,'fabric');k.box(bed,0,.754,-.21,1.25,.12,.23,'#d2dfdf',.055,'fabric');
    k.box(bed,0,.734,-.64,.90,.18,.45,'#f9efdc',.13,'fabric');
    for(const zz of [-1.04,1.04]){k.box(bed,0,.58,zz,1.47,.38,.10,WOOD,.04);for(const xx of [-.68,.68])k.cyl(bed,xx,.45,zz,.05,.89,EDGE);}
  }
  bear(k,rest,4.98,.82,-4.49,.39);
  for(let i=0;i<3;i++) {
    const x=4.57+i*1.08;k.box(p,x,3.31,-5.61,.87,.74,.06,'#d6bc8e');k.plane(p,x,3.31,-5.564,.76,.63,paintingTexture(k,i));
    k.box(p,x,3.74,-5.56,.055,.13,.04,'#b69c72',.008);
  }
  k.sign(p,5.6,4.20,-5.58,3.55,.51,'wall-rest-word',(c,w,h)=>{c.fillStyle='#8a9d77';c.font=`bold 80px ${FONT}`;c.textAlign='center';c.fillText('甜甜的梦 · 慢慢长大',w/2,h*.70);});
  // Decorative clock deliberately has no invented current clock hands.
  const clock=k.cyl(p,3.97,4.27,-5.60,.32,.10,'#cba57b');clock.rotation.x=Math.PI/2;
  k.sign(p,3.97,4.27,-5.52,.60,.60,'flower-clock',(c,w,h)=>{c.fillStyle='#fffae9';c.beginPath();c.arc(w/2,h/2,w*.47,0,Math.PI*2);c.fill();for(let i=0;i<12;i++){const a=i*Math.PI/6;c.fillStyle='#baa888';c.beginPath();c.arc(w/2+Math.cos(a)*w*.36,h/2+Math.sin(a)*h*.36,7,0,Math.PI*2);c.fill();}c.fillStyle='#b5c49b';c.font='210px serif';c.textAlign='center';c.fillText('✿',w/2,h*.65);});
  // Welcome objects, name cubbies, bags, health cabinet and mailbox.
  const cabinet=shelf(k,p,6.84,5.04,2.39,'roster',2);
  for(let i=0;i<3;i++){k.box(cabinet,-.73+i*.72,1.61,0,.41,.49,.27,BOOKS[i],.10,'fabric');const loop=k.ring(cabinet,-.73+i*.72,1.88,0,.078,.017,EDGE);loop.scale.y=.75;}
  const health=k.group(p,'health',[7.21,0,1.65]);
  k.box(health,0,.72,0,1.38,1.43,.67,'#f6efdf',.07);k.box(health,0,1.47,0,1.50,.08,.79,WOOD);
  for(const s of [-1,1]){k.box(health,s*.335,.73,.36,.625,1.26,.045,'#fff9e9',.025,'matte');k.ball(health,s*.11,.79,.41,.031,'#c5a476',[1,1,.4],'metal');}
  k.box(health,0,1.77,.025,.13,.37,.04,'#ca8982',.02,'matte');k.box(health,0,1.77,.025,.36,.13,.045,'#ca8982',.02,'matte');plant(k,health,-.48,1.53,-.09,.40);
  const mail=k.group(p,'contact',[4.18,0,4.88]);k.box(mail,0,.64,0,.13,1.2,.13,WOOD);k.box(mail,0,1.40,0,.87,.74,.54,'#d7a094',.11);k.box(mail,0,1.56,.29,.51,.063,.014,'#9f6e62',.016,'matte');k.box(mail,0,1.31,.293,.26,.19,.017,'#fff0d6',.03,'matte');k.shadow(p,4.18,4.88,1.1,.75,.22);
  const arrival=k.group(p,'attendance',[-7.05,0,4.93]);k.box(arrival,0,.65,0,.85,1.29,.57,WOOD,.06);k.box(arrival,0,1.55,-.015,.79,.62,.12,'#8fbdb7',.06,'matte');k.box(arrival,0,1.56,.062,.66,.48,.017,'#fff8e8',.02,'matte');
  k.sign(arrival,0,1.56,.078,.57,.37,'sign-arrival',(c,w,h)=>{c.fillStyle='#5a8d87';c.font=`bold 170px ${FONT}`;c.textAlign='center';c.fillText('点名',w/2,h*.74);});
  const leave=k.group(p,'leave',[-4.02,0,5.07]);k.box(leave,0,.73,0,1.08,.12,.66,WOOD);for(const x of [-.4,.4])k.box(leave,x,.36,0,.08,.73,.45,EDGE);
  k.box(leave,0,.862,0,.64,.08,.45,'#b3c89a',.018,'matte');k.box(leave,0,.911,0,.59,.02,.40,'#fff2d7',.007,'matte');
  const workflow=k.group(p,'workflow',[-3.75,0,-3.9]);k.box(workflow,0,1.78,0,.85,1.05,.11,WOOD);k.box(workflow,0,1.79,.067,.71,.90,.02,'#fff4dd',.02,'matte');k.box(workflow,0,.68,0,.11,1.24,.11,EDGE);k.box(workflow,0,.08,0,.73,.12,.49,EDGE);
  k.sign(workflow,0,1.79,.09,.66,.77,'daily-board',(c,w,h)=>{c.textAlign='center';c.fillStyle='#7f946e';c.font=`bold 118px ${FONT}`;c.fillText('一日工作',w/2,h*.24);for(let i=0;i<4;i++){c.fillStyle='#e6d8b5';c.fillRect(95,h*.34+i*170,65,65);c.fillRect(215,h*.36+i*170,625,18);}});
  // Woven basket, toys, globe, flower cushion and climbing plants.
  const toyShelf=shelf(k,p,-7.12,3.38,1.38,'art',2);toyShelf.rotation.y=.25;
  for(let i=0;i<7;i++)k.box(p,-2.64+(i%3)*.19,.15+(i>3?.17:0),4.13+Math.floor(i/3)*.18,.18,.20,.17,BOOKS[i%6],.025,'matte');
  for(const [x,z,s] of [[-7.65,-5.22,.7],[7.63,-5.25,.87],[7.72,.05,.87],[5.5,5.28,.62]])plant(k,p,x,0,z,s);
  k.ball(reading,-6.72,.55,-2.05,.19,'#e8c869',[1,.42,1],'fabric');
  for(let i=0;i<6;i++){const a=i*Math.PI/3;k.ball(reading,-6.72+Math.cos(a)*.23,.56,-2.05+Math.sin(a)*.23,.13,'#fff0d3',[1,.43,1],'fabric');}
  k.ball(p,-3.30,1.67,-5.04,.23,'#91b9c6',[1,1,1],'matte');k.cyl(p,-3.30,1.35,-5.04,.11,.07,WOOD);k.limb(p,[-3.3,1.39,-5.04],[-3.3,1.54,-5.04],.03,EDGE);
  // Small cloud light over the rear reading corner, not covering the work area.
  k.limb(p,[-4.7,5,-4.20],[-4.7,4.17,-4.20],.016,'#b8ac91','metal');
  for(const [dx,r] of [[-.30,.24],[0,.34],[.33,.26]])k.ball(p,-4.7+dx,4.16,-4.20,r,'#fff1cf',[1,.62,.72],'matte');
  for(let i=0;i<6;i++){const yy=4.50-i*.19;const leaf=k.ball(p,-7.84,yy,-5.50+i*.06,.11,'#94ad80',[.67,1.15,.35]);leaf.rotation.z=i%2?.4:-.4;}
  const release=k.batch(p);
  return {root:p,teacher:{x:.18,z:-3.82,angle:.24},
    updateClass(title){if(!title||title===currentTitle)return;currentTitle=String(title);drawBoard(boardTexture.image.getContext('2d'),boardTexture.image.width,boardTexture.image.height,currentTitle);boardTexture.needsUpdate=true;},
    dispose:release};
}
