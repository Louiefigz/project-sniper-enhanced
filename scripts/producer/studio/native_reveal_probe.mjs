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
 * data out. `reveal-probe.json` (exclusive create) holds the D-B series, the C1/C2 findings, and `visibleAtMount`:
 * the text visible on each mount's first frame, for the critic (information only), with that frame's screenshot
 * kept as evidence. A malformed capture or series fails closed; there is no partial result.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {VISIBLE_EPSILON, declaredRevealFindings, effectiveOpacitySource, flashFindings, probeFramePlan}
  from './native_reveal_conditions.mjs';
import {captureNativeFrame, createNativeCaptureContext, nativeCaptureEvidence, prepareNativeCaptureContext,
  withNativeCaptureSession} from './native_short_capture_context.mjs';

/** Where each session installs `effectiveOpacitySource()` once; `readRevealElements` reads it. */
const OPACITY_GLOBAL = '__sniperRevealOpacity';
/** A sha256 in hex, as the capture context reports its runtime and compiled documents. */
const SHA256 = /^[a-f0-9]{64}$/u;

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
 * One captured session, checked against its plan: same mount, order and frames, in order, each with elements.
 * @param {{mount: string, order: string, frames: number[]}} spec planned session
 * @param {any} seen captured session
 * @returns {Array<{frame: number, elements: Array<any>, screenshot: string}>}
 */
function capturedFrames(spec, seen) {
  const frames = Array.isArray(seen?.frames) ? seen.frames : [];
  if (seen?.mount !== spec.mount || seen?.order !== spec.order || frames.map(row => row?.frame).join() !== spec.frames.join()
      || !frames.every(row => Array.isArray(row.elements))) {
    refuse(`${spec.order} ${spec.mount}`);
  }
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
  const first = new Map(manifest.mounts.map(row => [row.id, row.first]));
  return sessions.flatMap((spec, index) => capturedFrames(spec, observed.sessions[index]).map(row => ({
    order: spec.order, mount: spec.mount, frame: row.frame, localFrame: row.frame - first.get(spec.mount),
    elements: row.elements.map(({key, opacity, ancestors}) => ({key, opacity, ancestors}))})));
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
 * @param {(request: object, sessions: Array<object>) => Promise<object>} capture the one capture step
 * @returns {Promise<object>} the report written
 */
export async function runRevealProbe(request, capture = captureRevealSessions) {
  const manifest = readProbeManifest(request.probeProject), sessions = probeSessions(manifest);
  fs.mkdirSync(request.output, {mode: 0o700});
  const observed = await capture(request, sessions);
  if (!SHA256.test(observed?.runtimeLibrarySha256 ?? '') || !SHA256.test(observed?.compiledSha256 ?? '')) refuse('runtime identity');
  const series = revealSeries(manifest, sessions, observed), findings = revealFindings(manifest, series);
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
 * One planned sequence inside one fresh session: install the opacity source once, then seek and read each frame.
 * @param {object} context prepared capture context
 * @param {{page: any}} session live capture session
 * @param {{mount: string, frames: number[]}} spec planned session
 * @returns {Promise<Array<{frame: number, screenshot: string, elements: Array<object> | null}>>}
 */
async function captureSequence(context, session, spec) {
  await session.page.evaluate(`window.${OPACITY_GLOBAL} = ${effectiveOpacitySource()}; true`);
  const rows = [];
  for (const frame of spec.frames) {
    const shot = await captureNativeFrame(context, session, frame);
    rows.push({frame, screenshot: shot.path, elements: await session.page.evaluate(readRevealElements, spec.mount)});
  }
  return rows;
}

/**
 * The one capture step (U5): the renderer's compile and zero-video path, one fresh session per planned sequence.
 * Each session keeps its own frames directory, so every screenshot path stays valid until the report is written.
 * @param {{probeProject: string, output: string, runtime: string}} request
 * @param {Array<{mount: string, order: string, frames: number[]}>} sessions planned sessions
 * @returns {Promise<{runtimeLibrarySha256: string, compiledSha256: string, sessions: Array<object>}>}
 */
export async function captureRevealSessions(request, sessions) {
  const work = path.join(request.output, 'capture');
  const context = await createNativeCaptureContext({project: request.probeProject, runtime: request.runtime}, work);
  await prepareNativeCaptureContext(context);
  const captured = [];
  for (const [index, spec] of sessions.entries()) {
    const receipt = {}, framesDir = path.join(work, `frames-${index}`);
    const frames = await withNativeCaptureSession(context, {framesDir, receipt}, session => captureSequence(context, session, spec));
    captured.push({mount: spec.mount, order: spec.order, frames, transport: receipt.transport});
  }
  const {runtimeLibrarySha256, compiledSha256} = nativeCaptureEvidence(context);
  return {runtimeLibrarySha256, compiledSha256, sessions: captured};
}

/**
 * Refuse a run outside its owned inspection (as `native_short_capture.mjs` refuses one outside its export owner):
 * the request is the live owner's pinned request, the owner is active and its supervisor is alive.
 * @param {string} file the inspection request (`request.json`)
 * @param {Record<string, string | undefined>} environment the process environment
 * @returns {void}
 */
export function assertRevealProbeOwner(file, environment = process.env) {
  const deny = message => { throw new Error(`Reveal probe admission: ${message}`); };
  if (typeof file !== 'string' || !path.isAbsolute(file) || environment.SNIPER_INSPECTION_REQUEST !== file
      || environment.SNIPER_INSPECTION_OWNER !== path.join(path.dirname(file), 'inspection.render.json')) {
    deny('the probe runs only inside its owned inspection');
  }
  const bytes = fs.readFileSync(file), owner = JSON.parse(fs.readFileSync(environment.SNIPER_INSPECTION_OWNER, 'utf8'));
  const pid = Number(environment.SNIPER_INSPECTION_PID);
  if (!Number.isSafeInteger(pid) || pid <= 1) deny('the inspection has no live supervisor');
  process.kill(pid, 0);
  const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
  if (owner.project !== JSON.parse(bytes).project || owner.completedAt || owner.abortReason
      || !['preparing', 'waiting-for-capacity', 'running'].includes(owner.status)
      || owner.additionalFilePinsBefore?.[file] !== sha256) {
    deny('the inspection owner does not bind this request');
  }
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  assertRevealProbeOwner(process.argv[2]);
  const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const report = await runRevealProbe({probeProject: request.project, runtime: request.runtime,
    output: path.join(path.dirname(process.argv[2]), 'reveal')});
  console.log(JSON.stringify({status: report.status, findings: report.findings.length}));
}
