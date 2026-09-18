/* Opt-in real headless UI regression; not desktop/manual or final-QC evidence.
 * Runs against the existing isolated Producer server. Creates a NEW synthetic
 * fixture, uses native click/type actions only, keeps evidence, closes browser.
 * Usage: node .../studio_native_ui_regression.cjs WORKSPACE FIXTURE_NUMBER
 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const {performance} = require('node:perf_hooks');

const root = path.resolve(__dirname, '../../..');
const puppeteer = require(path.join(root, 'templates/motion/node_modules/puppeteer-core'));
// Use the browser this install actually pins. An absolute literal here bound the
// harness to one machine's cache and to a build the release no longer uses.
const chrome = process.env.HYPERFRAMES_BROWSER_PATH
  || process.env.PRODUCER_HEADLESS_SHELL_PATH;
if (!chrome) throw new Error('set HYPERFRAMES_BROWSER_PATH to the pinned chrome-headless-shell');
const appOrigin = 'http://localhost:3327';
const started = performance.now();
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'sniper-native-headless-'));
const result = {kind: 'automated-headless-native-studio-ui', syntheticTestOnly: true,
  desktopRetest: false, passed: false, events: [], pageErrors: [], consoleErrors: [],
  blockedRequests: [], badResponses: [], artifacts};
let browser, page, studioOrigin = null, watchdog, closing = false;
const remaining = () => Math.max(1, Math.min(15000, 105000 - (performance.now() - started)));
const record = (name, detail = {}) => {
  const row = {name, elapsedMs: Math.round(performance.now() - started), ...detail};
  result.events.push(row); process.stdout.write(JSON.stringify(row) + '\n');
};
const save = (name, value) => fs.writeFileSync(path.join(artifacts, name), JSON.stringify(value, null, 2), {flag: 'wx'});
const hash = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function cleanup() {
  if (closing) return;
  closing = true;
  clearTimeout(watchdog);
  if (!browser) return;
  const child = browser.process();
  await Promise.race([browser.close().catch(() => {}), sleep(5000)]);
  if (child && child.exitCode === null && child.signalCode === null) {
    child.kill('SIGTERM'); await sleep(1000);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
  }
  result.browserClosed = !child || child.exitCode !== null || child.signalCode !== null;
}

async function screenshot(name) {
  await page.screenshot({path: path.join(artifacts, name + '.png')});
}

async function textClick(frame, text, selector = 'button') {
  await frame.waitForFunction((needle, tag) => [...document.querySelectorAll(tag)]
    .some(node => node.textContent.trim() === needle && node.getBoundingClientRect().width),
  {timeout: remaining()}, text, selector);
  const nodes = await frame.$$(selector);
  for (const node of nodes) {
    const match = await node.evaluate((element, needle) => element.textContent.trim() === needle, text);
    if (match) { await node.click(); return; }
    await node.dispose();
  }
  throw Error(`Visible UI control missing: ${text}`);
}

async function inspect(name) {
  const frames = [];
  for (const frame of page.frames()) {
    frames.push(await frame.evaluate(() => ({url: location.href,
      text: document.body?.innerText?.slice(0, 16000),
      controls: [...document.querySelectorAll('button,input,textarea,[role="textbox"]')].map(node => ({
        tag: node.tagName, text: node.textContent?.trim().slice(0, 100), value: node.value,
        aria: node.getAttribute('aria-label'), placeholder: node.getAttribute('placeholder'),
        title: node.getAttribute('title'), disabled: node.disabled}))})).catch(error => ({error: String(error)})));
  }
  save(name + '.json', frames); await screenshot(name);
}

function createFixture() {
  const workspace = fs.realpathSync(process.argv[2]);
  const number = process.argv[3];
  if (workspace !== '/private/tmp/sniper-ui-qualification.KsUcgq' || !/^[89]$|^[1-9][0-9]+$/.test(number)) throw Error('Explicit isolated fixture number >=8 required');
  const name = `studio-ui-synthetic-${number}`, producer = path.join(workspace, name, 'producer');
  const registry = JSON.parse(fs.readFileSync(path.join(workspace, '.project-sniper/projects.json')));
  if (['--reuse-synthetic-draft', '--verify-imported-preview'].includes(process.argv[4])) {
    const project = JSON.parse(fs.readFileSync(path.join(workspace, name, 'project.json')));
    const plan = JSON.parse(fs.readFileSync(path.join(producer, 'edit_plan.json')));
    if (project.syntheticTestOnly !== true || plan.planVersion !== (process.argv[4] === '--verify-imported-preview' ? 2 : 1)
        || !registry.some(row => row.dir === producer)) throw Error('Reuse requires exact test-only unimported fixture');
    result.fixture = {producerDir: producer, syntheticTestOnly: true, reusedWithoutRewrite: true};
    result.beforePlan = plan; record('fixture-reused-without-rewrite', result.fixture);
    return {name, producer};
  }
  if (fs.existsSync(path.dirname(producer)) || registry.some(row => row.dir === producer)) throw Error('Fixture already exists; never overwrite');
  const child = cp.spawnSync(path.join(root, '.venv/bin/python'),
    [path.join(__dirname, 'fixtures/create_studio_ui_fixture.py'), workspace, name],
    {cwd: root, encoding: 'utf8', timeout: 60000, maxBuffer: 1024 * 1024});
  save('fixture-command.json', {status: child.status, stdout: child.stdout, stderr: child.stderr, error: String(child.error || '')});
  if (child.status !== 0) throw Error('Synthetic fixture setup failed');
  result.fixture = JSON.parse(child.stdout);
  result.beforePlan = JSON.parse(fs.readFileSync(path.join(producer, 'edit_plan.json')));
  record('fixture-created', result.fixture);
  return {name, producer};
}

async function attachNetwork() {
  const session = await page.createCDPSession();
  await session.send('Network.enable');
  await session.send('Network.setBlockedURLs', {urls: ['ws://*', 'wss://*']});
  await page.setBypassServiceWorker(true);
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      const url = new URL(request.url());
      if (['data:', 'blob:', 'about:'].includes(url.protocol)) return request.continue();
      if (url.origin === appOrigin) return request.continue();
      if (!studioOrigin && url.hostname === '127.0.0.1' && /^399[0-9]$/.test(url.port)) {
        for (let count = 0; count < 20 && !studioOrigin; count++) await sleep(50);
      }
      if (url.origin === studioOrigin && url.protocol === 'http:') return request.continue();
      result.blockedRequests.push(request.url()); await request.abort('blockedbyclient');
    } catch (error) { result.consoleErrors.push(String(error)); }
  });
  page.on('response', async response => {
    if (response.status() >= 400) result.badResponses.push({url: response.url(), status: response.status()});
    if (response.url() !== appOrigin + '/api/producer/studio' || response.request().method() !== 'POST') return;
    try {
      const request = JSON.parse(response.request().postData());
      const body = await response.json();
      if (request.dir !== result.fixture.producerDir || body.state !== 'ready') return;
      const url = new URL(body.url);
      if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !/^399[0-9]$/.test(url.port)
          || url.pathname !== '/' || !url.hash.startsWith('#project/')) throw Error('Unexpected Studio URL');
      studioOrigin = url.origin; result.studioStatus = body; record('studio-open-response', {url: body.url});
    } catch (error) { result.pageErrors.push(String(error)); }
  });
}

async function studioFrame() {
  const handle = await page.waitForSelector('iframe[title="HyperFrames Studio timeline"]', {timeout: remaining()});
  const frame = await handle.contentFrame();
  await frame.waitForSelector('button', {timeout: remaining()});
  return frame;
}

async function openProject(name) {
  await page.goto(appOrigin + '/producer', {waitUntil: 'domcontentloaded', timeout: remaining()});
  await page.waitForSelector('button', {timeout: remaining()});
  for (let count = 0; count < 3; count++) {
    const button = await page.$('button[title="Open this project in the Sniper editor"]');
    if (await page.evaluate(needle => document.body.innerText.includes(needle), name)) break;
    const more = await page.$('::-p-text(Show)');
    const buttons = await page.$$('button');
    for (const item of buttons) {
      if (await item.evaluate(node => /^Show \d+ more projects?$/.test(node.textContent.trim()))) { await item.click(); break; }
    }
    await button?.dispose(); await more?.dispose(); await sleep(300);
  }
  await page.waitForFunction(needle => [...document.querySelectorAll('button')].some(node =>
    node.textContent.trim() === needle && node.title === 'Open this project in the Sniper editor'),
  {timeout: remaining()}, `SYNTHETIC · ${name}`);
  await textClick(page, `SYNTHETIC · ${name}`, 'button');
  await textClick(page, 'HyperFrames Studio');
  return studioFrame();
}

async function editNative(frame, text) {
  await textClick(frame, 'gfx-01-text-element', '*');
  await textClick(frame, 'Te Text', '*');
  await textClick(frame, 'Text');
  const field = await frame.waitForSelector('::-p-aria(Content)', {timeout: remaining()});
  await field.click({clickCount: 3}); await page.keyboard.press('Backspace');
  if (await field.evaluate(node => node.value) !== '') throw Error('Native Content field did not clear through keyboard UI');
  await page.keyboard.type(text, {delay: 20});
  if (await field.evaluate(node => node.value) !== text) throw Error('Native Content field readback differs after keyboard typing');
  await textClick(frame, 'Text');
  record('native-copy-ui-edit', {text});
}

async function assertRenderedCopy(expected) {
  const deadline = performance.now() + remaining();
  while (performance.now() < deadline) {
    for (const frame of page.frames()) {
      let value = null;
      try {
        if (!frame.url().includes('__hf_shader_loading=player')) continue;
        value = await frame.evaluate(() => {
          const node = document.getElementById('te-text');
          if (!node) return null;
          const bounds = node.getBoundingClientRect(), style = getComputedStyle(node);
          let effectiveOpacity = 1;
          for (let parent = node; parent; parent = parent.parentElement) {
            const computed = getComputedStyle(parent);
            if (computed.display === 'none' || computed.visibility !== 'visible') effectiveOpacity = 0;
            effectiveOpacity *= Number(computed.opacity);
          }
          return {text: node.textContent, width: bounds.width, height: bounds.height,
            display: style.display, visibility: style.visibility, opacity: style.opacity, effectiveOpacity};
        });
      } catch { /* A native save/remount legitimately detaches the previous player frame. */ }
      if (value?.text === expected && value.width > 0 && value.height > 0) return value;
    }
    await sleep(100);
  }
  throw Error(`Actual preview DOM never displayed expected copy: ${expected}`);
}

async function visiblePlayback(studio, expected, name) {
  return require('./studio_native_ui_repeat.cjs').visiblePlayback(
    {assertRenderedCopy, remaining, sleep, screenshot, record}, studio, expected, name);
}

async function verifyImportedPreview(studio, fixture) {
  const expected = result.beforePlan.graphicsTrack[0].spec.text;
  await textClick(studio, 'gfx-01-text-element', '*');
  result.visibleOpen = await visiblePlayback(studio, expected, '06-visible-open');
  await textClick(studio, 'Master'); await textClick(studio, 'gfx-01-text-element', '*');
  result.visibleRemount = await visiblePlayback(studio, expected, '07-visible-remount');
  await page.reload({waitUntil: 'domcontentloaded', timeout: remaining()});
  studio = await openProject(fixture.name);
  await textClick(studio, 'gfx-01-text-element', '*');
  result.visibleCold = await visiblePlayback(studio, expected, '08-visible-cold-reopen');
  const after = JSON.parse(fs.readFileSync(path.join(fixture.producer, 'edit_plan.json')));
  if (JSON.stringify(after) !== JSON.stringify(result.beforePlan)) throw Error('Playback-only check changed draft');
  result.previewVisualPassed = true;
  result.passed = result.pageErrors.length === 0;
  if (!result.passed) result.error = 'Visible cold-reopen copy passed; blocked runtime dependency errors remain';
}

async function run() {
  const fixture = createFixture();
  browser = await puppeteer.launch({executablePath: chrome, headless: 'shell', timeout: remaining(),
    args: ['--disable-background-networking', '--disable-component-update', '--no-first-run',
      '--disable-default-apps', '--disable-extensions', '--proxy-server=http://127.0.0.1:9',
      '--proxy-bypass-list=localhost;127.0.0.1', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1']});
  result.runtime = {chrome: await browser.version(), puppeteer: require(path.join(root, 'templates/motion/node_modules/puppeteer-core/package.json')).version,
    chromePath: chrome, chromeSha256: hash(chrome), harnessSha256: hash(__filename),
    helperSha256: hash(path.join(__dirname, 'studio_native_ui_repeat.cjs'))};
  page = await browser.newPage(); await page.setViewport({width: 1800, height: 1200});
  page.on('pageerror', error => result.pageErrors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error') result.consoleErrors.push(message.text().slice(0, 500)); });
  await attachNetwork();
  let studio = await openProject(fixture.name);
  await inspect('01-studio-open'); record('studio-mounted');
  if (process.argv[4] === '--verify-imported-preview') return verifyImportedPreview(studio, fixture);
  const copy = 'Review timing clearly';
  await editNative(studio, copy);
  await assertRenderedCopy(copy); await inspect('02-native-copy');
  await textClick(studio, 'Master'); await textClick(studio, 'gfx-01-text-element', '*');
  result.remount = await visiblePlayback(studio, copy, '03-master-remount'); record('master-remount-copy');
  await page.reload({waitUntil: 'domcontentloaded', timeout: remaining()});
  studio = await openProject(fixture.name);
  await textClick(studio, 'gfx-01-text-element', '*');
  result.coldReopen = await visiblePlayback(studio, copy, '04-cold-reopen'); record('cold-reopen-copy');
  await textClick(page, 'Preview Studio changes');
  await textClick(page, 'Apply to Sniper draft');
  await page.waitForFunction(() => document.querySelector('[aria-label="Import Studio changes"]')?.textContent.includes('imported into the Sniper draft'), {timeout: remaining()});
  await inspect('05-draft-import'); record('draft-imported');
  result.afterPlan = JSON.parse(fs.readFileSync(path.join(fixture.producer, 'edit_plan.json')));
  if (result.afterPlan.graphicsTrack[0].spec.text !== copy || result.afterPlan.planVersion !== 2
      || JSON.stringify(result.afterPlan.cutTrack) !== JSON.stringify(result.beforePlan.cutTrack)) throw Error('Canonical draft/readback mismatch');
  result.noFinal = !fs.existsSync(path.join(fixture.producer, 'final.mp4')) && !fs.existsSync(path.join(fixture.producer, '.sniper-qc-approved.json'));
  if (!result.noFinal) throw Error('Unexpected final/approval');
  result.nativeFlowPassed = true;
  await require('./studio_native_ui_repeat.cjs').repeatNativeImport({page, studio, fixture, result,
    editNative, assertRenderedCopy, textClick, screenshot, record, remaining, fs, path});
  result.passed = result.pageErrors.length === 0;
  if (!result.passed) result.error = 'Native edit/cold-reopen/import passed but runtime page errors remain';
}

watchdog = setTimeout(() => { result.error = '105s work deadline expired'; void cleanup(); }, 105000);
run().catch(async error => {
  result.error = String(error.stack || error); record('failed', {error: String(error)});
  if (page && !page.isClosed()) await inspect('failure').catch(() => {});
}).finally(async () => {
  await cleanup(); result.elapsedMs = Math.round(performance.now() - started);
  save('result.json', result); process.stdout.write(JSON.stringify({passed: result.passed, artifacts, elapsedMs: result.elapsedMs, error: result.error}) + '\n');
  process.exitCode = result.passed ? 0 : 1;
});
