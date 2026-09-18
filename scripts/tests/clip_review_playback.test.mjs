import assert from 'node:assert/strict';
import test from 'node:test';
import {SelectionPlayback} from '../../templates/clip-review/playback.mjs';

class Media extends EventTarget {
  readyState = 4;
  currentTime = 0;
  paused = true;
  seeking = false;
  ended = false;
  loadCount = 0;
  playResult = () => Promise.resolve();

  pause() {
    this.paused = true;
    this.dispatchEvent(new Event('pause'));
  }

  play() {
    this.paused = false;
    return this.playResult();
  }

  load() {
    this.loadCount += 1;
    this.readyState = 0;
    this.currentTime = 0;
    this.paused = true;
    this.ended = false;
  }

  tick(seconds) {
    this.currentTime = seconds;
    this.dispatchEvent(new Event('timeupdate'));
  }
}

function fixture() {
  const media = new Media();
  const reports = [];
  const player = new SelectionPlayback(media, state => reports.push(state));
  return {media, reports, player};
}

test('plays nonchronological ranges and stops instead of spilling into source', () => {
  const {media, player, reports} = fixture();
  const ranges = [{start: 120, end: 125}, {start: 40, end: 44}];
  player.start(ranges);
  assert.equal(media.currentTime, 120);
  media.tick(125.1);
  assert.equal(media.currentTime, 40);
  media.tick(44.1);
  assert.equal(media.paused, true);
  assert.equal(reports.at(-1).state, 'finished');
  // Browsers dispatch pause asynchronously after stop() has already reported.
  media.dispatchEvent(new Event('pause'));
  media.dispatchEvent(new Event('waiting'));
  assert.equal(reports.at(-1).state, 'finished');
  player.start(ranges);
  assert.equal(media.currentTime, 120);
  assert.equal(media.paused, false);
});

test('cold media retains the requested start until metadata arrives', () => {
  const {media, player} = fixture();
  media.readyState = 0;
  player.start([{start: 80, end: 90}]);
  assert.equal(media.paused, false);
  media.tick(100);
  assert.equal(player.step, 0);
  media.readyState = 1;
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.currentTime, 80);
});

test('browser blocking is visible and resume retries the retained selection', async () => {
  const {media, player, reports} = fixture();
  media.playResult = () => Promise.reject(Object.assign(new Error('Gesture required'), {name: 'NotAllowedError'}));
  player.start([{start: 80, end: 90}]);
  await Promise.resolve();
  assert.equal(reports.at(-1).state, 'blocked');
  assert.match(reports.at(-1).message, /Resume selection/);
  media.playResult = () => Promise.resolve();
  player.resume();
  assert.equal(media.currentTime, 80);
  assert.equal(media.paused, false);
});

test('a rejected old play request cannot overwrite a new selection', async () => {
  const {media, player, reports} = fixture();
  let rejectOld;
  media.playResult = () => new Promise((resolve, reject) => { rejectOld = reject; });
  player.start([{start: 10, end: 15}]);
  media.playResult = () => Promise.resolve();
  player.start([{start: 30, end: 35}]);
  rejectOld(new Error('Old request interrupted'));
  await Promise.resolve();
  assert.equal(media.currentTime, 30);
  assert.notEqual(reports.at(-1).state, 'error');
});

test('pause and seeking cannot advance the playlist; stopped metadata cannot restart it', () => {
  const {media, player} = fixture();
  player.start([{start: 10, end: 15}, {start: 30, end: 35}]);
  media.seeking = true;
  media.tick(20);
  assert.equal(player.step, 0);
  media.seeking = false;
  media.pause();
  media.tick(20);
  assert.equal(player.step, 0);
  player.stop();
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.paused, true);
  assert.equal(player.ranges.length, 0);
});

test('reload restores the current passage position after resetting the media decoder', () => {
  const {media, player} = fixture();
  player.start([{start: 40, end: 50}, {start: 10, end: 15}]);
  media.tick(43.25);
  player.reload();
  assert.equal(media.currentTime, 0);
  media.readyState = 1;
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.currentTime, 43.25);
  media.tick(50.1);
  assert.equal(media.currentTime, 10);
  player.stop();
  player.reload();
  assert.equal(media.paused, true);
});

test('switching from source ranges to an edited file resets decoder and starts at zero', () => {
  const {media, player} = fixture();
  media.src = 'original.mp4';
  media.getAttribute = name => name === 'src' ? media.src : null;
  player.start([{start: 120, end: 125}], 'original.mp4');
  media.readyState = 1;
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.currentTime, 120);
  player.start([{start: 0, end: 27}], 'edited.mp4');
  assert.equal(media.src, 'edited.mp4');
  assert.equal(media.currentTime, 0);
  assert.equal(player.pendingSeek, true);
  media.readyState = 1;
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.currentTime, 0);
  player.start([{start: 120, end: 125}], 'original.mp4');
  assert.equal(media.src, 'original.mp4');
  media.readyState = 1;
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.currentTime, 120);
});

test('same-file replay reloads the decoder and retains the new start through metadata', () => {
  const {media, player} = fixture();
  media.src = 'edited.mp4';
  media.getAttribute = () => media.src;
  media.currentTime = 56.24;
  media.ended = true;
  player.start([{start: 0, end: 56.24}], 'edited.mp4');
  assert.equal(media.loadCount, 1);
  assert.equal(player.pendingSeek, true);
  media.readyState = 1;
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.currentTime, 0);
  media.tick(1.4);
  player.start([{start: 0, end: 56.24}], 'edited.mp4');
  assert.equal(media.loadCount, 2);
  assert.equal(player.pendingSeek, true);
});

test('natural end restores a fresh paused media state for native replay', () => {
  const {media, player, reports} = fixture();
  player.start([{start: 0, end: 56.24}]);
  media.currentTime = 56.24;
  media.ended = true;
  media.dispatchEvent(new Event('ended'));
  assert.equal(reports.at(-1).state, 'finished');
  assert.equal(media.loadCount, 1);
  assert.equal(media.currentTime, 0);
  assert.equal(media.paused, true);
  media.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(media.paused, true);
});

test('native replay reports playing and paused, then finishes without stale pause reports', () => {
  const {media, reports} = fixture();
  media.play();
  media.dispatchEvent(new Event('playing'));
  assert.equal(reports.at(-1).state, 'playing');
  media.pause();
  assert.equal(reports.at(-1).state, 'paused');
  media.play();
  media.dispatchEvent(new Event('playing'));
  media.currentTime = 56.24;
  media.ended = true;
  media.dispatchEvent(new Event('ended'));
  assert.equal(reports.at(-1).state, 'finished');
  assert.equal(media.currentTime, 0);
  assert.equal(media.paused, true);
  media.dispatchEvent(new Event('pause'));
  assert.equal(reports.at(-1).state, 'finished');
});

test('stop and reload clear native replay tracking before asynchronous media events', () => {
  const {media, player, reports} = fixture();
  for (const action of ['stop', 'reload']) {
    media.play();
    media.dispatchEvent(new Event('playing'));
    player[action]();
    media.dispatchEvent(new Event('pause'));
    media.dispatchEvent(new Event('waiting'));
    assert.equal(reports.at(-1).state, 'stopped');
    assert.equal(media.paused, true);
  }
});
