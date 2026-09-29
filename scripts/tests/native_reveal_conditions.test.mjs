/** Pure reveal-condition checks (P2-01); synthetic series only, no browser and no saved plan. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {FLASH_RATIO, VISIBLE_EPSILON, declaredRevealFindings, effectiveOpacitySource, flashFindings,
  mountFrameRange, probeFramePlan} from '../producer/studio/native_reveal_conditions.mjs';

const MOUNT = 'sn-numbers-q1';
const FIRST = 745;

/** One D-B series row; `opacities` maps element key to [opacity, ancestors]. */
function row(order, localFrame, opacities) {
  return {order, mount: MOUNT, frame: FIRST + localFrame, localFrame,
    elements: Object.entries(opacities).map(([key, [opacity, ancestors = []]]) => ({key, opacity, ancestors}))};
}

/** A forward series over the given local frames, each element's opacity chosen per frame. */
function forward(frames, opacityAt) {
  return frames.map(local => row('forward', local, opacityAt(local)));
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
});

test('title visible from its first frame is not a flash', () => {
  assert.deepEqual(flashFindings(forward([0, 1, 2], () => ({title: [1]}))), []);
});

test('CSS-hidden panel fading in is not a flash', () => {
  assert.deepEqual(flashFindings(forward([0, 1, 2], local => ({panel: [local === 0 ? 0 : 0.2]}))), []);
});

test('declared later value visible before its cue', () => {
  const frames = [0, 1, 2, 15, 30, 223, 224, 225, 226];
  const series = forward(frames, local => ({arrow: [local === 0 || local >= 225 ? 1 : 0]}));
  const rows = declaredRevealFindings(series, [{mount: MOUNT, hfId: 'arrow', cueLocalFrame: 225}]);
  assert.deepEqual(rows, [{condition: 'visible-before-reveal', mount: MOUNT, element: 'arrow', frame: 745, localFrame: 0,
    order: 'forward', opacity: [1, 1]}]);
});

test('declared cue-0 reveal that starts visible', () => {
  const series = [...forward([0, 1, 2], local => ({panel: [local === 0 ? 1 : 0.2]})),
    row('cold-0', 0, {panel: [1]}), row('cold-0', 1, {panel: [0.2]})];
  const rows = declaredRevealFindings(series, [{mount: MOUNT, hfId: 'panel', cueLocalFrame: 0}]);
  assert.deepEqual(rows.map(value => [value.condition, value.order, value.frame, value.opacity]), [
    ['reveal-starts-visible', 'cold-0', 745, [1, 0.2]], ['reveal-starts-visible', 'forward', 745, [1, 0.2]]]);
  assert.ok(1 > 0.2 + VISIBLE_EPSILON);
});

test('outermost flashing element only', () => {
  // Real effective opacities: the browser function run over a stub DOM (panel fades, child keeps opacity 1).
  const measure = new Function('getComputedStyle', `return (${effectiveOpacitySource()});`)(node => node.style);
  const style = opacity => ({display: 'block', visibility: 'visible', clipPath: 'none', opacity: String(opacity)});
  const root = {nodeType: 9, parentElement: null};
  const panel = {nodeType: 1, parentElement: root, style: style(1)};
  const child = {nodeType: 1, parentElement: panel, style: style(1)};
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
  const plan = probeFramePlan({first, endExclusive}, [{cueLocalFrame: 81}], 30);
  assert.equal(plan.forward[0], 744);
  assert.deepEqual(plan.forward.slice(1, 4), [745, 746, 747]);
  assert.ok([745 + 15, 745 + 79, 745 + 80, 745 + 81, 745 + 82].every(frame => plan.forward.includes(frame)));
  assert.equal(plan.reverse[0], 745 + 83);
  assert.equal(plan.reverse.at(-1), 745);
  assert.deepEqual(plan.cold, [[745, 746], [825, 826]]);
});

test('malformed series fails closed', () => {
  const malformed = /^Error: Reveal series malformed: /u;
  const good = forward([0, 1], () => ({panel: [1]}));
  assert.throws(() => flashFindings([row('forward', 0, {panel: [Number.NaN]}), good[1]]), malformed);
  assert.throws(() => flashFindings([good[0]]), malformed);
  assert.throws(() => flashFindings([good[0], {...good[1], localFrame: undefined}]), malformed);
  assert.throws(() => flashFindings([good[0], row('forward', 1, {})]), malformed);
  assert.throws(() => flashFindings([...good, good[1]]), malformed);
  assert.throws(() => declaredRevealFindings(good, [{mount: MOUNT, hfId: 'panel', cueLocalFrame: 5}]), malformed);
  assert.throws(() => declaredRevealFindings(good, [{mount: MOUNT, hfId: 'arrow', cueLocalFrame: 1}]), malformed);
  assert.throws(() => mountFrameRange(Number.NaN, 1, 30), malformed);
  assert.throws(() => probeFramePlan({first: 10, endExclusive: 11}, [], 30), malformed);
});
