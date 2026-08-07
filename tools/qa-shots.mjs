import { chromium } from 'playwright-core';
import { mkdirSync } from 'fs';

const OUT = process.env.QA_OUT || '/tmp/qa';
mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader'] });

const errors = [];
async function newPage(vw, vh, reduced = false) {
  const ctx = await browser.newContext({
    viewport: { width: vw, height: vh },
    deviceScaleFactor: 1,
    reducedMotion: reduced ? 'reduce' : 'no-preference',
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(`[${vw}x${vh}${reduced ? ' rm' : ''}] ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`[console ${vw}x${vh}] ${m.text()}`); });
  await page.goto('http://localhost:8080/?forcegl=1', { waitUntil: 'networkidle' });
  for (let k = 0; k < 20; k++) await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });
  return { ctx, page };
}

const stops = [
  ['hero', 0], ['numbers-1', 0.42], ['numbers-2', 0.52], ['gap', 0.62], ['curriculum', 0.72],
  ['scale', 0.80], ['careers', 0.86], ['signup', 0.93], ['footer', 1],
];

const VIEWPORTS = process.env.QA_VP ? JSON.parse(process.env.QA_VP) : [[1440, 900], [390, 844], [768, 1024], [1920, 1080], [360, 740], [1024, 768]];
for (const [vw, vh] of VIEWPORTS) {
  const { ctx, page } = await newPage(vw, vh);
  const H = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  // headless only draws frames on demand — pump frames so Lenis + scrub settle
  const pump = async (n) => {
    for (let k = 0; k < n; k++) await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });
  };
  const jump = async (y) => {
    await page.evaluate((y) => {
      if (window.__lenis) window.__lenis.scrollTo(y, { immediate: true });
      else scrollTo(0, y);
    }, Math.round(y));
    await pump(24);
  };
  // craft scenes: positions relative to the pinned section
  const pin = await page.evaluate(() => {
    const el = document.querySelector('.craft-pin');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { top: r.top + scrollY, len: innerHeight * 4 };
  });
  for (const [name, f] of stops) {
    await jump(H * f);
    await page.screenshot({ path: `${OUT}/${vw}x${vh}-${name}.png` });
  }
  if (pin) {
    for (let i = 0; i < 4; i++) {
      await jump(pin.top + ((i + 0.45) / 4) * pin.len);
      await pump(6);
      await page.screenshot({ path: `${OUT}/${vw}x${vh}-craft-${i + 1}.png` });
    }
  }
  await ctx.close();
}

{
  const { ctx, page } = await newPage(1440, 900, true);
  await page.screenshot({ path: `${OUT}/reduced-full.png`, fullPage: true });
  await ctx.close();
}
{
  const { ctx, page } = await newPage(390, 844, true);
  await page.screenshot({ path: `${OUT}/reduced-mobile-full.png`, fullPage: true });
  await ctx.close();
}

console.log('errors:', errors.length ? errors : 'none');
await browser.close();
