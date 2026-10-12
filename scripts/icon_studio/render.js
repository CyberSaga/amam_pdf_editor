// Rasterize SVG files with Playwright Chromium.
// usage: node render.js jobs.json   where jobs = [{svg, out, size, bg}]
function loadPlaywright() {
  // PLAYWRIGHT_MODULE, then a local install, then the global npm root (npm i -g playwright).
  const tries = [process.env.PLAYWRIGHT_MODULE, 'playwright'];
  try { tries.push(require('path').join(require('child_process').execSync('npm root -g').toString().trim(), 'playwright')); } catch (e) { /* no npm */ }
  for (const t of tries.filter(Boolean)) { try { return require(t); } catch (e) { /* try next */ } }
  throw new Error('playwright not found: run `npm i -D playwright` or set PLAYWRIGHT_MODULE');
}
const { chromium } = loadPlaywright();
const fs = require('fs');

(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const j of jobs) {
    const svg = fs.readFileSync(j.svg, 'utf8');
    const size = j.size || 1024;
    const bg = j.bg || 'transparent';
    await page.setViewportSize({ width: size, height: size });
    const b64 = Buffer.from(svg).toString('base64');
    const html = `<!doctype html><html><head><style>html,body{margin:0;padding:0;background:${bg}}img{display:block}</style></head>` +
      `<body><img id="i" width="${size}" height="${size}" src="data:image/svg+xml;base64,${b64}"></body></html>`;
    await page.setContent(html);
    await page.waitForFunction(() => { const i = document.getElementById('i'); return i.complete && i.naturalWidth > 0; });
    await page.screenshot({ path: j.out, clip: { x: 0, y: 0, width: size, height: size }, omitBackground: bg === 'transparent' });
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
