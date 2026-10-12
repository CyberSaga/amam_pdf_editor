// Deterministic frame capture of player.html -> MP4 via ffmpeg.
function loadPlaywright() {
  // PLAYWRIGHT_MODULE, then a local install, then the global npm root (npm i -g playwright).
  const tries = [process.env.PLAYWRIGHT_MODULE, 'playwright'];
  try { tries.push(require('path').join(require('child_process').execSync('npm root -g').toString().trim(), 'playwright')); } catch (e) { /* no npm */ }
  for (const t of tries.filter(Boolean)) { try { return require(t); } catch (e) { /* try next */ } }
  throw new Error('playwright not found: run `npm i -D playwright` or set PLAYWRIGHT_MODULE');
}
const { chromium } = loadPlaywright();
const { spawn } = require('child_process');
const FPS = 30;
(async () => {
  const [html, out] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  await page.goto(require('url').pathToFileURL(html).href + '?capture=1');
  const total = await page.evaluate(() => window.TOTAL);
  const frames = Math.ceil(total * FPS);
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-c:v', 'mjpeg', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out],
    { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = 0; f < frames; f++) {
    await page.evaluate(t => window.renderAt(t), f / FPS);
    await page.evaluate(() => window.__waitImages());
    const buf = await page.screenshot({ type: 'jpeg', quality: 92 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (f % 600 === 0) console.log(`frame ${f}/${frames}  ${((Date.now() - t0) / 1000).toFixed(0)}s`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  console.log('done', frames, 'frames in', ((Date.now() - t0) / 1000).toFixed(0), 's; errors:', errs.slice(0, 3));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
