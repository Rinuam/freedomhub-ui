import { chromium } from 'playwright-core';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader'] });
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
const logs = [];
page.on('pageerror', e => logs.push('ERR ' + e.message));
await page.goto('http://localhost:8080/?forcegl=1', { waitUntil: 'networkidle' });
for (let k = 0; k < 15; k++) await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });

// mobile menu
await page.click('.nav-toggle');
const menuOpen = await page.evaluate(() => !document.getElementById('mobile-menu').hidden);
await page.screenshot({ path: process.env.SP + '/menu-open.png' });
await page.click('#mobile-menu a[href="#signup"]');
const menuClosed = await page.evaluate(() => document.getElementById('mobile-menu').hidden);
console.log('menu opens:', menuOpen, '| closes on link:', menuClosed);

// scroll to form
await page.evaluate(() => window.__lenis ? window.__lenis.scrollTo('#signup', { immediate: true }) : location.hash = '#signup');
for (let k = 0; k < 25; k++) await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });

// 1 · empty submit
await page.click('.btn-submit');
let s = await page.evaluate(() => ({
  nameErr: !document.getElementById('pf-name-error').hidden,
  emailErr: !document.getElementById('pf-email-error').hidden,
  focused: document.activeElement.id,
}));
console.log('empty submit → name error:', s.nameErr, '| email error:', s.emailErr, '| focus:', s.focused);

// 2 · bad email
await page.fill('#pf-name', 'Test Engineer');
await page.fill('#pf-email', 'not-an-email');
await page.click('.btn-submit');
s = await page.evaluate(() => ({
  emailErr: !document.getElementById('pf-email-error').hidden,
  ariaInvalid: document.getElementById('pf-email').getAttribute('aria-invalid'),
  focused: document.activeElement.id,
}));
console.log('bad email → error shown:', s.emailErr, '| aria-invalid:', s.ariaInvalid, '| focus:', s.focused);
await page.screenshot({ path: process.env.SP + '/form-bad-email.png' });

// 3 · valid (placeholder mode) — button disables, then success
await page.fill('#pf-email', 'test@example.com');
await page.click('.btn-submit');
const disabled = await page.evaluate(() => document.querySelector('.btn-submit').disabled);
await page.waitForTimeout(1300);
await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });
s = await page.evaluate(() => ({
  status: document.getElementById('form-status').textContent,
  cls: document.getElementById('form-status').className,
  nameCleared: document.getElementById('pf-name').value === '',
}));
console.log('valid → disabled while sending:', disabled, '| status:', JSON.stringify(s.status), '| class:', s.cls, '| form reset:', s.nameCleared);
await page.screenshot({ path: process.env.SP + '/form-success.png' });
console.log('page errors:', logs.length ? logs : 'none');
await browser.close();
