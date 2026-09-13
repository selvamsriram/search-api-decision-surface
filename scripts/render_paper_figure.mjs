// Render the self-contained designer figure with its embedded fonts, offline.
// Requires Playwright/Chromium. Set PLAYWRIGHT_MODULE for a bundled runtime.
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import { gunzipSync } from 'node:zlib';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error('Usage: node render_paper_figure.mjs input.html output.png');
const source = await fs.readFile(input, 'utf8');
const match = type => source.match(new RegExp(`<script type="__bundler/${type}">\\s*([\\s\\S]*?)\\s*</script>`));
const template = match('template');
const manifest = match('manifest');
if (!template || !manifest) throw new Error('Expected self-contained designer bundle');
let html = JSON.parse(template[1]);
html = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
  .replace(/<\/?(?:x-dc|helmet)\b[^>]*>/gi, '')
  .replace(/<link\b[^>]*rel="preconnect"[^>]*>/gi, '');
for (const [id, entry] of Object.entries(JSON.parse(manifest[1]))) {
  if (!html.includes(id)) continue;
  let bytes = Buffer.from(entry.data, 'base64');
  if (entry.compressed) bytes = gunzipSync(bytes);
  html = html.replaceAll(id, `data:${entry.mime};base64,${bytes.toString('base64')}`);
}
// Match the original 1400x600 designer canvas with six CSS pixels of padding.
html = html.replace('</head>', '<style>*{box-sizing:border-box}body{margin:0;padding:6px;background:white}body>div{margin:0!important}</style></head>');
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || chromium.executablePath() });
try {
  const page = await browser.newPage({ viewport: { width: 1412, height: 612 }, deviceScaleFactor: 2 });
  await page.route(/^https?:/, route => route.abort());
  await page.setContent(html, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  const fontsReady = await page.evaluate(() => document.fonts.check('600 24px "IBM Plex Mono"') && document.fonts.check('700 28px "IBM Plex Sans"'));
  if (!fontsReady) throw new Error('Designer fonts did not load');
  await page.screenshot({ path: output });
} finally {
  await browser.close();
}
