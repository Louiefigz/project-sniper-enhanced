/** Shared native layout/word-state checks on the real capture session. */
import assert from 'node:assert/strict';

/** Compare semantic paint state separately from subpixel browser antialiasing. */
export async function visualState(page) {
  return page.evaluate(() => [...document.querySelectorAll('[id],.__render_frame__')].filter(el => {
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
  }));
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
  boundary(input.titleCard.endFrame);
  for (const cue of input.motion) { boundary(cue.startFrame); boundary(cue.startFrame + cue.durationFrames); }
  for (const word of input.occurrences) { boundary(word[3]); boundary(word[4]); }
  for (const check of plan.expectations ?? []) boundary(check.frame);
  const forward = [...values].sort((a, b) => a - b);
  assert.ok(forward.length <= 1800, 'Native review packet exceeds the bounded capture inventory');
  const reverse = new Set(forward.filter((_, index) => index % 10 === 0));
  for (const check of plan.expectations ?? []) if (values.has(check.frame)) reverse.add(check.frame);
  return [...forward, ...[...reverse].sort((a, b) => b - a), 0];
}

function rgb(hex) {
  return `rgb(${[1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16)).join(', ')})`;
}

export async function checkTypography(page, frame, plan) {
  const input = plan.canvas, [num, den] = input.frameRate.split('/').map(Number), time = frame * den / num;
  const state = await page.evaluate(() => ({
    titleClip: getComputedStyle(document.getElementById('native-title-card')).clipPath,
    lines: [...document.querySelectorAll('[id^="native-title-line-"]')].map(el => ({
      text: el.textContent, left: el.getBoundingClientRect().left, right: el.getBoundingClientRect().right,
      scroll: el.scrollWidth, client: el.clientWidth })),
    captions: [...document.querySelectorAll('.caption')].map(el => ({
      id: el.id, start: Number(el.dataset.start), end: Number(el.dataset.start) + Number(el.dataset.duration),
      clip: getComputedStyle(el).clipPath, center: el.getBoundingClientRect().left + el.getBoundingClientRect().width / 2,
      top: el.getBoundingClientRect().top, scroll: el.scrollWidth, client: el.clientWidth })),
    words: [...document.querySelectorAll('[data-occurrence-id]')].map(el => ({
      id: Number(el.dataset.occurrenceId), view: Number(el.id.split('-').at(-1)), start: Number(el.dataset.wordStartFrame),
      end: Number(el.dataset.wordEndFrame), color: getComputedStyle(el).color, text: el.textContent })),
  }));
  if (input.captionMode === 'source-burned') {
    assert.equal(state.captions.length + state.words.length, 0, 'Source-burned mode must not add native caption layers');
  }
  assert.ok(state.lines.every(row => row.left >= 80 && row.right <= 1000 && row.scroll <= row.client), 'Title overflows its phone-safe card');
  assert.ok(state.captions.every(row => row.center === 540 && row.scroll <= row.client
    && row.top === input.captionViews[Number(row.id.split('-').at(-1))].box[1]), 'Caption placement/fit differs from strategy');
  assert.ok(state.captions.filter(row => row.start <= time && time < row.end - 1e-8 && row.clip !== 'inset(100%)').length <= 1,
    `More than one phrase owns frame ${frame}`);
  assert.equal(state.titleClip === 'inset(100%)', frame >= input.titleCard.endFrame);
  for (const word of state.words) {
    const correction = input.captionCorrections?.find(row => row.occurrenceId === word.id);
    assert.equal(word.text, correction?.displayText ?? input.occurrences[word.id][5], `Caption text ${word.id} at frame ${frame}`);
    const view = input.captionViews[word.view];
    const active = view.activeColor && Math.max(word.start, view.startFrame) <= frame && frame < Math.min(word.end, view.endFrame);
    assert.equal(word.color, rgb(active ? view.activeColor : view.style.color), `Word ${word.id} at frame ${frame}`);
  }
  for (const check of (plan.expectations ?? []).filter(row => row.frame === frame)) {
    const actual = await page.evaluate(({ id, property }) => {
      const el = document.getElementById(id);
      return property === 'textContent' ? el.textContent : getComputedStyle(el)[property];
    }, check);
    assert.equal(actual, check.equals, `Story checkpoint ${check.id}.${check.property} at frame ${frame}`);
  }
  return state;
}
