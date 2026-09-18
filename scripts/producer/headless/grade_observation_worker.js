/* Full ORIGINAL-source metadata decode. No scale, grade, trim, audio or network. */
const fs = require('node:fs');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const {TextDecoder} = require('node:util');
const INPUT = '/input/media';
const ENV = {PATH: '/usr/bin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8', TZ: 'UTC'};
const POLICY = 'sniper-private-grade-observation-v1';
const MAX_BYTES = 128 * 1024 ** 2;
const MAX_PIXELS = 37_324_800_000;
const V2_PROFILE = 'original-uhd-xvycc709-observation-v2';
const V1 = Object.freeze({version: 1, policy: POLICY, maxSourceBytes: 8 * 1024 ** 3,
  maxFrames: 1_296_000, maxWidth: 8192, maxHeight: 8192, maxDecodedPixels: MAX_PIXELS,
  maxWorkSeconds: 120, decoderThreads: 1, transfer: 'bt709'});
const V2 = Object.freeze({version: 2, policy: 'sniper-private-grade-observation-v2',
  maxSourceBytes: 16 * 1024 ** 3, maxFrames: 24_000, maxWidth: 3840, maxHeight: 2160,
  maxDecodedPixels: 199_065_600_000, maxWorkSeconds: 1200, decoderThreads: 4,
  transfer: 'iec61966-2-4'});
const BASE = ['-v', 'warning', '-err_detect', 'explode', '-threads', '1',
  '-protocol_whitelist', 'file,pipe'];
const DECODE_ARGS = [...BASE, '-select_streams', 'v:0', '-show_frames',
  '-of', 'default=noprint_wrappers=0:nokey=0', INPUT];
const clock = () => performance.now();
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

function profile(request) {
  if (request && Object.hasOwn(request, 'profile')) {
    if (request.profile !== V2_PROFILE || request.schemaVersion !== 2) throw Error('INVALID_PROFILE');
    return V2;
  }
  return V1;
}

function evidence(config) {
  if (config === V1) return {};
  const {maxSourceBytes, maxFrames, maxWidth, maxHeight, maxDecodedPixels,
    maxWorkSeconds, decoderThreads} = config;
  return {profile: V2_PROFILE, limits: {maxSourceBytes, maxFrames, maxWidth, maxHeight,
    maxDecodedPixels, maxWorkSeconds, decoderThreads, cpus: 4, memoryMiB: 768,
    maxRecordBytes: MAX_BYTES, cleanupSeconds: 90}};
}

function baseArgs(config) {
  return BASE.map((value, index) => index === 5 ? String(config.decoderThreads) : value);
}

function decodeArgs(config) {
  return [...baseArgs(config), ...DECODE_ARGS.slice(BASE.length)];
}

function validate(request) {
  const config = profile(request);
  const keys = config === V1 ? 'frameCount,sourceSha256,timeoutSeconds'
    : 'frameCount,profile,schemaVersion,sourceSha256,timeoutSeconds';
  if (!request || Array.isArray(request) || Object.keys(request).sort().join() !== keys
      || typeof request.sourceSha256 !== 'string' || !/^[a-f0-9]{64}$/.test(request.sourceSha256)
      || !Number.isSafeInteger(request.frameCount) || request.frameCount < 1
      || request.frameCount > config.maxFrames || !Number.isSafeInteger(request.timeoutSeconds)
      || request.timeoutSeconds < 30 || request.timeoutSeconds > config.maxWorkSeconds) throw Error('INVALID_REQUEST');
  return config;
}

function sourceHash(deadline, config) {
  const fd = fs.openSync(INPUT, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const before = fs.fstatSync(fd), hash = crypto.createHash('sha256');
    if (!before.isFile() || before.nlink !== 1 || before.size < 1 || before.size > config.maxSourceBytes) throw Error('UNSAFE_SOURCE');
    const buffer = Buffer.alloc(1024 * 1024);
    let size = 0, count;
    while ((count = fs.readSync(fd, buffer)) > 0) {
      if (clock() >= deadline) throw Error('WORK_DEADLINE');
      size += count;
      if (size > before.size) throw Error('SOURCE_GREW');
      hash.update(buffer.subarray(0, count));
    }
    const after = fs.fstatSync(fd), current = fs.lstatSync(INPUT);
    const fields = ['dev', 'ino', 'size', 'nlink', 'mtimeMs', 'ctimeMs'];
    if (size !== before.size || fields.some(key => before[key] !== after[key] || before[key] !== current[key])) throw Error('SOURCE_CHANGED');
    return hash.digest('hex');
  } finally { fs.closeSync(fd); }
}

function run(tool, args, deadline) {
  const remaining = deadline - clock();
  if (remaining <= 0) throw Error('WORK_DEADLINE');
  const result = cp.spawnSync(tool, args, {env: ENV, encoding: null,
    timeout: Math.max(1, Math.min(10000, remaining)), maxBuffer: 65536,
    killSignal: 'SIGKILL', stdio: ['ignore', 'pipe', 'pipe']});
  if (result.error || result.status !== 0 || result.stderr.length) {
    throw Error(`PROBE_REJECTED:${result.error?.code || result.status}:${result.stderr.toString('utf8').slice(0, 500)}`);
  }
  return result.stdout;
}

function probe(request, deadline) {
  const raw = run('/usr/bin/ffprobe', [...baseArgs(profile(request)), '-show_streams', '-show_format', '-of', 'json', INPUT], deadline);
  const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw));
  const proof = {sha256: sha(raw), bytes: raw.length};
  fs.writeFileSync('/scratch/probe.json', raw, {flag: 'wx', mode: 0o600});
  try { requireProbeClass(value, request); }
  catch (error) { error.probe = proof; throw error; }
  return proof;
}

function requireProbeClass(value, request) {
  const config = validate(request);
  if (!Array.isArray(value.streams) || value.streams.length > 32) throw Error('INVALID_STREAMS');
  const video = (value.streams || []).filter(row => row.codec_type === 'video');
  if (video.length !== 1) throw Error('ONE_VIDEO_REQUIRED');
  const row = video[0];
  if (!Number.isSafeInteger(row.width) || !Number.isSafeInteger(row.height)
      || row.width < 2 || row.height < 2 || row.width > config.maxWidth || row.height > config.maxHeight
      || row.width * row.height * request.frameCount > config.maxDecodedPixels) throw Error('FRAME_PIXEL_BUDGET');
  if (String(request.frameCount) !== row.nb_frames) throw Error('EXACT_DECLARED_FRAME_COUNT_REQUIRED');
  if (row.pix_fmt !== 'yuv420p' || row.color_range !== 'tv' || row.color_space !== 'bt709'
      || row.color_primaries !== 'bt709' || row.color_transfer !== config.transfer
      || (row.side_data_list || []).some(item => /mastering|content light|dovi|hdr/i.test(item.side_data_type || ''))) throw Error('UNSUPPORTED_STREAM_CLASS');
  if (config === V2) requireV2Probe(row);
}

function requireV2Probe(row) {
  if (row.width % 2 || row.height % 2 || row.codec_name !== 'h264'
      || (row.tags !== undefined && (!row.tags || Array.isArray(row.tags) || typeof row.tags !== 'object'))
      || Object.hasOwn(row.tags || {}, 'rotate')) throw Error('UNSUPPORTED_V2_GEOMETRY');
  const side = row.side_data_list || [];
  if (!Array.isArray(side) || side.length > 16 || side.some(item => !item
      || Object.keys(item).join() !== 'side_data_type'
      || item.side_data_type !== 'H.26[45] User Data Unregistered SEI message')) throw Error('UNSUPPORTED_V2_SIDE_DATA');
  const rates = [row.r_frame_rate, row.avg_frame_rate].map(exactRate);
  if (rates[0] !== rates[1]) throw Error('INCONSISTENT_SOURCE_RATE');
}

function exactRate(value) {
  if (typeof value !== 'string' || !/^[1-9][0-9]{0,8}\/[1-9][0-9]{0,8}$/.test(value)) throw Error('INVALID_SOURCE_RATE');
  const [n, d] = value.split('/').map(BigInt);
  if (n < d || n > 60n * d) throw Error('INVALID_SOURCE_RATE');
  let a = n, b = d;
  while (b) [a, b] = [b, a % b];
  return `${n / a}/${d / a}`;
}

function decode(request, deadline) {
  return new Promise((resolve, reject) => {
    const fd = fs.openSync('/scratch/frames.ffprobe', 'wx', 0o600);
    const child = cp.spawn('/usr/bin/ffprobe', decodeArgs(profile(request)),
      {env: ENV, stdio: ['ignore', 'pipe', 'pipe']});
    const state = {bytes: 0, frames: 0, stderrBytes: 0, stderr: '', partial: '', failure: null};
    const hash = crypto.createHash('sha256'), text = new TextDecoder('utf-8', {fatal: true});
    const fail = error => { state.failure ||= String(error.message || error); child.kill('SIGKILL'); };
    const timer = setTimeout(() => fail(Error('WORK_DEADLINE')), Math.max(1, deadline - clock()));
    child.on('error', fail);
    child.stdout.on('data', chunk => {
      try { consume(chunk, {fd, state, hash, text}, request); }
      catch (error) { fail(error); }
    });
    child.stderr.on('data', chunk => {
      state.stderrBytes += chunk.length;
      if (state.stderr.length < 8192) state.stderr += chunk.toString('utf8').slice(0, 8192 - state.stderr.length);
      fail(Error(state.stderrBytes > 65536 ? 'STDERR_BUDGET' : 'DECODER_WARNING_OR_ERROR'));
    });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      try { text.decode(); fs.fsyncSync(fd); } catch (error) { state.failure ||= String(error); }
      fs.closeSync(fd);
      const terminal = {exitCode: code, signal, stderrBytes: state.stderrBytes,
        stderr: state.stderr, frames: state.frames, bytes: state.bytes, sha256: hash.digest('hex'),
        reachedEof: code === 0 && !signal && !state.failure && state.partial === '',
        perFrameCorruptFlag: 'unavailable', perFrameDecodeErrorFlags: 'unavailable'};
      if (state.failure || !terminal.reachedEof || state.frames !== request.frameCount) {
        const error = Error(state.failure || 'INCOMPLETE_SOURCE_EOF'); error.terminal = terminal; reject(error);
      } else resolve(terminal);
    });
  });
}

function consume(chunk, context, request) {
  const {fd, state, hash, text} = context;
  state.bytes += chunk.length;
  if (state.bytes > MAX_BYTES) throw Error('FRAME_RECORD_BUDGET');
  let offset = 0;
  while (offset < chunk.length) {
    const written = fs.writeSync(fd, chunk, offset);
    if (written <= 0) throw Error('FRAME_RECORD_WRITE_STALLED');
    offset += written;
  }
  hash.update(chunk);
  state.partial += text.decode(chunk, {stream: true});
  const lines = state.partial.split('\n'); state.partial = lines.pop();
  for (const line of lines) {
    if (line.length > 32768) throw Error('FRAME_LINE_BUDGET');
    if (line === '[FRAME]') state.frames++;
  }
  if (state.partial.length > 32768 || state.frames > request.frameCount) throw Error('FRAME_COVERAGE_BUDGET');
}

async function observe(request) {
  const config = validate(request);
  const started = clock(), deadline = started + request.timeoutSeconds * 1000;
  const value = {schemaVersion: config.version, policy: config.policy, ...evidence(config), request, status: 'failed',
    gradeApplicable: false, deliveryApproved: false, decodedFrameFlagsAvailable: false,
    invocation: {executable: '/usr/bin/ffprobe', args: decodeArgs(config)}, timing: {}};
  try {
    value.sourceBeforeSha256 = sourceHash(deadline, config);
    if (value.sourceBeforeSha256 !== request.sourceSha256) throw Error('ADMITTED_SOURCE_HASH_MISMATCH');
    value.tool = {version: run('/usr/bin/ffprobe', ['-version'], deadline).toString('utf8').split('\n')[0],
      sha256: sha(fs.readFileSync('/usr/bin/ffprobe'))};
    value.probe = probe(request, deadline);
    const decodeStarted = clock();
    value.decoder = await decode(request, deadline);
    value.timing.decodeMs = Math.round(clock() - decodeStarted);
    value.sourceAfterSha256 = sourceHash(deadline, config);
    if (value.sourceAfterSha256 !== request.sourceSha256 || clock() >= deadline) throw Error('SOURCE_OR_DEADLINE_CHANGED');
    value.status = 'complete';
  } catch (error) {
    value.error = String(error.message).slice(0, 1000);
    if (error.probe) value.probe = error.probe;
    if (error.terminal) value.decoder = error.terminal;
  }
  value.timing.elapsedMs = Math.round(clock() - started);
  return value;
}

async function main() {
  let value;
  try { value = await observe(JSON.parse(process.argv[1])); }
  catch (error) { value = {status: 'failed', error: String(error.message)}; }
  fs.writeFileSync('/scratch/result.json.tmp', JSON.stringify(value) + '\n', {flag: 'wx', mode: 0o600});
  fs.renameSync('/scratch/result.json.tmp', '/scratch/result.json');
  setTimeout(() => {}, 30000);
}

module.exports = {validate, consume, observe, requireProbeClass, evidence, decodeArgs,
  DECODE_ARGS, POLICY, MAX_BYTES, MAX_PIXELS, V1, V2, V2_PROFILE};
if (!module.parent) void main();
