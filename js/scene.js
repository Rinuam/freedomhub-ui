/* ============================================================
   THIN FILM ENGINEER — scroll-driven WebGL wafer journey
   Stages: 0 intro · 1 substrate · 2 deposition · 3 etch ·
           4 metrology · 5 finale
   ============================================================ */
import * as THREE from '../vendor/three.module.min.js';

const canvas = document.getElementById('webgl');
const stageScroll = document.getElementById('stageScroll');
if (!canvas || !stageScroll) throw new Error('stage missing');

const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
} catch (e) {
  document.body.classList.add('no-webgl');
  canvas.style.display = 'none';
  throw e;
}
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.12;
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x05070d, 0.045);

const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 60);
camera.position.set(0, 2.2, 7.2);

/* ---------- environment (procedural studio for metal reflections) ---------- */
function buildEnvironment() {
  const envScene = new THREE.Scene();
  const geo = new THREE.PlaneGeometry(1, 1);
  const panel = (color, intensity, w, h, pos, lookAt) => {
    const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }));
    m.material.color.multiplyScalar(intensity);
    m.scale.set(w, h, 1);
    m.position.copy(pos);
    m.lookAt(lookAt);
    envScene.add(m);
  };
  envScene.background = new THREE.Color(0x0b0f18);
  const c = new THREE.Vector3(0, 0, 0);
  panel(0xffffff, 6.0, 6, 2, new THREE.Vector3(0, 6, 0), c);          // big soft top light
  panel(0x9fd8ff, 2.4, 3, 4, new THREE.Vector3(-6, 1.5, 2), c);       // cool left
  panel(0xb9a7ff, 1.8, 3, 4, new THREE.Vector3(6, 1.2, -2), c);       // violet right
  panel(0xffc890, 0.9, 4, 1, new THREE.Vector3(0, -3, 5), c);         // warm floor bounce
  const pmrem = new THREE.PMREMGenerator(renderer);
  const envTex = pmrem.fromScene(envScene, 0.04).texture;
  pmrem.dispose();
  return envTex;
}
scene.environment = buildEnvironment();

/* ---------- lights ---------- */
const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
keyLight.position.set(3, 6, 4);
scene.add(keyLight);
const rimLight = new THREE.PointLight(0x5bd3e8, 12, 20);
rimLight.position.set(-4, 1.4, -4);
scene.add(rimLight);
const fillLight = new THREE.PointLight(0x8a7be8, 6, 18);
fillLight.position.set(4.5, 0.8, 3.5);
scene.add(fillLight);
scene.add(new THREE.AmbientLight(0x22283a, 1.6));
const plasmaLight = new THREE.PointLight(0xa07dff, 0, 12, 1.6);
plasmaLight.position.set(0, 1.6, 0);
scene.add(plasmaLight);
const laserLight = new THREE.PointLight(0x5bd3e8, 0, 6, 2);
scene.add(laserLight);

/* ---------- helper: canvas textures ---------- */
function makeCanvas(size, draw) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  draw(cv.getContext('2d'), size);
  const tex = new THREE.CanvasTexture(cv);
  tex.anisotropy = 8;
  return tex;
}

const dieTexture = makeCanvas(1024, (ctx, s) => {
  ctx.fillStyle = '#b9c2d4';
  ctx.fillRect(0, 0, s, s);
  const g = ctx.createRadialGradient(s / 2, s / 2, s * 0.05, s / 2, s / 2, s * 0.52);
  g.addColorStop(0, 'rgba(160,190,230,0.55)');
  g.addColorStop(0.45, 'rgba(150,140,220,0.32)');
  g.addColorStop(0.8, 'rgba(120,180,210,0.28)');
  g.addColorStop(1, 'rgba(90,100,140,0.5)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  // die grid
  ctx.strokeStyle = 'rgba(40,50,80,0.65)';
  ctx.lineWidth = 3;
  const step = s / 14;
  for (let i = 0; i <= 14; i++) {
    ctx.beginPath(); ctx.moveTo(i * step, 0); ctx.lineTo(i * step, s); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, i * step); ctx.lineTo(s, i * step); ctx.stroke();
  }
  // subtle die detail
  ctx.fillStyle = 'rgba(60,72,110,0.35)';
  for (let x = 0; x < 14; x++) for (let y = 0; y < 14; y++) {
    ctx.fillRect(x * step + step * 0.16, y * step + step * 0.16, step * 0.3, step * 0.2);
    ctx.fillRect(x * step + step * 0.55, y * step + step * 0.45, step * 0.28, step * 0.34);
  }
});

const dieEmissive = makeCanvas(1024, (ctx, s) => {
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, s, s);
  const step = s / 14;
  for (let x = 0; x < 14; x++) for (let y = 0; y < 14; y++) {
    const r = Math.hypot(x - 6.5, y - 6.5);
    if (r > 7) continue;
    const on = (x * 31 + y * 17) % 7;
    ctx.fillStyle = on < 2 ? '#2fb7d3' : on < 3 ? '#7c6ce0' : '#122031';
    ctx.fillRect(x * step + 4, y * step + 4, step - 8, step - 8);
  }
});

const glowTexture = makeCanvas(256, (ctx, s) => {
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.25, 'rgba(255,255,255,0.55)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
});

/* ---------- ground ---------- */
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(30, 64),
  new THREE.MeshStandardMaterial({ color: 0x0a0e18, metalness: 0.85, roughness: 0.38, envMapIntensity: 0.6 })
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -0.65;
scene.add(ground);

/* ---------- wafer ---------- */
const waferGroup = new THREE.Group();
scene.add(waferGroup);

const WAFER_R = 2;
const waferMat = new THREE.MeshPhysicalMaterial({
  color: 0xd7dde9,
  metalness: 0.92,
  roughness: 0.16,
  clearcoat: 1,
  clearcoatRoughness: 0.22,
  iridescence: 0.4,
  iridescenceIOR: 1.6,
  map: dieTexture,
  emissive: 0xffffff,
  emissiveMap: dieEmissive,
  emissiveIntensity: 0,
  envMapIntensity: 1.15
});
const wafer = new THREE.Mesh(new THREE.CylinderGeometry(WAFER_R, WAFER_R, 0.07, 96), waferMat);
waferGroup.add(wafer);

// polished edge ring
const edge = new THREE.Mesh(
  new THREE.TorusGeometry(WAFER_R, 0.028, 12, 96),
  new THREE.MeshStandardMaterial({ color: 0xaeb6c6, metalness: 1, roughness: 0.25 })
);
edge.rotation.x = Math.PI / 2;
waferGroup.add(edge);

// growing film layer
const filmMat = new THREE.MeshStandardMaterial({
  color: 0xd9944f, metalness: 1, roughness: 0.3, envMapIntensity: 1.2,
  transparent: true, opacity: 0
});
const film = new THREE.Mesh(new THREE.CylinderGeometry(WAFER_R * 0.985, WAFER_R * 0.985, 1, 96), filmMat);
film.scale.y = 0.0001;
film.position.y = 0.035;
waferGroup.add(film);

/* ---------- sputter target (deposition source) ---------- */
const targetGroup = new THREE.Group();
const targetDisc = new THREE.Mesh(
  new THREE.CylinderGeometry(1.15, 1.15, 0.12, 64),
  new THREE.MeshStandardMaterial({ color: 0xc98a4a, metalness: 1, roughness: 0.35, emissive: 0xff9a4d, emissiveIntensity: 0.15 })
);
targetGroup.add(targetDisc);
const targetHolder = new THREE.Mesh(
  new THREE.CylinderGeometry(0.16, 0.16, 0.6, 24),
  new THREE.MeshStandardMaterial({ color: 0x39404f, metalness: 0.8, roughness: 0.4 })
);
targetHolder.position.y = 0.35;
targetGroup.add(targetHolder);
const targetGlow = new THREE.Sprite(new THREE.SpriteMaterial({
  map: glowTexture, color: 0xffa25e, transparent: true, opacity: 0,
  blending: THREE.AdditiveBlending, depthWrite: false
}));
targetGlow.scale.set(3.2, 3.2, 1);
targetGlow.position.y = -0.15;
targetGroup.add(targetGlow);
targetGroup.position.set(0, 2.7, 0);
targetGroup.visible = false;
scene.add(targetGroup);

/* ---------- deposition atoms (instanced) ---------- */
const ATOMS = 650;
const atomGeo = new THREE.SphereGeometry(0.02, 6, 6);
const atomMat = new THREE.MeshBasicMaterial({
  color: 0xffc07a, transparent: true, opacity: 0,
  blending: THREE.AdditiveBlending, depthWrite: false
});
const atoms = new THREE.InstancedMesh(atomGeo, atomMat, ATOMS);
atoms.visible = false;
scene.add(atoms);
const atomData = [];
for (let i = 0; i < ATOMS; i++) {
  const r = Math.sqrt(Math.random()) * 1.75;
  const a = Math.random() * Math.PI * 2;
  atomData.push({
    x: Math.cos(a) * r, z: Math.sin(a) * r,
    y: 0.1 + Math.random() * 2.5,
    v: 0.9 + Math.random() * 1.6,
    drift: (Math.random() - 0.5) * 0.12
  });
}
const dummy = new THREE.Object3D();

/* ---------- plasma coil + glow (etch) ---------- */
const coilGroup = new THREE.Group();
const coilMat = new THREE.MeshStandardMaterial({ color: 0xd9944f, metalness: 1, roughness: 0.25, emissive: 0xa07dff, emissiveIntensity: 0 });
for (let i = 0; i < 3; i++) {
  const t = new THREE.Mesh(new THREE.TorusGeometry(1.5 - i * 0.28, 0.045, 12, 72), coilMat);
  t.rotation.x = Math.PI / 2;
  t.position.y = i * 0.22;
  coilGroup.add(t);
}
const plasmaGlow = new THREE.Sprite(new THREE.SpriteMaterial({
  map: glowTexture, color: 0x9a6bff, transparent: true, opacity: 0,
  blending: THREE.AdditiveBlending, depthWrite: false
}));
plasmaGlow.scale.set(5.4, 3.4, 1);
plasmaGlow.position.y = -0.9;
coilGroup.add(plasmaGlow);
const plasmaGlow2 = plasmaGlow.clone();
plasmaGlow2.material = plasmaGlow.material.clone();
plasmaGlow2.material.color = new THREE.Color(0x4fd0e8);
plasmaGlow2.scale.set(3.4, 2.2, 1);
plasmaGlow2.position.y = -1.4;
coilGroup.add(plasmaGlow2);
coilGroup.position.set(0, 2.55, 0);
coilGroup.visible = false;
scene.add(coilGroup);

/* ---------- ion streaks (instanced) ---------- */
const IONS = 220;
const ionGeo = new THREE.CylinderGeometry(0.006, 0.006, 0.42, 4);
const ionMat = new THREE.MeshBasicMaterial({
  color: 0xb99cff, transparent: true, opacity: 0,
  blending: THREE.AdditiveBlending, depthWrite: false
});
const ions = new THREE.InstancedMesh(ionGeo, ionMat, IONS);
ions.visible = false;
scene.add(ions);
const ionData = [];
for (let i = 0; i < IONS; i++) {
  const r = Math.sqrt(Math.random()) * 1.7;
  const a = Math.random() * Math.PI * 2;
  ionData.push({ x: Math.cos(a) * r, z: Math.sin(a) * r, y: Math.random() * 2.2, v: 4.5 + Math.random() * 3 });
}

/* ---------- cross-section stack (etch close-up hero) ---------- */
const xsec = new THREE.Group();
{
  const sub = new THREE.Mesh(
    new THREE.BoxGeometry(1.7, 0.4, 0.95),
    new THREE.MeshStandardMaterial({ color: 0x707c96, metalness: 0.75, roughness: 0.35 })
  );
  xsec.add(sub);
  const filmSlab = new THREE.Mesh(
    new THREE.BoxGeometry(1.7, 0.26, 0.95),
    new THREE.MeshStandardMaterial({ color: 0xd9944f, metalness: 1, roughness: 0.3 })
  );
  filmSlab.position.y = 0.33;
  xsec.add(filmSlab);
  // mask lines
  const maskMat = new THREE.MeshStandardMaterial({ color: 0x3d4d70, metalness: 0.5, roughness: 0.5 });
  const maskW = 0.2, gapW = 0.14, n = 5;
  const total = n * maskW + (n - 1) * gapW;
  const x0 = -total / 2 + maskW / 2;
  for (let i = 0; i < n; i++) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(maskW, 0.07, 0.95), maskMat);
    m.position.set(x0 + i * (maskW + gapW), 0.33 + 0.13 + 0.035, 0);
    xsec.add(m);
  }
  // trench cuts (grow downward through film)
  xsec.userData.trenches = [];
  const trenchMat = new THREE.MeshStandardMaterial({
    color: 0x0a0d16, metalness: 0.2, roughness: 0.9,
    emissive: 0x8a5cff, emissiveIntensity: 0
  });
  for (let i = 0; i < n - 1; i++) {
    const t = new THREE.Mesh(new THREE.BoxGeometry(gapW, 1, 0.96), trenchMat);
    const x = x0 + maskW / 2 + gapW / 2 + i * (maskW + gapW);
    t.position.set(x, 0.46, 0);   // top of film = 0.33+0.13 = 0.46
    t.scale.y = 0.0001;
    t.userData.topY = 0.46;
    xsec.add(t);
    xsec.userData.trenches.push(t);
  }
}
xsec.position.set(2.9, 1.15, 0.1);
xsec.rotation.set(0.12, -0.5, 0.02);
xsec.scale.setScalar(0.0001);
xsec.visible = false;
scene.add(xsec);

/* ---------- metrology laser ---------- */
const laserGroup = new THREE.Group();
const beamMat = new THREE.MeshBasicMaterial({
  color: 0x5bd3e8, transparent: true, opacity: 0,
  blending: THREE.AdditiveBlending, depthWrite: false
});
const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.026, 2.4, 8, 1, true), beamMat);
beam.position.y = 1.3;
laserGroup.add(beam);
const beamCore = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.009, 2.4, 6, 1, true), beamMat.clone());
beamCore.material.color = new THREE.Color(0xffffff);
beamCore.position.y = 1.3;
laserGroup.add(beamCore);
const spot = new THREE.Sprite(new THREE.SpriteMaterial({
  map: glowTexture, color: 0x8ae6f5, transparent: true, opacity: 0,
  blending: THREE.AdditiveBlending, depthWrite: false
}));
spot.scale.set(0.9, 0.9, 1);
spot.position.y = 0.12;
laserGroup.add(spot);
const scanRing = new THREE.Mesh(
  new THREE.RingGeometry(0.2, 0.24, 48),
  new THREE.MeshBasicMaterial({ color: 0x5bd3e8, transparent: true, opacity: 0, side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false })
);
scanRing.rotation.x = -Math.PI / 2;
scanRing.position.y = 0.09;
laserGroup.add(scanRing);
const scanHead = new THREE.Mesh(
  new THREE.BoxGeometry(0.34, 0.16, 0.5),
  new THREE.MeshStandardMaterial({ color: 0x2c3446, metalness: 0.8, roughness: 0.3 })
);
scanHead.position.y = 2.55;
laserGroup.add(scanHead);
laserGroup.visible = false;
scene.add(laserGroup);

/* ---------- ambient chamber dust ---------- */
const dustGeo = new THREE.BufferGeometry();
{
  const N = 420, pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 16;
    pos[i * 3 + 1] = Math.random() * 7 - 0.5;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 16;
  }
  dustGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
}
const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
  map: glowTexture, color: 0x7fa8c8, size: 0.05, transparent: true, opacity: 0.35,
  blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true
}));
scene.add(dust);

/* ============================================================
   SCROLL → STAGE MAPPING
   ============================================================ */
const STAGES = [
  { start: 0.00, end: 0.13 },  // 0 intro
  { start: 0.13, end: 0.30 },  // 1 substrate
  { start: 0.30, end: 0.48 },  // 2 deposition
  { start: 0.48, end: 0.66 },  // 3 etch
  { start: 0.66, end: 0.84 },  // 4 metrology
  { start: 0.84, end: 1.00 }   // 5 finale
];

const CAM_KEYS = [
  { p: 0.00, pos: [0.0, 2.9, 7.8], look: [0, 1.05, 0], fov: 38 },
  { p: 0.13, pos: [2.9, 0.75, 3.6], look: [0, 0.10, 0], fov: 36 },
  { p: 0.30, pos: [1.2, 2.7, 4.6], look: [0, 0.85, 0], fov: 38 },
  { p: 0.48, pos: [3.75, 1.75, 2.9], look: [2.9, 1.05, 0.1], fov: 36 },
  { p: 0.66, pos: [-1.7, 3.1, 3.8], look: [0, 0.35, 0], fov: 38 },
  { p: 0.84, pos: [0.0, 3.4, 8.4], look: [0, 1.35, 0], fov: 40 },
  { p: 1.00, pos: [0.0, 3.8, 9.2], look: [0, 1.45, 0], fov: 40 }
];

const smooth = t => t * t * (3 - 2 * t);
const clamp01 = v => Math.min(1, Math.max(0, v));
const lerp = (a, b, t) => a + (b - a) * t;

// bell weight for a stage: ramps in/out at its edges
function stageWeight(p, s, ramp = 0.045) {
  const { start, end } = STAGES[s];
  const inW = smooth(clamp01((p - start) / ramp));
  const outW = 1 - smooth(clamp01((p - (end - ramp)) / ramp));
  return Math.min(inW, outW);
}
// 0→1 progress within a stage
function stageT(p, s) {
  const { start, end } = STAGES[s];
  return clamp01((p - start) / (end - start));
}

const camPos = new THREE.Vector3();
const camLook = new THREE.Vector3();
function updateCamera(p, mouseX, mouseY, t) {
  let i = 0;
  while (i < CAM_KEYS.length - 2 && p > CAM_KEYS[i + 1].p) i++;
  const a = CAM_KEYS[i], b = CAM_KEYS[i + 1];
  const tt = smooth(clamp01((p - a.p) / (b.p - a.p)));
  camPos.fromArray(a.pos).lerp(new THREE.Vector3().fromArray(b.pos), tt);
  camLook.fromArray(a.look).lerp(new THREE.Vector3().fromArray(b.look), tt);
  const fov = lerp(a.fov, b.fov, tt);

  // idle orbit + drift on intro/finale
  const w0 = stageWeight(p, 0, 0.06), w5 = stageWeight(p, 5, 0.08);
  const orbit = (w0 + w5) * 0.22;
  camPos.x += Math.sin(t * 0.18) * orbit * 2.2;
  camPos.z += (Math.cos(t * 0.18) - 1) * orbit * 1.1;
  camPos.y += Math.sin(t * 0.24) * orbit * 0.35;

  // mouse parallax
  camPos.x += mouseX * 0.35;
  camPos.y += -mouseY * 0.22;

  camera.position.lerp(camPos, 0.08);
  if (Math.abs(camera.fov - fov) > 0.05) { camera.fov = lerp(camera.fov, fov, 0.08); camera.updateProjectionMatrix(); }
  camera.lookAt(camLook);
}

/* ============================================================
   RENDER LOOP
   ============================================================ */
let progress = 0;
let mouseX = 0, mouseY = 0;
let visible = true;
let staticMode = false;
const clock = new THREE.Clock();

function computeProgress() {
  const rect = stageScroll.getBoundingClientRect();
  const total = rect.height - window.innerHeight;
  return total > 0 ? clamp01(-rect.top / total) : 0;
}

window.addEventListener('pointermove', (e) => {
  mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
  mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
}, { passive: true });

function resize() {
  const w = canvas.clientWidth || window.innerWidth;
  const h = canvas.clientHeight || window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

new IntersectionObserver(([entry]) => {
  visible = entry.isIntersecting;
  if (visible && !prefersReduced) clock.getDelta();  // avoid dt spike
}, { threshold: 0 }).observe(stageScroll);

function tick() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;
  progress = computeProgress();
  const p = progress;

  // weights
  const wDep = stageWeight(p, 2);
  const wEtch = stageWeight(p, 3);
  const wMet = stageWeight(p, 4);
  const w5 = stageWeight(p, 5, 0.07);
  const tDep = stageT(p, 2);
  const tEtch = stageT(p, 3);
  const tMet = stageT(p, 4);

  /* wafer idle motion */
  waferGroup.rotation.y += dt * (0.05 + w5 * 0.12);
  waferGroup.position.y = Math.sin(t * 0.5) * 0.02;

  /* film growth: grows through deposition, persists after */
  const grow = p < STAGES[2].start ? 0 : (p < STAGES[2].end ? smooth(tDep) : 1);
  film.scale.y = Math.max(grow * 0.09, 0.0001);
  film.position.y = 0.035 + film.scale.y / 2;
  // film fades away into the finale so the patterned dies shine through
  const filmFade = 1 - smooth(clamp01((p - STAGES[5].start) / 0.07));
  filmMat.opacity = grow > 0.02 ? filmFade : 0;
  film.visible = filmMat.opacity > 0.01;

  /* deposition source + atoms */
  targetGroup.visible = wDep > 0.01;
  atoms.visible = wDep > 0.01;
  if (targetGroup.visible) {
    targetGroup.position.y = 2.7 + (1 - wDep) * 1.4;
    targetGlow.material.opacity = wDep * (0.5 + Math.sin(t * 7) * 0.08);
    targetDisc.material.emissiveIntensity = wDep * 0.5;
    atomMat.opacity = wDep * 0.9;
    for (let i = 0; i < ATOMS; i++) {
      const a = atomData[i];
      a.y -= a.v * dt;
      a.x += a.drift * dt;
      const floor = 0.1 + film.scale.y;
      if (a.y < floor) {
        a.y = 2.3 + Math.random() * 0.4;
        const r = Math.sqrt(Math.random()) * 1.75, an = Math.random() * Math.PI * 2;
        a.x = Math.cos(an) * r; a.z = Math.sin(an) * r;
      }
      dummy.position.set(a.x, a.y, a.z);
      const s = 0.7 + 0.5 * Math.sin(i + t * 3);
      dummy.scale.setScalar(s);
      dummy.updateMatrix();
      atoms.setMatrixAt(i, dummy.matrix);
    }
    atoms.instanceMatrix.needsUpdate = true;
  }

  /* plasma etch */
  coilGroup.visible = wEtch > 0.01;
  ions.visible = wEtch > 0.01;
  plasmaLight.intensity = wEtch * (22 + Math.sin(t * 11) * 5);
  if (coilGroup.visible) {
    coilGroup.position.y = 2.55 + (1 - wEtch) * 1.4;
    plasmaGlow.material.opacity = wEtch * (0.55 + Math.sin(t * 9) * 0.1);
    plasmaGlow2.material.opacity = wEtch * (0.4 + Math.sin(t * 13 + 1) * 0.1);
    coilGroup.children.forEach((c) => {
      if (c.material && c.material.emissive) c.material.emissiveIntensity = wEtch * (0.9 + Math.sin(t * 10) * 0.3);
    });
    ionMat.opacity = wEtch * 0.85;
    for (let i = 0; i < IONS; i++) {
      const d = ionData[i];
      d.y -= d.v * dt;
      if (d.y < 0.15) {
        d.y = 2 + Math.random() * 0.6;
        const r = Math.sqrt(Math.random()) * 1.7, an = Math.random() * Math.PI * 2;
        d.x = Math.cos(an) * r; d.z = Math.sin(an) * r;
      }
      dummy.position.set(d.x, d.y, d.z);
      dummy.scale.set(1, 1, 1);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      ions.setMatrixAt(i, dummy.matrix);
    }
    ions.instanceMatrix.needsUpdate = true;
  }

  /* cross-section stack: pops in for etch, trenches cut with progress */
  const xsecW = stageWeight(p, 3, 0.06);
  xsec.visible = xsecW > 0.002;
  if (xsec.visible) {
    const sc = smooth(xsecW);
    xsec.scale.setScalar(Math.max(sc * 0.9, 0.0001));
    xsec.rotation.y = -0.5 + Math.sin(t * 0.4) * 0.06;
    const depth = smooth(clamp01((tEtch - 0.15) / 0.6));   // trenches open mid-stage
    xsec.userData.trenches.forEach((tr, i) => {
      const d = clamp01(depth * 1.15 - i * 0.04);
      const h = d * 0.36;                                   // cut through film into substrate a touch
      tr.scale.y = Math.max(h, 0.0001);
      tr.position.y = tr.userData.topY - h / 2;
      tr.material.emissiveIntensity = wEtch * d * (0.5 + Math.sin(t * 12 + i) * 0.25);
    });
  }

  /* metrology laser sweep */
  laserGroup.visible = wMet > 0.01;
  laserLight.intensity = wMet * 6;
  if (laserGroup.visible) {
    const sweep = Math.sin(tMet * Math.PI * 2.2 - Math.PI / 2);
    const sx = sweep * 1.45;
    laserGroup.position.set(sx, 0, 0.25);
    beamMat.opacity = wMet * 0.55;
    beamCore.material.opacity = wMet * 0.9;
    spot.material.opacity = wMet * (0.75 + Math.sin(t * 18) * 0.15);
    laserLight.position.set(sx, 0.5, 0.25);
    const ringPulse = (t * 1.4) % 1;
    scanRing.scale.setScalar(0.4 + ringPulse * 2.2);
    scanRing.material.opacity = wMet * (1 - ringPulse) * 0.6;
  }

  /* finale — dies light up */
  waferMat.emissiveIntensity = w5 * (1.15 + Math.sin(t * 2) * 0.15);
  dust.material.opacity = 0.3 + w5 * 0.25;
  dust.rotation.y = t * 0.01;

  /* stage-reactive rim colors */
  rimLight.color.setHex(wEtch > 0.4 ? 0xa07dff : 0x5bd3e8);
  rimLight.intensity = 12 + w5 * 10;

  updateCamera(p, mouseX, mouseY, t);
  renderer.render(scene, camera);
}

function loop() {
  if (visible && !document.hidden) tick();
  if (!staticMode) requestAnimationFrame(loop);
}

/* static fallback for reduced motion: render one mid-journey frame */
if (prefersReduced) {
  staticMode = true;
  document.body.classList.add('static-stage');
  progress = 0.05;
  film.scale.y = 0.09; film.position.y = 0.08; filmMat.opacity = 1;
  camera.position.set(0, 2.3, 7.4);
  camera.lookAt(0, 0.15, 0);
  resize();
  renderer.render(scene, camera);
} else {
  requestAnimationFrame(loop);
}
