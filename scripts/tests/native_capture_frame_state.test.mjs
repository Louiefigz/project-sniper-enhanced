/** The combined per-frame read equals the separate readers and keeps checkTypography's verdicts. */
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {test} from 'node:test';
import {assertNativeFrameState,checkTypography,readNativeFrameState,visualState} from '../producer/studio/native_short_capture_checks.mjs';

/** A small in-realm DOM: just the selectors, styles and geometry the in-page readers use. */
class Node {
  constructor(tag, props={}) {
    Object.assign(this, {tag, id: '', classes: [], dataset: {}, text: '', style: {}, rect: [0, 0, 10, 10],
      scrollWidth: 10, clientWidth: 10, parentElement: null, children: []}, props);
    this.attributes = props.attributes ?? {};
  }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } return this; }
  get textContent() { return this.children.length ? this.children.map(node => node.textContent).join('') : this.text; }
  get previousElementSibling() {
    const siblings = this.parentElement?.children ?? [];
    return siblings[siblings.indexOf(this) - 1] ?? null;
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  getBoundingClientRect() {
    const [x, y, width, height] = this.rect;
    return {x, y, left: x, top: y, width, height, right: x + width, bottom: y + height};
  }
}

function walk(node, rows=[]) { rows.push(node); node.children.forEach(child => walk(child, rows)); return rows; }

function sandbox(root) {
  const all = () => walk(root).slice(1);
  const matches = {'[id],.__render_frame__': el => el.id || el.classes.includes('__render_frame__'),
    '[id^="native-title-line-"]': el => el.id.startsWith('native-title-line-'), '.caption': el => el.classes.includes('caption'),
    '[data-occurrence-id]': el => el.dataset.occurrenceId !== undefined};
  const defaults = {display: 'block', visibility: 'visible', opacity: '1', clipPath: 'none', transform: 'none',
    backgroundColor: 'rgba(0, 0, 0, 0)', color: 'rgb(255, 255, 255)', font: '16px Inter', border: '0px none rgb(0, 0, 0)'};
  class DOMMatrix { constructor(value) { this.value = value; } toFloat64Array() { return Float64Array.of(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1); } }
  return vm.createContext({DOMMatrix, window: {__timelines: {'line-swap': {}}},
    getComputedStyle: el => ({...defaults, ...el.style}),
    document: {querySelectorAll: selector => all().filter(matches[selector]), getElementById: id => all().find(el => el.id === id) ?? null}});
}

/** Puppeteer returns serialized values; so does this page. */
function page(root) {
  const context = sandbox(root), calls = [];
  return {calls, evaluate: async (fn, arg) => {
    calls.push(typeof fn);
    const source = typeof fn === 'string' ? fn : `(${fn})(${JSON.stringify(arg)})`;
    return JSON.parse(JSON.stringify(vm.runInContext(source, context)));
  }};
}

function scene(frame, {doubleOwner=false, suppressFirst=false, leak=false}={}) {
  const root = new Node('root'), canvas = new Node('div', {id: 'native-canvas', rect: [0, 0, 1080, 1920]});
  const title = new Node('div', {id: 'native-title-card', style: {clipPath: frame >= 30 ? 'inset(100%)' : 'inset(0%)'}});
  title.append(new Node('div', {id: 'native-title-line-0', text: 'TEST title', rect: [120, 96, 840, 80], scrollWidth: 840, clientWidth: 840}));
  const video = new Node('video', {id: 'source-0-0'}), frameImage = new Node('img', {classes: ['__render_frame__'], rect: [-195, 0, 2880, 1620]});
  const crop = new Node('div', {id: 'source-crop-0-0', style: {clipPath: 'inset(0%)'}}).append(video, frameImage);
  // suppressFirst mirrors the compositor: a suppressed opening emits no caption-0-0 at all.
  const captions = (suppressFirst ? [1] : [0, 1]).map(index => {
    const owns = doubleOwner || leak || (index === 0 ? frame < 15 : frame >= 15);
    const caption = new Node('div', {id: `caption-${index}-0`, classes: ['caption'], dataset: {start: doubleOwner ? '0' : String(index * 0.5), duration: doubleOwner ? '1' : '0.5'},
      style: {clipPath: owns ? 'inset(0%)' : 'inset(100%)'}, rect: [120, 1660, 840, 160], scrollWidth: 840, clientWidth: 840});
    const words = [0, 1].map(offset => {
      const id = index * 2 + offset, [start, end] = [id * 8, id * 8 + 8];
      return new Node('span', {id: `word-${id}-0`, text: `w${id}`, dataset: {occurrenceId: String(id), wordStartFrame: String(start),
        wordEndFrame: String(end)}, style: {color: start <= frame && frame < end ? 'rgb(255, 176, 32)' : 'rgb(255, 255, 255)'}});
    });
    return caption.append(...words);
  });
  const mount = new Node('div', {id: 'catalog-title', text: 'TEST catalog copy', rect: [0, 0, 1080, 400], dataset: {start: '0', duration: '1'},
    attributes: {'data-composition-src': 'compositions/title.html'}});
  const label = new Node('div', {id: 'label', text: 'TEST label', style: {opacity: frame >= 20 ? '1' : '0'}});
  canvas.append(title, crop, ...captions, mount, label);
  return root.append(canvas);
}

function plan() {
  return {catalogFiles: [{file: 'compositions/title.html'}], catalogTitle: {file: 'compositions/title.html', copy: {text: 'TEST catalog copy'}},
    extension: {markup: '<div id="catalog-title" data-composition-id="line-swap" data-composition-src="compositions/title.html" data-start="0" data-duration="1"></div>'},
    expectations: [{frame: 24, id: 'label', property: 'opacity', equals: '1'}, {frame: 24, id: 'label', property: 'textContent', equals: 'TEST label'}],
    canvas: {frameRate: '30/1', totalFrames: 60, captionMode: 'native', titleCard: {endFrame: 30},
      occurrences: [0, 1, 2, 3].map(id => [id, 0, id, id * 8, id * 8 + 8, `w${id}`, 0]),
      captionViews: [{startFrame: 0, endFrame: 60, box: [120, 1660, 840, 160], activeColor: '#FFB020', style: {color: '#FFFFFF'}}]}};
}

/** Frames 0-14 are a reasoned caption-free opening; the only caption view resumes at 15. */
function suppressedPlan() {
  const value = plan();
  value.canvas.captionSuppressions = [{startFrame: 0, endFrame: 15, reason: 'TEST catalog title holds'}];
  value.canvas.captionViews[0].startFrame = 15;
  return value;
}

test('one combined read returns exactly what the separate readers return',async()=>{
  for (const frame of [0, 12, 24, 40]) {
    const combined = await readNativeFrameState(page(scene(frame)), frame, plan());
    assert.deepEqual(combined.visualState, await visualState(page(scene(frame))));
    const separate = page(scene(frame));
    assert.deepEqual(assertNativeFrameState(combined, frame, plan()), await checkTypography(separate, frame, plan()));
    assert.deepEqual(combined.checkpoints, frame === 24 ? ['1', 'TEST label'] : []);
    assert.equal(combined.mounts[0].text, 'TEST catalog copy');
    assert.ok(separate.calls.length >= 2);
  }
});

test('the combined read is one page evaluation per frame',async()=>{
  const combinedPage = page(scene(24));
  await readNativeFrameState(combinedPage, 24, plan());
  assert.deepEqual(combinedPage.calls, ['string']);
});

test('failures and their messages match checkTypography on the same page state',async()=>{
  const cases = [
    ['two phrases', 14, scene(14, {doubleOwner: true}), plan()],
    ['checkpoint', 24, scene(24), (() => { const value = plan(); value.expectations[0].equals = '0.5'; return value; })()],
    ['word text', 5, scene(5), (() => { const value = plan(); value.canvas.occurrences[0][5] = 'changed'; return value; })()],
    ['catalog copy', 10, scene(10), (() => { const value = plan(); value.catalogTitle.copy.text = 'other'; return value; })()],
  ];
  for (const [name, frame, root, value] of cases) {
    const combined = await readNativeFrameState(page(root), frame, value);
    const expected = await checkTypography(page(root), frame, value).then(() => null, error => error.message);
    assert.ok(expected, `${name}: the separate check should fail`);
    assert.throws(() => assertNativeFrameState(combined, frame, value), error => error.message === expected, name);
  }
});

test('a suppression window is checked for expected caption absence by both readers',async()=>{
  for (const frame of [0, 14, 15, 24]) {
    const combined = await readNativeFrameState(page(scene(frame, {suppressFirst: true})), frame, suppressedPlan());
    const typography = assertNativeFrameState(combined, frame, suppressedPlan());
    assert.deepEqual(typography, await checkTypography(page(scene(frame, {suppressFirst: true})), frame, suppressedPlan()));
    assert.deepEqual(typography.captions.filter(row => row.painted).map(row => row.id), frame < 15 ? [] : ['caption-1-0']);
  }
  const cases = [
    ['stale opening phrase', 5, scene(5), /Caption suppression 0-15 still shows a caption at frame 5/],
    ['painted outside its window', 5, scene(5, {suppressFirst: true, leak: true}), /Caption suppression 0-15 still shows a caption at frame 5/],
  ];
  for (const [name, frame, root, pattern] of cases) {
    const combined = await readNativeFrameState(page(root), frame, suppressedPlan());
    const expected = await checkTypography(page(root), frame, suppressedPlan()).then(() => null, error => error.message);
    assert.match(expected ?? '', pattern, name);
    assert.throws(() => assertNativeFrameState(combined, frame, suppressedPlan()), error => error.message === expected, name);
  }
});
