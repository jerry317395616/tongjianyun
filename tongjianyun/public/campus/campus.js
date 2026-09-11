import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

// Coordinates are illustrative scene units, not surveyed metres. No telemetry is simulated.
const host = document.getElementById('scene');
const scene = new THREE.Scene();
scene.background = new THREE.Color('#e8eef0');
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.95;
host.appendChild(renderer.domElement);
const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 250);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.09;
controls.minDistance = 7;
controls.maxDistance = 110;
controls.maxPolarAngle = Math.PI / 2 - 0.035;
controls.autoRotateSpeed = 0.35;
controls.target.set(0, 3, 0);
scene.add(new THREE.HemisphereLight(0xe7f5ff, 0x799671, 2.6));
const sun = new THREE.DirectionalLight(0xfff0d7, 3.2);
sun.position.set(-22, 45, 25);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -45, right: 45, top: 45, bottom: -45, far: 150 });
sun.shadow.normalBias = 0.045;
scene.add(sun);

const model = new THREE.Group();
scene.add(model);
const materials = new Map();
function material(color) {
  if (!materials.has(color)) materials.set(color, new THREE.MeshStandardMaterial({ color, roughness: 0.85 }));
  return materials.get(color);
}
function box(parent, x, y, z, w, h, d, color) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material(color));
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}
function cylinder(parent, x, y, z, radius, height, color, top = radius) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(top, radius, height, 12), material(color));
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}
function beam(parent, a, b, radius, color) {
  const start = new THREE.Vector3(...a), end = new THREE.Vector3(...b);
  const mesh = cylinder(parent, 0, 0, 0, radius, start.distanceTo(end), color);
  mesh.position.copy(start.clone().add(end).multiplyScalar(0.5));
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.sub(start).normalize());
  return mesh;
}
function line(parent, coords, color = '#e4efd6') {
  const geo = new THREE.BufferGeometry().setFromPoints(coords.map(p => new THREE.Vector3(...p)));
  const mesh = new THREE.Line(geo, new THREE.LineBasicMaterial({ color }));
  parent.add(mesh);
  return mesh;
}

box(model, 0, -0.7, 0, 44, 1.25, 49, '#d1d6cf');
box(model, 0, -0.08, 0, 42, 0.15, 47, '#719961');
box(model, -3, 0.025, 2, 28, 0.035, 36, '#6b9959');
// Calm terrain pedestal; no neighbouring buildings or fictitious site boundary.
const floor = box(scene, 0, -1.5, 0, 500, 0.1, 500, '#e3e9eb');
floor.castShadow = false;

const zones = [
  { id: 'front', title: '招牌楼与玻璃走廊', description: '浅绿与浅黄相间的立面、封闭玻璃走廊和竖向园名招牌。楼层外观按照片简化；前后教学楼名称与房间对应关系尚未绑定。', source: '依据正面照片；尺寸、内部房间与屋顶待核实', target: [-5, 6, -17], eye: [-19, 17, 7], label: [-8, 16, -17] },
  { id: 'side', title: '黄色侧楼', description: '沿院落一侧延伸的黄色建筑，保留窗户、空调、金属外廊和地面遮棚。楼内用途与房间分布尚未确认。', source: '依据视频侧楼画面；长度与连接关系为示意', target: [18, 5, -1], eye: [-10, 16, 18], label: [19, 13, 0] },
  { id: 'track', title: '彩色跑道', description: '红、黄、蓝、紫四条跑道沿院落一侧展开，旁边为绿色活动场地。没有采集人员位置，也没有用动画模拟幼儿活动。', source: '依据院内照片及视频；无实际距离标尺', target: [6, 0, 4], eye: [-9, 20, 25], label: [5, 1.5, 10] },
  { id: 'play', title: '滑梯与沿楼游乐区', description: '以彩色滑梯、木质攀爬、轮胎和沿楼遮棚表达照片中的户外游乐区域。设施造型为简化模型，并非设备资产清单。', source: '依据照片与视频；设备数量及细节未逐一核对', target: [13, 2, -8], eye: [-2, 11, 8], label: [13, 7, -10] },
  { id: 'passage', title: '入口楼与楼下通道', description: '新增照片确认：入口是楼体底层的穿行通道，不是独立门廊。通道上方可见三层连续窗带，灰白色外墙，两侧楼体转折连接。已补充窗框、立柱、遮棚和通道尽头铁门；不加入照片中的人物。', source: '外观依据入口新照片；总长度、背面与园区连接位置待核实', target: [-10.5, 6.5, 20], eye: [-9, 10, -10], label: [-10.5, 15, 21] }
];
const groups = new Map();
for (const zone of zones) {
  const group = new THREE.Group();
  group.userData.zone = zone.id;
  model.add(group);
  groups.set(zone.id, group);
}

function frontBuilding(parent, x, z, width, height, depth, levels) {
  box(parent, x, height / 2, z, width, height, depth, '#e1dfb3');
  box(parent, x, height + 0.15, z, width + 0.25, 0.3, depth + 0.2, '#a6bbb0');
  for (let level = 0; level < levels; level++) {
    const y = level * height / levels;
    box(parent, x, y + 0.5, z + depth / 2 + 0.04, width, 0.85, 0.12, level % 2 ? '#d6df9e' : '#a7cfc1');
    const count = Math.floor(width / 1.7), space = width / count;
    for (let j = 0; j < count; j++) {
      const xx = x - width / 2 + space * (j + 0.5);
      box(parent, xx, y + 2.0, z + depth / 2 + 0.09, space - 0.1, 1.8, 0.08, j % 3 ? '#6f8e91' : '#879e9d');
      box(parent, xx, y + 2.0, z + depth / 2 + 0.15, 0.055, 1.8, 0.045, '#e7e9dc');
      box(parent, xx, y + 2.0, z + depth / 2 + 0.15, space - 0.08, 0.06, 0.045, '#e7e9dc');
    }
    box(parent, x, y + 3.0, z + depth / 2 + 0.09, width, 0.12, 0.18, '#e7e9dc');
  }
}
const front = groups.get('front');
frontBuilding(front, -9, -18, 19, 14, 6, 4);
frontBuilding(front, 8, -18, 15, 10.5, 6, 3);
// Sign tower and low entrance stage.
box(front, 0.2, 7.25, -14.8, 2.8, 14.5, 1.0, '#946f44');
for (let j = 0; j < 16; j++) box(front, -1.14 + j * 0.175, 7.25, -14.24, 0.045, 14.5, 0.06, '#b59360');
for (let i = 0; i < 3; i++) box(front, 0.2, 0.12 + i * 0.17, -13.7 - i * 0.35, 4 - i * 0.45, 0.2, 2 - i * 0.35, '#c9c2b0');
box(front, -10, 0.2, -13.8, 15, 0.3, 2.2, '#4c783c');
box(front, -10, 0.08, -12.7, 15.6, 0.14, 0.5, '#7b9b62');
function signText() {
  const canvas = document.createElement('canvas'); canvas.width = 160; canvas.height = 1200;
  const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, 160, 1200);
  ctx.textAlign = 'center'; ctx.font = 'bold 83px "Microsoft YaHei",sans-serif';
  const letters = [...'西安市临潼区幼儿园'];
  letters.forEach((ch, i) => {ctx.lineWidth = 5; ctx.strokeStyle = '#fff6d4'; ctx.strokeText(ch, 80, 92 + i * 108); ctx.fillStyle = ['#27768c', '#c35759', '#378768'][Math.floor(i / 3) % 3]; ctx.fillText(ch, 80, 92 + i * 108);});
  const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 11.4), new THREE.MeshBasicMaterial({ map: texture, transparent: true }));
  mesh.position.set(0.2, 8.05, -14.15); front.add(mesh);
}
signText();

const side = groups.get('side');
box(side, 19, 5.3, 0, 5, 10.6, 35, '#e6ca85');
box(side, 19, 10.85, 0, 5.5, 0.35, 35.5, '#68777a');
for (let floorIndex = 0; floorIndex < 3; floorIndex++) {
  for (let i = 0; i < 9; i++) {
    const z = -14.5 + i * 3.7;
    box(side, 16.43, 2 + floorIndex * 3.25, z, 0.12, 1.8, 1.55, '#5d7478');
    box(side, 16.34, 2 + floorIndex * 3.25, z, 0.06, 1.8, 0.06, '#c6cfbf');
    if (floorIndex === 1 && i % 2 === 0) {
      box(side, 16.17, 3.9, z + 1.3, 0.6, 0.65, 0.8, '#d6d7bf');
      const fan = cylinder(side, 15.85, 3.9, z + 1.3, 0.22, 0.04, '#819090'); fan.rotation.z = Math.PI / 2;
    }
  }
}
box(side, 15.6, 3.25, 0, 1.8, 0.16, 34, '#8b8c79');
for (let z = -16.5; z < 17; z += 1.1) box(side, 14.75, 3.85, z, 0.065, 1.2, 0.065, '#536b5e');
box(side, 14.75, 4.45, 0, 0.075, 0.08, 34, '#536b5e');
box(side, 14.8, 2.95, 2, 3.3, 0.15, 29, '#9a8362');
for (let z = -12; z < 17; z += 4) cylinder(side, 13.25, 1.45, z, 0.1, 2.9, '#8e7858');

const track = groups.get('track');
['#d55258', '#eac54a', '#389bd0', '#9273b7'].forEach((color, i) => {
  box(track, 3.7 + i * 1.55, 0.055, 4, 1.51, 0.04, 34, color);
  box(track, 2.925 + i * 1.55, 0.085, 4, 0.055, 0.025, 34, '#f9f5df');
});
box(track, 9.125, 0.085, 4, 0.055, 0.025, 34, '#f9f5df');
line(track, [[-15, .09, 3], [-3, .09, 3], [-3, .09, 17], [-15, .09, 17], [-15, .09, 3]], '#e9eacf');
line(track, [[-15, .09, 10], [-3, .09, 10]], '#e9eacf');
const circle = [];
for (let i = 0; i <= 64; i++) circle.push([-9 + 2 * Math.cos(i / 64 * Math.PI * 2), .09, 10 + 2 * Math.sin(i / 64 * Math.PI * 2)]);
line(track, circle);

const play = groups.get('play');
function tower(x, z, height, color) {
  for (const dx of [-.7, .7]) for (const dz of [-.7, .7]) cylinder(play, x + dx, height / 2, z + dz, .08, height, '#618894');
  box(play, x, height, z, 1.7, .2, 1.7, '#c7b985');
  const roof = new THREE.Mesh(new THREE.ConeGeometry(1.45, 1.5, 4), material(color));
  roof.position.set(x, height + 2, z); roof.rotation.y = Math.PI / 4; roof.castShadow = true; play.add(roof);
  for (const dx of [-.75, .75]) {
    beam(play, [x + dx, height, z - .75], [x + dx, height + 1.3, z - .75], .07, '#7a9493');
    beam(play, [x + dx, height + 1, z - .75], [x + dx, height + 1, z + .75], .055, '#7a9493');
  }
}
function slide(x, z, h, color, shift) {
  const path = new THREE.CatmullRomCurve3([new THREE.Vector3(x, h, z), new THREE.Vector3(x + shift * .2, h * .8, z + 1.4), new THREE.Vector3(x + shift, .5, z + 3.4), new THREE.Vector3(x + shift, .3, z + 4.1)]);
  const points = path.getPoints(35), vertices = [], indices = [];
  points.forEach(p => vertices.push(p.x - .48, p.y, p.z, p.x + .48, p.y, p.z));
  for (let i = 0; i < points.length - 1; i++) {const a = i * 2; indices.push(a, a + 2, a + 1, a + 1, a + 2, a + 3);}
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3)); geo.setIndex(indices); geo.computeVertexNormals();
  const mat = new THREE.MeshStandardMaterial({ color, side: THREE.DoubleSide, roughness: .55 });
  const mesh = new THREE.Mesh(geo, mat); mesh.castShadow = true; play.add(mesh);
  for (const offset of [-.48, .48]) {
    const railPath = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(p.x + offset, p.y + .14, p.z)));
    play.add(new THREE.Mesh(new THREE.TubeGeometry(railPath, 35, .09, 6, false), mat));
  }
}
tower(11.4, -11, 2.6, '#cc4d4a'); tower(13.5, -8.5, 2, '#d4a84a');
slide(11.4, -10.2, 2.6, '#d7484b', -1.1); slide(13.5, -7.7, 2, '#e7b447', -.8);
box(play, 12.5, 2.2, -9.6, 2.5, .2, 1, '#709caf');
// Wooden climbing frame and ladder under the side canopy.
for (const z of [3, 9]) {
  for (const x of [13.8, 15.8]) beam(play, [x, 0, z - 1], [x, 2, z], .1, '#a98851');
  beam(play, [13.8, 2, z], [15.8, 2, z], .12, '#a98851');
  for (let i = 0; i < 5; i++) beam(play, [13.8, .3 + i * .3, z - .85 + i * .15], [15.8, .3 + i * .3, z - .85 + i * .15], .065, '#b99b66');
}
for (let i = 0; i < 7; i++) {
  const tire = new THREE.Mesh(new THREE.TorusGeometry(.32, .1, 7, 16), material(['#d4ab4e', '#779e91', '#bd6357'][i % 3]));
  tire.rotation.y = Math.PI / 2; tire.position.set(15.9, .4, 11 + i * .65); tire.castShadow = true; play.add(tire);
}
for (let i = 0; i < 8; i++) box(play, 11 + (i % 2) * .8, .07, 4 + Math.floor(i / 2) * .85, .72, .04, .76, ['#e6bb46', '#df745e', '#83c1d0'][i % 3]);

// New entrance photo: three window bands ABOVE the ground-floor passage.
// Keep the passage open; this is not a freestanding gate or a measured footprint.
const passage = groups.get('passage');
const plaster = '#d9ddd8', frame = '#e9efeb', glass = '#758e91';
// Ground-floor side rooms leave a 4.8-unit wide opening through the centre.
box(passage, -16, 2, 21, 6.2, 4, 4, '#b2c5c0');
box(passage, -5, 2, 21, 6.2, 4, 4, '#b2c5c0');
box(passage, -10.5, 8.65, 21, 17.2, 9.3, 4, plaster);
box(passage, -10.5, 13.4, 21, 17.5, .2, 4.2, '#b7c1bd');
// Court-facing facade is towards negative Z, matching the view into the gate.
for (let level = 0; level < 3; level++) {
  const y = 5.6 + level * 3.1;
  for (let bay = 0; bay < 4; bay++) {
    const x = -16.8 + bay * 4.2;
    box(passage, x, y, 18.95, 3.7, 1.95, .12, glass);
    for (let mullion = 0; mullion <= 4; mullion++) box(passage, x - 1.85 + mullion * .925, y, 18.86, .055, 2.04, .05, frame);
    for (const dy of [-.99, .43, .99]) box(passage, x, y + dy, 18.84, 3.78, .06, .055, frame);
  }
}
for (const x of [-19, -14.7, -10.5, -6.3, -2]) {
  box(passage, x, 8.6, 18.85, .24, 9.25, .24, '#c7d0cb');
}
// Short return wings show only the visible turn, not inferred full building lengths.
for (const x of [-18.1, -2.9]) {
  box(passage, x, 6.65, 17.2, 2, 13.3, 3.6, plaster);
  box(passage, x, 13.4, 17.2, 2.15, .2, 3.7, '#b7c1bd');
  const face = x < -10 ? x + 1.04 : x - 1.04;
  for (let level = 0; level < 3; level++) {
    const y = 5.6 + level * 3.1;
    box(passage, face, y, 17.2, .08, 1.8, 2.6, glass);
    box(passage, face, y, 17.2, .13, 1.9, .06, frame);
    for (const dy of [-.95, .95]) box(passage, face, y + dy, 17.2, .13, .065, 2.65, frame);
  }
}
// Low brown canopy, orange supports and iron gate behind the open passage.
box(passage, -10.5, 3.9, 18.25, 15.2, .18, 1.6, '#7d715b');
for (const x of [-13, -8]) cylinder(passage, x, 1.9, 18, .14, 3.8, '#b88d48');
for (let x = -12.75; x <= -8.25; x += .3) box(passage, x, 1.5, 22.9, .05, 3, .05, '#43564f');
for (const y of [.4, 2.5, 3]) box(passage, -10.5, y, 22.9, 4.65, .06, .06, '#43564f');
for (const x of [-16.2, -4.8]) {
  box(passage, x, 4.5, 18.65, 1.1, .75, .55, '#d5d6ce');
  box(passage, x, 4.5, 18.34, .7, .48, .04, '#929f99');
  box(passage, x, 1.8, 18.93, 2.2, 1.3, .08, '#6d8585');
}
const dashPoints = [[-19.4, .1, 15], [-1.6, .1, 15], [-1.6, .1, 23.4], [-19.4, .1, 23.4], [-19.4, .1, 15]];
const dash = new THREE.Line(new THREE.BufferGeometry().setFromPoints(dashPoints.map(p => new THREE.Vector3(...p))), new THREE.LineDashedMaterial({ color: '#be8848', dashSize: .4, gapSize: .25 }));
dash.computeLineDistances(); passage.add(dash);

for (const [x, z, size] of [[-20, 13, 1.6], [-20, 18, 1.5], [-18, -4, 1.5]]) {
  cylinder(model, x, 1.7, z, .18, 3.4, '#877655');
  const tree = new THREE.Mesh(new THREE.IcosahedronGeometry(size, 1), material('#497453'));
  tree.position.set(x, 4.1, z); tree.scale.y = 1.25; tree.castShadow = true; model.add(tree);
}

const labels = new THREE.Group(); scene.add(labels);
function makeLabel(zone) {
  const c = document.createElement('canvas'); c.width = 768; c.height = 104;
  const ctx = c.getContext('2d'); ctx.fillStyle = zone.id === 'passage' ? '#996c34' : '#205547';
  ctx.beginPath(); ctx.roundRect(0, 0, 768, 104, 28); ctx.fill();
  ctx.font = '36px "Microsoft YaHei",sans-serif'; ctx.textAlign = 'center'; ctx.fillStyle = '#fff'; ctx.fillText(zone.title, 384, 66);
  const texture = new THREE.CanvasTexture(c); texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: true }));
  sprite.position.set(...zone.label); sprite.scale.set(9, 1.22, 1); sprite.userData.zone = zone.id; labels.add(sprite);
}
zones.forEach(makeLabel);
let selection = null, selectedId = null;
const raycaster = new THREE.Raycaster();
function select(id, focus = true) {
  const zone = zones.find(z => z.id === id); if (!zone) return;
  selectedId = id;
  document.getElementById('zone-title').textContent = zone.title;
  document.getElementById('zone-description').textContent = zone.description;
  document.getElementById('zone-source').textContent = zone.source;
  document.querySelectorAll('[data-zone]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.zone === id)));
  if (selection) {scene.remove(selection); selection.geometry.dispose(); selection.material.dispose();}
  selection = new THREE.BoxHelper(groups.get(id), '#d0a349'); scene.add(selection);
  if (focus) {setView(null, zone.eye, zone.target);}
}
for (const [index, zone] of zones.entries()) {
  const button = document.createElement('button'); button.dataset.zone = zone.id; button.setAttribute('aria-pressed', 'false');
  const number = document.createElement('small'); number.textContent = `0${index + 1}`; button.append(number, zone.title);
  button.addEventListener('click', () => select(zone.id)); document.getElementById('zones').append(button);
}
const views = {overview: {eye: [-37, 36, 48], target: [0, 3, 0]}, courtyard: {eye: [-7, 4.5, 18], target: [1, 5, -16]}, top: {eye: [0, 68, 0.1], target: [0, 0, 0]}};
let transition = null;
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
function setView(name, eye, target) {
  const view = name ? views[name] : {eye, target};
  if (!view) return;
  setRotate(false);
  transition = {start: performance.now(), eye: camera.position.clone(), target: controls.target.clone(), endEye: new THREE.Vector3(...view.eye), endTarget: new THREE.Vector3(...view.target)};
  if (reducedMotion) {camera.position.copy(transition.endEye); controls.target.copy(transition.endTarget); transition = null; controls.update();}
  document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === name)));
}
function setRotate(value) {controls.autoRotate = value; document.getElementById('rotate').setAttribute('aria-pressed', String(value));}
camera.position.set(...views.overview.eye); controls.update();
document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
document.getElementById('reset').addEventListener('click', () => {
  setView('overview'); selectedId = null;
  if (selection) {scene.remove(selection); selection.geometry.dispose(); selection.material.dispose(); selection = null;}
  document.querySelectorAll('[data-zone]').forEach(b => b.setAttribute('aria-pressed', 'false'));
  document.getElementById('zone-title').textContent = '园区总览';
  document.getElementById('zone-description').textContent = '以实拍照片和视频为参考，复现招牌楼、玻璃走廊、黄色侧楼、彩色跑道与游乐区的主要外观。';
  document.getElementById('zone-source').textContent = '尺寸、楼栋连接及室内布局尚未实测';
});
document.getElementById('labels').addEventListener('click', () => {labels.visible = !labels.visible; document.getElementById('labels').setAttribute('aria-pressed', String(labels.visible));});
document.getElementById('rotate').addEventListener('click', () => {transition = null; setRotate(!controls.autoRotate);});
const fullscreen = document.getElementById('fullscreen');
fullscreen.disabled = !document.fullscreenEnabled;
fullscreen.addEventListener('click', async () => {
  try {if (document.fullscreenElement) await document.exitFullscreen(); else await document.querySelector('.viewport').requestFullscreen();}
  catch {fullscreen.textContent = '全屏不可用';}
});
document.addEventListener('fullscreenchange', () => {fullscreen.textContent = document.fullscreenElement ? '退出全屏' : '全屏';});
controls.addEventListener('start', () => {transition = null;});
let pointerStart = null;
renderer.domElement.addEventListener('pointerdown', event => {pointerStart = {x: event.clientX, y: event.clientY, time: performance.now()};});
renderer.domElement.addEventListener('pointerup', event => {
  if (!pointerStart || event.button !== 0 || performance.now() - pointerStart.time > 600 || Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) > 6) {pointerStart = null; return;}
  pointerStart = null;
  const rect = host.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
  const objects = labels.visible ? [model, labels] : [model];
  for (const hit of raycaster.intersectObjects(objects, true)) {
    let object = hit.object;
    while (object && !object.userData.zone) object = object.parent;
    if (object?.userData.zone) {select(object.userData.zone, false); break;}
    // An opaque object in front must not select a hidden zone behind it.
    if (hit.object.isMesh) break;
  }
});
renderer.domElement.addEventListener('webglcontextlost', event => {event.preventDefault(); const loading = document.getElementById('loading'); loading.hidden = false; loading.textContent = '三维显示已中断，请刷新页面恢复。'; renderer.setAnimationLoop(null);});
const resize = new ResizeObserver(() => {const {width, height} = host.getBoundingClientRect(); if (width && height) {renderer.setSize(width, height); camera.aspect = width / height; camera.fov = width < 600 ? 72 : 42; camera.updateProjectionMatrix();}});
resize.observe(host);
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const delta = Math.min(clock.getDelta(), .05);
  if (document.hidden) return;
  if (transition) {
    const t = Math.min((performance.now() - transition.start) / 850, 1), ease = 1 - Math.pow(1 - t, 3);
    camera.position.lerpVectors(transition.eye, transition.endEye, ease); controls.target.lerpVectors(transition.target, transition.endTarget, ease);
    if (t === 1) transition = null;
  }
  controls.update(delta); renderer.render(scene, camera);
});
document.getElementById('loading').hidden = true;
// Read-only diagnostics for regression tests; contains no identity or business data.
host.dataset.ready = 'true'; host.dataset.engine = `Three.js r${THREE.REVISION}`;
window.addEventListener('pagehide', () => {
  renderer.setAnimationLoop(null); resize.disconnect(); controls.dispose();
  const geometries = new Set(), mats = new Set(), textures = new Set();
  scene.traverse(object => {if (object.geometry) geometries.add(object.geometry); for (const mat of [object.material].flat().filter(Boolean)) {mats.add(mat); if (mat.map) textures.add(mat.map);}});
  geometries.forEach(g => g.dispose()); mats.forEach(m => m.dispose()); textures.forEach(t => t.dispose()); renderer.dispose();
});
window.addEventListener('pageshow', event => {if (event.persisted) location.reload();});
