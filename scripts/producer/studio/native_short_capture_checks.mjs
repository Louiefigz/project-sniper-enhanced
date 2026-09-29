/** Shared native layout/word-state checks on the real capture session. */
import assert from 'node:assert/strict';
import {assertCatalogMountValues,catalogCapturePoints,catalogMounts,checkCatalogMounts,readCatalogMounts} from './native_catalog_checks.mjs';

/** In-page semantic paint state, separate from subpixel browser antialiasing (no outer references). */
function readVisualState() {
  return [...document.querySelectorAll('[id],.__render_frame__')].filter(el => {
    for (let node = el; node; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0' || s.clipPath === 'inset(100%)') return false;
    }
    return true;
  }).map(el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return { id: el.id || `frame:${el.previousElementSibling?.id}`, text: el.children.length ? null : el.textContent,
      box: [r.x, r.y, r.width, r.height], transform: [...new DOMMatrix(s.transform).toFloat64Array()], clip: s.clipPath,
      opacity: s.opacity, display: s.display, visibility: s.visibility,
      background: s.backgroundColor, color: s.color, font: s.font, border: s.border };
  });
}

/** Compare semantic paint state separately from subpixel browser antialiasing. */
export async function visualState(page) {
  return page.evaluate(readVisualState);
}

export function capturePoints(plan) {
  const input = plan.canvas, values = new Set([0, input.totalFrames - 1]);
  const boundary = frame => [frame - 1, frame, frame + 1].forEach(value => {
    if (Number.isSafeInteger(value) && value >= 0 && value < input.totalFrames) values.add(value);
  });
  for (const scene of plan.strategy.scenes) { boundary(scene.startFrame); boundary(scene.endFrame); }
  for (const view of [...input.pictureViews, ...input.captionViews, ...input.text, ...input.shapes]) {
    boundary(view.startFrame); boundary(view.endFrame);
  }
  if(input.titleCard)boundary(input.titleCard.endFrame);
  for(const frame of catalogCapturePoints(plan))boundary(frame);
  for (const cue of input.motion) { boundary(cue.startFrame); boundary(cue.startFrame + cue.durationFrames); }
  for (const word of input.occurrences) { boundary(word[3]); boundary(word[4]); }
  for (const check of plan.expectations ?? []) boundary(check.frame);
  // A suppression edge is where a stale phrase could survive a seek: both sides, forward and backward.
  const suppressions = input.captionSuppressions ?? [];
  for (const row of suppressions) { boundary(row.startFrame); boundary(row.endFrame); }
  const suppressionEdges = suppressions.flatMap(row => [row.startFrame - 1, row.startFrame, row.endFrame - 1, row.endFrame]);
  const forward = [...values].sort((a, b) => a - b);
  assert.ok(forward.length <= 1800, 'Native review packet exceeds the bounded capture inventory');
  const reverse = new Set(forward.filter((_, index) => index % 10 === 0));
  for (const frame of [...(plan.expectations ?? []).map(check => check.frame), ...suppressionEdges]) {
    if (values.has(frame)) reverse.add(frame);
  }
  return [...forward, ...[...reverse].sort((a, b) => b - a), 0];
}

function rgb(hex) {
  return `rgb(${[1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16)).join(', ')})`;
}

/** In-page title, phrase and word state (no outer references). */
function readTypography() {
  const painted = el => {
    for (let node = el; node; node = node.parentElement) {
      const s = getComputedStyle(node);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0' || s.clipPath === 'inset(100%)') return false;
    }
    return true;
  };
  return {
    titleClip: document.getElementById('native-title-card') ? getComputedStyle(document.getElementById('native-title-card')).clipPath : null,
    lines: [...document.querySelectorAll('[id^="native-title-line-"]')].map(el => ({
      text: el.textContent, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right,
      scroll: el.scrollWidth, client: el.clientWidth })),
    captions: [...document.querySelectorAll('.caption')].map(el => ({
      id: el.id, start: Number(el.dataset.start), end: Number(el.dataset.start) + Number(el.dataset.duration),
      clip: getComputedStyle(el).clipPath, center: el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2,
      top: el.getBoundingClientRect().top, scroll: el.scrollWidth, client: el.clientWidth, painted: painted(el) })),
    words: [...document.querySelectorAll('[data-occurrence-id]')].map(el => ({
      id: Number(el.dataset.occurrenceId), view: Number(el.id.split('-').at(-1)), start: Number(el.dataset.wordStartFrame),
      end: Number(el.dataset.wordEndFrame), color: getComputedStyle(el).color, text: el.textContent })),
  };
}

/** In-page story checkpoint value (no outer references). */
function readCheckpoint({ id, property }) {
  const el = document.getElementById(id);
  return property === 'textContent' ? el.textContent : getComputedStyle(el)[property];
}

function frameCheckpoints(plan, frame) {
  return (plan.expectations ?? []).filter(row => row.frame === frame);
}

/**
 * One page read per captured frame: scene state, typography, catalog mounts and story checkpoints.
 * Each part is the unchanged in-page reader used by visualState/checkTypography, composed into a
 * single evaluation of the same seeked page; assertNativeFrameState applies checkTypography's checks.
 */
export async function readNativeFrameState(page, frame, plan) {
  const mounts = plan.catalogFiles?.length ? catalogMounts(plan) : [];
  const checks = frameCheckpoints(plan, frame).map(({ id, property }) => ({ id, property }));
  return page.evaluate(`/* native-frame-state */ ({visualState: (${readVisualState})(), typography: (${readTypography})(), `
    + `mounts: (${readCatalogMounts})(${JSON.stringify(mounts)}), checkpoints: ${JSON.stringify(checks)}.map(${readCheckpoint})})`);
}

/** checkTypography's assertions, in its order, on one combined read; returns the typography state. */
export function assertNativeFrameState(observed, frame, plan) {
  assertTypographyLayout(observed.typography, frame, plan);
  assertCatalogMountValues(observed.mounts, frame, plan, plan.catalogFiles?.length ? catalogMounts(plan) : []);
  assertTypographyWords(observed.typography, frame, plan);
  frameCheckpoints(plan, frame).forEach((check, index) => assert.equal(observed.checkpoints[index], check.equals,
    `Story checkpoint ${check.id}.${check.property} at frame ${frame}`));
  return observed.typography;
}

export async function checkTypography(page, frame, plan) {
  const state = await page.evaluate(readTypography);
  assertTypographyLayout(state, frame, plan);
  await checkCatalogMounts(page,frame,plan);
  assertTypographyWords(state, frame, plan);
  for (const check of frameCheckpoints(plan, frame)) {
    const actual = await page.evaluate(readCheckpoint, check);
    assert.equal(actual, check.equals, `Story checkpoint ${check.id}.${check.property} at frame ${frame}`);
  }
  return state;
}

/** Title fit, caption placement, phrase ownership and title exit on one typography state. */
function assertTypographyLayout(state, frame, plan) {
  const input = plan.canvas, [num, den] = input.frameRate.split('/').map(Number), time = frame * den / num;
  if (input.captionMode === 'source-burned') {
    assert.equal(state.captions.length + state.words.length, 0, 'Source-burned mode must not add native caption layers');
  }
  assert.ok(state.lines.every(row => row.left >= 80 && row.right <= 1000 && row.scroll <= row.client), 'Title overflows its phone-safe card');
  assert.ok(state.captions.every(row => row.center === 540 && row.scroll <= row.client
    && row.top === input.captionViews[Number(row.id.split('-').at(-1))].box[1]), 'Caption placement/fit differs from strategy');
  assert.ok(state.captions.filter(row => row.start <= time && time < row.end - 1e-8 && row.clip !== 'inset(100%)').length <= 1,
    `More than one phrase owns frame ${frame}`);
  // Expected absence: a reasoned suppression window paints no native caption at all.
  const hidden = (input.captionSuppressions ?? []).find(row => row.startFrame <= frame && frame < row.endFrame);
  if (hidden) {
    assert.deepEqual(state.captions.filter(row => row.painted || (row.start <= time && time < row.end - 1e-8)).map(row => row.id), [],
      `Caption suppression ${hidden.startFrame}-${hidden.endFrame} still shows a caption at frame ${frame}`);
  }
  if(input.titleCard)assert.equal(state.titleClip === 'inset(100%)', frame >= input.titleCard.endFrame);
  else assert.equal(state.titleClip,null,'Catalog title must not stack a built-in title');
}

/** Every word's displayed text and active/inactive color on one typography state. */
function assertTypographyWords(state, frame, plan) {
  const input = plan.canvas;
  for (const word of state.words) {
    const correction = input.captionCorrections?.find(row => row.occurrenceId === word.id);
    assert.equal(word.text, correction?.displayText ?? input.occurrences[word.id][5], `Caption text ${word.id} at frame ${frame}`);
    const view = input.captionViews[word.view];
    const active = view.activeColor && Math.max(word.start, view.startFrame) <= frame && frame < Math.min(word.end, view.endFrame);
    assert.equal(word.color, rgb(active ? view.activeColor : view.style.color), `Word ${word.id} at frame ${frame}`);
  }
}
