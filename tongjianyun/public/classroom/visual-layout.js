// All positions and appearances are illustration choices, not observations.
// Neither attendance nor health nor the student's name influences a pose.
export const VISUAL_PAGE_SIZE = 24;
export const ROOM_VIEW = Object.freeze({eye:[9.2,10.4,20.8], target:[0,1.0,0], zoom:1.12, vertical:13.6, horizontal:20.5});
export function seedOf(value) {
  let seed=2166136261;
  for (const char of String(value)) seed=Math.imul(seed^char.codePointAt(0),16777619);
  return seed>>>0;
}
export function appearanceFor(id) {
  const n=seedOf(id);
  return {seed:n, hair:n%6, skin:(n>>>4)%4, outfit:(n>>>7)%6, accessory:(n>>>11)%5, phase:(n%1000)/1000*Math.PI*2};
}
const seats=[];
function circle(x,z,r,count,start,station,pose) {
  for(let i=0;i<count;i++) {
    const a=start+i*Math.PI*2/count,px=x+Math.cos(a)*r,pz=z+Math.sin(a)*r;
    seats.push({x:px,z:pz,angle:Math.atan2(x-px,z-pz),pose,station,seated:true});
  }
}
// Central activity table, then art, dining, reading and welcome areas.
circle(-.85,-1.45,1.77,6,Math.PI/6,'activity','draw');
for(const [x,z,a] of [[-5.8,1.05,0],[-4.5,1.05,0],[-5.8,3.02,Math.PI],[-4.5,3.02,Math.PI]])
  seats.push({x,z,angle:a,pose:'draw',station:'art',seated:true});
circle(3.45,.45,1.46,6,Math.PI/6,'dining','sit');
for(const [x,z,a] of [[-6.75,-2.7,.55],[-5.3,-3.30,.15],[-6.4,-.75,.6]])
  seats.push({x,z,angle:a,pose:'read',station:'reading',seated:true,cushion:true});
for(const [x,z,a] of [[-1.9,3.4,.45],[-.20,4.25,-.3],[1.15,3.05,.3]])
  seats.push({x,z,angle:a,pose:'wave',station:'rug',seated:false});
seats.push({x:5.40,z:3.40,angle:.35,pose:'wave',station:'welcome',seated:false});
seats.push({x:6.9,z:4.18,angle:-.35,pose:'stand',station:'welcome',seated:false});
export const ILLUSTRATIVE_SLOTS=Object.freeze(seats.map(s=>Object.freeze(s)));
export function slotFor(index) {
  if(!Number.isInteger(index)||index<0||index>=VISUAL_PAGE_SIZE) throw new RangeError('Illustrative slot outside this page');
  return ILLUSTRATIVE_SLOTS[index];
}
export function blinkScale(seconds,phase) {
  const t=(seconds+phase)%5.8;
  return t<.16 ? Math.max(.065,Math.abs(t-.08)/.08) : 1;
}
