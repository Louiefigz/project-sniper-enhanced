/**
 * Pure reveal conditions for mounted catalog graphics (MASTER-PLAN M-066, P2-EARLY-CHECKS P2-01).
 *
 * Data in, data out: no browser, no files. The runtime reveal probe (P2-03) seeks each catalog mount in fixed
 * orders and records every element's effective opacity (the product over its ancestors) per sampled frame.
 * This module plans those frames and evaluates two exact conditions on the recorded series:
 *   C1 first-frame flash, which needs no declaration;
 *   C2 declared reveals (`data-hf-reveal`): visible before the cue, or visible at the cue and then dipping.
 *
 * Series shape (coordinator decision D-B), one row per seek order, mount and sampled root frame:
 *   {order: 'forward'|'reverse'|'cold-<n>', mount, frame, localFrame,
 *    elements: [{key: <data-hf-id or DOM index path>, opacity, ancestors: [key, ... outermost first]}]}
 * Finding rows: {condition, mount, element, frame, localFrame, order, opacity: [before, after]}.
 * Malformed input fails closed with `Error('Reveal series malformed: ...')`; nothing is assumed.
 */

/** C1 threshold: visible at local frame 0 means at least this opacity; the dip keeps at most this share of it. */
export const FLASH_RATIO = 0.5;
/** An effective opacity above this is visible (C2). */
export const VISIBLE_EPSILON = 0.001;

/** Probe grid spacing in frames inside [0, last cue) (P2-01). */
const GRID_FRAMES = 15;
/** The runtime's clip-bound snap: floor(seconds * rate + 1e-9) (native-review-regions.ts mountFrames). */
const SNAP_EPSILON = 1e-9;
/** Seek-order labels are syntax, not meaning: forward, reverse, or cold-<index into probeFramePlan().cold>. */
const ORDER = /^(?:forward|reverse|cold-(?:0|[1-9]\d*))$/u;

/**
 * Fail closed on input the conditions cannot evaluate.
 * @param {string} detail what is wrong
 * @returns {never}
 */
function malformed(detail) {
  throw new Error(`Reveal series malformed: ${detail}`);
}

/**
 * Browser function source returning an element's effective opacity: the product of `opacity` over the element
 * and its ancestors, and 0 when any of them has display none, visibility hidden or clip-path inset(100%). This is
 * the ancestor walk of `visualState` (native_short_capture_checks.mjs), returning the product instead of a flag.
 * @returns {string} source of `el => number`, for `page.evaluate`
 */
export function effectiveOpacitySource() {
  return "el => { let o = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) { "
    + "const s = getComputedStyle(n); "
    + "if (s.display === 'none' || s.visibility === 'hidden' || s.clipPath === 'inset(100%)') return 0; "
    + "o *= Number(s.opacity); } return o; }";
}

/**
 * Active root frames of a mount, snapped exactly as the runtime snaps clip bounds.
 * @param {number} start mount start in seconds (`data-start`)
 * @param {number} duration mount duration in seconds (`data-duration`)
 * @param {number} rate frames per second
 * @returns {[number, number]} `[first, endExclusive]`
 */
export function mountFrameRange(start, duration, rate) {
  if (![start, duration, rate].every(Number.isFinite) || start < 0 || duration <= 0 || rate <= 0) {
    malformed(`mount timing ${start}s + ${duration}s at ${rate} fps`);
  }
  const snap = (/** @type {number} */ seconds) => Math.floor(seconds * rate + SNAP_EPSILON);
  return [snap(start), snap(start + duration)];
}

/**
 * A declared cue frame: a mount-local frame index.
 * @param {unknown} value
 * @returns {number}
 */
function cueFrame(value) {
  if (!Number.isSafeInteger(value) || /** @type {number} */ (value) < 0) malformed(`cue frame ${JSON.stringify(value)}`);
  return /** @type {number} */ (value);
}

/**
 * Root frames the probe seeks for one mount. Local frames sampled: 0, 1, 2; K-2..K+1 for each declared cue
 * frame K; a 15-frame grid over [0, max K); all clipped to the mount's active range. `forward` ascends from the
 * inactive neighbour `first - 1`; `reverse` descends from local `max K + 2` to `first`; each `cold` entry is a
 * fresh-session seek sequence: `[first, first + 1]`, and `[first + K - 1, first + K, first + K + 1]` for each K > 0
 * (coordinator ruling X60(3): the before-cue neighbour and C2(b) inside one session), clipped to the active range;
 * a clipped sequence equal to an earlier one is dropped.
 * @param {{first: number, endExclusive: number}} mount active root frames (P2-03 `RevealProbeManifest.mounts`)
 * @param {Array<{cueLocalFrame: number}>} declarations declared reveals of this mount
 * @param {number} rate frames per second; validated only, since the grid is counted in frames
 * @returns {{forward: number[], reverse: number[], cold: number[][]}} root frames
 */
export function probeFramePlan(mount, declarations, rate) {
  const {first, endExclusive} = mount ?? {};
  if (!Number.isSafeInteger(first) || !Number.isSafeInteger(endExclusive) || first < 0 || endExclusive - first < 2
      || !Number.isFinite(rate) || rate <= 0 || !Array.isArray(declarations)) {
    malformed('probe mount needs integer frames, at least two active frames, a positive rate and a declaration list');
  }
  const cues = [...new Set(declarations.map(row => cueFrame(row?.cueLocalFrame)))].sort((a, b) => a - b);
  const active = (/** @type {number} */ local) => local >= 0 && local < endExclusive - first;
  const last = Math.max(0, ...cues), local = new Set([0, 1, 2, ...cues.flatMap(k => [k - 2, k - 1, k, k + 1])]);
  for (let k = 0; k < last; k += GRID_FRAMES) local.add(k);
  const sampled = [...local].filter(active).sort((a, b) => a - b);
  const reverse = [...new Set([...sampled, last + 2])].filter(active).sort((a, b) => b - a);
  const clipped = [[0, 1], ...cues.filter(k => k > 0).map(k => [k - 1, k, k + 1])].map(frames => frames.filter(active));
  const cold = [...new Map(clipped.filter(frames => frames.length).map(frames => [frames.join(), frames])).values()];
  const root = (/** @type {number[]} */ frames) => frames.map(k => first + k);
  return {forward: [...(first > 0 ? [first - 1] : []), ...root(sampled)], reverse: root(reverse), cold: cold.map(root)};
}

/**
 * One validated element entry.
 * @param {any} value `{key, opacity, ancestors}`
 * @returns {[string, {opacity: number, ancestors: string[]}]}
 */
function elementEntry(value) {
  const {key, opacity, ancestors} = value ?? {};
  if (typeof key !== 'string' || !key || !Number.isFinite(opacity) || opacity < 0 || opacity > 1
      || !Array.isArray(ancestors) || !ancestors.every(row => typeof row === 'string' && row)) {
    malformed(`element ${JSON.stringify(key)} needs a key, an effective opacity in [0, 1] and its ancestor keys`);
  }
  return [key, {opacity, ancestors}];
}

/**
 * One validated series row, with its elements keyed.
 * @param {any} row D-B row
 * @returns {{order: string, mount: string, frame: number, localFrame: number, elements: Map<string, {opacity: number, ancestors: string[]}>}}
 */
function checkedRow(row) {
  const {order, mount, frame, localFrame, elements} = row ?? {};
  if (typeof order !== 'string' || !ORDER.test(order) || typeof mount !== 'string' || !mount
      || !Number.isSafeInteger(frame) || frame < 0 || !Number.isSafeInteger(localFrame) || !Array.isArray(elements)) {
    malformed(`row ${JSON.stringify({order, mount, frame, localFrame})} needs an order, a mount, frames and elements`);
  }
  const entries = new Map(elements.map(elementEntry));
  if (entries.size !== elements.length) malformed(`${order} ${mount} frame ${frame} repeats an element key`);
  return {order, mount, frame, localFrame, elements: entries};
}

/**
 * Index a series by mount, then seek order, then local frame. Every row of a mount must agree on the mount's
 * first root frame (`frame - localFrame`), and no order samples one local frame twice.
 * @param {unknown} series D-B rows
 * @returns {Map<string, {first: number, orders: Map<string, Map<number, Map<string, {opacity: number, ancestors: string[]}>>>}>}
 */
function indexSeries(series) {
  if (!Array.isArray(series)) malformed('series is not a list');
  const mounts = new Map();
  for (const {order, mount, frame, localFrame, elements} of series.map(checkedRow)) {
    const entry = mounts.get(mount) ?? {first: frame - localFrame, orders: new Map()};
    if (entry.first !== frame - localFrame) malformed(`rows of mount ${mount} disagree on its first frame`);
    const frames = entry.orders.get(order) ?? new Map();
    if (frames.has(localFrame)) malformed(`${order} samples ${mount} local frame ${localFrame} twice`);
    mounts.set(mount, entry);
    entry.orders.set(order, frames.set(localFrame, elements));
  }
  return mounts;
}

/**
 * One finding row in the D-B key order.
 * @param {string} condition first-frame-flash | visible-before-reveal | reveal-starts-visible
 * @param {{mount: string, element: string, first: number, order: string}} group where it was seen
 * @param {number} local mount-local frame
 * @param {[number, number | null]} opacity [before, after]
 * @returns {object}
 */
function finding(condition, group, local, opacity) {
  return {condition, mount: group.mount, element: group.element, frame: group.first + local, localFrame: local,
    order: group.order, opacity};
}

/**
 * Deterministic order: mount, element, condition, seek order, local frame.
 * @param {Array<any>} rows
 * @returns {Array<any>}
 */
function sortFindings(rows) {
  const text = (/** @type {any} */ row) => [row.mount, row.element, row.condition, row.order].join('\u0000');
  return rows.sort((a, b) => (text(a) < text(b) ? -1 : text(a) > text(b) ? 1 : a.localFrame - b.localFrame));
}

/**
 * C1 inside one seek order of one mount; drops a flashing element whose ancestor also flashes.
 * @param {{mount: string, first: number, order: string, frames: Map<number, Map<string, {opacity: number, ancestors: string[]}>>}} group
 * @returns {Array<object>}
 */
function orderFlashes(group) {
  const zero = group.frames.get(0), one = group.frames.get(1), flashing = new Map();
  for (const [key, value] of zero ?? []) {
    const next = one?.get(key);
    if (!next) malformed(`${group.order} ${group.mount} element ${key} is missing at local frame 1`);
    if (value.opacity >= FLASH_RATIO && next.opacity <= value.opacity * FLASH_RATIO) flashing.set(key, {value, next});
  }
  return [...flashing].filter(([, {value}]) => !value.ancestors.some(key => flashing.has(key)))
    .map(([key, {value, next}]) => finding('first-frame-flash', {...group, element: key}, 0, [value.opacity, next.opacity]));
}

/**
 * Condition C1, first-frame flash (no declaration needed): an element of a mount whose effective opacity o0 at
 * local frame 0 and o1 at local frame 1, in the same seek order, satisfy `o0 >= FLASH_RATIO && o1 <= o0 *
 * FLASH_RATIO`. Only the outermost flashing element is kept. Every mount needs local frames 0 and 1 in at least
 * one order, and an element seen at frame 0 must be reported at frame 1 too.
 * @param {Array<object>} series D-B rows
 * @returns {Array<object>} finding rows, condition `first-frame-flash`
 */
export function flashFindings(series) {
  const rows = [];
  for (const [mount, entry] of indexSeries(series)) {
    const pairs = [...entry.orders].filter(([, frames]) => frames.has(0) && frames.has(1));
    if (!pairs.length) malformed(`mount ${mount} lacks local frames 0 and 1 in every seek order`);
    rows.push(...pairs.flatMap(([order, frames]) => orderFlashes({mount, first: entry.first, order, frames})));
  }
  return sortFindings(rows);
}

/**
 * One validated declaration.
 * @param {any} value `{mount, hfId, cueLocalFrame}`
 * @returns {{mount: string, hfId: string, cueLocalFrame: number}}
 */
function checkedDeclaration(value) {
  const {mount, hfId, cueLocalFrame} = value ?? {};
  if (typeof mount !== 'string' || !mount || typeof hfId !== 'string' || !hfId) {
    malformed(`declaration ${JSON.stringify(value)} needs a mount and an hfId`);
  }
  return {mount, hfId, cueLocalFrame: cueFrame(cueLocalFrame)};
}

/**
 * C2 inside one seek order for one declaration.
 * @param {{mount: string, element: string, cue: number, first: number, order: string, frames: Map<number, Map<string, {opacity: number}>>}} group
 * @returns {Array<object>}
 */
function orderReveals(group) {
  const cue = group.cue, used = [...group.frames.keys()].filter(k => k >= 0 && k <= cue + 1).sort((a, b) => a - b);
  const opacity = new Map(used.map(k => [k, group.frames.get(k)?.get(group.element)?.opacity]));
  const missing = used.find(k => opacity.get(k) === undefined);
  if (missing !== undefined) malformed(`${group.order} ${group.mount} lacks declared ${group.element} at local frame ${missing}`);
  const at = (/** @type {number} */ k) => /** @type {number} */ (opacity.get(k));
  const rows = [], early = used.find(k => k < cue && at(k) > VISIBLE_EPSILON);
  if (early !== undefined) rows.push(finding('visible-before-reveal', group, early, [at(early), opacity.has(cue) ? at(cue) : null]));
  if (opacity.has(cue) && opacity.has(cue + 1) && at(cue) > at(cue + 1) + VISIBLE_EPSILON) {
    rows.push(finding('reveal-starts-visible', group, cue, [at(cue), at(cue + 1)]));
  }
  return rows;
}

/**
 * The active root frames of every probed mount, keyed by id (P2-03 `RevealProbeManifest.mounts`).
 * @param {unknown} mounts `[{id, first, endExclusive}]`
 * @returns {Map<string, {first: number, endExclusive: number}>}
 */
function mountRanges(mounts) {
  if (!Array.isArray(mounts)) malformed('mount ranges are not a list');
  const ranges = new Map(mounts.map(row => [row?.id, {first: row?.first, endExclusive: row?.endExclusive}]));
  const valid = ([id, {first, endExclusive}]) => typeof id === 'string' && id && Number.isSafeInteger(first)
    && first >= 0 && Number.isSafeInteger(endExclusive) && endExclusive > first;
  if (ranges.size !== mounts.length || ![...ranges].every(valid)) malformed('mount ranges need unique ids and frames');
  return ranges;
}

/**
 * The series entry of a declared mount, after proving its cue frame K was sampled and that K+1 was sampled
 * whenever it lies inside the mount (X72(c): "outside the mount" is then the only reason K+1 is absent).
 * @param {Map<string, any>} index indexed series
 * @param {Map<string, {first: number, endExclusive: number}>} ranges
 * @param {{mount: string, hfId: string, cueLocalFrame: number}} declaration
 * @returns {{first: number, orders: Map<string, Map<number, Map<string, {opacity: number}>>>}}
 */
function sampledCue(index, ranges, declaration) {
  const {mount, hfId, cueLocalFrame: cue} = declaration, range = ranges.get(mount), entry = index.get(mount);
  if (!range || !entry || entry.first !== range.first) malformed(`mount ${mount} of ${hfId} lacks its range or its rows disagree`);
  const active = range.endExclusive - range.first;
  const sampled = (/** @type {number} */ local) => [...entry.orders.values()].some(frames => frames.has(local));
  if (cue >= active || !sampled(cue)) malformed(`declared cue frame ${cue} of ${hfId} in ${mount} is outside it or unsampled`);
  if (cue + 1 < active && !sampled(cue + 1)) malformed(`frame ${cue + 1} after the cue of ${hfId} is inside ${mount} but unsampled`);
  return entry;
}

/**
 * Condition C2 for declared reveals, each with its mount-local cue frame K:
 * (a) `visible-before-reveal` when a sampled local frame 0 <= k < K has effective opacity > VISIBLE_EPSILON
 *     (one row per declaration and seek order, at the earliest such frame; `opacity` is [o(k), o(K) in that
 *     order, or null when that order did not sample K]);
 * (b) `reveal-starts-visible` when o(K) > o(K+1) + VISIBLE_EPSILON in an order that sampled both.
 * K must be sampled in some order, K+1 too whenever it lies inside the mount, and the declared element must be
 * reported in every sampled frame 0..K+1.
 * @param {Array<object>} series D-B rows
 * @param {Array<{mount: string, hfId: string, cueLocalFrame: number}>} declarations
 * @param {Array<{id: string, first: number, endExclusive: number}>} mounts active root frames per mount
 * @returns {Array<object>} finding rows
 */
export function declaredRevealFindings(series, declarations, mounts) {
  const index = indexSeries(series), ranges = mountRanges(mounts);
  if (!Array.isArray(declarations)) malformed('declarations are not a list');
  return sortFindings(declarations.map(checkedDeclaration).flatMap(declaration => {
    const entry = sampledCue(index, ranges, declaration);
    return [...entry.orders].flatMap(([order, frames]) => orderReveals({mount: declaration.mount,
      element: declaration.hfId, cue: declaration.cueLocalFrame, first: entry.first, order, frames}));
  }));
}
