/* Thin Film Engineer · WebGL centrepiece
   Real-time scenes tone-mapped to the light "cleanroom" aesthetic:
   S1 wafer (hero) · S2 deposition · S3 etch · S4 metrology · S5 stack.
   All driven by scroll progress from main.js. */

import {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Color,
  Mesh, InstancedMesh, Object3D, Matrix4,
  CylinderGeometry, SphereGeometry, BoxGeometry, RingGeometry, PlaneGeometry,
  MeshPhysicalMaterial, MeshBasicMaterial, MeshStandardMaterial,
  DirectionalLight, AmbientLight,
  ACESFilmicToneMapping, PMREMGenerator, DoubleSide, AdditiveBlending,
  CanvasTexture,
} from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

const IRIDESCENT = { iridescence: 1.0, iridescenceIOR: 1.32, iridescenceThicknessRange: [120, 480] };

function contactShadowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 6, 64, 64, 62);
  grad.addColorStop(0, 'rgba(10,12,16,0.42)');
  grad.addColorStop(1, 'rgba(10,12,16,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new CanvasTexture(c);
}

export function init(canvas, opts = {}) {
  let renderer;
  try {
    renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'high-performance' });
  } catch {
    return null;
  }
  const mobile = !!opts.mobile;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.setClearColor(0x000000, 0);

  const scene = new Scene();
  const camera = new PerspectiveCamera(34, 1, 0.1, 60);
  camera.position.set(0, 0.55, 7.2);
  camera.lookAt(0, 0, 0);

  const pmrem = new PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.045).texture;
  pmrem.dispose();

  const sun = new DirectionalLight(0xffffff, 1.4);
  sun.position.set(3, 6, 4);
  scene.add(sun);
  scene.add(new AmbientLight(0xdfe4ee, 0.35));

  const shadowTex = contactShadowTexture();
  const fadables = []; // materials registered for group fades

  const fadable = (mat) => { mat.transparent = true; fadables.push(mat); return mat; };

  function setGroupFade(group, v) {
    group.traverse((o) => {
      if (o.isMesh && o.material && o.material.userData.baseOpacity !== undefined) {
        o.material.opacity = o.material.userData.baseOpacity * v;
      }
    });
  }
  function registerOpacity(group) {
    group.traverse((o) => {
      if (o.isMesh && o.material) {
        o.material.transparent = true;
        o.material.userData.baseOpacity = o.material.opacity;
      }
    });
  }

  /* layout: where the "media column" sits in world units
     (center: used by the build-time poster generator) */
  const center = !!opts.center;
  const sideX = center ? 0 : (mobile ? 0 : 1.35);
  const sideY = center ? 0 : (mobile ? 1.15 : 0);
  const sideScale = center ? 1 : (mobile ? 0.5 : 1);

  /* ── S1 · wafer ─────────────────────────────────────── */
  const waferGroup = new Group();
  {
    const waferMat = new MeshPhysicalMaterial({
      color: 0xd6d9de,
      metalness: 1.0,
      roughness: 0.07,
      clearcoat: 1.0,
      clearcoatRoughness: 0.14,
      envMapIntensity: 1.35,
      ...IRIDESCENT,
    });
    const wafer = new Mesh(new CylinderGeometry(1.55, 1.55, 0.035, 128), waferMat);
    waferGroup.add(wafer);

    const shadow = new Mesh(new PlaneGeometry(4.6, 4.6), new MeshBasicMaterial({
      map: shadowTex, transparent: true, depthWrite: false, opacity: 0.55,
    }));
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = -1.35;
    waferGroup.add(shadow);

    const baseX = center ? 0 : (mobile ? 0 : 1.7);
    const baseY = center ? 0.05 : (mobile ? 0.95 : 0.05);
    waferGroup.position.set(baseX, baseY, 0);
    waferGroup.scale.setScalar(center ? 0.95 : (mobile ? 0.62 : 1));
    waferGroup.userData.wafer = wafer;
    waferGroup.userData.mat = waferMat;
    waferGroup.userData.baseY = baseY;
  }
  scene.add(waferGroup);

  /* ── S2 · deposition ────────────────────────────────── */
  const depositGroup = new Group();
  const NX = mobile ? 8 : 10;
  const NZ = mobile ? 6 : 7;
  const SP = 0.34;
  let topLayer;
  {
    const base = new Mesh(
      new BoxGeometry(NX * SP + 0.5, 0.16, NZ * SP + 0.5),
      new MeshPhysicalMaterial({ color: 0x2a2e37, metalness: 0.9, roughness: 0.12, clearcoat: 1, envMapIntensity: 1.2 }),
    );
    base.position.y = -0.55;
    depositGroup.add(base);

    const sphGeo = new SphereGeometry(0.145, mobile ? 20 : 28, mobile ? 14 : 20);
    const sphMat = new MeshPhysicalMaterial({
      color: 0xd9dde4, metalness: 0.35, roughness: 0.12, clearcoat: 1, clearcoatRoughness: 0.1,
      envMapIntensity: 1.25, ...IRIDESCENT,
    });
    // two settled layers
    const settled = new InstancedMesh(sphGeo, sphMat, NX * NZ * 2);
    const dummy = new Object3D();
    let k = 0;
    for (let layer = 0; layer < 2; layer++) {
      for (let i = 0; i < NX; i++) {
        for (let j = 0; j < NZ; j++) {
          dummy.position.set(
            (i - (NX - 1) / 2) * SP + (layer % 2) * SP * 0.5,
            -0.47 + 0.145 + layer * 0.26,
            (j - (NZ - 1) / 2) * SP + (layer % 2) * SP * 0.5,
          );
          dummy.updateMatrix();
          settled.setMatrixAt(k++, dummy.matrix);
        }
      }
    }
    depositGroup.add(settled);

    // top layer assembles with scroll
    topLayer = new InstancedMesh(sphGeo, sphMat.clone(), NX * NZ);
    topLayer.userData.slots = [];
    const order = [];
    for (let i = 0; i < NX; i++) for (let j = 0; j < NZ; j++) order.push([i, j]);
    // settle diagonally across the lattice
    order.sort((a, b) => (a[0] + a[1]) - (b[0] + b[1]) || a[0] - b[0]);
    order.forEach(([i, j], idx) => {
      topLayer.userData.slots.push({
        x: (i - (NX - 1) / 2) * SP,
        z: (j - (NZ - 1) / 2) * SP,
        y: -0.47 + 0.145 + 2 * 0.26,
        t: idx / (NX * NZ),
      });
    });
    depositGroup.add(topLayer);
    depositGroup.rotation.x = 0.32;
    depositGroup.rotation.y = -0.4;
  }

  /* ── S3 · etch ──────────────────────────────────────── */
  const etchGroup = new Group();
  const trenches = [];
  const ions = [];
  {
    const W = 3.1; const D = 1.7;
    const strata = [
      { c: 0xcdb492, h: 0.34 },
      { c: 0xb9c3cf, h: 0.34 },
      { c: 0xa99bc9, h: 0.34 },
      { c: 0x8fb6c4, h: 0.34 },
    ];
    let y = 0.55;
    strata.forEach((s) => {
      const m = new Mesh(
        new BoxGeometry(W, s.h, D),
        new MeshPhysicalMaterial({ color: s.c, metalness: 0.15, roughness: 0.35, clearcoat: 0.6, envMapIntensity: 1 }),
      );
      y -= s.h;
      m.position.y = y + s.h / 2;
      etchGroup.add(m);
    });
    const topY = 0.55;

    // hard mask segments with 4 openings
    const openings = [-1.05, -0.35, 0.35, 1.05];
    const gapW = 0.2;
    const maskMat = new MeshPhysicalMaterial({ color: 0x3a3f4a, metalness: 0.6, roughness: 0.3 });
    let cursor = -W / 2;
    openings.concat([W / 2 + gapW / 2]).forEach((gx) => {
      const segW = (gx - gapW / 2) - cursor;
      if (segW > 0.01) {
        const seg = new Mesh(new BoxGeometry(segW, 0.09, D), maskMat);
        seg.position.set(cursor + segW / 2, topY + 0.045, 0);
        etchGroup.add(seg);
      }
      cursor = gx + gapW / 2;
    });

    // trenches: dark boxes growing downward from the mask openings
    const trenchMat = new MeshBasicMaterial({ color: 0x0b0d12 });
    openings.forEach((gx) => {
      const t = new Mesh(new BoxGeometry(gapW, 1, D + 0.02), trenchMat);
      t.position.set(gx, topY, 0);
      t.scale.y = 0.001;
      etchGroup.add(t);
      const glow = new Mesh(
        new BoxGeometry(gapW, 0.03, D + 0.03),
        new MeshBasicMaterial({ color: 0x9d8bf5, transparent: true, opacity: 0.9, blending: AdditiveBlending, depthWrite: false }),
      );
      glow.position.set(gx, topY, 0);
      etchGroup.add(glow);
      trenches.push({ box: t, glow, x: gx, topY });
    });

    // ion streaks
    const ionGeo = new BoxGeometry(0.012, 0.34, 0.012);
    const ionColors = [0x7fd4ec, 0xa78bfa, 0xe79ac2];
    const nIons = mobile ? 18 : 34;
    for (let i = 0; i < nIons; i++) {
      const mat = new MeshBasicMaterial({
        color: ionColors[i % 3], transparent: true, opacity: 0.75,
        blending: AdditiveBlending, depthWrite: false,
      });
      const ion = new Mesh(ionGeo, mat);
      const lane = openings[i % openings.length];
      ion.position.set(lane + (Math.random() - 0.5) * 0.1, 1 + Math.random() * 2.2, (Math.random() - 0.5) * D * 0.8);
      ion.userData = { speed: 1.6 + Math.random() * 1.4, top: 3.1, floor: topY + 0.1 };
      etchGroup.add(ion);
      ions.push(ion);
    }

    etchGroup.rotation.x = 0.12;
    etchGroup.rotation.y = -0.35;
    etchGroup.position.y = 0.15;
  }

  /* ── S4 · metrology ─────────────────────────────────── */
  const metroGroup = new Group();
  const rings = [];
  let beamPivot;
  {
    const film = new Mesh(
      new BoxGeometry(3.0, 0.1, 1.9),
      new MeshPhysicalMaterial({
        color: 0xc9ced6, metalness: 0.85, roughness: 0.08, clearcoat: 1, envMapIntensity: 1.3, ...IRIDESCENT,
      }),
    );
    film.position.y = -0.45;
    metroGroup.add(film);

    beamPivot = new Group();
    const beamMat = new MeshBasicMaterial({
      color: 0xc4b2ff, transparent: true, opacity: 0.85, blending: AdditiveBlending, depthWrite: false,
    });
    const mkBeam = (angle) => {
      const len = 2.6;
      const b = new Mesh(new CylinderGeometry(0.012, 0.012, len, 10), beamMat);
      const holder = new Group();
      b.position.y = len / 2;
      holder.add(b);
      const halo = new Mesh(new CylinderGeometry(0.045, 0.045, len, 10), new MeshBasicMaterial({
        color: 0xc4b2ff, transparent: true, opacity: 0.14, blending: AdditiveBlending, depthWrite: false,
      }));
      halo.position.y = len / 2;
      holder.add(halo);
      holder.rotation.z = angle;
      return holder;
    };
    beamPivot.add(mkBeam(0.62));   // incident
    beamPivot.add(mkBeam(-0.62));  // reflected
    const spot = new Mesh(new SphereGeometry(0.06, 16, 12), new MeshBasicMaterial({
      color: 0xf2ecff, transparent: true, opacity: 0.95, blending: AdditiveBlending, depthWrite: false,
    }));
    beamPivot.add(spot);
    beamPivot.position.y = -0.4;
    metroGroup.add(beamPivot);

    const ringColors = [0x7fd4ec, 0xa78bfa, 0xe79ac2, 0xecc989];
    for (let i = 0; i < 4; i++) {
      const ring = new Mesh(
        new RingGeometry(0.96, 1, 64),
        new MeshBasicMaterial({
          color: ringColors[i], transparent: true, opacity: 0, side: DoubleSide,
          blending: AdditiveBlending, depthWrite: false,
        }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = -0.39;
      ring.userData.phase = i / 4;
      metroGroup.add(ring);
      rings.push(ring);
    }
    metroGroup.rotation.x = 0.3;
    metroGroup.rotation.y = 0.25;
  }

  /* ── S5 · exploded stack ────────────────────────────── */
  const stackGroup = new Group();
  const slabs = [];
  {
    const cols = [0x394050, 0xcdb492, 0xa99bc9, 0x8fb6c4, 0xd7a9bd, 0xd6d9de];
    cols.forEach((c, i) => {
      const iri = i === cols.length - 1 ? IRIDESCENT : {};
      const slab = new Mesh(
        new BoxGeometry(2.5, 0.11, 1.8),
        new MeshPhysicalMaterial({
          color: c, metalness: i === 0 || i === cols.length - 1 ? 0.85 : 0.2,
          roughness: 0.18, clearcoat: 0.8, envMapIntensity: 1.15, ...iri,
        }),
      );
      slab.userData.idx = i;
      stackGroup.add(slab);
      slabs.push(slab);
    });
    stackGroup.rotation.x = 0.42;
    stackGroup.rotation.y = -0.5;
  }

  /* craft groups share the media-column position */
  const craftGroups = [depositGroup, etchGroup, metroGroup, stackGroup];
  craftGroups.forEach((g) => {
    const holder = new Group();
    holder.position.set(sideX, sideY, 0);
    holder.scale.setScalar(sideScale);
    holder.add(g);
    holder.visible = false;
    scene.add(holder);
    g.userData.holder = holder;
    registerOpacity(holder);
  });
  registerOpacity(waferGroup);

  /* ── state & loop ───────────────────────────────────── */
  let heroP = 0;
  let craftP = -1; // <0 → hero zone
  let visible = true;
  let raf = 0;
  const clock = { t: 0, last: performance.now() };

  function resize() {
    const w = canvas.clientWidth || innerWidth;
    const h = canvas.clientHeight || innerHeight;
    const dpr = Math.min(devicePixelRatio || 1, mobile ? 1.5 : 1.75);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  function update(dt) {
    clock.t += dt;
    const t = clock.t;

    /* wafer */
    const inHero = craftP < 0.02;
    waferGroup.visible = inHero;
    if (inHero) {
      const w = waferGroup.userData.wafer;
      w.rotation.y = t * 0.22;
      w.rotation.x = 0.42 + heroP * 0.55 + Math.sin(t * 0.3) * 0.02;
      w.rotation.z = 0.06;
      // iridescent sweep travelling across the film
      const m = waferGroup.userData.mat;
      const sweep = (Math.sin(t * 0.45) + 1) / 2;
      m.iridescenceThicknessRange = [140 + sweep * 260 + heroP * 220, 520 + sweep * 380 + heroP * 260];
      m.clearcoatRoughness = 0.08;
      waferGroup.position.y = waferGroup.userData.baseY - heroP * 0.7;
      setGroupFade(waferGroup, Math.max(0, 1 - Math.max(0, heroP - 0.55) / 0.45));
    }

    /* craft scenes — switch at the crossfade midpoint (i - 0.07) */
    const idx = Math.max(0, Math.min(3, Math.floor(craftP + 0.07)));
    const local = Math.max(0, craftP - idx + 0.07);
    craftGroups.forEach((g, i) => {
      const holder = g.userData.holder;
      const active = craftP >= 0 && i === idx;
      holder.visible = active;
      if (!active) return;
      // ease each scene in over its first 15%
      const fadeIn = Math.min(1, local / 0.15);
      setGroupFade(holder, fadeIn);
      holder.scale.setScalar(sideScale * (0.94 + 0.06 * fadeIn));
    });

    if (craftP >= 0 && idx === 0 && craftGroups[0].userData.holder.visible) {
      // deposition: settle the top layer
      const p = Math.min(1, local / 0.85);
      const dummy = new Object3D();
      const slots = topLayer.userData.slots;
      for (let i = 0; i < slots.length; i++) {
        const s = slots[i];
        const lp = Math.max(0, Math.min(1, (p - s.t * 0.75) / 0.25));
        const e = 1 - Math.pow(1 - lp, 3);
        dummy.position.set(s.x, s.y + (1 - e) * 2.2, s.z);
        dummy.scale.setScalar(lp <= 0 ? 0.0001 : 1);
        dummy.updateMatrix();
        topLayer.setMatrixAt(i, dummy.matrix);
      }
      topLayer.instanceMatrix.needsUpdate = true;
      depositGroup.rotation.y = -0.4 + t * 0.03;
    }

    if (craftP >= 0 && idx === 1) {
      // etch: trenches sink, ions rain
      const depth = 1.32 * Math.min(1, local / 0.85);
      trenches.forEach((tr) => {
        tr.box.scale.y = Math.max(0.001, depth);
        tr.box.position.y = tr.topY - depth / 2;
        tr.glow.position.y = tr.topY - depth;
      });
      ions.forEach((ion) => {
        ion.position.y -= ion.userData.speed * dt;
        if (ion.position.y < ion.userData.floor) ion.position.y = ion.userData.top;
      });
      etchGroup.rotation.y = -0.35 + t * 0.02;
    }

    if (craftP >= 0 && idx === 2) {
      // metrology: rings spread from the measurement spot
      rings.forEach((r) => {
        const ph = ((t * 0.35 + r.userData.phase) % 1);
        const s = 0.12 + ph * 1.15;
        r.scale.setScalar(s);
        r.material.opacity = (1 - ph) * 0.5;
      });
      beamPivot.rotation.y = Math.sin(t * 0.4) * 0.12;
      metroGroup.rotation.y = 0.25 + Math.sin(t * 0.15) * 0.05;
    }

    if (craftP >= 0 && idx === 3) {
      // finale: the stack floats apart
      const p = Math.min(1, local / 0.8);
      const e = 1 - Math.pow(1 - p, 3);
      slabs.forEach((s) => {
        s.position.y = (s.userData.idx - 2.5) * (0.13 + e * 0.42);
      });
      stackGroup.rotation.y = -0.5 + t * 0.06;
    }
  }

  function loop() {
    raf = requestAnimationFrame(loop);
    const now = performance.now();
    const dt = Math.min(0.05, (now - clock.last) / 1000);
    clock.last = now;
    if (!visible || document.hidden) return;
    update(dt);
    renderer.render(scene, camera);
  }

  resize();
  addEventListener('resize', resize);
  loop();

  return {
    setHero(p) { heroP = p; },
    setCraft(p) { craftP = p; },
    setVisible(v) {
      visible = v;
      canvas.style.opacity = v ? '1' : '0';
    },
    resize,
    /* used by the poster generator during the build — not called at runtime */
    _debug: { scene, camera, renderer, force(scenePart, p) {
      if (scenePart === 'hero') { heroP = p; craftP = -1; }
      else { craftP = p; }
      clock.last = performance.now();
      update(1 / 60);
      renderer.render(scene, camera);
    } },
  };
}
