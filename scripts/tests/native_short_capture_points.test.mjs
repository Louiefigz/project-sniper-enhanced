/** Pure schedule checks; native browser and encoded-picture tests remain separate. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {capturePoints} from '../producer/studio/native_short_capture_checks.mjs';

function fixture() {
  return {
    canvas: {
      totalFrames: 100,
      pictureViews: [{startFrame: 0, endFrame: 100}],
      captionViews: [{startFrame: 0, endFrame: 100}],
      text: [], shapes: [], motion: [], occurrences: [],
      titleCard: {endFrame: 25},
    },
    strategy: {scenes: [{startFrame: 0, endFrame: 100}]},
    expectations: [{frame: 37, id: 'label', property: 'opacity', equals: '1'}],
  };
}

test('every explicit state checkpoint is captured forward and backward', () => {
  const plan = fixture();
  for (const frame of [37, 38, 75]) {
    plan.expectations = [{frame, id: 'label', property: 'opacity', equals: '1'}];
    const points = capturePoints(plan);
    assert.equal(points.filter(value => value === frame).length, 2);
    const lastForward = points.indexOf(99);
    assert.ok(points.indexOf(frame) < lastForward);
    assert.ok(points.lastIndexOf(frame) > lastForward);
  }
});

test('motion and phrase boundaries keep adjacent probes within the output clock', () => {
  const plan = fixture();
  plan.canvas.motion = [{startFrame: 10, durationFrames: 5}];
  plan.canvas.occurrences = [[0, 0, 0, 50, 65, 'Word', 0]];
  const points = capturePoints(plan);
  for (const frame of [9, 10, 11, 14, 15, 16, 49, 50, 51, 64, 65, 66]) {
    assert.ok(points.includes(frame));
  }
  assert.ok(points.every(frame => Number.isSafeInteger(frame) && frame >= 0 && frame < 100));
});

test('a repeated checkpoint does not grow the reverse inventory and invalid frames stay out', () => {
  const plan = fixture();
  plan.expectations.push(plan.expectations[0], {...plan.expectations[0], frame: -1});
  const points = capturePoints(plan);
  assert.equal(points.filter(frame => frame === 37).length, 2);
  assert.equal(points.includes(-1), false);
});

test('large capture schedules fail before starting a browser', () => {
  const plan = fixture();
  plan.canvas.totalFrames = 3000;
  plan.canvas.motion = Array.from({length: 1000}, (_, index) => ({startFrame: index * 3, durationFrames: 1}));
  assert.throws(() => capturePoints(plan), /bounded capture inventory/);
});

test('catalog title capture covers actual mount boundaries without a built-in title', () => {
  const plan=fixture();delete plan.canvas.titleCard;
  plan.canvas.frameRate='30/1';plan.canvas.totalFrames=120;
  plan.catalogFiles=[{file:'compositions/title.html'}];
  plan.catalogTitle={file:'compositions/title.html'};
  plan.extension={markup:'<div id="catalog-title" data-composition-id="line-swap" data-composition-src="compositions/title.html" data-start="0" data-duration="3.5"></div>'};
  const points=capturePoints(plan);
  for(const frame of [0,1,52,53,54,104,105,106])assert.ok(points.includes(frame));
  plan.extension.markup=plan.extension.markup.replace('id="catalog-title"','');
  assert.throws(()=>capturePoints(plan),/stable IDs/);
});
