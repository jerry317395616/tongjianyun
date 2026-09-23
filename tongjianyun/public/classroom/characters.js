import * as THREE from 'three';
import {appearanceFor,blinkScale} from './visual-layout.js?v=refined-20260923-1';

const SHIRTS=['#e9ba4b','#80b3d6','#e4a3ac','#94bc8b','#b5a4ca','#de9b76'];
const SKIN=['#f5cda9','#ecc09b','#dfac87','#c88d6c'];
const HAIR=['#52382a','#3c2e29','#75513b','#644033'];

/** A designed toy-like avatar. No facial-photo, gender, mood or health inference. */
export function createCharacter(k,id,{pose='sit',teacher=false}={}) {
  const a=appearanceFor(id),style=teacher?4:a.hair,skin=teacher?'#f4c8a4':SKIN[a.skin],hair=HAIR[a.seed%4];
  const shirt=teacher?'#f4e9cf':SHIRTS[a.outfit],root=new THREE.Group(),releases=[];
  root.userData.illustration=true;root.userData.pose=pose;root.userData.appearance=a;
  const seated=['sit','read','draw'].includes(pose),body=new THREE.Group(),head=new THREE.Group(),face=new THREE.Group();root.add(body,head);
  head.position.set(0,1.40,0);head.rotation.set(-.025,((a.seed%7)-3)*.035,((a.seed%5)-2)*.018);const baseHead=head.rotation.clone();
  head.add(face);
  // Smooth oversized head, soft cheeks and ears. All detail is actual geometry.
  k.ball(face,0,0,0,.393,skin,[1,1.06,.94],'skin');
  for(const sign of [-1,1]) {
    k.ball(face,sign*.387,-.014,.016,.070,skin,[.60,1,.80],'skin');
    k.ball(face,sign*.408,-.013,.052,.032,'#dc9b84',[.55,.82,.55],'skin');
    k.ball(face,sign*.234,-.116,.296,.057,'#e8a18f',[1,.48,.22],'skin');
  }
  // A variable hairline leaves the face visible; different hairstyles share it.
  const cap=k.geometry('sculpted-hair:'+style,()=>{
    // A partial sphere keeps the last ring's quads. Re-purposing a full sphere
    // would omit half that ring and create an unintended saw-tooth hairline.
    const g=new THREE.SphereGeometry(.404,36,20,0,Math.PI*2,0,1.83);
    const p=g.attributes.position,uv=g.attributes.uv;
    for(let i=0;i<p.count;i++) {
      const phi=uv.getX(i)*Math.PI*2,front=Math.max(0,Math.sin(phi)),v=1-uv.getY(i);
      const edge=1.83-front*(.63+.1*Math.cos(phi+style*.5));const theta=v*edge;
      p.setXYZ(i,-.404*Math.cos(phi)*Math.sin(theta),.404*Math.cos(theta),.387*Math.sin(phi)*Math.sin(theta));
    }
    g.computeVertexNormals();return g;
  });k.mesh(face,cap,hair,[0,.029,-.015],'hair');
  // Swept locks rather than identical bead-like bangs.
  for(let i=0;i<4;i++) {
    const x=-.22+i*.135,y=.27+Math.sin(i*.85)*.045;
    const lock=k.ball(face,x,y,.225,.173,hair,[.63,.97,.48],'hair');lock.rotation.z=-.63+i*.14;
  }
  if(style===0||style===3) {
    for(let i=0;i<3;i++){const lock=k.ball(face,.19+i*.05,.32+i*.006,-.04,.15,hair,[.55,1.24,.74],'hair');lock.rotation.z=-.65;}
    k.ball(face,-.337,.025,.02,.11,hair,[.5,1.15,.6],'hair');
  }
  if(style===1||style===5)for(const s of [-1,1]) {
    const lobe=k.ball(face,s*.326,-.02,-.038,.17,hair,[.63,1.48,.95],'hair');lobe.rotation.z=s*.13;
    if(style===1)k.ball(face,s*.306,-.19,-.075,.12,hair,[.7,.8,.9],'hair');
  }
  if(style===2)for(const s of [-1,1]) {
    k.ball(face,s*.397,.10,-.14,.16,hair,[1.04,.88,.89],'hair');
    const tail=k.ball(face,s*.465,-.025,-.17,.17,hair,[.66,1.23,.83],'hair');tail.rotation.z=s*.4;
    for(const dx of [-.038,.038]){const bow=k.ball(face,s*.37+dx,.17,.035,.062,shirt,[1,.59,.45],'fabric');bow.rotation.z=dx>0?.35:-.35;}
    k.ball(face,s*.37,.17,.077,.025,'#fff2d6');
  }
  if(style===4) {
    k.ball(face,.055,.449,-.13,.155,hair,[1,.96,1],'hair');
    for(let i=0;i<5;i++){const t=i*1.22;k.ball(face,.055+Math.cos(t)*.08,.46+Math.sin(t)*.06,-.096,.081,hair,[.68,.91,.85],'hair');}
    const tie=k.ring(face,.055,.411,-.12,.111,.02,teacher?'#bb8961':shirt);tie.rotation.x=Math.PI/2;
  }
  // Large brown irises with two restrained highlights and upper-lid contours.
  const eyes=[];
  for(const s of [-1,1]) {
    const eye=new THREE.Group();eye.position.set(s*.142,.018,.335);head.add(eye);eyes.push(eye);
    k.ball(eye,0,0,0,.080,'#fffaf0',[.93,1.16,.41],'eye');
    k.ball(eye,s*.003,-.001,.026,.069,'#35291f',[.91,1.15,.49],'eye');
    k.ball(eye,-.017,.030,.064,.015,'#fffaf0',[1,1,.42],'eye');
    k.ball(eye,.020,-.021,.063,.006,'#fffaf0',[1,1,.40],'eye');
    k.curve(face,[[s*.142-.071,.045,.361],[s*.142-.052,.094,.354],[s*.142,.106,.352],[s*.142+.066,.070,.352]],.008,hair,'hair');
    k.curve(face,[[s*.142-.051,.154,.323],[s*.142,.169,.340],[s*.142+.052,.150,.320]],.010,hair,'hair');
  }
  k.ball(face,0,-.084,.357,.044,skin,[.76,.81,.82],'skin');
  if(!teacher&&a.outfit%3===0) {
    k.curve(face,[[-.068,-.181,.332],[0,-.211,.340],[.068,-.181,.332]],.009,'#996951','skin');
  } else {
    k.ball(face,0,-.201,.313,.082,'#87493d',[1.03,.65,.29],'matte');
    k.ball(face,0,-.178,.340,.059,'#fff7e8',[1,.27,.18],'matte');
    k.ball(face,0,-.231,.333,.041,'#e49a91',[1,.40,.23],'matte');
  }
  if(!teacher&&a.accessory===0) {
    for(const s of [-1,1]){const rim=k.ring(face,s*.142,.02,.41,.092,.011,'#967350',Math.PI*2,'metal');rim.scale.y=1.12;}
    k.curve(face,[[-.052,.022,.423],[0,.036,.43],[.052,.022,.423]],.010,'#967350','metal');
  }
  // Rounded knit clothing, cuffs, overalls and tiny seams.
  k.ball(body,0,.881,-.01,.233,shirt,[1,1.10,.76],'fabric');
  k.cyl(body,0,1.107,.012,.071,.12,skin,.067,'skin');
  for(const s of [-1,1]){const collar=k.ball(body,s*.066,1.071,.145,.081,'#fffae9',[.70,.37,.33],'fabric');collar.rotation.z=s*.4;}
  if(teacher||a.outfit%2===0) {
    const apron=teacher?'#e9ce91':['#719cad','#a2ad7c','#c79491'][a.outfit%3];
    k.box(body,0,.86,.158,.284,.30,.07,apron,.043,'fabric');
    for(const s of [-1,1]) {k.limb(body,[s*.096,1.084,.123],[s*.112,.822,.209],.024,apron,'fabric');k.ball(body,s*.111,.923,.206,.017,'#f2dbb7');}
    k.box(body,0,.802,.204,.131,.089,.018,teacher?'#f6e9bf':shirt,.022,'fabric');
    k.ball(body,0,.94,.214,.035,'#f6d571',[1,1,.2]);
  } else {
    k.ball(body,0,.914,.177,.055,'#fff2ce',[1,1,.22]);
    for(let i=0;i<6;i++){const t=i*Math.PI/3;k.ball(body,Math.cos(t)*.074,.914+Math.sin(t)*.074,.178,.020,'#fff2ce',[1,1,.25]);}
  }
  const pants=teacher?'#aa967c':['#88a1ba','#afaa8f','#9ea993'][a.outfit%3];
  for(const s of [-1,1]) {
    const hip=[s*.12,.689,0],knee=[s*.136,.41,seated?.31:.005],ankle=[s*.14,.165,seated?.40:.03];
    k.limb(body,hip,knee,.094,pants,'fabric');k.limb(body,knee,ankle,.078,pants,'fabric');
    k.cyl(body,s*.14,.169,ankle[2],.067,.13,'#fcf4df',.067,'fabric');
    k.box(body,s*.142,.097,ankle[2]+.07,.207,.133,.325,teacher?'#8b7764':'#fff5de',.045,'matte');
    k.box(body,s*.142,.040,ankle[2]+.07,.213,.038,.333,'#eadfc9',.018,'matte');
    for(let j=0;j<2;j++)k.box(body,s*.142,.174,ankle[2]+.079+j*.061,.118,.012,.019,shirt,.004,'fabric');
  }
  const arms=[];
  for(const s of [-1,1]) {
    const arm=new THREE.Group();arm.position.set(s*.196,1.027,0);root.add(arm);
    const wave=(pose==='wave'||teacher)&&s===-1;
    const elbow=wave?[s*.17,.18,.04]:[s*.13,-.19,.09];
    const hand=wave?[s*.22,.43,.09]:pose==='read'?[s*.025,-.13,.43]:pose==='draw'?[s*.13,-.07,.41]:[s*.13,-.37,.20];
    k.limb(arm,[0,0,0],elbow,.071,shirt,'fabric');k.limb(arm,elbow,hand,.059,shirt,'fabric');
    k.ball(arm,...hand,.075,skin,[.84,1,.64],'skin');
    if(wave)for(let f=0;f<4;f++)k.limb(arm,[hand[0]-.045+f*.029,hand[1]+.03,hand[2]],[hand[0]-.045+f*.031,hand[1]+.10-Math.abs(f-1.4)*.01,hand[2]],.014,skin,'skin');
    if(pose==='draw'&&s===1) {
      k.limb(arm,[hand[0],hand[1]-.1,hand[2]+.06],[hand[0]+.05,hand[1]+.18,hand[2]-.04],.012,SHIRTS[(a.outfit+1)%6]);
      k.ball(arm,hand[0],hand[1]-.11,hand[2]+.063,.018,'#bb705a',[.6,1.6,.6]);
    }
    releases.push(k.batch(arm));arms.push({group:arm,wave});
  }
  if(pose==='read') {
    const book=new THREE.Group();book.position.set(0,.96,.47);book.rotation.x=-.28;body.add(book);
    for(const s of [-1,1]){const page=new THREE.Group();page.rotation.y=s*.23;book.add(page);k.box(page,s*.113,0,0,.222,.277,.037,s===1?'#afbd79':'#a8bc8a',.012,'matte');k.box(page,s*.112,0,.025,.202,.246,.012,'#fff3d5',.003,'matte');k.ball(page,s*.113,.028,.038,.045,s===1?'#e1b46e':'#8ab39b',[1,1,.16]);for(let i=0;i<3;i++)k.box(page,s*.112,-.038-i*.024,.036,.136,.007,.004,'#c0b098',0,'matte');}
  }
  if(!seated&&!teacher){
    k.box(body,0,.884,-.203,.334,.361,.148,SHIRTS[(a.outfit+2)%6],.07,'fabric');k.box(body,0,.785,-.292,.220,.129,.037,shirt,.032,'fabric');
    for(const s of [-1,1])k.curve(body,[[s*.10,1.066,-.15],[s*.183,1.01,.04],[s*.195,.82,.125],[s*.148,.718,-.08]],.024,SHIRTS[(a.outfit+2)%6],'fabric');
  }
  releases.push(k.batch(body),k.batch(face));
  for(const eye of eyes)releases.push(k.batch(eye));
  if(teacher){root.scale.setScalar(1.31);head.scale.setScalar(.9);head.position.y=1.53;body.scale.y=1.12;arms.forEach(a=>{a.group.position.y+=.115;});}
  const rig={root,head,eyes,arms,phase:a.phase,
    animate(seconds,active=true){
      const blink=active?blinkScale(seconds,a.phase):1;eyes.forEach(e=>{e.scale.y=blink;});
      head.rotation.x=baseHead.x+(active?Math.sin(seconds*.9+a.phase)*.018:0);
      head.rotation.z=baseHead.z+(active?Math.sin(seconds*.65+a.phase)*.017:0);
      arms.forEach(({group,wave})=>{group.rotation.z=active&&wave?Math.sin(seconds*2.1+a.phase)*.075:0;});
    },
    dispose(){releases.forEach(release=>release());root.removeFromParent();}
  };
  return rig;
}
