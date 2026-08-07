/* ============================================================
   THIN FILM ENGINEER — scroll orchestration, reveals, charts
   ============================================================ */
(function () {
  'use strict';

  const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp01 = v => Math.min(1, Math.max(0, v));
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const COLOR = {
    cyan: css('--cyan') || '#2B9DB6',
    cyanBright: css('--cyan-bright') || '#5BD3E8',
    violet: css('--violet') || '#8A7BE8',
    amber: css('--amber') || '#BB853B',
    text: css('--text') || '#E9EDF6',
    text2: css('--text-2') || '#A7B1C7',
    text3: css('--text-3') || '#77829C',
    grid: 'rgba(148,168,210,0.10)',
    axis: 'rgba(148,168,210,0.22)'
  };
  const MONO = '500 11px "JetBrains Mono", monospace';

  /* ---------------- nav ---------------- */
  const nav = document.getElementById('nav');
  const onNavScroll = () => nav.classList.toggle('is-scrolled', window.scrollY > 40);
  window.addEventListener('scroll', onNavScroll, { passive: true });
  onNavScroll();

  /* ---------------- stage overlays ---------------- */
  const stageScroll = document.getElementById('stageScroll');
  const cards = Array.from(document.querySelectorAll('.stage-card'));
  const railFill = document.getElementById('railFill');
  const railLabel = document.getElementById('railLabel');
  const railDots = Array.from(document.querySelectorAll('.stage-rail__dots i'));
  const hudThickness = document.getElementById('hudThickness');
  const hudUniformity = document.getElementById('hudUniformity');

  const STAGES = [
    { start: 0.00, end: 0.13, label: 'INTRO' },
    { start: 0.13, end: 0.30, label: 'SUBSTRATE' },
    { start: 0.30, end: 0.48, label: 'DEPOSITION' },
    { start: 0.48, end: 0.66, label: 'PLASMA ETCH' },
    { start: 0.66, end: 0.84, label: 'METROLOGY' },
    { start: 0.84, end: 1.00, label: 'THE STACK' }
  ];
  // visibility windows slightly inset so cards breathe between stages
  const CARD_PAD = 0.022;

  let activeStage = -1;
  function updateStage() {
    if (!stageScroll) return;
    const rect = stageScroll.getBoundingClientRect();
    const total = rect.height - window.innerHeight;
    const p = total > 0 ? clamp01(-rect.top / total) : 0;

    let current = 0;
    for (let i = 0; i < STAGES.length; i++) {
      const s = STAGES[i];
      const isLast = i === STAGES.length - 1;
      const start = i === 0 ? s.start : s.start + CARD_PAD;
      const end = isLast ? s.end + 0.01 : s.end - CARD_PAD;
      if (p >= s.start) current = i;
      const show = p >= start && p < end;
      const card = cards[i];
      if (card) card.classList.toggle('is-active', show);
    }

    if (railFill) railFill.style.height = (p * 100).toFixed(1) + '%';
    if (current !== activeStage) {
      activeStage = current;
      if (railLabel) railLabel.textContent = STAGES[current].label;
      railDots.forEach((d, i) => d.classList.toggle('is-on', i <= current));
    }

    // metrology HUD: numbers settle as the laser sweeps
    if (hudThickness && p > STAGES[4].start - 0.02 && p < STAGES[4].end + 0.02) {
      const t = clamp01((p - STAGES[4].start) / (STAGES[4].end - STAGES[4].start));
      const settle = Math.min(1, t * 1.8);
      const jitter = (1 - settle) * 6;
      const thick = 42.3 + (Math.random() - 0.5) * jitter;
      const uni = 0.4 + (Math.random() - 0.5) * jitter * 0.12;
      hudThickness.textContent = thick.toFixed(1) + ' nm';
      hudUniformity.textContent = Math.max(uni, 0.2).toFixed(1) + '%';
    }
  }

  if (!prefersReduced) {
    let ticking = false;
    window.addEventListener('scroll', () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(() => { updateStage(); ticking = false; });
      }
    }, { passive: true });
    updateStage();
  } else {
    // static mode: all cards visible (scene.js adds body.static-stage)
    cards.forEach(c => c.classList.add('is-active'));
    if (hudThickness) hudThickness.textContent = '42.3 nm';
  }

  /* ---------------- reveal on scroll ---------------- */
  const revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !prefersReduced) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('in-view');
          io.unobserve(e.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    revealEls.forEach(el => io.observe(el));
  } else {
    revealEls.forEach(el => el.classList.add('in-view'));
  }

  /* ---------------- animated counters ---------------- */
  function animateCount(el) {
    const target = parseFloat(el.dataset.count);
    const decimals = parseInt(el.dataset.decimals || '0', 10);
    if (prefersReduced) { el.textContent = target.toFixed(decimals); return; }
    const dur = 1400;
    const t0 = performance.now();
    (function step(now) {
      const t = clamp01((now - t0) / dur);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = (target * eased).toFixed(decimals);
      if (t < 1) requestAnimationFrame(step);
    })(t0);
  }
  const counters = document.querySelectorAll('[data-count]');
  if ('IntersectionObserver' in window) {
    const cio = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) { animateCount(e.target); cio.unobserve(e.target); }
      });
    }, { threshold: 0.6 });
    counters.forEach(el => cio.observe(el));
  } else {
    counters.forEach(el => { el.textContent = el.dataset.count; });
  }

  /* ---------------- skill bars ---------------- */
  const skills = document.querySelectorAll('.skill');
  if ('IntersectionObserver' in window && skills.length) {
    const sio = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          const bar = e.target.querySelector('.skill__bar i');
          if (bar) bar.style.width = e.target.dataset.weight + '%';
          sio.unobserve(e.target);
        }
      });
    }, { threshold: 0.5 });
    skills.forEach((el, i) => {
      const bar = el.querySelector('.skill__bar i');
      if (bar) bar.style.transitionDelay = (i * 90) + 'ms';
      sio.observe(el);
    });
  }

  /* ============================================================
     CHARTS — hand-rolled canvas, DPR-aware, tooltip layer
     ============================================================ */
  function setupCanvas(canvas) {
    const rect = canvas.parentElement.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w: rect.width, h: rect.height };
  }

  function makeTooltip(host) {
    const tip = document.createElement('div');
    tip.style.cssText = 'position:absolute;pointer-events:none;z-index:5;padding:8px 12px;' +
      'border-radius:10px;border:1px solid rgba(91,211,232,.35);background:rgba(6,12,20,.92);' +
      'font:500 12px Inter,sans-serif;color:#E9EDF6;opacity:0;transition:opacity .15s;white-space:nowrap;' +
      'transform:translate(-50%,-130%);backdrop-filter:blur(6px)';
    host.style.position = 'relative';
    host.appendChild(tip);
    return tip;
  }

  /* ---------- revenue line chart ---------- */
  const REVENUE = [
    { year: 2015, v: 335 }, { year: 2016, v: 339 }, { year: 2017, v: 412 },
    { year: 2018, v: 469 }, { year: 2019, v: 412 }, { year: 2020, v: 440 },
    { year: 2021, v: 556 }, { year: 2022, v: 574 }, { year: 2023, v: 527 },
    { year: 2024, v: 628 },
    { year: 2025, v: 700, f: true }, { year: 2026, v: 800, f: true },
    { year: 2028, v: 900, f: true }, { year: 2030, v: 1000, f: true }
  ];

  function drawRevenue(canvas, animT) {
    const { ctx, w, h } = setupCanvas(canvas);
    const padL = 46, padR = 18, padT = 16, padB = 30;
    const iw = w - padL - padR, ih = h - padT - padB;
    const x0 = 2015, x1 = 2030, yMax = 1100;
    const X = yr => padL + ((yr - x0) / (x1 - x0)) * iw;
    const Y = v => padT + ih - (v / yMax) * ih;

    ctx.clearRect(0, 0, w, h);

    // grid + y labels
    ctx.font = MONO;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let v = 0; v <= 1000; v += 250) {
      ctx.strokeStyle = COLOR.grid;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, Y(v)); ctx.lineTo(w - padR, Y(v)); ctx.stroke();
      ctx.fillStyle = COLOR.text3;
      ctx.fillText(v === 1000 ? '$1T' : '$' + v + 'B', padL - 8, Y(v));
    }
    // x labels
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    [2015, 2018, 2021, 2024, 2027, 2030].forEach(yr => {
      ctx.fillStyle = COLOR.text3;
      ctx.fillText(String(yr), X(yr), h - padB + 10);
    });

    // clip for draw-on animation
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, padL + iw * animT + 2, h);
    ctx.clip();

    const actual = REVENUE.filter(d => !d.f);
    const forecast = REVENUE.filter(d => d.f);
    const lastActual = actual[actual.length - 1];

    // area fill under actual
    const grad = ctx.createLinearGradient(0, padT, 0, h - padB);
    grad.addColorStop(0, 'rgba(43,157,182,0.28)');
    grad.addColorStop(1, 'rgba(43,157,182,0)');
    ctx.beginPath();
    actual.forEach((d, i) => i ? ctx.lineTo(X(d.year), Y(d.v)) : ctx.moveTo(X(d.year), Y(d.v)));
    ctx.lineTo(X(lastActual.year), h - padB);
    ctx.lineTo(X(actual[0].year), h - padB);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // actual line
    ctx.beginPath();
    actual.forEach((d, i) => i ? ctx.lineTo(X(d.year), Y(d.v)) : ctx.moveTo(X(d.year), Y(d.v)));
    ctx.strokeStyle = COLOR.cyanBright;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.stroke();

    // forecast dashed
    ctx.beginPath();
    ctx.moveTo(X(lastActual.year), Y(lastActual.v));
    forecast.forEach(d => ctx.lineTo(X(d.year), Y(d.v)));
    ctx.setLineDash([5, 6]);
    ctx.strokeStyle = COLOR.violet;
    ctx.stroke();
    ctx.setLineDash([]);

    // milestone markers + selective direct labels
    const mark = (d, color, label, dy) => {
      ctx.beginPath();
      ctx.arc(X(d.year), Y(d.v), 4, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#0A0F1C';
      ctx.lineWidth = 2;
      ctx.stroke();
      if (label) {
        ctx.font = MONO;
        const nearRight = X(d.year) + ctx.measureText(label).width / 2 > w - 6;
        ctx.textAlign = nearRight ? 'right' : 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillStyle = COLOR.text2;
        ctx.fillText(label, nearRight ? X(d.year) + 4 : X(d.year), Y(d.v) + dy);
      }
    };
    mark(actual.find(d => d.year === 2021), COLOR.cyanBright, '$556B', -10);
    mark(lastActual, COLOR.cyanBright, '$628B', -10);
    mark(forecast[forecast.length - 1], COLOR.violet, '≈$1T FORECAST', -10);
    ctx.restore();

    return { X, Y, padL, padR, padT, padB };
  }

  function initRevenue() {
    const canvas = document.getElementById('chartRevenue');
    if (!canvas) return;
    let geom = null;
    const render = (t) => { geom = drawRevenue(canvas, t); };

    const animate = () => {
      if (prefersReduced) { render(1); return; }
      const t0 = performance.now(), dur = 1600;
      (function step(now) {
        const t = clamp01((now - t0) / dur);
        render(1 - Math.pow(1 - t, 3));
        if (t < 1) requestAnimationFrame(step);
      })(t0);
    };

    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) { animate(); io.disconnect(); }
    }, { threshold: 0.35 });
    io.observe(canvas);

    // crosshair tooltip
    const tip = makeTooltip(canvas.parentElement);
    canvas.addEventListener('pointermove', (e) => {
      if (!geom) return;
      const r = canvas.getBoundingClientRect();
      const mx = e.clientX - r.left;
      let best = null, bd = 1e9;
      REVENUE.forEach(d => {
        const dx = Math.abs(geom.X(d.year) - mx);
        if (dx < bd) { bd = dx; best = d; }
      });
      if (best && bd < 40) {
        tip.style.opacity = '1';
        tip.style.left = geom.X(best.year) + 'px';
        tip.style.top = geom.Y(best.v) + 'px';
        tip.innerHTML = '<strong style="font-family:JetBrains Mono">' + best.year + '</strong> · $' + best.v + 'B' +
          (best.f ? ' <span style="color:#A99BFF">forecast</span>' : '');
      } else tip.style.opacity = '0';
    });
    canvas.addEventListener('pointerleave', () => { tip.style.opacity = '0'; });

    window.addEventListener('resize', debounce(() => render(1), 200));
  }

  /* ---------- thickness log-scale bars ---------- */
  const LAYERS = [
    { name: 'Gate dielectric', nm: 1.5 },
    { name: 'Diffusion barrier', nm: 3 },
    { name: 'Work-function metal', nm: 5 },
    { name: 'Etch stop layer', nm: 15 },
    { name: 'Hard mask', nm: 80 },
    { name: 'Human hair (for scale)', nm: 70000, hair: true }
  ];

  function drawThickness(canvas, animT) {
    const { ctx, w, h } = setupCanvas(canvas);
    const padL = 8, padR = 20, padT = 8, padB = 34;
    const labelW = Math.min(190, w * 0.34);
    const bx = padL + labelW;
    const iw = w - bx - padR;
    const rowH = (h - padT - padB) / LAYERS.length;
    const barH = Math.min(26, rowH * 0.48);

    const logMin = 0, logMax = Math.log10(100000);
    const W = nm => ((Math.log10(Math.max(nm, 1)) - logMin) / (logMax - logMin)) * iw;

    ctx.clearRect(0, 0, w, h);

    // log gridlines: 1, 10, 100, 1k, 10k, 100k
    ctx.font = MONO;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    [1, 10, 100, 1000, 10000, 100000].forEach(v => {
      const x = bx + W(v);
      ctx.strokeStyle = COLOR.grid;
      ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, h - padB); ctx.stroke();
      ctx.fillStyle = COLOR.text3;
      const lab = v >= 1000 ? (v / 1000) + 'k' : String(v);
      ctx.fillText(lab + (v === 1 ? ' nm' : ''), x, h - padB + 10);
    });

    LAYERS.forEach((d, i) => {
      const y = padT + i * rowH + rowH / 2;
      // label
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.font = '500 13px Inter, sans-serif';
      ctx.fillStyle = d.hair ? COLOR.text : COLOR.text2;
      ctx.fillText(d.name, padL, y);

      // bar (rounded end, thin, baseline-anchored)
      const bw = Math.max(W(d.nm) * animT, 2);
      const grad = ctx.createLinearGradient(bx, 0, bx + bw, 0);
      if (d.hair) {
        grad.addColorStop(0, 'rgba(187,133,59,0.55)');
        grad.addColorStop(1, '#D9944F');
      } else {
        grad.addColorStop(0, 'rgba(43,157,182,0.5)');
        grad.addColorStop(1, COLOR.cyanBright);
      }
      ctx.fillStyle = grad;
      ctx.beginPath();
      const r = Math.min(4, barH / 2);
      ctx.roundRect(bx, y - barH / 2, bw, barH, [0, r, r, 0]);
      ctx.fill();

      // direct value label — inside the bar when it would overflow the plot
      ctx.font = MONO;
      const label = d.nm >= 1000 ? '~70,000 nm' : '~' + d.nm + ' nm';
      const labelW = ctx.measureText(label).width;
      if (bx + bw + 10 + labelW > w - 4) {
        ctx.fillStyle = '#171006';
        ctx.textAlign = 'right';
        ctx.fillText(label, bx + bw - 10, y);
      } else {
        ctx.fillStyle = d.hair ? '#E8BA84' : COLOR.cyanBright;
        ctx.textAlign = 'left';
        ctx.fillText(label, bx + bw + 10, y);
      }
    });

    return { bx, W, rowH, padT, barH };
  }

  function initThickness() {
    const canvas = document.getElementById('chartThickness');
    if (!canvas) return;
    let geom = null;
    const render = t => { geom = drawThickness(canvas, t); };

    const io = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) {
        if (prefersReduced) { render(1); io.disconnect(); return; }
        const t0 = performance.now(), dur = 1400;
        (function step(now) {
          const t = clamp01((now - t0) / dur);
          render(1 - Math.pow(1 - t, 4));
          if (t < 1) requestAnimationFrame(step);
        })(t0);
        io.disconnect();
      }
    }, { threshold: 0.35 });
    io.observe(canvas);

    const tip = makeTooltip(canvas.parentElement);
    canvas.addEventListener('pointermove', (e) => {
      if (!geom) return;
      const r = canvas.getBoundingClientRect();
      const my = e.clientY - r.top;
      const i = Math.floor((my - geom.padT) / geom.rowH);
      if (i >= 0 && i < LAYERS.length) {
        const d = LAYERS[i];
        const y = geom.padT + i * geom.rowH + geom.rowH / 2;
        tip.style.opacity = '1';
        tip.style.left = (geom.bx + geom.W(d.nm) / 2) + 'px';
        tip.style.top = y + 'px';
        tip.innerHTML = '<strong>' + d.name + '</strong> · ' + (d.nm >= 1000 ? '≈70,000 nm' : '≈' + d.nm + ' nm') +
          (d.hair ? '' : ' <span style="color:#77829C">(' + Math.round(70000 / d.nm).toLocaleString() + '× thinner than hair)</span>');
      } else tip.style.opacity = '0';
    });
    canvas.addEventListener('pointerleave', () => { tip.style.opacity = '0'; });
    window.addEventListener('resize', debounce(() => render(1), 200));
  }

  function debounce(fn, ms) {
    let id;
    return (...a) => { clearTimeout(id); id = setTimeout(() => fn(...a), ms); };
  }

  initRevenue();
  initThickness();

  /* ---------------- interview pack form ---------------- */
  const form = document.getElementById('packForm');
  if (form) {
    const hint = document.getElementById('emailHint');
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const email = form.email.value.trim();
      const ok = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
      if (!ok) {
        hint.textContent = 'That email doesn’t look right — check the address and try again.';
        hint.className = 'pack__hint is-error';
        form.email.focus();
        return;
      }
      const btn = form.querySelector('button');
      btn.disabled = true;
      btn.textContent = 'Sending…';
      setTimeout(() => {
        btn.textContent = 'Sent ✓';
        hint.textContent = 'You’re in. The interview pack is on its way to ' + email + '.';
        hint.className = 'pack__hint is-success';
        form.email.value = '';
        setTimeout(() => { btn.disabled = false; btn.textContent = 'Send it'; }, 4000);
      }, 900);
    });
  }
})();
