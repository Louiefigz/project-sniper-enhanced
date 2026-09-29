/**
 * Runtime reveal probe (P2-03, M-068) with its one capture step injected: synthetic frames only.
 *
 * No browser, capture context, owned inspection, render or decode runs here (G17). Each injected capture returns
 * what the renderer's session would read, per planned session and frame; the runs that need the real capture are
 * listed in the lane hand-over and run at M-068's integration. The two X72 cases (a matching animation whose first
 * keyframe is visible; `all: unset`) are ones the static rule accepts (native-reveal-probe-project.test.ts proves
 * that for the same CSS); here the runtime state Chrome computes for them is injected and the probe must block.
 */
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {after, test} from 'node:test';
import {parseHTML} from 'linkedom';
import {probeFramePlan} from '../producer/studio/native_reveal_conditions.mjs';
import {assertRevealProbeOwner, probeSessions, readProbeManifest, readRevealElements, runRevealProbe}
  from '../producer/studio/native_reveal_probe.mjs';

const TITLE = {id: 'sn-title-q1', compositionId: 'title', file: 'compositions/title-q1.html', start: 0, duration: 4.8,
  variables: {}, first: 0, endExclusive: 144};
/** run-1 Q1's numbers mount: 24.833333333333332 s + 11.4 s at 30 fps is root frames [745, 1087). */
const NUMBERS = {id: 'sn-numbers-q1', compositionId: 'numbers', file: 'compositions/numbers-q1.html',
  start: 24.833333333333332, duration: 11.4, variables: {}, first: 745, endExclusive: 1087};
/** `hf-later` reveals at 2.7 s: mount-local frame 81. */
const LATER = {mountId: NUMBERS.id, file: NUMBERS.file, hfId: 'hf-later', cue: '2.7', cueSeconds: 2.7, cueLocalFrame: 81};

/** Every temporary folder a test makes; all are removed when the file's tests end. */
const folders = [];
after(() => folders.forEach(folder => fs.rmSync(folder, {recursive: true, force: true})));

/** A new temporary folder, removed after the run. */
function folder(prefix) {
  const made = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), prefix)));
  folders.push(made);
  return made;
}

/** A new probe project folder holding only its manifest. */
function project(mounts, declarations) {
  const directory = folder('sniper-reveal-probe-');
  const manifest = {schemaVersion: 1, source: {plan: '/TEST/plan.json', sha256: '0'.repeat(64)}, rate: 30,
    totalFrames: 1447, mounts, declarations};
  fs.writeFileSync(path.join(directory, 'REVEAL-PROBE.json'), JSON.stringify(manifest));
  return directory;
}

/** One element as the in-page read returns it. */
function element(key, opacity, ancestors = [], text = '') {
  return {key, opacity, ancestors, text};
}

/**
 * The injected capture: `state(spec, local)` gives the elements seen at a mount-local frame of a planned session.
 * Every screenshot is one TEST file under `<output>/capture`, where the real sessions keep theirs.
 */
function capture(state, calls = []) {
  return async (request, sessions) => {
    calls.push(sessions);
    const shot = path.join(request.output, 'capture', 'TEST-frame.jpg'), first = new Map([[TITLE.id, 0], [NUMBERS.id, 745]]);
    fs.mkdirSync(path.dirname(shot));
    fs.writeFileSync(shot, 'TEST jpeg bytes; nothing was captured');
    return {runtimeLibrarySha256: 'a'.repeat(64), compiledSha256: 'b'.repeat(64), sessions: sessions.map(spec => ({
      mount: spec.mount, order: spec.order, transport: {errors: 0},
      frames: spec.frames.map(frame => ({frame, screenshot: shot, elements: state(spec, frame - first.get(spec.mount))}))}))};
  };
}

/** Run the probe on a new project with `state` injected; returns the report and the output folder. */
async function probe(mounts, declarations, state, calls) {
  const directory = project(mounts, declarations), output = path.join(directory, 'out');
  const report = await runRevealProbe({probeProject: directory, output, runtime: '/TEST/runtime'}, capture(state, calls));
  return {report, output};
}

/** The numbers panel as run-1 Q1 drew it: `tl.set(panel, {opacity: 0}, 0)` does not render at exactly time 0. */
function numbersPanel(spec, local) {
  const shown = local === 0 && spec.order !== 'reverse';
  return [element('hf-panel', shown ? 1 : 0, [], 'Numbers'), element('path:0.0', shown ? 1 : 0, ['hf-panel'], '42')];
}

test('probe sessions follow probeFramePlan: per mount, forward, reverse, then each cold sequence', () => {
  const sessions = probeSessions({rate: 30, mounts: [TITLE, NUMBERS], declarations: [LATER]});
  const title = probeFramePlan(TITLE, [], 30), numbers = probeFramePlan(NUMBERS, [LATER], 30);
  assert.deepEqual(sessions, [
    {mount: TITLE.id, order: 'forward', frames: title.forward}, {mount: TITLE.id, order: 'reverse', frames: title.reverse},
    ...title.cold.map((frames, index) => ({mount: TITLE.id, order: `cold-${index}`, frames})),
    {mount: NUMBERS.id, order: 'forward', frames: numbers.forward}, {mount: NUMBERS.id, order: 'reverse', frames: numbers.reverse},
    ...numbers.cold.map((frames, index) => ({mount: NUMBERS.id, order: `cold-${index}`, frames}))]);
  assert.deepEqual(numbers.cold, [[745, 746], [825, 826, 827]]);
  assert.equal(numbers.forward[0], 744);
});

test('the series keeps exactly the D-B shape, with local frames counted from the mount', async () => {
  const {report} = await probe([NUMBERS], [], () => [{...element('hf-panel', 0, [], 'Numbers'), extra: 'TEST'}]);
  assert.equal(report.status, 'reveal-probe-pass');
  for (const row of report.series) {
    assert.deepEqual(Object.keys(row), ['order', 'mount', 'frame', 'localFrame', 'elements']);
    assert.equal(row.frame - row.localFrame, 745);
    assert.deepEqual(row.elements, [{key: 'hf-panel', opacity: 0, ancestors: []}]);
  }
  assert.deepEqual(report.series[0], {order: 'forward', mount: NUMBERS.id, frame: 744, localFrame: -1,
    elements: [{key: 'hf-panel', opacity: 0, ancestors: []}]});
  assert.deepEqual([...new Set(report.series.map(row => row.order))], ['forward', 'reverse', 'cold-0']);
});

test('run-1 Q1: the first-frame flash blocks in every order that shows it; evidence is kept', async () => {
  const {report, output} = await probe([NUMBERS], [], numbersPanel);
  assert.equal(report.status, 'premature-reveal-found');
  assert.deepEqual(report.findings.map(row => [row.condition, row.element, row.frame, row.localFrame, row.order, row.opacity]), [
    ['first-frame-flash', 'hf-panel', 745, 0, 'cold-0', [1, 0]], ['first-frame-flash', 'hf-panel', 745, 0, 'forward', [1, 0]]]);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(output, 'reveal-probe.json'), 'utf8')), report);
  assert.deepEqual(Object.keys(report), ['schemaVersion', 'scope', 'status', 'runtimeLibrarySha256', 'compiledSha256',
    'series', 'findings', 'visibleAtMount']);
  const shot = path.join(output, 'mount-first-0.jpg');
  assert.deepEqual(report.visibleAtMount, [{mount: NUMBERS.id, frame: 745,
    elements: [{key: 'hf-panel', text: 'Numbers'}, {key: 'path:0.0', text: '42'}],
    screenshot: {file: 'mount-first-0.jpg', sha256: crypto.createHash('sha256').update(fs.readFileSync(shot)).digest('hex')}}]);
});

test('X72: a matching animation whose first keyframe is visible is caught at runtime', async () => {
  // Composition CSS the static rule accepts: `#numbers .later{opacity:0;animation:pop .5s linear 0s both}` with
  // `@keyframes pop{from{opacity:1}to{opacity:0}}`. The backwards fill shows the first keyframe from the mount's
  // first frame, fading over 15 frames; the GSAP cue at frame 81 then fades the element in from 0.
  // Local -1 is the inactive neighbour. `cold-0` never samples the cue, so its "after" value is null.
  const later = local => (local < 0 ? 0 : local < 15 ? 1 - local / 15 : local < 81 ? 0 : Math.min(1, (local - 81) / 10));
  const {report} = await probe([NUMBERS], [LATER], (spec, local) => [element('hf-later', later(local), [], 'later')]);
  assert.equal(report.status, 'premature-reveal-found');
  assert.deepEqual(report.findings.map(row => [row.condition, row.element, row.localFrame, row.order, row.opacity]), [
    ['visible-before-reveal', 'hf-later', 0, 'cold-0', [1, null]], ['visible-before-reveal', 'hf-later', 0, 'forward', [1, 0]],
    ['visible-before-reveal', 'hf-later', 0, 'reverse', [1, 0]]]);
});

test('X72: all:unset re-showing a hidden declared element is caught at runtime', async () => {
  // Composition CSS the static rule accepts: `#numbers .later{opacity:0}` and a later `#numbers .stat{all:unset}` on
  // the same element. `all` resets opacity to 1, so the element shows until the cue's inline tween starts from 0.
  const later = local => (local < 0 ? 0 : local < 81 ? 1 : Math.min(1, (local - 81) / 10));
  const {report} = await probe([NUMBERS], [LATER], (spec, local) => [
    element('hf-numbers', local < 0 ? 0 : 1), element('hf-later', later(local), ['hf-numbers'], 'later')]);
  assert.equal(report.status, 'premature-reveal-found');
  assert.deepEqual(report.findings.map(row => [row.condition, row.element, row.localFrame, row.order, row.opacity]), [
    ['visible-before-reveal', 'hf-later', 0, 'cold-0', [1, null]], ['visible-before-reveal', 'hf-later', 80, 'cold-1', [1, 0]],
    ['visible-before-reveal', 'hf-later', 0, 'forward', [1, 0]], ['visible-before-reveal', 'hf-later', 0, 'reverse', [1, 0]]]);
});

test('each seek order is evaluated on its own (E-R1, E-R2)', async () => {
  const {report} = await probe([NUMBERS], [LATER], (spec, local) => [
    element('hf-panel', spec.order === 'cold-0' && local === 0 ? 1 : 0),
    element('hf-later', spec.order === 'reverse' && local === 60 ? 0.5 : local >= 81 ? 1 : 0)]);
  assert.deepEqual(report.findings.map(row => [row.condition, row.element, row.localFrame, row.order, row.opacity]), [
    ['first-frame-flash', 'hf-panel', 0, 'cold-0', [1, 0]], ['visible-before-reveal', 'hf-later', 60, 'reverse', [0.5, 1]]]);
});

test('a capture that differs from its plan fails closed and writes no report', async () => {
  const cases = [
    [(request, sessions) => capture(numbersPanel)(request, sessions.slice(1)), /session count/],
    [async (request, sessions) => {
      const value = await capture(numbersPanel)(request, sessions);
      value.sessions[0].frames.reverse();
      return value;
    }, /differs from its plan: forward sn-numbers-q1/],
    [async (request, sessions) => ({...await capture(numbersPanel)(request, sessions), compiledSha256: 'TEST'}), /runtime identity/],
    [(request, sessions) => capture(() => [element('hf-panel', Number.NaN)])(request, sessions), /Reveal series malformed/],
    [(request, sessions) => capture(() => null)(request, sessions), /differs from its plan/],
  ];
  for (const [injected, message] of cases) {
    const directory = project([NUMBERS], []), output = path.join(directory, 'out');
    await assert.rejects(runRevealProbe({probeProject: directory, output, runtime: '/TEST/runtime'}, injected), message);
    assert.equal(fs.existsSync(path.join(output, 'reveal-probe.json')), false);
  }
});

test('an existing output is refused before any capture; a manifest must name its mounts', async () => {
  const directory = project([NUMBERS], []), output = path.join(directory, 'out'), calls = [];
  fs.mkdirSync(output);
  await assert.rejects(runRevealProbe({probeProject: directory, output, runtime: '/TEST/runtime'}, capture(numbersPanel, calls)),
    /EEXIST/);
  assert.equal(calls.length, 0);
  assert.throws(() => readProbeManifest(project([NUMBERS], [{...LATER, mountId: 'sn-other'}])), /manifest is malformed/);
  assert.throws(() => readProbeManifest(project([], [])), /manifest is malformed/);
});

test('the in-page read keys elements by data-hf-id or index path, ancestors inside the host only', () => {
  const {document} = parseHTML('<html><body><div id="native-canvas"><div id="sn-x" data-hf-id="hf-host">'
    + '<div data-hf-id="hf-panel" data-o="1"><span>42</span> users <i data-o="0"></i></div><p>Plain</p></div></div></body></html>');
  const globals = {document: globalThis.document, window: globalThis.window};
  Object.assign(globalThis, {document, window: {__sniperRevealOpacity: el => Number(el.getAttribute('data-o') ?? 0.5)}});
  try {
    assert.deepEqual(readRevealElements('sn-x'), [
      {key: 'hf-panel', opacity: 1, ancestors: [], text: 'users'},
      {key: 'path:0.0', opacity: 0.5, ancestors: ['hf-panel'], text: '42'},
      {key: 'path:0.1', opacity: 0, ancestors: ['hf-panel'], text: ''},
      {key: 'path:1', opacity: 0.5, ancestors: [], text: 'Plain'}]);
    assert.equal(readRevealElements('sn-missing'), null);
  } finally {
    Object.assign(globalThis, globals);
  }
});

test('the CLI runs only inside its owned inspection', () => {
  const directory = folder('sniper-reveal-owner-');
  const file = path.join(directory, 'request.json'), owner = path.join(directory, 'inspection.render.json');
  fs.writeFileSync(file, JSON.stringify({project: '/TEST/probe-project'}));
  const pin = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  const record = {project: '/TEST/probe-project', status: 'running', additionalFilePinsBefore: {[file]: pin}};
  const live = {SNIPER_INSPECTION_REQUEST: file, SNIPER_INSPECTION_OWNER: owner, SNIPER_INSPECTION_PID: String(process.pid)};
  const admit = (value, environment = live) => {
    fs.writeFileSync(owner, JSON.stringify(value));
    return () => assertRevealProbeOwner(file, environment);
  };
  assert.doesNotThrow(admit(record));
  assert.throws(admit(record, {}), /runs only inside its owned inspection/);
  assert.throws(admit(record, {...live, SNIPER_INSPECTION_OWNER: path.join(directory, 'other.render.json')}), /owned inspection/);
  assert.throws(admit(record, {...live, SNIPER_INSPECTION_PID: '1'}), /no live supervisor/);
  assert.throws(admit({...record, completedAt: 'TEST'}), /does not bind this request/);
  assert.throws(admit({...record, status: 'failed'}), /does not bind this request/);
  assert.throws(admit({...record, additionalFilePinsBefore: {[file]: '0'.repeat(64)}}), /does not bind this request/);
  assert.throws(admit({...record, project: '/TEST/another'}), /does not bind this request/);
});
