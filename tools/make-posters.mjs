import { chromium } from 'playwright-core';
import sharp from 'sharp';

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1080, height: 810 }, deviceScaleFactor: 2 });
page.on('pageerror', e => console.error('PAGEERROR', e.message));
await page.goto('http://localhost:8081/poster.html');
await page.waitForFunction(() => !!window.API);

const shots = [
  { name: 'poster-wafer',     part: 'hero',  p: 0.08, dark: false, w: 1200, h: 900, wait: 1400 },
  { name: 'poster-deposit',   part: 'craft', p: 0.62, dark: true,  w: 1080, h: 810, wait: 900 },
  { name: 'poster-etch',      part: 'craft', p: 1.60, dark: true,  w: 1080, h: 810, wait: 1600 },
  { name: 'poster-metrology', part: 'craft', p: 2.55, dark: true,  w: 1080, h: 810, wait: 1200 },
  { name: 'poster-stack',     part: 'craft', p: 3.72, dark: true,  w: 1080, h: 810, wait: 1000 },
];

for (const s of shots) {
  await page.setViewportSize({ width: s.w, height: s.h });
  await page.evaluate(({ part, p, dark }) => {
    window.API.resize();
    window.setScene(part, p, dark);
    // keep progress pinned every frame while the rAF loop animates time
    if (window.__pin) cancelAnimationFrame(window.__pin);
    const pin = () => { window.API[part === 'hero' ? 'setHero' : 'setCraft'](p); window.__pin = requestAnimationFrame(pin); };
    if (part === 'hero') { window.API.setCraft(-1); } 
    pin();
  }, s);
  await page.waitForTimeout(s.wait);
  const png = await page.screenshot({ type: 'png' });
  await sharp(png).resize(s.w, s.h).webp({ quality: 82 }).toFile(`./site/assets/img/${s.name}.webp`);
  console.log('saved', s.name);
}
await browser.close();
