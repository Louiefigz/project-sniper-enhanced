/** Play original passages or an edited file with visible loading and recovery. */
export class SelectionPlayback {
  constructor(media, onChange) {
    this.media = media;
    this.onChange = onChange;
    this.ranges = [];
    this.step = 0;
    this.revision = 0;
    this.pendingSeek = false;
    this.recoveryTime = null;
    this.nativePlayback = false;
    media.addEventListener('loadedmetadata', () => {
      if (this.pendingSeek) this.seek();
    });
    media.addEventListener('timeupdate', () => this.advance());
    media.addEventListener('ended', () => {
      this.advance();
      if (this.nativePlayback) this.stop('finished');
      // Reset the exhausted decoder before the native controls replay the file.
      if (!this.ranges.length) media.load();
    });
    media.addEventListener('playing', () => this.reportActive('playing'));
    media.addEventListener('waiting', () => this.reportActive('loading'));
    media.addEventListener('pause', () => this.reportActive('paused'));
    media.addEventListener('error', () => this.report('error',
      'The source video could not load. Check the media file and reload this page.'));
  }

  report(state, message = '') {
    this.onChange({state, message, range: this.ranges[this.step],
      step: this.step, total: this.ranges.length});
  }

  reportActive(state) {
    if (state === 'playing' && !this.ranges.length) this.nativePlayback = true;
    if (this.ranges.length || this.nativePlayback) this.report(state);
  }

  start(ranges, source = null) {
    this.revision += 1;
    this.nativePlayback = false;
    this.media.pause();
    if (source) {
      if (this.media.getAttribute('src') !== source) this.media.src = source;
      // A warm, same-file seek can report ready while displaying a black frame.
      // Explicit selection playback starts with a fresh decoder, including replay.
      this.media.load();
    }
    this.ranges = ranges.slice();
    this.step = 0;
    this.recoveryTime = null;
    this.pendingSeek = true;
    this.report('loading');
    this.resume();
  }

  seek() {
    if (!this.ranges.length || this.media.readyState < 1) return false;
    try {
      this.media.currentTime = this.recoveryTime ?? this.ranges[this.step].start;
      this.recoveryTime = null;
      this.pendingSeek = false;
      return true;
    } catch (error) {
      this.report('error', `Could not seek to this passage: ${error.message}`);
      return false;
    }
  }

  resume() {
    if (!this.ranges.length) return;
    const revision = this.revision;
    if (this.pendingSeek && this.media.readyState >= 1 && !this.seek()) return;
    // Keep play() inside the button gesture, even before metadata is available.
    try {
      Promise.resolve(this.media.play()).catch(error => this.playFailed(error, revision));
    } catch (error) {
      this.playFailed(error, revision);
    }
  }

  playFailed(error, revision) {
    if (revision !== this.revision || !this.ranges.length) return;
    const blocked = error.name === 'NotAllowedError';
    this.report(blocked ? 'blocked' : 'error', blocked
      ? 'Playback was blocked. Click Resume selection below.'
      : `Playback could not start: ${error.message}. Click Resume selection to retry.`);
  }

  reload() {
    this.revision += 1;
    this.nativePlayback = false;
    const range = this.ranges[this.step];
    this.recoveryTime = range
      ? Math.max(range.start, Math.min(this.media.currentTime, range.end - 0.05)) : null;
    this.pendingSeek = Boolean(range);
    this.media.load();
    this.report(range ? 'loading' : 'stopped', range
      ? 'Reloading the video at your current passage…' : 'Video reloaded. Choose a selection to play.');
    if (range) this.resume();
  }

  advance() {
    if (!this.ranges.length || this.pendingSeek || this.media.seeking) return;
    if (this.media.paused && !this.media.ended) return;
    if (this.media.currentTime < this.ranges[this.step].end) return;
    this.step += 1;
    if (this.step >= this.ranges.length) {
      this.stop('finished');
      return;
    }
    this.pendingSeek = true;
    this.report('loading');
    this.resume();
  }

  stop(state = 'stopped') {
    this.revision += 1;
    this.nativePlayback = false;
    this.ranges = [];
    this.pendingSeek = false;
    this.recoveryTime = null;
    this.media.pause();
    this.report(state);
  }
}
