/* Actual headless app/client lifecycle against explicitly intercepted TEST DTOs.
 * NOT server-selection, creative-quality, listening or approval evidence.
 * node --import tsx THIS_FILE http://localhost:3327 CHROME_PATH PREPARATION_ROOT
 * Existing tiny synthetic core/review MP4s are read, not regenerated/overwritten.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../../..');
const puppeteer = require(path.join(root, 'templates/motion/node_modules/puppeteer-core'));
const {parseGuidedOpeningStatus} = require(path.join(root, 'src/lib/producer/guided-opening-client.ts'));
const origin = process.argv[2], chrome = process.argv[3], preparation = process.argv[4];
assert.match(origin, /^http:\/\/localhost:[0-9]{4,5}$/);
assert.ok(path.isAbsolute(chrome) && fs.statSync(chrome).isFile());
assert.ok(path.isAbsolute(preparation) && fs.statSync(preparation).isDirectory());
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'sniper-opening-ui-'));
const dir = path.join(artifacts, 'TEST-NONEXISTENT-PROJECT', 'producer');
const at = '2026-09-06T00:01:00.000Z', began = performance.now();
const result = {scope: 'intercepted-test-dto-browser-lifecycle-only', syntheticTestOnly: true,
  authenticatedMediaSelection: false, creativeQuality: false, subjectiveListening: false,
  passed: false, artifacts, events: [], pageErrors: [], blocked: [], registryWritesIntercepted: 0};
const state = {mode: 'pending', projectError: false, revision: 0, openingReads: 0, deferred: null};
let browser, page, watchdog;
const identity = {requestId: '11111111-1111-4111-8111-111111111111',
  executionId: '22222222-2222-4222-8222-222222222222', claimHash: '3'.repeat(64)};
const selectionHash = '2'.repeat(64), buffers = {};
const note = (name, detail = {}) => result.events.push({name, elapsedMs: Math.round(performance.now() - began), ...detail});
const remaining = () => Math.max(1, Math.min(12000, 85000 - (performance.now() - began)));
const save = (name, value) => fs.writeFileSync(path.join(artifacts, name), JSON.stringify(value, null, 2), {flag: 'wx'});

function descriptor(range, frames) {
  const file = path.join(preparation, 'execution', range + '.mp4');
  assert.ok(fs.statSync(file).size < 1024 * 1024, 'Only the tiny retained synthetic fixture is allowed');
  const bytes = fs.readFileSync(file), mediaSha256 = crypto.createHash('sha256').update(bytes).digest('hex');
  buffers[range] = bytes;
  return {url: `/api/producer/guided-opening/media?${new URLSearchParams({dir, selectionHash, mediaSha256, range})}`,
    mediaSha256, sizeBytes: bytes.length, width: 160, height: 90, frameRate: '30000/1001',
    videoFrames: frames, startFrame: 0, endFrameExclusive: frames, audioSamples: frames * 16016 / 10};
}
const media = {core: descriptor('core', 10), review: descriptor('review', 110)};

function opening(mode = state.mode) {
  const base = {ok: true, schemaVersion: 1, scope: 'private-opening-not-opening-body-or-delivery-approval', ...identity,
    openingApproved: false, deliveryApproved: false, subjectiveListening: 'not-performed-by-system',
    detail: 'TEST INTERCEPTED RESPONSE. This checks browser behavior, not an authenticated opening render.',
    timing: {generationStartedAt: at, engineElapsedMs: null, cleanupElapsedMs: null, elapsedStatus: 'unavailable', coverage: 'unavailable'}};
  if (mode === 'pending') return {...base, state: 'pending-owned-execution'};
  const timing = {generationStartedAt: at, engineElapsedMs: 60000, cleanupElapsedMs: 1250,
    elapsedStatus: 'completed', coverage: 'recorded-owned-attempt-only'};
  if (mode === 'failed') return {...base, timing, state: 'failed'};
  const selected = mode === 'mismatch' ? {core: {...media.core, width: 162}, review: {...media.review, width: 162}} : media;
  return {...base, timing, state: 'ready-for-review', selectionHash, receiptHash: '4'.repeat(64),
    receiptSha256: '5'.repeat(64), selectionQualifiedAt: '2026-09-06T00:02:01.250Z',
    sourceFreshness: 'not-rechecked-by-status', media: selected,
    journal: {token: 'TEST-guided-job', sha256: '7'.repeat(64)}, approval: null};
}

function projectStatus() {
  return {dir, producerDir: dir, projectRoot: path.dirname(dir), origin: 'raw', intent: null, requestedIntent: null,
    intentDecisions: [], stages: {ingested: true, transcribed: true, plan: true, base: false, final: false},
    segments: [], clipperFiles: [], sourceDir: null, manifestPath: null,
    finalArtifact: {state: 'missing', path: null, reason: null}, palmier: {state: 'no_workspace', detail: 'TEST only'},
    run: {kind: 'auto_edit', status: 'treatment_admitted', phase: 'planning_review', workflowVersion: 2,
      workflowPolicy: 'cut-first', deliveryPolicy: 'mp4-only', startedAt: at,
      updatedAt: new Date(Date.parse(at) + state.revision * 1000).toISOString(),
      controlToken: `test-only-${state.revision}`, message: 'TEST INTERCEPTED v2 checkpoint', events: []}};
}

function json(request, value, status = 200) {
  return request.respond({status, contentType: 'application/json', headers: {'Cache-Control': 'no-store'}, body: JSON.stringify(value)});
}

async function intercept(request) {
  const url = new URL(request.url()), method = request.method();
  if (['data:', 'blob:', 'about:'].includes(url.protocol)) return request.continue();
  if (url.origin !== origin) { result.blocked.push({url: url.href, method}); return request.abort('blockedbyclient'); }
  if (url.pathname === '/api/producer/projects' && method === 'POST') {
    result.registryWritesIntercepted++; return json(request, {ok: true, syntheticTestOnly: true});
  }
  if (!['GET', 'HEAD'].includes(method)) {
    result.blocked.push({url: url.href, method}); return request.abort('blockedbyclient');
  }
  if (url.pathname === '/api/producer/plan') return json(request, {cutTrack: [], graphicsTrack: []});
  if (url.pathname === '/api/producer/project-status') return state.projectError
    ? json(request, {error: 'TEST project status temporarily unavailable'}, 409) : json(request, projectStatus());
  if (url.pathname === '/api/producer/guided-opening/status') {
    state.openingReads++;
    if (state.mode === 'deferred') { state.deferred = request; return; }
    const value = opening(); parseGuidedOpeningStatus(value, dir); return json(request, value);
  }
  if (url.pathname === '/api/producer/guided-opening/media') {
    const range = url.searchParams.get('range'); assert.ok(range === 'core' || range === 'review');
    assert.equal(url.pathname + url.search, media[range].url);
    return request.respond({status: 200, contentType: 'video/mp4', body: buffers[range], headers: {'Cache-Control': 'no-store'}});
  }
  if (url.pathname === '/api/runtime') return json(request, {brain: {provider: 'legacy', model: 'test-only', reasoning: null}});
  if (url.pathname === '/api/producer/projects') return json(request, {projects: []});
  if (url.pathname === '/api/producer/references') return json(request, {references: []});
  if (url.pathname.startsWith('/api/')) { result.blocked.push({url: url.href, method}); return json(request, {error: 'TEST unexpected API'}, 409); }
  return request.continue();
}

async function textWait(text) {
  await page.waitForFunction(needle => document.body.innerText.includes(needle), {timeout: remaining()}, text);
}
async function click(text) {
  const buttons = await page.$$('button');
  for (const button of buttons) {
    if (await button.evaluate((node, label) => node.textContent.trim() === label && !node.disabled, text)) {
      await button.click(); return;
    }
  }
  throw Error('Missing enabled button: ' + text);
}
async function noMedia() {
  assert.equal(await page.$$eval('video,iframe', nodes => nodes.length), 0);
}
async function snapshot(name) {
  save(name + '.json', {text: await page.evaluate(() => document.body.innerText), openingReads: state.openingReads});
  await page.screenshot({path: path.join(artifacts, name + '.png'), fullPage: true});
}

async function checkPlayback() {
  state.mode = 'ready'; await click('Recheck opening evidence');
  await textWait('Playback metadata matches.');
  assert.equal(await page.$eval('video', video => new URL(video.currentSrc).searchParams.get('range')), 'review');
  assert.deepEqual(await page.$eval('video', video => ({muted: video.muted, autoplay: video.autoplay, width: video.videoWidth, height: video.videoHeight})),
    {muted: false, autoplay: false, width: 160, height: 90});
  await page.$eval('video', video => video.play());
  await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1, {timeout: remaining()});
  await page.$eval('video', video => video.pause());
  await snapshot('ready-context'); note('actual-retained-tiny-mp4-decoded-and-played');
  await click('Opening only'); await textWait('Playback metadata matches.');
  assert.equal(await page.$eval('video', video => new URL(video.currentSrc).searchParams.get('range')), 'core');
  state.mode = 'mismatch'; await click('Recheck opening evidence');
  await textWait('Playback dimensions or duration do not match');
  assert.equal(await page.$eval('video', video => video.paused), true);
  await snapshot('metadata-mismatch'); note('actual-metadata-mismatch-stays-unapproved');
}

async function checkRecheckLifecycle() {
  state.mode = 'deferred'; await click('Recheck opening evidence');
  await textWait('Checking opening state and current evidence'); await noMedia();
  await page.waitForFunction(() => !!document.querySelector('section[aria-label="HyperFrames opening review"]'), {timeout: remaining()});
  while (!state.deferred && performance.now() - began < 80000) await new Promise(resolve => setTimeout(resolve, 25));
  assert.ok(state.deferred);
  const old = state.deferred; state.deferred = null; state.mode = 'pending'; state.revision++;
  await click('Recheck project status'); await textWait('Opening execution outcome is not yet verified'); await noMedia();
  await json(old, opening('ready')).catch(() => {});
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await noMedia(); await textWait('Opening execution outcome is not yet verified');
  note('late-old-readback-cannot-reopen-after-current-journal-key-change');
  state.mode = 'failed'; await click('Recheck opening evidence');
  await textWait('Opening attempt failed'); await noMedia();
  state.projectError = true; await click('Recheck project status');
  await textWait('Opening playback is hidden until status is current again'); await noMedia();
  assert.equal(await page.$('section[aria-label="HyperFrames opening review"]'), null);
  await snapshot('project-read-failed'); note('failed-project-read-hides-opening');
}

async function closeBrowser() {
  clearTimeout(watchdog);
  if (!browser) { result.browserClosed = true; return; }
  const child = browser.process();
  let deadline;
  try {
    await Promise.race([browser.close().catch(() => {}), new Promise(resolve => { deadline = setTimeout(resolve, 5000); })]);
  } finally { clearTimeout(deadline); }
  if (child && child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  if (child && child.exitCode === null && child.signalCode === null) await new Promise(resolve => {
    const ended = () => { clearTimeout(timer); child.removeListener('exit', ended); resolve(); };
    const timer = setTimeout(ended, 1000); child.once('exit', ended);
  });
  result.browserClosed = !child || child.exitCode !== null || child.signalCode !== null;
}

(async () => {
  try {
    browser = await puppeteer.launch({executablePath: chrome, headless: true, timeout: 15000});
    watchdog = setTimeout(() => { result.watchdog = true; void closeBrowser(); }, 90000);
    page = await browser.newPage(); await page.setViewport({width: 1280, height: 1000});
    page.on('pageerror', error => result.pageErrors.push(String(error)));
    await page.setBypassServiceWorker(true); await page.setRequestInterception(true);
    page.on('request', request => void intercept(request).catch(error => { result.pageErrors.push(String(error)); void request.abort().catch(() => {}); }));
    await page.goto(`${origin}/producer?${new URLSearchParams({open: dir})}`, {waitUntil: 'domcontentloaded', timeout: remaining()});
    await textWait('Opening execution outcome is not yet verified'); await noMedia();
    note('real-editor-mounted-read-only-checkpoint'); await snapshot('pending');
    await checkPlayback(); await checkRecheckLifecycle();
    assert.deepEqual(result.pageErrors, []);
    assert.equal(result.blocked.filter(row => row.method !== 'GET' && row.method !== 'HEAD').length, 0);
    assert.equal(fs.existsSync(dir), false, 'No fake project or approval may be written to disk');
    result.passed = true;
  } catch (error) {
    result.error = String(error); process.exitCode = 1;
    if (page) await snapshot('failed').catch(() => {});
  } finally {
    await closeBrowser(); result.elapsedMs = performance.now() - began; result.openingReads = state.openingReads;
    if (!result.browserClosed) { result.passed = false; result.error = 'Owned browser stop not observed'; process.exitCode = 1; }
    save('result.json', result); console.log(JSON.stringify({artifacts, passed: result.passed, elapsedMs: result.elapsedMs, error: result.error}));
  }
})();
