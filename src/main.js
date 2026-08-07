/* Thin Film Engineer · main
   Smooth scroll, scroll-driven storytelling, charts, form.
   WebGL centrepiece loads lazily from webgl.js (separate chunk). */

import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

const html = document.documentElement;
const q = (s, c = document) => c.querySelector(s);
const qa = (s, c = document) => [...c.querySelectorAll(s)];

const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const saveData = !!(navigator.connection && navigator.connection.saveData);
const isTouch = matchMedia('(pointer: coarse)').matches;
const motion = !reduced;

let glApi = null;

/* ───────────────────────── nav ───────────────────────── */
function initNav() {
  const nav = q('#nav');
  const toggle = q('.nav-toggle');
  const menu = q('#mobile-menu');

  const onScroll = () => nav.classList.toggle('scrolled', (window.scrollY || 0) > 8);
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  let open = false;
  const setMenu = (v) => {
    open = v;
    menu.hidden = !v;
    toggle.setAttribute('aria-expanded', String(v));
    toggle.setAttribute('aria-label', v ? 'Close menu' : 'Open menu');
  };
  toggle.addEventListener('click', () => setMenu(!open));
  qa('a', menu).forEach((a) => a.addEventListener('click', () => setMenu(false)));
  addEventListener('keydown', (e) => { if (e.key === 'Escape' && open) setMenu(false); });

  // dark-section awareness for nav ink
  const darks = qa('.section-dark');
  const check = () => {
    const y = nav.offsetHeight * 0.6;
    const dark = darks.some((s) => {
      const r = s.getBoundingClientRect();
      return r.top <= y && r.bottom >= y;
    });
    nav.classList.toggle('on-dark', dark);
  };
  addEventListener('scroll', check, { passive: true });
  addEventListener('resize', check);
  check();
}

/* ─────────────────── smooth scroll ───────────────────── */
let lenis = null;
function initLenis() {
  if (!motion) return;
  lenis = new Lenis({ duration: 1.15, smoothWheel: true });
  window.__lenis = lenis; // programmatic scrolling (tests, console)
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((t) => lenis.raf(t * 1000));
  gsap.ticker.lagSmoothing(0);
  // pin spacers change the page height after Lenis measures it
  ScrollTrigger.addEventListener('refresh', () => lenis && lenis.resize());
}

function initAnchors() {
  qa('a[href^="#"]').forEach((a) => {
    a.addEventListener('click', (e) => {
      const id = a.getAttribute('href');
      if (id.length < 2) return;
      const el = q(id);
      if (!el) return;
      e.preventDefault();
      if (lenis) lenis.scrollTo(el, { offset: -20, duration: 1.4 });
      else el.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' });
      history.replaceState(null, '', id);
    });
  });
}

/* ─────────────────── text & reveals ──────────────────── */
function initReveals() {
  // masked line reveals, staggered per heading block
  qa('.hero-h, .chapter-title, .footer-line').forEach((block) => {
    const lines = qa('.line-in', block);
    if (!lines.length) return;
    gsap.to(lines, {
      y: 0,
      duration: 1.15,
      ease: 'power4.out',
      stagger: 0.14,
      scrollTrigger: { trigger: block, start: 'top 88%', once: true },
    });
  });

  qa('.reveal').forEach((el) => {
    gsap.to(el, {
      opacity: 1,
      y: 0,
      duration: 0.9,
      ease: 'power3.out',
      scrollTrigger: { trigger: el, start: 'top 88%', once: true },
    });
  });
}

/* ─────────────────────── hero ────────────────────────── */
function initHero() {
  ScrollTrigger.create({
    trigger: '.hero',
    start: 'top top',
    end: 'bottom top',
    scrub: true,
    onUpdate: (st) => { if (glApi) glApi.setHero(st.progress); },
  });
  gsap.to('.hero-copy', {
    y: -60,
    opacity: 0.25,
    ease: 'none',
    scrollTrigger: { trigger: '.hero', start: '55% top', end: 'bottom top', scrub: true },
  });
  gsap.to('.scroll-cue', {
    opacity: 0,
    ease: 'none',
    scrollTrigger: { trigger: '.hero', start: '10% top', end: '30% top', scrub: true },
  });
}

/* ────────────────── chapter I · pinned ───────────────── */
function initCraft() {
  const scenes = qa('.craft-scene');
  const n = scenes.length;

  // initial states
  scenes.forEach((s, i) => gsap.set(s, { autoAlpha: i === 0 ? 1 : 0 }));

  const tl = gsap.timeline({
    scrollTrigger: {
      trigger: '.craft-pin',
      start: 'top top',
      end: `+=${n * 100}%`,
      pin: true,
      scrub: 0.6,
      anticipatePin: 1,
      onUpdate: (st) => { if (glApi) glApi.setCraft(st.progress * n); },
    },
    defaults: { ease: 'none' },
  });

  // dummy spanning tween keeps the timeline exactly n scene-units long,
  // so DOM crossfades and the GL scene index share one progress scale
  tl.to({}, { duration: n }, 0);
  window.__craftTl = tl;
  for (let i = 1; i < n; i++) {
    const prev = scenes[i - 1];
    const next = scenes[i];
    const at = i - 0.14;
    tl.to(qa('.scene-copy', prev), { y: -50, duration: 0.14 }, at)
      .to(prev, { autoAlpha: 0, duration: 0.12 }, at)
      .fromTo(next, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.14 }, i - 0.02)
      .fromTo(qa('.scene-copy', next), { y: 60 }, { y: 0, duration: 0.18 }, i - 0.02);
  }

  // stop rendering once the story has scrolled past the canvas
  ScrollTrigger.create({
    trigger: '.numbers',
    start: 'top 30%',
    onEnter: () => { if (glApi) glApi.setVisible(false); },
    onLeaveBack: () => { if (glApi) glApi.setVisible(true); },
  });
}

/* ─────────────────── chapter II · data ───────────────── */
function fmt(v, dec, prefix, suffix) {
  return `${prefix}${v.toFixed(dec)}${suffix}`;
}

function initNumbers() {
  qa('.count').forEach((el) => {
    const target = parseFloat(el.dataset.count);
    const dec = parseInt(el.dataset.decimals || '0', 10);
    const prefix = el.dataset.prefix || '';
    const suffix = el.dataset.suffix || '';
    const obj = { v: 0 };
    gsap.to(obj, {
      v: target,
      duration: 1.6,
      ease: 'power2.out',
      onUpdate: () => { el.textContent = fmt(obj.v, dec, prefix, suffix); },
      scrollTrigger: { trigger: el, start: 'top 85%', once: true },
    });
  });

  qa('.chart-a, .chart-b').forEach((chart) => {
    gsap.fromTo(qa('.bar', chart), { scaleX: 0 }, {
      scaleX: 1,
      duration: 1.2,
      ease: 'power3.out',
      stagger: 0.15,
      transformOrigin: 'left center',
      scrollTrigger: { trigger: chart, start: 'top 82%', once: true },
    });
  });

  const growth = q('.chart-c');
  if (growth) {
    const tl = gsap.timeline({
      scrollTrigger: { trigger: growth, start: 'top 80%', once: true },
    });
    tl.fromTo(qa('.growth-bar', growth), { scaleY: 0 }, {
      scaleY: 1, duration: 1.1, ease: 'power3.out', stagger: 0.25, transformOrigin: 'bottom center',
    })
      .to(q('.growth-path', growth), { strokeDashoffset: 0, duration: 1.0, ease: 'power2.inOut' }, 0.35);
  }

  const salary = q('.chart-salary');
  if (salary) {
    const tl = gsap.timeline({
      scrollTrigger: { trigger: salary, start: 'top 80%', once: true },
    });
    tl.fromTo(q('.salary-band'), { scaleX: 0 }, { scaleX: 1, duration: 1.0, ease: 'power3.out', transformOrigin: 'left center' })
      .fromTo(q('.salary-entry'), { scaleX: 0 }, { scaleX: 1, duration: 0.7, ease: 'power3.out', transformOrigin: 'left center' }, 0.2)
      .fromTo(q('.salary-median'), { scaleY: 0 }, { scaleY: 1, duration: 0.5, ease: 'power2.out', transformOrigin: 'bottom center' }, 0.6);
  }
}

/* ──────────────── curriculum scale visual ────────────── */
function initScale() {
  const marks = qa('.scale-mark');
  if (!marks.length) return;
  gsap.fromTo(marks, { opacity: 0, scale: 0.6, transformOrigin: '50% 50%' }, {
    opacity: 1,
    scale: 1,
    duration: 0.7,
    ease: 'back.out(1.6)',
    stagger: 0.12,
    scrollTrigger: { trigger: '.scale-visual', start: 'top 82%', once: true },
  });
}

/* ─────────────────────── form ────────────────────────── */
function initForm() {
  const form = q('#pack-form');
  if (!form) return;
  const nameEl = q('#pf-name');
  const emailEl = q('#pf-email');
  const nameErr = q('#pf-name-error');
  const emailErr = q('#pf-email-error');
  const btn = q('.btn-submit', form);
  const label = q('.btn-submit-label', form);
  const status = q('#form-status');
  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  const setFieldError = (input, errEl, bad) => {
    input.setAttribute('aria-invalid', bad ? 'true' : 'false');
    errEl.hidden = !bad;
  };

  nameEl.addEventListener('blur', () => setFieldError(nameEl, nameErr, !nameEl.value.trim()));
  emailEl.addEventListener('blur', () => {
    if (emailEl.value) setFieldError(emailEl, emailErr, !EMAIL_RE.test(emailEl.value.trim()));
  });
  [nameEl, emailEl].forEach((el) => el.addEventListener('input', () => {
    el.setAttribute('aria-invalid', 'false');
    (el === nameEl ? nameErr : emailErr).hidden = true;
  }));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = nameEl.value.trim();
    const email = emailEl.value.trim();
    const nameBad = !name;
    const emailBad = !EMAIL_RE.test(email);
    setFieldError(nameEl, nameErr, nameBad);
    setFieldError(emailEl, emailErr, emailBad);
    if (nameBad) { nameEl.focus(); return; }
    if (emailBad) { emailEl.focus(); return; }

    status.textContent = '';
    status.className = 'form-status';
    btn.disabled = true;
    label.textContent = 'Sending…';

    const key = window.W3F_KEY || '';
    const placeholder = !key || key === 'PASTE-YOUR-ACCESS-KEY-HERE';

    try {
      let ok;
      if (placeholder) {
        await new Promise((r) => setTimeout(r, 900)); // demo mode — nothing is sent
        ok = true;
      } else {
        const res = await fetch('https://api.web3forms.com/submit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            access_key: key,
            subject: 'New Interview Pack signup — ' + name,
            from_name: 'Thin Film Engineer website',
            name,
            email,
            source: 'thinfilmengineer.com',
          }),
        });
        const data = await res.json().catch(() => ({}));
        ok = res.ok && data.success !== false;
      }
      if (ok) {
        status.textContent = 'Done — the pack is on its way. Check your inbox.';
        status.classList.add('ok');
        form.reset();
      } else {
        throw new Error('send failed');
      }
    } catch {
      status.textContent = 'Something went wrong sending the form. Please try again, or email info@thinfilmengineer.com.';
      status.classList.add('err');
    } finally {
      btn.disabled = false;
      label.textContent = 'Send me the pack';
    }
  });
}

/* ─────────────────────── WebGL ───────────────────────── */
function initGL() {
  if (!motion || saveData) return;
  let ctxOk = false;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    ctxOk = !!gl;
    // software rasterizers render these scenes on the CPU — serve the
    // static posters instead (override with ?forcegl for testing)
    if (gl && !/[?&]forcegl/.test(location.search)) {
      const dbg = gl.getExtension('WEBGL_debug_renderer_info');
      const name = dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : '';
      if (/swiftshader|llvmpipe|software/i.test(name)) ctxOk = false;
    }
  } catch { ctxOk = false; }
  if (!ctxOk) return;

  // keep the WebGL boot out of the load window — the page is fully
  // readable without it, so it can wait for idle time
  const start = () => {
    const idle = window.requestIdleCallback || ((f) => setTimeout(f, 350));
    idle(loadGL, { timeout: 2500 });
  };
  if (document.readyState === 'complete') start();
  else addEventListener('load', start, { once: true });
}

function loadGL() {
  import('./webgl.js')
    .then((m) => {
      const canvas = q('#gl');
      glApi = m.init(canvas, { mobile: isTouch || innerWidth < 860 });
      if (!glApi) return;
      html.classList.add('gl');
      // sync current scroll state into the freshly-created scenes
      ScrollTrigger.refresh();
    })
    .catch(() => { /* the site is fully usable without WebGL */ });
}

/* ─────────────────────── boot ────────────────────────── */
function boot() {
  initNav();
  initForm();

  if (!motion) return; // reduced motion: everything is already visible

  try {
    html.classList.add('motion');
    gsap.registerPlugin(ScrollTrigger);
    initLenis();
    initAnchors();
    initReveals();
    initHero();
    initCraft();
    initNumbers();
    initScale();
    initGL();
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => ScrollTrigger.refresh());
    }
    addEventListener('resize', () => { if (glApi) glApi.resize(); });
  } catch (err) {
    // never leave content hidden if anything above throws
    html.classList.add('no-anim');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
