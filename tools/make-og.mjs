import { chromium } from 'playwright-core';
import sharp from 'sharp';

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--use-angle=swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 2 });
await page.goto('http://localhost:8080/?forcegl=1', { waitUntil: 'networkidle' });
// let fonts + WebGL settle (pump frames — headless draws on demand)
for (let k = 0; k < 40; k++) await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });
// hide the scroll cue & nav for a cleaner card
await page.addStyleTag({ content: '.scroll-cue,.nav{display:none!important}' });
await page.screenshot({ clip: { x: 0, y: 0, width: 2, height: 2 } });
const png = await page.screenshot({ type: 'png' });
await sharp(png).resize(1200, 630).jpeg({ quality: 84 }).toFile('./site/assets/img/og.jpg');
console.log('saved og.jpg');
await browser.close();
