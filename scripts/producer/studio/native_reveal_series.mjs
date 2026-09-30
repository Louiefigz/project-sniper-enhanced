/**
 * Series and declaration validation for the reveal conditions (MASTER-PLAN M-066, P2-01; split from
 * native_reveal_conditions.mjs to keep each file within the 300-line rule, X77). Pure data in, data out; every
 * failure is `Error('Reveal series malformed: ...')`. The shapes are coordinator decision D-B, amended by X72(c).
 */

/** Seek-order labels are syntax, not meaning: forward, reverse, or cold-<index into probeFramePlan().cold>. */
const ORDER = /^(?:forward|reverse|cold-(?:0|[1-9]\d*))$/u;

/**
 * Fail closed on input the conditions cannot evaluate.
 * @param {string} detail what is wrong
 * @returns {never}
 */
export function malformed(detail) {
  throw new Error(`Reveal series malformed: ${detail}`);
}

/**
 * A declared cue frame: a mount-local frame index.
 * @param {unknown} value
 * @returns {number}
 */
export function cueFrame(value) {
  if (!Number.isSafeInteger(value) || /** @type {number} */ (value) < 0) malformed(`cue frame ${JSON.stringify(value)}`);
  return /** @type {number} */ (value);
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
export function indexSeries(series) {
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
 * One validated declaration.
 * @param {any} value `{mount, hfId, cueLocalFrame}`
 * @returns {{mount: string, hfId: string, cueLocalFrame: number}}
 */
export function checkedDeclaration(value) {
  const {mount, hfId, cueLocalFrame} = value ?? {};
  if (typeof mount !== 'string' || !mount || typeof hfId !== 'string' || !hfId) {
    malformed(`declaration ${JSON.stringify(value)} needs a mount and an hfId`);
  }
  return {mount, hfId, cueLocalFrame: cueFrame(cueLocalFrame)};
}

/**
 * The active root frames of every probed mount, keyed by id (P2-03 `RevealProbeManifest.mounts`).
 * @param {unknown} mounts `[{id, first, endExclusive}]`
 * @returns {Map<string, {first: number, endExclusive: number}>}
 */
export function mountRanges(mounts) {
  if (!Array.isArray(mounts)) malformed('mount ranges are not a list');
  const ranges = new Map(mounts.map(row => [row?.id, {first: row?.first, endExclusive: row?.endExclusive}]));
  const valid = ([id, {first, endExclusive}]) => typeof id === 'string' && id && Number.isSafeInteger(first)
    && first >= 0 && Number.isSafeInteger(endExclusive) && endExclusive > first;
  if (ranges.size !== mounts.length || ![...ranges].every(valid)) malformed('mount ranges need unique ids and non-empty frames');
  return ranges;
}

/**
 * The series entry of a declared mount, after proving the samples can decide C2 (X72(c), X77):
 * every row lies inside the mount range (local -1 is forward's inactive neighbour); K lies inside the mount;
 * K was sampled; and, whenever K+1 lies inside the mount, one seek order sampled both K and K+1.
 * @param {Map<string, any>} index indexed series
 * @param {Map<string, {first: number, endExclusive: number}>} ranges
 * @param {{mount: string, hfId: string, cueLocalFrame: number}} declaration
 * @returns {{first: number, orders: Map<string, Map<number, Map<string, {opacity: number}>>>}}
 */
export function sampledCue(index, ranges, declaration) {
  const {mount, hfId, cueLocalFrame: cue} = declaration, range = ranges.get(mount), entry = index.get(mount);
  if (!range || !entry || entry.first !== range.first) malformed(`mount ${mount} of ${hfId} lacks its range or its rows disagree`);
  const active = range.endExclusive - range.first, orders = [...entry.orders.values()];
  const outside = orders.flatMap(frames => [...frames.keys()]).find(local => local < -1 || local >= active);
  if (outside !== undefined) malformed(`mount ${mount} has a row at local frame ${outside}, outside its range`);
  if (cue >= active) malformed(`declared cue frame ${cue} of ${hfId} lies outside mount ${mount}`);
  if (!orders.some(frames => frames.has(cue))) malformed(`declared cue frame ${cue} of ${hfId} in ${mount} was not sampled`);
  if (cue + 1 < active && !orders.some(frames => frames.has(cue) && frames.has(cue + 1))) {
    malformed(`frames ${cue} and ${cue + 1} of ${hfId} in ${mount} are not sampled in one seek order`);
  }
  return entry;
}
