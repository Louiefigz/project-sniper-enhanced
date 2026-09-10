/* Mounted actual React hook/components against TEST-only launch metadata. No media, providers or real API writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { build } = require('esbuild');
const root = path.resolve(__dirname, '../../../..');
const puppeteer = require(path.join(root, 'templates/motion/node_modules/puppeteer-core'));
const artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'sniper-launch-ui-'));
const result = { scope: 'mounted-test-metadata-only-not-authentic-launch-or-quality', passed: false, events: [], errors: [], artifacts };
const source = `
import React from 'react';
import {createRoot} from 'react-dom/client';
import {GuidedOpeningLaunch} from './src/components/producer/guided-opening-panel';
const root=createRoot(document.getElementById('root'));
const T=window.__test={mode:'eligible',post:'defer',gets:0,posts:[],pending:[],evidence:0};
const H='a'.repeat(64);
const eligible={ok:true,state:'eligible',detail:'TEST-only eligible metadata.',request:{expectedToken:'TEST',expectedJournalHash:H,proposalReadinessHash:H,treatmentDraftRevisionHash:H},receivedAt:null};
const status=()=>T.mode==='eligible'?eligible:{...eligible,state:T.mode,request:null,receivedAt:'2026-09-06T00:00:00.000Z'};
const reply=(body)=>({ok:true,replayed:false,state:'launch-recorded',journalHash:H,requestId:body.submission.idempotencyKey,openingApproved:false,bodyGenerated:false,deliveryApproved:false});
window.fetch=async(url,init)=>{
 if(!String(url).startsWith('/api/producer/guided-opening/launch'))throw Error('Unexpected network surface');
 if(init?.method!=='POST'){T.gets++;return Response.json(status());}
 const body=JSON.parse(init.body);T.posts.push(body);
 if(T.post==='confirm'){T.mode='launch-recorded';return Response.json(reply(body),{status:202});}
 return new Promise((resolve,reject)=>T.pending.push({resolve:()=>resolve(Response.json(reply(body),{status:202})),reject:()=>reject(Error('TEST lost connection'))}));
};
T.mount=(dir)=>root.render(React.createElement(GuidedOpeningLaunch,{key:dir,dir,onEvidenceRefresh:()=>T.evidence++}));
T.mount('/private/tmp/TEST-project-A/producer');
`;

async function ready(page, text) {
  await page.waitForFunction(value => document.body.innerText.includes(value), { timeout: 5000 }, text);
}
async function click(page, text) {
  await page.evaluate(value => {
    const button = [...document.querySelectorAll('button')].find(item => item.textContent === value);
    if (!button) throw Error('Missing button: ' + value); button.click();
  }, text);
}

async function lifecycle(page) {
  await ready(page, 'Generate opening');
  assert.equal(await page.evaluate(() => window.__test.posts.length), 0);
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent === 'Generate opening'); b.click(); b.click(); });
  await page.waitForFunction(() => window.__test.posts.length === 1);
  const first = await page.evaluate(() => window.__test.posts[0]);
  await page.evaluate(() => window.__test.pending[0].reject()); await ready(page, 'Retry saved opening request');
  assert.equal(await page.evaluate(() => window.__test.posts.length), 1);
  result.events.push('mount sends no POST; double click sends one; lost response retains pending request');
  await page.reload({ waitUntil: 'domcontentloaded' }); await ready(page, 'Retry saved opening request');
  assert.equal(await page.evaluate(() => window.__test.posts.length), 0);
  await page.evaluate(() => { window.__test.post = 'confirm'; }); await click(page, 'Retry saved opening request');
  await ready(page, 'Opening launch recorded.');
  const retried = await page.evaluate(() => window.__test.posts[0]); assert.deepEqual(retried, first);
  const before = await page.evaluate(() => ({ gets: window.__test.gets, evidence: window.__test.evidence }));
  await page.waitForFunction(n => window.__test.gets > n, { timeout: 7000 }, before.gets);
  assert.equal(await page.evaluate(() => window.__test.posts.length), 1);
  assert.equal(await page.evaluate(() => window.__test.evidence), before.evidence);
  result.events.push('reload/retry preserves exact UUID and submission; five-second polling is GET-only and not media readback');
  await page.evaluate(() => { window.__test.mode = 'unavailable'; });
  await page.waitForFunction(n => window.__test.evidence > n, { timeout: 7000 }, before.evidence);
  assert.equal(await page.evaluate(() => [...document.querySelectorAll('button')].some(x => x.textContent === 'Generate opening')), false);
  assert.equal(await page.evaluate(() => document.body.innerText.includes('Opening launch recorded.')), false);
  assert.equal(await page.evaluate(() => window.__test.posts.length), 1);
  result.events.push('terminal metadata automatically refreshes evidence, clears sticky launch warning and retains duplicate protection');
}

async function coldTerminal(page) {
  for (const mode of ['failed', 'unavailable']) {
    const before = await page.evaluate(mode => {
      window.__test.mode = mode;
      const before = { evidence: window.__test.evidence, posts: window.__test.posts.length, gets: window.__test.gets };
      window.__test.mount('/private/tmp/TEST-cold-' + mode + '/producer'); return before;
    }, mode);
    await page.waitForFunction(n => window.__test.evidence > n, {}, before.evidence);
    assert.deepEqual(await page.evaluate(() => ({ evidence: window.__test.evidence, posts: window.__test.posts.length,
      gets: window.__test.gets })), { evidence: before.evidence + 1, posts: before.posts, gets: before.gets + 1 });
    assert.equal(await page.evaluate(() => document.body.innerText.includes('Opening launch recorded.')), false);
  }
  result.events.push('cold terminal metadata refreshes potentially stale media evidence exactly once without POST');
}

async function changedProject(page) {
  await page.evaluate(() => { window.__test.mode = 'eligible'; window.__test.post = 'defer'; window.__test.mount('/private/tmp/TEST-project-B/producer'); });
  await ready(page, 'Generate opening'); await click(page, 'Generate opening');
  await page.waitForFunction(() => window.__test.pending.length === 1);
  const old = await page.evaluate(() => window.__test.posts.at(-1));
  await page.evaluate(() => window.__test.mount('/private/tmp/TEST-project-C/producer')); await ready(page, 'Generate opening');
  await page.evaluate(() => window.__test.pending[0].resolve());
  await page.evaluate(() => new Promise(resolve => setTimeout(resolve, 50)));
  assert.equal(await page.evaluate(() => document.body.innerText.includes('Opening launch recorded.')), false);
  const pending = await page.evaluate(dir => sessionStorage.getItem('sniper:opening-launch:v1:' + encodeURIComponent(dir)), old.dir);
  assert.equal(JSON.parse(pending).submission.idempotencyKey, old.submission.idempotencyKey);
  result.events.push('late old-project POST response cannot update new project or erase its preserved old request');
}

async function main() {
  const began = performance.now(); let browser, server;
  try {
    const bundle = await build({ stdin: { contents: source, resolveDir: root, loader: 'tsx' }, bundle: true, write: false, platform: 'browser', format: 'iife', jsx: 'automatic' });
    const html = '<!doctype html><meta charset="utf-8"><div id="root"></div><script>' + bundle.outputFiles[0].text.replace(/<\/script/gi, '<\\/script') + '</script>';
    server = http.createServer((req, res) => { res.setHeader('Content-Type', 'text/html'); res.end(html); });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
    const origin = 'http://127.0.0.1:' + server.address().port;
    browser = await puppeteer.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true,
      args: ['--disable-background-networking', '--no-first-run', '--disable-component-update'] });
    const page = await browser.newPage(); page.on('pageerror', error => result.errors.push(String(error)));
    await page.setRequestInterception(true);
    page.on('request', request => request.url().startsWith(origin) ? request.continue() : request.abort());
    await page.goto(origin, { waitUntil: 'domcontentloaded' });
    await lifecycle(page); await changedProject(page); await coldTerminal(page);
    await page.screenshot({ path: path.join(artifacts, 'launch.png'), fullPage: true });
    assert.deepEqual(result.errors, []); result.passed = true;
  } catch (error) { result.error = String(error.stack ?? error); process.exitCode = 1; }
  finally {
    if (browser) await browser.close(); if (server?.listening) await new Promise(resolve => server.close(resolve));
    result.cleanupVerified = true; result.elapsedMs = performance.now() - began;
    fs.writeFileSync(path.join(artifacts, 'result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result));
  }
}
main();
