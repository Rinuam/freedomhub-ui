import { chromium } from 'playwright-core';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errs = [];
page.on('pageerror', e => errs.push(e.message));
page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
await page.goto('http://localhost:8081/tfe-live.html?forcegl=1', { waitUntil: 'load' });
for (let k = 0; k < 20; k++) await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });
const state = await page.evaluate(() => ({
  cls: document.documentElement.className,
  fonts: document.fonts.status,
  title: document.title,
}));
await page.screenshot({ path: process.env.SP + '/artifact-check.png' });
console.log(state, 'errors:', errs.length ? errs : 'none');
await browser.close();
