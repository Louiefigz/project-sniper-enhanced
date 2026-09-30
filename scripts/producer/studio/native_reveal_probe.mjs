/**
 * Runtime reveal probe (MASTER-PLAN M-068, P2-EARLY-CHECKS P2-03): C1 and C2 in the exact pinned runtime, before
 * any render.
 *
 * Input is a graphics-only probe project (`native-reveal-probe-project.ts`) and its `REVEAL-PROBE.json`. For each
 * mount the probe runs one fresh session for `forward`, one for `reverse` and one per `cold` sequence of
 * `probeFramePlan`, seeks each planned root frame with the renderer's own compile, zero-video session and seek path
 * (`native_short_capture_context.mjs`), and reads every element under the mount host: its key (`data-hf-id`, else a
 * DOM index path under the host), its effective opacity (`effectiveOpacitySource`) and its ancestors' keys. The
 * capture is one function (`captureRevealSessions`), passed to `runRevealProbe`; everything after it is data in,
 * data out. Every captured frame must show its mount live, by the renderer's own check (`readCatalogMounts`,
 * `assertCatalogMountValues`, P2 U3), and at least one element under the host while the mount is active: a mount
 * the page never made live cannot pass as clean (review X128 M1). `reveal-probe.json` (exclusive create) holds the
 * D-B series, the C1/C2 findings, and `visibleAtMount`: the text visible on each mount's first frame, for the critic
 * (information only), with that frame's screenshot kept as evidence. A malformed capture or series fails closed;
 * there is no partial result.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {assertCatalogMountValues, readCatalogMounts} from './native_catalog_checks.mjs';
import {readRecord} from './runtime/native-export-guard.mjs';
import {VISIBLE_EPSILON, declaredRevealFindings, effectiveOpacitySource, flashFindings, probeFramePlan}
  from './native_reveal_conditions.mjs';
import {captureNativeFrame, createNativeCaptureContext, nativeCaptureEvidence, prepareNativeCaptureContext,
  withNativeCaptureSession} from './native_short_capture_context.mjs';

/** Where each session installs `effectiveOpacitySource()` once; `readRevealElements` reads it. */
const OPACITY_GLOBAL = '__sniperRevealOpacity';
/** A sha256 in hex, as the capture context reports its runtime and compiled documents. */
const SHA256 = /^[a-f0-9]{64}$/u;
/** The owned-inspection worker that runs this CLI (`native_reveal_probe.py --worker`). */
const WORKER = fileURLToPath(new URL('./native_reveal_probe.py', import.meta.url));
/** Owner states in which a worker may run (as `owned_inspection.require_worker`). */
const ACTIVE = ['preparing', 'waiting-for-capacity', 'running'];

/**
 * Fail closed on a capture the plan did not ask for.
 * @param {string} detail what differs
 * @returns {never}
 */
function refuse(detail) {
  throw new Error(`Reveal probe capture differs from its plan: ${detail}`);
}

/**
 * Read `REVEAL-PROBE.json`; every declaration must name a probed mount.
 * @param {string} project probe project directory
 * @returns {{schemaVersion: 1, rate: number, mounts: Array<any>, declarations: Array<any>}}
 */
export function readProbeManifest(project) {
  const manifest = JSON.parse(fs.readFileSync(path.join(project, 'REVEAL-PROBE.json'), 'utf8'));
  const ids = new Set(Array.isArray(manifest?.mounts) ? manifest.mounts.map(row => row?.id) : []);
  if (manifest?.schemaVersion !== 1 || !ids.size || !Array.isArray(manifest.declarations)
      || !manifest.declarations.every(row => ids.has(row?.mountId))) {
    throw new Error('Reveal probe manifest is malformed');
  }
  return manifest;
}

/**
 * Every fresh session the probe runs: per mount, forward, reverse, then each cold sequence (`cold-<index>`).
 * @param {{rate: number, mounts: Array<{id: string, first: number, endExclusive: number}>, declarations: Array<{mountId: string, cueLocalFrame: number}>}} manifest
 * @returns {Array<{mount: string, order: string, frames: number[]}>}
 */
export function probeSessions(manifest) {
  return manifest.mounts.flatMap(mount => {
    const plan = probeFramePlan(mount, manifest.declarations.filter(row => row.mountId === mount.id), manifest.rate);
    return [{mount: mount.id, order: 'forward', frames: plan.forward}, {mount: mount.id, order: 'reverse', frames: plan.reverse},
      ...plan.cold.map((frames, index) => ({mount: mount.id, order: `cold-${index}`, frames}))];
  });
}

/**
 * One captured session, checked against its plan: same mount, order and frames, in order, each with elements, and
 * at least one element at every frame where the mount is active (an empty host is a dead mount, not a clean one).
 * @param {{mount: string, order: string, frames: number[]}} spec planned session
 * @param {any} seen captured session
 * @param {{first: number, endExclusive: number}} mount the mount's active root frames
 * @returns {Array<{frame: number, elements: Array<any>, screenshot: string, live: object}>}
 */
function capturedFrames(spec, seen, mount) {
  const frames = Array.isArray(seen?.frames) ? seen.frames : [];
  if (seen?.mount !== spec.mount || seen?.order !== spec.order || frames.map(row => row?.frame).join() !== spec.frames.join()
      || !frames.every(row => Array.isArray(row.elements))) {
    refuse(`${spec.order} ${spec.mount}`);
  }
  const empty = frames.find(row => row.frame >= mount.first && row.frame < mount.endExclusive && !row.elements.length);
  if (empty) refuse(`${spec.order} ${spec.mount} shows no element of the mount at active frame ${empty.frame}`);
  return frames;
}

/**
 * The D-B series from a capture: one row per session and frame, `localFrame` counted from the mount's first frame,
 * and exactly `{key, opacity, ancestors}` per element (other captured fields, such as text, stay out).
 * @param {{mounts: Array<{id: string, first: number}>}} manifest
 * @param {Array<{mount: string, order: string, frames: number[]}>} sessions planned sessions
 * @param {{sessions: Array<any>}} observed the capture's result
 * @returns {Array<object>} D-B rows
 */
export function revealSeries(manifest, sessions, observed) {
  if (!Array.isArray(observed?.sessions) || observed.sessions.length !== sessions.length) refuse('session count');
  const mounts = new Map(manifest.mounts.map(row => [row.id, row]));
  return sessions.flatMap((spec, index) => capturedFrames(spec, observed.sessions[index], mounts.get(spec.mount)).map(row => ({
    order: spec.order, mount: spec.mount, frame: row.frame, localFrame: row.frame - mounts.get(spec.mount).first,
    elements: row.elements.map(({key, opacity, ancestors}) => ({key, opacity, ancestors}))})));
}

/**
 * The renderer's own liveness check on every captured frame (P2 U3): the mount's host is present with its file,
 * start and duration, its composition registered a timeline, it has a box, and while active it is neither
 * `display:none` nor clipped away (`assertCatalogMountValues`, from the `readCatalogMounts` facts the capture read).
 * @param {{mounts: Array<{id: string, compositionId: string, file: string, start: number, duration: number}>}} manifest
 * @param {Array<{mount: string}>} sessions planned sessions
 * @param {{sessions: Array<{frames: Array<{frame: number, live: object}>}>}} observed the checked capture
 * @param {string} frameRate the probe project's `num/den` clock
 * @returns {void}
 */
export function assertMountsLive(manifest, sessions, observed, frameRate) {
  const plan = {canvas: {frameRate}, catalogFiles: manifest.mounts.map(row => ({file: row.file}))};
  const rows = new Map(manifest.mounts.map(row => [row.id, [catalogRow(row)]]));
  sessions.forEach((spec, index) => observed.sessions[index].frames.forEach(frame =>
    assertCatalogMountValues([frame.live], frame.frame, plan, rows.get(spec.mount))));
}

/**
 * One manifest mount in `catalogMounts`' row shape, as `readCatalogMounts` and `assertCatalogMountValues` read it.
 * @param {{id: string, compositionId: string, file: string, start: number, duration: number}} mount
 * @returns {{id: string, composition: string, file: string, start: number, duration: number}}
 */
function catalogRow(mount) {
  return {id: mount.id, composition: mount.compositionId, file: mount.file, start: mount.start, duration: mount.duration};
}

/**
 * C1 on every seek order, and C2 for the declarations (`mountId` becomes `mount`, X75); the manifest's mount
 * ranges pass unchanged as the third argument.
 * @param {{mounts: Array<any>, declarations: Array<any>}} manifest
 * @param {Array<object>} series D-B rows
 * @returns {Array<object>} finding rows
 */
export function revealFindings(manifest, series) {
  const declarations = manifest.declarations.map(row => ({mount: row.mountId, hfId: row.hfId, cueLocalFrame: row.cueLocalFrame}));
  return [...flashFindings(series), ...declaredRevealFindings(series, declarations, manifest.mounts)];
}

/**
 * The text of every element visible at each mount's first frame in the forward order, with that frame's screenshot
 * copied into `output` as evidence (information for the critic; never a verdict).
 * @param {{mounts: Array<{id: string, first: number}>}} manifest
 * @param {Array<{mount: string, order: string}>} sessions planned sessions
 * @param {{sessions: Array<any>}} observed the capture's result
 * @param {string} output the probe's output directory
 * @returns {Array<{mount: string, frame: number, elements: Array<{key: string, text: string}>, screenshot: {file: string, sha256: string}}>}
 */
export function visibleAtMount(manifest, sessions, observed, output) {
  return manifest.mounts.map((mount, index) => {
    const at = sessions.findIndex(row => row.mount === mount.id && row.order === 'forward');
    const row = observed.sessions[at].frames.find(frame => frame.frame === mount.first);
    const file = `mount-first-${index}.jpg`, target = path.join(output, file);
    fs.copyFileSync(row.screenshot, target, fs.constants.COPYFILE_EXCL);
    const elements = row.elements.filter(element => element.opacity > VISIBLE_EPSILON && element.text)
      .map(({key, text}) => ({key, text}));
    const sha256 = crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');
    return {mount: mount.id, frame: mount.first, elements, screenshot: {file, sha256}};
  });
}

/**
 * Run the probe: plan the sessions, capture them with `capture`, evaluate, and write `reveal-probe.json` (`wx`).
 * @param {{probeProject: string, output: string, runtime: string}} request `output` must not exist yet
 * @param {(request: object, sessions: Array<object>, mounts: Array<object>) => Promise<object>} capture the one capture step
 * @returns {Promise<object>} the report written
 */
export async function runRevealProbe(request, capture = captureRevealSessions) {
  const manifest = readProbeManifest(request.probeProject), sessions = probeSessions(manifest);
  const {frameRate} = JSON.parse(fs.readFileSync(path.join(request.probeProject, 'SHORT-PROJECT.json'), 'utf8')).canvas;
  fs.mkdirSync(request.output, {mode: 0o700});
  const observed = await capture(request, sessions, manifest.mounts);
  if (!SHA256.test(observed?.runtimeLibrarySha256 ?? '') || !SHA256.test(observed?.compiledSha256 ?? '')) refuse('runtime identity');
  const series = revealSeries(manifest, sessions, observed);
  assertMountsLive(manifest, sessions, observed, frameRate);
  const findings = revealFindings(manifest, series);
  const report = {schemaVersion: 1, scope: 'native-reveal-probe', status: findings.length ? 'premature-reveal-found' : 'reveal-probe-pass',
    runtimeLibrarySha256: observed.runtimeLibrarySha256, compiledSha256: observed.compiledSha256, series, findings,
    visibleAtMount: visibleAtMount(manifest, sessions, observed, request.output)};
  fs.writeFileSync(path.join(request.output, 'reveal-probe.json'), JSON.stringify(report), {flag: 'wx', mode: 0o600});
  return report;
}

/**
 * In-page read of one mount host (serialized into the page; no outer references). Every element under the host:
 * its key, its effective opacity by the installed `effectiveOpacitySource()`, its ancestors' keys inside the host
 * (outermost first) and its own text.
 * @param {string} mountId the host element's id
 * @returns {Array<{key: string, opacity: number, ancestors: string[], text: string}> | null} null when the host is absent
 */
export function readRevealElements(mountId) {
  const host = document.getElementById(mountId), opacity = window.__sniperRevealOpacity;
  if (!host) return null;
  const position = el => {
    const steps = [];
    for (let node = el; node !== host; node = node.parentElement) steps.unshift([...node.parentElement.children].indexOf(node));
    return `path:${steps.join('.')}`;
  };
  const key = el => el.getAttribute('data-hf-id') || position(el);
  const chain = el => {
    const keys = [];
    for (let node = el.parentElement; node !== host; node = node.parentElement) keys.unshift(key(node));
    return keys;
  };
  const text = el => [...el.childNodes].filter(node => node.nodeType === 3).map(node => node.textContent).join(' ')
    .replace(/\s+/gu, ' ').trim();
  return [...host.querySelectorAll('*')].map(el => ({key: key(el), opacity: opacity(el), ancestors: chain(el), text: text(el)}));
}

/**
 * One planned sequence inside one fresh session: install the opacity source once, then seek each frame and read
 * the mount's elements and its liveness facts (`readCatalogMounts`).
 * @param {object} context prepared capture context
 * @param {{page: any}} session live capture session
 * @param {{spec: {mount: string, frames: number[]}, row: object}} planned the session and its mount's catalog row
 * @returns {Promise<Array<{frame: number, screenshot: string, elements: Array<object> | null, live: object | null}>>}
 */
async function captureSequence(context, session, planned) {
  await session.page.evaluate(`window.${OPACITY_GLOBAL} = ${effectiveOpacitySource()}; true`);
  const rows = [];
  for (const frame of planned.spec.frames) {
    const shot = await captureNativeFrame(context, session, frame);
    const elements = await session.page.evaluate(readRevealElements, planned.spec.mount);
    const [live] = await session.page.evaluate(readCatalogMounts, [planned.row]);
    rows.push({frame, screenshot: shot.path, elements, live});
  }
  return rows;
}

/**
 * The one capture step (U5): the renderer's compile and zero-video path, one fresh session per planned sequence.
 * Each session keeps its own frames directory, so every screenshot path stays valid until the report is written.
 * @param {{probeProject: string, output: string, runtime: string}} request
 * @param {Array<{mount: string, order: string, frames: number[]}>} sessions planned sessions
 * @param {Array<{id: string, compositionId: string, file: string, start: number, duration: number}>} mounts manifest mounts
 * @returns {Promise<{runtimeLibrarySha256: string, compiledSha256: string, sessions: Array<object>}>}
 */
export async function captureRevealSessions(request, sessions, mounts) {
  const work = path.join(request.output, 'capture'), rows = new Map(mounts.map(row => [row.id, catalogRow(row)]));
  const context = await createNativeCaptureContext({project: request.probeProject, runtime: request.runtime}, work);
  await prepareNativeCaptureContext(context);
  const captured = [];
  for (const [index, spec] of sessions.entries()) {
    const receipt = {}, framesDir = path.join(work, `frames-${index}`), planned = {spec, row: rows.get(spec.mount)};
    const frames = await withNativeCaptureSession(context, {framesDir, receipt}, session => captureSequence(context, session, planned));
    captured.push({mount: spec.mount, order: spec.order, frames, transport: receipt.transport});
  }
  const {runtimeLibrarySha256, compiledSha256} = nativeCaptureEvidence(context);
  return {runtimeLibrarySha256, compiledSha256, sessions: captured};
}

/**
 * Refuse a run outside its owned inspection, at parity with `assertNativeCaptureOwner` (review X128 m4) and with
 * `owned_inspection.require_worker`: the request is `SNIPER_INSPECTION_REQUEST`, the owner file its sibling; both
 * are read safely (`readRecord`: absolute, canonical, regular, unlinked); the supervisor is alive; the owner is active,
 * names the request's project, pins its exact bytes, writes this inspection's `result.json`, and runs this probe's
 * own worker on this request.
 * @param {string} file the inspection request (`request.json`)
 * @param {Record<string, string | undefined>} environment the process environment
 * @returns {object} the request, parsed from the bytes that were checked
 */
export function assertRevealProbeOwner(file, environment = process.env) {
  const deny = message => { throw new Error(`Reveal probe admission: ${message}`); };
  const folder = typeof file === 'string' ? path.dirname(file) : '';
  if (environment.SNIPER_INSPECTION_REQUEST !== file || environment.SNIPER_INSPECTION_OWNER !== path.join(folder, 'inspection.render.json')) {
    deny('the probe runs only inside its owned inspection');
  }
  const request = readRecord(file), owner = readRecord(environment.SNIPER_INSPECTION_OWNER).value;
  const pid = Number(environment.SNIPER_INSPECTION_PID);
  if (!Number.isSafeInteger(pid) || pid <= 1) deny('the inspection has no live supervisor');
  process.kill(pid, 0);
  const args = owner.args, worker = Array.isArray(args) && args.length === 5 && typeof args[0] === 'string'
    && path.isAbsolute(args[0]) && args[1] === '-B' && args[2] === WORKER && args[3] === '--worker' && args[4] === file;
  if (owner.project !== request.value.project || owner.completedAt || owner.abortReason || !ACTIVE.includes(owner.status)
      || owner.additionalFilePinsBefore?.[file] !== request.sha || owner.output !== path.join(folder, 'result.json')) {
    deny('the inspection owner does not bind this request');
  }
  if (!worker) deny('the inspection did not originate from the reveal probe worker');
  return request.value;
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  const request = assertRevealProbeOwner(process.argv[2]);
  const report = await runRevealProbe({probeProject: request.project, runtime: request.runtime,
    output: path.join(path.dirname(process.argv[2]), 'reveal')});
  console.log(JSON.stringify({status: report.status, findings: report.findings.length}));
}
