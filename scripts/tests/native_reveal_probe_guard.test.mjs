/**
 * Runtime reveal probe (P2-03, M-068): the CLI's owned-inspection guard (review X128 m4) and the in-page element
 * read (D-B keys and outermost-first ancestors, m5). TEST records in temporary folders and a linkedom document;
 * no browser, owned inspection or child process runs here (G17).
 */
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {after, test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {parseHTML} from 'linkedom';
import {assertRevealProbeOwner, readRevealElements} from '../producer/studio/native_reveal_probe.mjs';

/** The worker the probe's owner must run: `native_reveal_probe.py --worker <request>`. */
const WORKER = fileURLToPath(new URL('../producer/studio/native_reveal_probe.py', import.meta.url));
/** A PID no process holds (above macOS's PID range). */
const DEAD_PID = '2147483647';

/** Every temporary folder a test makes; all are removed when the file's tests end. */
const folders = [];
after(() => folders.forEach(folder => fs.rmSync(folder, {recursive: true, force: true})));

/** One owned inspection's request and a matching live owner record, in a new temporary folder. */
function inspection() {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'sniper-reveal-owner-')));
  folders.push(directory);
  const file = path.join(directory, 'request.json'), owner = path.join(directory, 'inspection.render.json');
  fs.writeFileSync(file, JSON.stringify({project: '/TEST/probe-project', runtime: '/TEST/runtime'}));
  const pin = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  const record = {project: '/TEST/probe-project', status: 'running', output: path.join(directory, 'result.json'),
    additionalFilePinsBefore: {[file]: pin}, args: [process.execPath, '-B', WORKER, '--worker', file]};
  const live = {SNIPER_INSPECTION_REQUEST: file, SNIPER_INSPECTION_OWNER: owner, SNIPER_INSPECTION_PID: String(process.pid)};
  return {directory, file, owner, record, live};
}

/** The guard's verdict on `record` written as the owner, under `environment`. */
function admit(value, record, environment = value.live, file = value.file) {
  fs.writeFileSync(value.owner, JSON.stringify(record));
  return () => assertRevealProbeOwner(file, environment);
}

test('the CLI admits only its own live owned inspection and returns the checked request', () => {
  const value = inspection();
  assert.deepEqual(admit(value, value.record)(), {project: '/TEST/probe-project', runtime: '/TEST/runtime'});
});

test('the guard refuses a detached, moved or unsafe request', () => {
  const value = inspection(), {record, live, directory} = value;
  assert.throws(admit(value, record, {}), /runs only inside its owned inspection/);
  assert.throws(admit(value, record, {...live, SNIPER_INSPECTION_OWNER: path.join(directory, 'other.render.json')}),
    /runs only inside its owned inspection/);
  const relative = path.relative(process.cwd(), value.file);
  assert.throws(admit(value, record, {...live, SNIPER_INSPECTION_REQUEST: relative,
    SNIPER_INSPECTION_OWNER: path.join(path.dirname(relative), 'inspection.render.json')}, relative),
  /missing absolute owner\/request path/);
  const link = path.join(directory, 'linked', 'request.json');
  fs.mkdirSync(path.dirname(link));
  fs.symlinkSync(value.file, link);  // a link to the TEST request JSON only
  fs.copyFileSync(value.owner, path.join(directory, 'linked', 'inspection.render.json'));
  assert.throws(admit(value, record, {...live, SNIPER_INSPECTION_REQUEST: link,
    SNIPER_INSPECTION_OWNER: path.join(directory, 'linked', 'inspection.render.json')}, link), /unsafe owner\/request file/);
});

test('the guard refuses a missing or dead supervisor', () => {
  const value = inspection();
  assert.throws(admit(value, value.record, {...value.live, SNIPER_INSPECTION_PID: '1'}), /no live supervisor/);
  assert.throws(admit(value, value.record, {...value.live, SNIPER_INSPECTION_PID: ''}), /no live supervisor/);
  assert.throws(admit(value, value.record, {...value.live, SNIPER_INSPECTION_PID: DEAD_PID}), {code: 'ESRCH'});
});

test('the guard refuses an owner that is not active or does not bind this request', () => {
  const value = inspection(), {record, file, directory} = value;
  for (const changed of [{completedAt: 'TEST'}, {abortReason: 'TEST'}, {status: 'failed'}, {project: '/TEST/another'},
    {additionalFilePinsBefore: {[file]: '0'.repeat(64)}}, {output: path.join(directory, 'other.json')}]) {
    assert.throws(admit(value, {...record, ...changed}), /does not bind this request/, JSON.stringify(changed));
  }
});

test('the guard refuses an inspection that runs any other worker or request', () => {
  const value = inspection(), {record, file} = value;
  for (const args of [[process.execPath, '-B', path.join(path.dirname(WORKER), 'ordinary_previews.py'), '--worker', file],
    [process.execPath, '-B', WORKER, '--worker', `${file}.other`], ['python3', '-B', WORKER, '--worker', file],
    ['/usr/bin/sandbox-exec', '-f', 'TEST.sb', process.execPath, WORKER, file, 'capture'], undefined]) {
    assert.throws(admit(value, {...record, args}), /did not originate from the reveal probe worker/, JSON.stringify(args));
  }
});

/** Run `read(mountId)` against a linkedom document of `markup`, with each element's `data-o` as its opacity. */
function readIn(markup, mountId) {
  const {document} = parseHTML(`<html><body><div id="native-canvas">${markup}</div></body></html>`);
  const globals = {document: globalThis.document, window: globalThis.window};
  Object.assign(globalThis, {document, window: {__sniperRevealOpacity: el => Number(el.getAttribute('data-o') ?? 0.5)}});
  try {
    return readRevealElements(mountId);
  } finally {
    Object.assign(globalThis, globals);
  }
}

test('the in-page read keys elements by data-hf-id or index path, ancestors inside the host only', () => {
  const markup = '<div id="sn-x" data-hf-id="hf-host"><div data-hf-id="hf-panel" data-o="1"><span>42</span> users '
    + '<i data-o="0"></i></div><p>Plain</p></div>';
  assert.deepEqual(readIn(markup, 'sn-x'), [
    {key: 'hf-panel', opacity: 1, ancestors: [], text: 'users'},
    {key: 'path:0.0', opacity: 0.5, ancestors: ['hf-panel'], text: '42'},
    {key: 'path:0.1', opacity: 0, ancestors: ['hf-panel'], text: ''},
    {key: 'path:1', opacity: 0.5, ancestors: [], text: 'Plain'}]);
  assert.equal(readIn(markup, 'sn-missing'), null);
});

test('ancestors run outermost first, three deep (D-B)', () => {
  const markup = '<div id="sn-x"><section data-hf-id="a"><div><span data-hf-id="c">x</span></div></section></div>';
  assert.deepEqual(readIn(markup, 'sn-x').map(row => [row.key, row.ancestors]), [
    ['a', []], ['path:0.0', ['a']], ['c', ['a', 'path:0.0']]]);
});
