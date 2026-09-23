import * as THREE from 'three';

/** Shared procedural materials/geometry. Assets stay on this site. */
export class VisualKit {
  constructor(renderer) { this.renderer=renderer;this.materials=new Map();this.geometries=new Map();this.textures=new Map();this.merged=new Set(); }
  geometry(key,build) {if(!this.geometries.has(key))this.geometries.set(key,build());return this.geometries.get(key);}
  texture(key,draw,w=512,h=w) {
    if(this.textures.has(key))return this.textures.get(key);
    const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;draw(canvas.getContext('2d'),w,h);
    const t=new THREE.CanvasTexture(canvas);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=Math.min(8,this.renderer.capabilities.getMaxAnisotropy());this.textures.set(key,t);return t;
  }
  grain(kind) {
    return this.texture('grain:'+kind,(c,w,h)=>{
      let n=773;const rand=()=>{n=(Math.imul(n,1664525)+1013904223)>>>0;return n/4294967296;};
      c.fillStyle=kind==='wood'?'#fff3dd':'#fffdf8';c.fillRect(0,0,w,h);
      if(kind==='wood')for(let i=0;i<170;i++){
        const y=rand()*h;c.strokeStyle=`rgba(139,96,41,${.025+rand()*.075})`;c.lineWidth=.4+rand()*1.4;c.beginPath();c.moveTo(0,y);
        for(let x=0;x<=w;x+=16)c.lineTo(x,y+Math.sin(x/90+i)*(.8+rand()*2.5));c.stroke();
      } else {
        for(let i=0;i<w;i+=4){c.strokeStyle='rgba(144,127,99,.06)';c.beginPath();c.moveTo(i,0);c.lineTo(i,h);c.stroke();c.beginPath();c.moveTo(0,i);c.lineTo(w,i);c.stroke();}
        for(let i=0;i<2800;i++){c.fillStyle=`rgba(118,105,78,${rand()*.055})`;c.fillRect(rand()*w,rand()*h,1,1);}
      }
    },512);
  }
  material(color,kind='matte') {
    const key=kind+':'+color;
    if(!this.materials.has(key)) {
      const roughness={skin:.78,hair:.64,eye:.32,wood:.67,fabric:.96,ceramic:.38,metal:.34,matte:.78}[kind]??.78;
      const material=new THREE.MeshStandardMaterial({color,roughness,metalness:kind==='metal'?.35:0});
      if(kind==='wood'||kind==='fabric')material.map=this.grain(kind);
      this.materials.set(key,material);
    }
    return this.materials.get(key);
  }
  mesh(parent,geometry,color,pos=[0,0,0],kind='matte') {
    const m=new THREE.Mesh(geometry,typeof color==='string'?this.material(color,kind):color);m.position.set(...pos);m.castShadow=true;m.receiveShadow=true;parent.add(m);return m;
  }
  box(p,x,y,z,w,h,d,color,r=.04,kind='wood') {
    const key=['rounded',w,h,d,r].join(':');
    const geometry=this.geometry(key,()=>{
      if(!r)return new THREE.BoxGeometry(w,h,d);
      const radius=Math.min(r,w*.22,h*.22,d*.22),a=w/2-radius,b=h/2-radius,s=new THREE.Shape();
      s.moveTo(-a,-h/2);s.lineTo(a,-h/2);s.quadraticCurveTo(w/2,-h/2,w/2,-b);s.lineTo(w/2,b);s.quadraticCurveTo(w/2,h/2,a,h/2);s.lineTo(-a,h/2);s.quadraticCurveTo(-w/2,h/2,-w/2,b);s.lineTo(-w/2,-b);s.quadraticCurveTo(-w/2,-h/2,-a,-h/2);
      const g=new THREE.ExtrudeGeometry(s,{steps:1,depth:d-2*radius,bevelEnabled:true,bevelSize:radius*.45,bevelThickness:radius,bevelSegments:3,curveSegments:5});g.translate(0,0,-(d-2*radius)/2);
      // ExtrudeGeometry's default world-unit UVs clamp long tabletops/quilts to
      // one edge texel. Normalise each face so actual grain and fabric stay visible.
      const position=g.attributes.position,normal=g.attributes.normal,uv=g.attributes.uv;
      for(let i=0;i<position.count;i++) {
        const nx=Math.abs(normal.getX(i)),ny=Math.abs(normal.getY(i)),nz=Math.abs(normal.getZ(i));
        if(ny>nx&&ny>nz)uv.setXY(i,position.getX(i)/w+.5,position.getZ(i)/d+.5);
        else if(nx>nz)uv.setXY(i,position.getZ(i)/d+.5,position.getY(i)/h+.5);
        else uv.setXY(i,position.getX(i)/w+.5,position.getY(i)/h+.5);
      }
      return g;
    });return this.mesh(p,geometry,color,[x,y,z],kind);
  }
  ball(p,x,y,z,r,color,scale=[1,1,1],kind='matte') {
    const m=this.mesh(p,this.geometry('ball:'+r,()=>new THREE.SphereGeometry(r,r>=.32?32:16,r>=.32?20:10)),color,[x,y,z],kind);m.scale.set(...scale);return m;
  }
  cyl(p,x,y,z,r,h,color,top=r,kind='wood') {return this.mesh(p,this.geometry(`cyl:${r}:${h}:${top}`,()=>new THREE.CylinderGeometry(top,r,h,24)),color,[x,y,z],kind);}
  ring(p,x,y,z,r,t,color,arc=Math.PI*2,kind='matte') {return this.mesh(p,this.geometry(`ring:${r}:${t}:${arc}`,()=>new THREE.TorusGeometry(r,t,8,40,arc)),color,[x,y,z],kind);}
  limb(p,a,b,r,color,kind='matte',caps=true) {
    const start=new THREE.Vector3(...a),end=new THREE.Vector3(...b),length=start.distanceTo(end);
    const geometry=this.geometry(`limb:${r}:${length.toFixed(5)}:${caps}`,()=>caps?new THREE.CapsuleGeometry(r,Math.max(.005,length-2*r),4,12):new THREE.CylinderGeometry(r,r,length,12));
    const m=this.mesh(p,geometry,color,[0,0,0],kind);m.position.copy(start.clone().add(end).multiplyScalar(.5));m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),end.sub(start).normalize());return m;
  }
  curve(p,points,r,color,kind='matte') {
    const key='curve:'+JSON.stringify([points,r]);const geometry=this.geometry(key,()=>new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points.map(a=>new THREE.Vector3(...a))),20,r,7,false));return this.mesh(p,geometry,color,[0,0,0],kind);
  }
  plane(p,x,y,z,w,h,texture,rotation=[0,0,0],opacity=1) {
    const key='plane-material:'+texture.uuid+':'+opacity;
    if(!this.materials.has(key))this.materials.set(key,new THREE.MeshBasicMaterial({map:texture,transparent:true,opacity,depthWrite:false,side:THREE.DoubleSide,toneMapped:false}));
    const m=this.mesh(p,this.geometry(`plane:${w}:${h}`,()=>new THREE.PlaneGeometry(w,h)),this.materials.get(key),[x,y,z]);m.rotation.set(...rotation);m.castShadow=false;m.receiveShadow=false;return m;
  }
  sign(p,x,y,z,w,h,key,draw) {return this.plane(p,x,y,z,w,h,this.texture(key,draw,1024,Math.max(128,Math.round(1024*h/w))));}
  shadow(p,x,z,w,d,opacity=.18) {
    const t=this.texture('contact-shadow',(c,W,H)=>{const g=c.createRadialGradient(W/2,H/2,0,W/2,H/2,W/2);g.addColorStop(0,'rgba(79,57,34,.65)');g.addColorStop(.48,'rgba(79,57,34,.25)');g.addColorStop(1,'rgba(79,57,34,0)');c.fillStyle=g;c.fillRect(0,0,W,H);},128);
    const mesh=this.plane(p,x,.055,z,w,d,t,[-Math.PI/2,0,0],opacity);mesh.raycast=()=>{};return mesh;
  }
  group(p,action=null,pos=[0,0,0]) {const g=new THREE.Group();g.position.set(...pos);if(action)g.userData.action=action;p.add(g);return g;}
  /** Batch opaque static meshes by material AND business action. Preserve raycast semantics. */
  batch(root) {
    root.updateWorldMatrix(true,true);const inverse=root.matrixWorld.clone().invert(),buckets=new Map(),sources=[];
    root.traverse(m=>{
      if(!m.isMesh||m.material.transparent||m.userData.keepSeparate)return;
      let action=null,q=m;while(q){if(q.userData.action)action=q.userData.action;if(q===root)break;q=q.parent;}
      const key=[m.material.uuid,action||'',m.castShadow,m.receiveShadow].join(':');
      if(!buckets.has(key))buckets.set(key,{items:[],material:m.material,action,cast:m.castShadow,receive:m.receiveShadow});
      buckets.get(key).items.push({m,matrix:new THREE.Matrix4().multiplyMatrices(inverse,m.matrixWorld)});sources.push(m);
    });
    const owned=[];
    for(const b of buckets.values()) {
      let count=0,indexCount=0;
      for(const {m} of b.items){count+=m.geometry.attributes.position.count;indexCount+=m.geometry.index?.count||m.geometry.attributes.position.count;}
      const positions=new Float32Array(count*3),normals=new Float32Array(count*3),uvs=new Float32Array(count*2),indices=new (count>65535?Uint32Array:Uint16Array)(indexCount);let offset=0,k=0;
      for(const {m,matrix} of b.items){const g=m.geometry.clone().applyMatrix4(matrix),n=g.attributes.position.count;positions.set(g.attributes.position.array,offset*3);if(g.attributes.normal)normals.set(g.attributes.normal.array,offset*3);if(g.attributes.uv)uvs.set(g.attributes.uv.array,offset*2);const idx=g.index?.array;for(let j=0;j<(idx?.length||n);j++)indices[k++]=offset+(idx?idx[j]:j);offset+=n;g.dispose();}
      const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(positions,3));g.setAttribute('normal',new THREE.BufferAttribute(normals,3));g.setAttribute('uv',new THREE.BufferAttribute(uvs,2));g.setIndex(new THREE.BufferAttribute(indices,1));g.computeBoundingSphere();
      const mesh=new THREE.Mesh(g,b.material);mesh.castShadow=b.cast;mesh.receiveShadow=b.receive;if(b.action)mesh.userData.action=b.action;root.add(mesh);owned.push(g);this.merged.add(g);
    }
    sources.forEach(m=>m.removeFromParent());return ()=>owned.forEach(g=>{g.dispose();this.merged.delete(g);});
  }
  dispose(){this.geometries.forEach(g=>g.dispose());this.merged.forEach(g=>g.dispose());this.materials.forEach(m=>m.dispose());this.textures.forEach(t=>t.dispose());this.merged.clear();}
}
