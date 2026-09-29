/** Pure reveal-condition checks (P2-01); synthetic series only, no browser and no saved plan. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {FLASH_RATIO, VISIBLE_EPSILON, declaredRevealFindings, effectiveOpacitySource, flashFindings,
  mountFrameRange, probeFramePlan} from '../producer/studio/native_reveal_conditions.mjs';

const MOUNT = 'sn-numbers-q1';
const FIRST = 745;
/** The mount's active root frames, as P2-03's manifest records them (run-1 Q1: 24.833333333333332 s + 11.4 s). */
const RANGES = [{id: MOUNT, first: FIRST, endExclusive: 1087}];
/** The browser function body as P2-01 is amended by X77 (own computed visibility; ancestor opacity product). */
const X77_SOURCE = "el => { if (getComputedStyle(el).visibility !== 'visible') return 0; let o = 1; for (let n = el; "
  + "n && n.nodeType === 1; n = n.parentElement) { const s = getComputedStyle(n); if (s.display === 'none' || "
  + "s.clipPath === 'inset(100%)') return 0; o *= Number(s.opacity); } return o; }";

/** One D-B series row; `opacities` maps element key to [opacity, ancestors]. */
function row(order, localFrame, opacities) {
  return {order, mount: MOUNT, frame: FIRST + localFrame, localFrame,
    elements: Object.entries(opacities).map(([key, [opacity, ancestors = []]]) => ({key, opacity, ancestors}))};
}

/** A forward series over the given local frames, each element's opacity chosen per frame. */
function forward(frames, opacityAt) {
  return frames.map(local => row('forward', local, opacityAt(local)));
}

/** C1 on a two-frame forward series of one panel. */
function flashes(o0, o1) {
  return flashFindings(forward([0, 1], local => ({panel: [local === 0 ? o0 : o1]})));
}

test('numbers tl.set pattern is a first-frame flash', () => {
  const rows = flashFindings(forward([-1, 0, 1, 2], local => ({panel: [local === 0 ? 1 : 0]})));
  assert.deepEqual(rows, [{condition: 'first-frame-flash', mount: MOUNT, element: 'panel', frame: 745, localFrame: 0,
    order: 'forward', opacity: [1, 0]}]);
});

test('pipeline panel fade without CSS hide is a first-frame flash', () => {
  const rows = flashFindings(forward([0, 1, 2], local => ({panel: [local === 0 ? 1 : 0.2]})));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].element, 'panel');
  assert.deepEqual(rows[0].opacity, [1, 0.2]);
  assert.ok(0.2 <= 1 * FLASH_RATIO);
  // Both C1 bounds are inclusive: o0 >= 0.5 and o1 <= o0 * 0.5.
  assert.equal(flashes(0.5, 0.25).length, 1);
  assert.equal(flashes(0.5, 0.2501).length, 0);
  assert.equal(flashes(0.4999, 0).length, 0);
});

test('title visible from its first frame is not a flash', () => {
  assert.deepEqual(flashFindings(forward([0, 1, 2], () => ({title: [1]}))), []);
});

test('CSS-hidden panel fading in is not a flash', () => {
  assert.deepEqual(flashFindings(forward([0, 1, 2], local => ({panel: [local === 0 ? 0 : 0.2]}))), []);
});

/** Numbers pattern: `panel` declared at 81 holds `arrow` (declared at 225); `arrowAt(k)` is the arrow's opacity. */
function nested(arrowAt) {
  return forward([-1, 0, 1, 79, 80, 81, 82, 150, 224, 225, 226],
    local => ({panel: [local >= 81 ? 1 : 0], arrow: [arrowAt(local), ['panel']]}));
}
const NESTED = [{mount: MOUNT, hfId: 'panel', cueLocalFrame: 81}, {mount: MOUNT, hfId: 'arrow', cueLocalFrame: 225}];

test('declared later value visible before its cue', () => {
  const frames = [-1, 0, 1, 2, 15, 30, 223, 224, 225, 226];
  const at = early => forward(frames, local => ({arrow: [local === 0 ? early : local >= 225 ? 1 : 0]}));
  const declared = [{mount: MOUNT, hfId: 'arrow', cueLocalFrame: 225}];
  assert.deepEqual(declaredRevealFindings(at(1), declared, RANGES), [{condition: 'visible-before-reveal', mount: MOUNT,
    element: 'arrow', frame: 745, localFrame: 0, order: 'forward', opacity: [1, 1]}]);
  // Visible means strictly above VISIBLE_EPSILON.
  assert.deepEqual(declaredRevealFindings(at(VISIBLE_EPSILON), declared, RANGES), []);
  assert.equal(declaredRevealFindings(at(0.0011), declared, RANGES).length, 1);
  // X84 FD1: a child made visible early inside its still-hidden declared parent is a C2(a) finding on the child.
  const child = forward([0, 1, 2, 15, 29, 30, 31], local => ({panel: [local >= 30 ? 1 : 0], label: [1, ['panel']]}));
  assert.deepEqual(declaredRevealFindings(child, [{mount: MOUNT, hfId: 'panel', cueLocalFrame: 30}], RANGES), [{
    condition: 'visible-before-reveal', mount: MOUNT, element: 'label', frame: 745, localFrame: 0, order: 'forward', opacity: [1, 1]}]);
  const shown = forward([0, 1, 2, 15, 29, 30, 31], () => ({panel: [1], label: [1, ['panel']]}));
  assert.deepEqual(declaredRevealFindings(shown, [{mount: MOUNT, hfId: 'panel', cueLocalFrame: 30}], RANGES)
    .map(value => value.element), ['panel'], 'only the outermost early element is reported');
  // Nested declarations: an arrow shown with its panel at 81 and at its own cue 225 is fine; shown at 150 it is
  // early for itself only; forced visible from frame 0 inside the hidden panel it is one finding, not two.
  const row0 = {condition: 'visible-before-reveal', mount: MOUNT, element: 'arrow', order: 'forward'};
  assert.deepEqual(declaredRevealFindings(nested(k => (k >= 225 ? 1 : 0)), NESTED, RANGES), []);
  assert.deepEqual(declaredRevealFindings(nested(k => (k >= 150 ? 1 : 0)), NESTED, RANGES),
    [{...row0, frame: 745 + 150, localFrame: 150, opacity: [1, 1]}]);
  assert.deepEqual(declaredRevealFindings(nested(k => (k >= 0 ? 1 : 0)), NESTED, RANGES),
    [{...row0, frame: 745, localFrame: 0, opacity: [1, 1]}]);
});

test('declared cue-0 reveal that starts visible', () => {
  const series = [...forward([0, 1, 2], local => ({panel: [local === 0 ? 1 : 0.2]})),
    row('cold-0', 0, {panel: [1]}), row('cold-0', 1, {panel: [0.2]})];
  const declared = [{mount: MOUNT, hfId: 'panel', cueLocalFrame: 0}];
  const rows = declaredRevealFindings(series, declared, RANGES);
  assert.deepEqual(rows.map(value => [value.condition, value.order, value.frame, value.opacity]), [
    ['reveal-starts-visible', 'cold-0', 745, [1, 0.2]], ['reveal-starts-visible', 'forward', 745, [1, 0.2]]]);
  assert.ok(1 > 0.2 + VISIBLE_EPSILON);
  // The dip must exceed VISIBLE_EPSILON: 0.5 -> 0.499 is not a reveal that starts visible; 0.5 -> 0.4989 is.
  const dip = next => forward([0, 1], local => ({panel: [local === 0 ? 0.5 : next]}));
  assert.deepEqual(declaredRevealFindings(dip(0.499), declared, RANGES), []);
  assert.equal(declaredRevealFindings(dip(0.4989), declared, RANGES).length, 1);
});

test('outermost flashing element only', () => {
  assert.equal(effectiveOpacitySource(), X77_SOURCE);
  // The browser function over a stub DOM whose styles stand for computed styles (inheritance written out).
  const measure = new Function('getComputedStyle', `return (${effectiveOpacitySource()});`)(node => node.style);
  const style = (opacity, extra = {}) => ({display: 'block', visibility: 'visible', clipPath: 'none',
    opacity: String(opacity), ...extra});
  const root = {nodeType: 9, parentElement: null};
  const panel = {nodeType: 1, parentElement: root, style: style(1)};
  const child = {nodeType: 1, parentElement: panel, style: style(1)};
  const seen = (panelStyle, childStyle) => { panel.style = panelStyle; child.style = childStyle; return measure(child); };
  const hiddenParent = style(1, {visibility: 'hidden'});
  assert.equal(seen(style(1, {display: 'none'}), style(1)), 0, 'display none on an ancestor hides');
  assert.equal(seen(style(1, {clipPath: 'inset(100%)'}), style(1)), 0, 'a fully clipped ancestor hides');
  assert.equal(seen(hiddenParent, style(1, {visibility: 'hidden'})), 0, 'inherited hidden stays hidden');
  assert.equal(seen(hiddenParent, style(1)), 1, 'a child set visible inside a hidden parent is seen');
  assert.equal(seen(hiddenParent, style(1, {display: 'inline'})), 1, 'an all:initial child (inline, visible) is seen');
  assert.equal(seen(style(0.5), style(1)), 0.5, 'opacity is the ancestor product');
  child.style = style(1);
  const sample = local => {
    panel.style = style(local === 0 ? 1 : 0);
    return {panel: [measure(panel)], child: [measure(child), ['panel']]};
  };
  const series = forward([0, 1, 2], sample);
  assert.deepEqual(series[1].elements.map(value => value.opacity), [0, 0]);
  const rows = flashFindings(series);
  assert.deepEqual(rows.map(value => value.element), ['panel']);
});

test('mountFrameRange matches the runtime snap', () => {
  const [first, endExclusive] = mountFrameRange(24.833333333333332, 11.4, 30);
  assert.equal(first, 745);
  assert.equal(endExclusive, 1087);
  // Cases where a bare floor (1.16*25 = 28.999999999999996) or Math.round (30.6) would be wrong.
  assert.equal(mountFrameRange(1.16, 1, 25)[0], 29);
  assert.equal(mountFrameRange(1.02, 1, 30)[0], 30);
  const plan = probeFramePlan({first, endExclusive}, [{cueLocalFrame: 81}], 30);
  assert.equal(plan.forward[0], 744);
  assert.deepEqual(plan.forward.slice(1, 4), [745, 746, 747]);
  assert.ok([745 + 15, 745 + 79, 745 + 80, 745 + 81, 745 + 82].every(frame => plan.forward.includes(frame)));
  assert.equal(plan.reverse[0], 745 + 83);
  assert.equal(plan.reverse.at(-1), 745);
  assert.deepEqual(plan.cold, [[745, 746], [825, 826, 827]]);
  // K + 1 outside the mount: local frames 0..81 are active, so every order and the cold sequence stop at K.
  const edge = probeFramePlan({first, endExclusive: first + 82}, [{cueLocalFrame: 81}, {cueLocalFrame: 1}], 30);
  assert.deepEqual(edge.cold, [[745, 746], [745, 746, 747], [825, 826]]);
  assert.equal(edge.forward.at(-1), 826);
  assert.equal(edge.reverse[0], 826);
  assert.ok([...edge.forward, ...edge.reverse, ...edge.cold.flat()].every(frame => frame >= 744 && frame < first + 82));
  // A clipped per-cue sequence equal to an earlier one is dropped (two-frame mount, K = 1).
  assert.deepEqual(probeFramePlan({first: 10, endExclusive: 12}, [{cueLocalFrame: 1}], 30).cold, [[10, 11]]);
});

test('malformed series fails closed', () => {
  const malformed = /^Error: Reveal series malformed: /u;
  const good = forward([0, 1], () => ({panel: [1]}));
  const cue = (cueLocalFrame, hfId = 'panel') => [{mount: MOUNT, hfId, cueLocalFrame}];
  assert.throws(() => flashFindings([row('forward', 0, {panel: [Number.NaN]}), good[1]]), malformed);
  assert.throws(() => flashFindings([good[0]]), malformed);
  assert.throws(() => flashFindings([good[0], {...good[1], localFrame: undefined}]), malformed);
  assert.throws(() => flashFindings([good[0], row('forward', 1, {})]), malformed);
  assert.throws(() => flashFindings([...good, good[1]]), malformed);
  assert.throws(() => declaredRevealFindings(good, cue(5), RANGES), malformed);
  assert.throws(() => declaredRevealFindings(good, cue(1, 'arrow'), [{id: MOUNT, first: FIRST, endExclusive: 747}]), malformed);
  // K+1 = 2 lies inside a five-frame mount but was never sampled; in a two-frame mount it lies outside.
  assert.throws(() => declaredRevealFindings(good, cue(1), [{id: MOUNT, first: FIRST, endExclusive: 750}]), malformed);
  assert.equal(declaredRevealFindings(good, cue(1), [{id: MOUNT, first: FIRST, endExclusive: 747}])[0].condition,
    'visible-before-reveal');
  assert.throws(() => declaredRevealFindings(good, cue(0), []), malformed);
  assert.throws(() => declaredRevealFindings(good, cue(0), [{id: MOUNT, first: 700, endExclusive: 800}]), malformed);
  assert.throws(() => declaredRevealFindings(good, cue(0), [...RANGES, ...RANGES]), malformed);
  // Rows at or beyond the mount's end, K beyond it, an empty range, and K / K+1 only in different orders.
  const threeFrames = forward([0, 1, 2], () => ({panel: [0]})), twoFrames = [{id: MOUNT, first: FIRST, endExclusive: 747}];
  assert.throws(() => declaredRevealFindings(threeFrames, cue(0), twoFrames), /row at local frame 2, outside its range$/u);
  assert.throws(() => declaredRevealFindings(good, cue(2), twoFrames), /cue frame 2 of panel lies outside mount sn-numbers-q1$/u);
  assert.throws(() => declaredRevealFindings(good, cue(0), [{id: MOUNT, first: FIRST, endExclusive: FIRST}]),
    /mount ranges need unique ids and non-empty frames$/u);
  const split = [row('cold-0', 0, {panel: [1]}), row('reverse', 1, {panel: [0]})];
  assert.throws(() => declaredRevealFindings(split, cue(0), RANGES), /frames 0 and 1 of panel in sn-numbers-q1 are not sampled in one seek order$/u);
  assert.throws(() => mountFrameRange(Number.NaN, 1, 30), malformed);
  assert.throws(() => probeFramePlan({first: 10, endExclusive: 11}, [], 30), malformed);
});
