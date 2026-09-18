/** Record actual browser scrolling; freeze an MP4 before offline Short assembly. */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { performance } from 'node:perf_hooks';
import { requestPolicy, validatePlan } from './web_capture_policy.mjs';

const repo = path.resolve(import.meta.dirname, '../../..');
const require = createRequire(path.join(repo, 'templates/motion/package.json'));
const puppeteer = require('puppeteer-core');
const sha256 = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const write = (file, value) => fs.writeFileSync(file, JSON.stringify(value, null, 2), { flag: 'wx' });

async function inventory(page) {
  return page.evaluate(() => ({ title: document.title, url: location.href,
    height: document.documentElement.scrollHeight,
    headings: [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(el => el.getClientRects().length)
      .slice(0, 100).map(el => ({ tag: el.tagName.toLowerCase(), id: el.id,
        text: el.textContent.trim().slice(0, 200), y: Math.round(el.getBoundingClientRect().top + scrollY) })),
  }));
}

async function targetPosition(page, target) {
  return page.evaluate(target => {
    const matches = [...document.querySelectorAll(target.selector)].filter(el => el.getClientRects().length
      && el.textContent.replace(/\s+/gu, ' ').trim() === target.text);
    if (matches.length !== 1) throw new Error(`Target must identify exactly one visible element: ${target.text} (${matches.length})`);
    const rect = matches[0].getBoundingClientRect();
    return { y: Math.max(0, Math.min(document.documentElement.scrollHeight - innerHeight, scrollY + rect.top - target.top)),
      text: matches[0].textContent.trim(), height: rect.height };
  }, target);
}

async function targetVisible(page, target) {
  return page.evaluate(target => {
    const el = [...document.querySelectorAll(target.selector)].find(el => el.getClientRects().length
      && el.textContent.replace(/\s+/gu, ' ').trim() === target.text);
    if (!el) return false;
    const rect = el.getBoundingClientRect(), hit = document.elementFromPoint(
      Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width / 2)), rect.top + rect.height / 2);
    return rect.top >= 0 && rect.bottom <= innerHeight && (hit === el || el.contains(hit));
  }, target);
}

async function settleAt(page, position) {
  await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), position.y);
  await page.waitForNetworkIdle({ idleTime: 500, timeout: 7000 }).catch(() => {});
  const broken = await page.evaluate(() => [...document.images].filter(el => {
    const box = el.getBoundingClientRect();
    return box.width > 8 && box.height > 8 && box.bottom > 0 && box.top < innerHeight
      && getComputedStyle(el).visibility !== 'hidden' && (!el.complete || el.naturalWidth === 0);
  }).map(el => el.currentSrc || el.src));
  if (broken.length) throw new Error(`Visible images are missing or still loading: ${broken.join(', ')}`);
}

async function openPage(browser, plan, evidence) {
  const page = await browser.newPage(), allowed = await requestPolicy(plan);
  await page.setViewport({ width: plan.viewport.width, height: plan.viewport.height, deviceScaleFactor: plan.viewport.scale });
  await page.setBypassServiceWorker(true);
  await page.setRequestInterception(true);
  page.on('request', request => {
    void (async () => {
      if (await allowed(request)) { await request.continue(); return; }
      if (evidence.blocked.length < 80) evidence.blocked.push({ method: request.method(), url: request.url().split('?')[0] });
      await request.abort('blockedbyclient');
    })().catch(error => { evidence.errors.push(error.message); });
  });
  page.on('dialog', dialog => { void dialog.dismiss(); });
  const response = await page.goto(plan.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  evidence.httpStatus = response?.status();
  if (!response?.ok() || !plan.allowedHosts.includes(new URL(page.url()).hostname)
      || !(await page.title()).toLowerCase().includes(plan.expectedTitle.toLowerCase())) {
    throw new Error(`Page identity/status mismatch: ${evidence.httpStatus}, ${await page.title()}`);
  }
  await page.waitForNetworkIdle({ idleTime: 700, timeout: 10000 }).catch(() => {});
  await page.evaluate(() => Promise.race([document.fonts.ready, new Promise(resolve => setTimeout(resolve, 5000))]));
  return page;
}

/** Move the real document on the output frame clock, then let the browser paint. */
async function scrollFrame(page, input) {
  return page.evaluate(async ({ plan, positions, frame }) => {
    const seconds = frame / plan.fps;
    const progress = Math.max(0, Math.min(1, (seconds - plan.holdStart) / (plan.duration - plan.holdStart - plan.holdEnd)));
    const ease = progress * progress * (3 - 2 * progress);
    scrollTo({ top: positions.start.y + (positions.end.y - positions.start.y) * ease, behavior: 'instant' });
    await new Promise(resolve => requestAnimationFrame(resolve));
    return { seconds, y: scrollY };
  }, input);
}

function runTool(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8', timeout: 90000, maxBuffer: 8 * 1024 * 1024 });
  if (result.error || result.status !== 0) throw new Error(`Capture media check failed: ${result.error ?? result.stderr}`);
  return result.stdout;
}

function encode(request, frames, elapsed) {
  const { tools, output, plan } = request, fps = plan.fps;
  const first = frames[0].timestamp, rows = frames.filter(row => row.timestamp - first < elapsed);
  const concat = rows.flatMap((row, index) => [`file 'frames/${row.file}'`,
    `duration ${Math.max(1 / 1000, (rows[index + 1]?.timestamp ?? first + elapsed) - row.timestamp).toFixed(6)}`]);
  concat.push(`file 'frames/${rows.at(-1).file}'`);
  fs.writeFileSync(path.join(output, 'frames.ffconcat'), concat.join('\n'));
  runTool(tools.ffmpeg, ['-v', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-i', path.join(output, 'frames.ffconcat'),
    '-vf', `fps=${fps},scale=${plan.viewport.width * plan.viewport.scale}:${plan.viewport.height * plan.viewport.scale}:flags=lanczos:out_color_matrix=bt709:out_range=tv`,
    '-frames:v', String(Math.round(plan.duration * fps)), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16',
    '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'iec61966-2-1', '-colorspace', 'bt709',
    '-movflags', '+faststart', path.join(output, 'capture.mp4')]);
  const probe = JSON.parse(runTool(tools.ffprobe, ['-v', 'error', '-show_streams', '-show_format', '-of', 'json', path.join(output, 'capture.mp4')]));
  const video = probe.streams.find(row => row.codec_type === 'video');
  if (Number(video?.nb_frames) !== Math.round(plan.duration * fps) || video.width !== plan.viewport.width * plan.viewport.scale
      || video.height !== plan.viewport.height * plan.viewport.scale || probe.streams.length !== 1) throw new Error('Unexpected capture dimensions, frame clock or audio');
  runTool(tools.ffmpeg, ['-v', 'error', '-xerror', '-nostdin', '-i', path.join(output, 'capture.mp4'), '-f', 'null', '-']);
  runTool(tools.ffmpeg, ['-v', 'error', '-nostdin', '-i', path.join(output, 'capture.mp4'), '-vf',
    `select='eq(n,0)+eq(n,${Math.floor(plan.duration * fps / 2)})+eq(n,${Math.round(plan.duration * fps) - 1})'`,
    '-fps_mode', 'vfr', '-frames:v', '3', '-start_number', '0', path.join(output, 'review-%02d.png')]);
  return { width: video.width, height: video.height, fps, frames: Number(video.nb_frames), fullDecode: 'passed' };
}

/** Decode the dimensions of Chrome's baseline/progressive JPEG surface frames. */
function jpegSize(data) {
  if (data.readUInt16BE(0) !== 0xffd8) throw new Error('Invalid JPEG surface frame');
  let offset = 2;
  while (offset + 9 < data.length) {
    const marker = data[offset + 1], length = data.readUInt16BE(offset + 2);
    if ([0xc0, 0xc2].includes(marker)) return [data.readUInt16BE(offset + 7), data.readUInt16BE(offset + 5)];
    if (length < 2) break;
    offset += length + 2;
  }
  throw new Error('JPEG surface has no supported frame dimensions');
}

/** Sample every planned viewport frame; heavy pages cannot silently drop scroll frames. */
async function recordSurface(page, request, positions) {
  const { plan, output } = request, frames = [], samples = [], session = page._client();
  const started = performance.now();
  let bytes = 0;
  for (let frame = 0; frame < Math.round(plan.duration * plan.fps); frame++) {
    samples.push(await scrollFrame(page, { plan, positions, frame }));
    const image = await session.send('Page.captureScreenshot', { format: 'jpeg', quality: 95, fromSurface: true,
      captureBeyondViewport: false, optimizeForSpeed: true });
    const data = Buffer.from(image.data, 'base64'), file = `${String(frame).padStart(5, '0')}.jpg`;
    const [width, height] = jpegSize(data);
    bytes += data.length;
    if (bytes > 512 * 1024 ** 2 || width !== plan.viewport.width * plan.viewport.scale
        || height !== plan.viewport.height * plan.viewport.scale) throw new Error('Capture exceeded frame budget or lost native pixel resolution');
    fs.writeFileSync(path.join(output, 'frames', file), data);
    frames.push({ file, timestamp: frame / plan.fps, wallSeconds: (performance.now() - started) / 1000 });
  }
  return { frames, samples, bytes };
}

async function record(page, request) {
  const { plan, output } = request, directory = path.join(output, 'frames');
  fs.mkdirSync(directory);
  const positions = { start: await targetPosition(page, plan.start), end: await targetPosition(page, plan.end) };
  await settleAt(page, positions.end);
  positions.start = await targetPosition(page, plan.start);
  await settleAt(page, positions.start);
  positions.end = await targetPosition(page, plan.end);
  const distance = positions.end.y - positions.start.y;
  if (Math.abs(distance) < 80 || Math.abs(distance) > plan.viewport.height * 3) throw new Error('Scroll must reveal a distinct nearby section (80px–3 viewport heights)');
  if (!await targetVisible(page, plan.start)) throw new Error('Opening target is obscured or outside the viewport');
  await page.screenshot({ path: path.join(output, 'start.png') });
  const { frames, samples, bytes } = await recordSurface(page, request, positions);
  if (frames.length < 12 || !await targetVisible(page, plan.end)) throw new Error('Capture lacks moving frames or its unobscured result');
  const moved = samples.at(-1).y - samples[0].y;
  if (Math.abs(moved - distance) > 4) throw new Error('Page did not execute the intended scroll');
  await page.screenshot({ path: path.join(output, 'end.png') });
  write(path.join(output, 'scroll-evidence.json'), { positions, samples, surfaceFrames: frames });
  const media = encode(request, frames, plan.duration);
  return { ...media, positions, observedScrollPixels: moved, capturedSourceFrames: frames.length,
    method: 'native-resolution-frame-stepped-browser', nativeResolution: true, capturedSourceBytes: bytes,
    startVisible: true, endVisible: true, holds: { start: plan.holdStart, end: plan.holdEnd } };
}

async function main() {
  const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')), { output, tools } = request;
  const plan = validatePlan(request.plan), started = performance.now();
  const evidence = { schemaVersion: 1, kind: 'public-web-scroll', plan, capturedAt: new Date().toISOString(),
    authenticated: false, pageRestyled: false, blocked: [], errors: [] };
  let browser;
  try {
    browser = await puppeteer.launch({ executablePath: tools.browser, headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking', '--disable-quic', '--force-color-profile=srgb'] });
    const page = await openPage(browser, plan, evidence);
    evidence.page = await inventory(page);
    if (plan.mode === 'inspect' && plan.start) {
      evidence.inspectionPosition = await targetPosition(page, plan.start);
      await settleAt(page, evidence.inspectionPosition);
      if (!await targetVisible(page, plan.start)) throw new Error('Inspection target is obscured');
    }
    await page.screenshot({ path: path.join(output, 'page.png') });
    if (plan.mode === 'capture') {
      evidence.capture = await record(page, request);
      evidence.video = { file: 'capture.mp4', sha256: sha256(path.join(output, 'capture.mp4')) };
    }
    if (evidence.errors.length) throw new Error('Browser request policy encountered errors');
    evidence.status = plan.mode === 'capture' ? 'captured-for-review' : 'inspected';
  } catch (error) {
    evidence.status = 'failed'; evidence.failure = error.stack; process.exitCode = 1;
  } finally {
    if (browser) await browser.close().catch(error => {
      evidence.status = 'failed'; evidence.errors.push(error.message); process.exitCode = 1;
    });
    evidence.elapsedSeconds = (performance.now() - started) / 1000;
    write(path.join(output, 'capture.json'), evidence);
  }
  console.log(JSON.stringify({ status: evidence.status, output, failure: evidence.failure }));
}

await main();
