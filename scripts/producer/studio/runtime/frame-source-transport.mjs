/** Experimental same-origin transport; only native extraction paths are admitted. */
import { createHash, randomBytes } from 'node:crypto';
import { closeSync, constants, createReadStream, fstatSync, openSync,
  realpathSync, statSync } from 'node:fs';
import { basename, dirname, extname, isAbsolute, join } from 'node:path';
import { Readable } from 'node:stream';

export const FRAME_PREFIX = '/__sniper_native_frame/';
export const NATIVE_SOURCE_FRAME_CLOCK = 'sniper-zero-clock-v1';

/** Cover every positive sample interval without adding a frame for float noise. */
export function nativeSourceFrameCount(duration, fps) {
  const frames = duration * fps;
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(fps) || fps <= 0
      || !Number.isFinite(frames) || frames > Number.MAX_SAFE_INTEGER) {
    throw new RangeError('Native extraction requires a finite positive frame clock');
  }
  return Math.max(1, Math.ceil(frames - 1e-7));
}
const IMAGE_TYPES = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg' };
const MAX_FRAME_BYTES = 64 * 1024 * 1024;
const MAX_REGISTERED_FRAMES = 100000;

function identity(stat) {
  return [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].map(String).join(':');
}

function openImage(path) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = fstatSync(fd, { bigint: true });
    if (!stat.isFile() || stat.size <= 0n || stat.size > BigInt(MAX_FRAME_BYTES)) {
      throw new Error('Frame source must be a nonempty bounded regular image');
    }
    return { fd, stat, identity: identity(stat) };
  } catch (error) {
    closeSync(fd);
    throw error;
  }
}

export class NativeFrameTransport {
  /** Construct one server-owned registry without opening sockets or source files. */
  constructor() {
    this.secret = randomBytes(32).toString('hex');
    this.roots = null;
    this.rootAliases = new Map();
    this.entries = new Map();
    this.streams = new Set();
    this.descriptors = new Set();
    this.closed = false;
    this.failure = null;
    this.counters = { registrations: 0, requests: 0, completed: 0, head: 0,
      rejected: 0, errors: 0, aborted: 0, peakStreams: 0, peakSourceDescriptors: 0,
      bytes: 0, base64Fallbacks: 0 };
  }

  /** Called only by the native orchestrator, using actual extraction result roots. */
  configure(extractionRoots) {
    this.assertHealthy();
    if (this.roots !== null || !Array.isArray(extractionRoots) || !extractionRoots.length) {
      throw new Error('Frame transport requires one explicit nonempty root configuration');
    }
    this.roots = new Map(extractionRoots.map((root) => {
      const canonical = realpathSync(root);
      const stat = statSync(canonical, { bigint: true });
      if (!isAbsolute(root) || !stat.isDirectory()) throw new Error('Invalid extraction root');
      this.rootAliases.set(root, canonical);
      this.rootAliases.set(canonical, canonical);
      return [canonical, `${stat.dev}:${stat.ino}`];
    }));
  }

  /** Prevent traversal, parent substitution and paths not admitted by frameLookup. */
  validatePath(path) {
    if (!this.roots || !isAbsolute(path) || !IMAGE_TYPES[extname(path).toLowerCase()]) {
      throw new Error('Unconfigured or invalid extracted frame path');
    }
    const parent = this.rootAliases.get(dirname(path));
    if (!parent) throw new Error('Frame source has no admitted extraction-root alias');
    const canonical = realpathSync(path);
    const expected = this.roots.get(parent);
    const actual = statSync(parent, { bigint: true });
    if (!expected || `${actual.dev}:${actual.ino}` !== expected ||
        realpathSync(dirname(path)) !== parent || canonical !== join(parent, basename(path))) {
      throw new Error('Frame source escaped or replaced its canonical extraction root: ' +
        JSON.stringify({ suppliedPath: path, canonicalPath: canonical, roots: [...this.roots.keys()] }));
    }
    return canonical;
  }

  /** Return a short exact-page-origin URL or throw; never fall back to base64. */
  resolve(framePath) {
    this.assertHealthy();
    const path = this.validatePath(framePath);
    const token = createHash('sha256').update(this.secret).update(path).digest('hex');
    if (this.entries.has(token)) return FRAME_PREFIX + token;
    if (this.entries.size >= MAX_REGISTERED_FRAMES) throw new Error('Frame registry limit exceeded');
    const file = this.openFrame(path);
    this.closeFrame(file.fd);
    this.entries.set(token, { path, source: framePath, identity: file.identity,
      mime: IMAGE_TYPES[extname(path).toLowerCase()] });
    this.counters.registrations++;
    if (this.counters.registrations % 256 === 0) this.report('progress');
    return FRAME_PREFIX + token;
  }

  /** Closed/malformed namespace requests never fall through to project serving. */
  handle(request) {
    const pathname = new URL(request.url).pathname;
    const token = pathname.slice(FRAME_PREFIX.length);
    if (this.closed || !pathname.startsWith(FRAME_PREFIX) || !/^[a-f0-9]{64}$/.test(token)) {
      return this.reject(404);
    }
    const entry = this.entries.get(token);
    if (!entry) return this.reject(404);
    if (!['GET', 'HEAD'].includes(request.method)) return this.reject(405);
    this.counters.requests++;
    try {
      this.assertHealthy();
      if (this.validatePath(entry.source) !== entry.path) throw new Error('Frame alias target changed');
      return this.respond(request, entry);
    } catch (error) {
      this.fail(error);
      return new Response('Frame source unavailable', { status: 500, headers: { 'Cache-Control': 'no-store' } });
    }
  }

  /** Open and validate the same descriptor that supplies the response bytes. */
  respond(request, entry) {
    const file = this.openFrame(entry.path);
    let ownsDescriptor = true;
    try {
      if (file.identity !== entry.identity) throw new Error('Registered frame identity changed');
      const headers = { 'Content-Type': entry.mime, 'Content-Length': String(file.stat.size),
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' };
      if (request.method === 'HEAD') {
        this.counters.head++;
        return new Response(null, { status: 200, headers });
      }
      const stream = createReadStream(entry.path, { fd: file.fd, autoClose: true });
      ownsDescriptor = false;
      this.trackStream(stream, request, Number(file.stat.size), file.fd);
      try {
        return new Response(Readable.toWeb(stream), { status: 200, headers });
      } catch (error) {
        stream.destroy(error);
        throw error;
      }
    } finally {
      if (ownsDescriptor) this.closeFrame(file.fd);
    }
  }

  /** Bound descriptor lifetime for normal completion, disconnect and shutdown. */
  trackStream(stream, request, size, fd) {
    this.streams.add(stream);
    this.counters.peakStreams = Math.max(this.counters.peakStreams, this.streams.size);
    const abort = () => {
      this.counters.aborted++;
      stream.destroy(new Error('Frame response aborted'));
    };
    request.signal.addEventListener('abort', abort, { once: true });
    stream.once('end', () => {
      this.counters.completed++;
      this.counters.bytes += size;
    });
    stream.once('error', (error) => this.fail(error));
    stream.once('close', () => {
      this.descriptors.delete(fd);
      this.streams.delete(stream);
      request.signal.removeEventListener('abort', abort);
    });
    if (request.signal.aborted) abort();
  }

  openFrame(path) {
    const file = openImage(path);
    this.descriptors.add(file.fd);
    this.counters.peakSourceDescriptors = Math.max(this.counters.peakSourceDescriptors, this.descriptors.size);
    return file;
  }

  closeFrame(fd) {
    closeSync(fd);
    this.descriptors.delete(fd);
  }

  reject(status) {
    this.counters.rejected++;
    return new Response('Not found', { status, headers: { 'Cache-Control': 'no-store' } });
  }

  fail(error) {
    this.counters.errors++;
    this.failure ??= error instanceof Error ? error : new Error(String(error));
  }

  assertHealthy() {
    if (this.closed) throw new Error('Frame transport is closed');
    if (this.failure) throw new Error(`Frame transport failed: ${this.failure.message}`);
  }

  stats() {
    return { ...this.counters, entries: this.entries.size, activeStreams: this.streams.size,
      activeSourceDescriptors: this.descriptors.size,
      closed: this.closed, failed: this.failure !== null, mode: 'same-origin-url' };
  }

  report(event) {
    console.info('[NativeFrameTransport]', JSON.stringify({ event, atUnixMs: Date.now(), ...this.stats() }));
  }

  /** Existing native file server owns and invokes this on every cleanup path. */
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const stream of this.streams) stream.destroy();
    this.entries.clear();
    this.roots?.clear();
    this.rootAliases.clear();
    this.report('close');
  }
}
