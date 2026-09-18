/* Fixed-path, bounded color sampling inside the approved networkless image. */
const fs = require('node:fs');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const clock = () => performance.now();
const ENV = {PATH: '/usr/bin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8', TZ: 'UTC'};
const INPUT = '/input/media';

function validate(request) {
  if (Object.keys(request).sort().join() !== 'samples,sourceSha256,timeoutSeconds'
      || !/^[a-f0-9]{64}$/.test(request.sourceSha256)
      || !Number.isInteger(request.timeoutSeconds) || request.timeoutSeconds < 30
      || request.timeoutSeconds > 120 || !Array.isArray(request.samples)
      || request.samples.length < 1 || request.samples.length > 64) throw Error('INVALID_REQUEST');
  const ids = new Set();
  for (const sample of request.samples) {
    if (typeof sample.id !== 'string' || sample.id.length > 200 || ids.has(sample.id)
        || !Number.isFinite(sample.sourceTime) || sample.sourceTime < 0
        || sample.sourceTime > 21600) throw Error('INVALID_SAMPLE');
    ids.add(sample.id);
  }
}

function run(tool, args, context, limit = 8000) {
  const remaining = context.deadline - clock();
  if (remaining <= 0) throw Error('ATTEMPT_TIMEOUT');
  const result = cp.spawnSync(tool, args, {env: ENV, encoding: null,
    timeout: Math.max(1, Math.min(limit, remaining)), maxBuffer: 1048576,
    killSignal: 'SIGKILL', stdio: ['ignore', 'pipe', 'pipe']});
  if (result.error || result.status !== 0) {
    throw Error(result.error?.code || `COMMAND_FAILED_${result.signal || result.status}`);
  }
  return result;
}

function hashBytes(fd, stat, context) {
  const hash = crypto.createHash('sha256'), buffer = Buffer.alloc(1048576);
  let bytes = 0, count;
  while ((count = fs.readSync(fd, buffer)) !== 0) {
    if (clock() > context.deadline) throw Error('ATTEMPT_TIMEOUT');
    bytes += count;
    if (bytes > stat.size) throw Error('SOURCE_GREW');
    hash.update(buffer.subarray(0, count));
  }
  const after = fs.fstatSync(fd);
  if (bytes !== stat.size || after.mtimeMs !== stat.mtimeMs || after.ctimeMs !== stat.ctimeMs) throw Error('SOURCE_CHANGED');
  return hash.digest('hex');
}

function sourceHash(context) {
  const fd = fs.openSync(INPUT, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.nlink !== 1 || stat.size <= 0 || stat.size > 8 * 1024 ** 3) throw Error('UNSAFE_SOURCE');
    return hashBytes(fd, stat, context);
  } finally { fs.closeSync(fd); }
}

function supported(probe) {
  const video = (probe.streams || []).filter(row => row.codec_type === 'video');
  if (video.length !== 1) return false;
  const row = video[0];
  const hdr = (row.side_data_list || []).some(item => /mastering|content light|dovi|hdr/i.test(item.side_data_type || ''));
  return row.color_range === 'tv' && row.color_space === 'bt709'
    && row.color_transfer === 'bt709' && row.color_primaries === 'bt709'
    && row.pix_fmt === 'yuv420p' && [undefined, null, 0, 8, '0', '8'].includes(row.bits_per_raw_sample)
    && !hdr;
}

function percentile(histogram, count, fraction) {
  let total = 0;
  for (let index = 0; index < histogram.length; index++) {
    total += histogram[index];
    if (total >= Math.max(1, Math.ceil(count * fraction))) return index;
  }
  throw Error('EMPTY_HISTOGRAM');
}

function statistics(raw, pixels) {
  if (raw.length !== pixels * 3 || pixels < 1 || pixels > 320 * 320) throw Error('FRAME_SIZE');
  const histogram = Array(256).fill(0);
  let y = 0, u = 0, v = 0, black = 0, white = 0;
  for (let index = 0; index < pixels; index++) {
    const value = raw[index];
    histogram[value]++; y += value; u += raw[pixels + index]; v += raw[2 * pixels + index];
    if (value <= 16) black++;
    if (value >= 235) white++;
  }
  return {yMin: percentile(histogram, pixels, 0), yP10: percentile(histogram, pixels, 0.1),
    yMedian: percentile(histogram, pixels, 0.5), yMean: y / pixels,
    yP90: percentile(histogram, pixels, 0.9), yMax: percentile(histogram, pixels, 1),
    uMean: u / pixels, vMean: v / pixels,
    nominalBlackFraction: black / pixels, nominalWhiteFraction: white / pixels};
}

function frameFacts(text) {
  const lines = text.split('\n').filter(line => /^\[showinfo@source\s+@/.test(line));
  const first = lines.findIndex(line => /\bn:\s*0\s+pts:/.test(line));
  if (first < 0) throw Error('MISSING_SOURCE_FRAME_METADATA');
  const next = lines.findIndex((line, index) => index > first && /\bn:\s*\d+\s+pts:/.test(line));
  const block = lines.slice(first, next < 0 ? undefined : next).join('\n');
  const value = {pixelFormat: block.match(/\bfmt:(\S+)/)?.[1] ?? null};
  for (const [key, field] of [['range', 'color_range'], ['matrix', 'color_space'],
    ['primaries', 'color_primaries'], ['transfer', 'color_trc']]) {
    value[key] = block.match(new RegExp(`\\b${field}:(\\S+)`))?.[1] ?? null;
  }
  value.hdrSignaled = /mastering|content light|dovi|hdr/i.test(block)
    || ['smpte2084', 'arib-std-b67'].includes(value.transfer);
  return value;
}

function supportedFrame(value) {
  return value.pixelFormat === 'yuv420p' && value.range === 'tv'
    && value.matrix === 'bt709' && value.primaries === 'bt709'
    && value.transfer === 'bt709' && value.hdrSignaled === false;
}

function sampleFrame(sample, probe, context) {
  const begin = clock();
  const base = {id: sample.id, requestedTime: sample.sourceTime};
  if (!supported(probe)) return {...base, status: 'skipped', error: 'UNSUPPORTED_COLOR_METADATA', elapsedMs: 0};
  try {
    const filters = 'showinfo@source,scale=320:320:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=area:in_range=tv:out_range=tv,format=yuv444p,showinfo@sample';
    const result = run('/usr/bin/ffmpeg', ['-nostdin', '-hide_banner', '-v', 'info',
      '-nostats', '-threads', '1', '-filter_threads', '1', '-protocol_whitelist', 'file,pipe',
      '-ss', String(sample.sourceTime), '-copyts', '-i', INPUT, '-map', '0:v:0', '-an',
      '-vf', filters, '-frames:v', '1', '-threads', '1', '-f', 'rawvideo', 'pipe:1'], context);
    const text = result.stderr.toString('utf8');
    const frameMetadata = frameFacts(text);
    if (!supportedFrame(frameMetadata)) return {...base, frameMetadata, status: 'skipped',
      error: 'UNSUPPORTED_SOURCE_FRAME_METADATA', elapsedMs: Math.round(clock() - begin)};
    const info = text.split('\n').filter(line => /^\[showinfo@sample\s+@/.test(line)).join('\n')
      .match(/\bn:\s*0\s+pts:\s*-?\d+\s+pts_time:([-+\d.e]+).*?\bs:(\d+)x(\d+)/);
    if (!info) throw Error('MISSING_ACTUAL_FRAME_PTS');
    const video = probe.streams.find(row => row.codec_type === 'video');
    const origin = Number(video.start_time || 0), pts = Number(info[1]);
    if (!Number.isFinite(origin) || !Number.isFinite(pts)) throw Error('INVALID_ACTUAL_FRAME_PTS');
    return {...base, frameMetadata, status: 'sampled', actualPtsTime: pts, actualSourceTime: pts - origin,
      width: Number(info[2]), height: Number(info[3]),
      statistics: statistics(result.stdout, Number(info[2]) * Number(info[3])),
      elapsedMs: Math.round(clock() - begin)};
  } catch (error) {
    return {...base, status: 'failed', error: String(error.message).slice(0, 160), elapsedMs: Math.round(clock() - begin)};
  }
}

function analyze(request) {
  validate(request);
  const started = clock(), context = {deadline: clock() + request.timeoutSeconds * 1000};
  const value = {schemaVersion: 1, sourceSha256: request.sourceSha256, probe: null, samples: [], tools: {}, timing: {}};
  try {
    if (sourceHash(context) !== request.sourceSha256) throw Error('ADMITTED_SOURCE_HASH_MISMATCH');
    const raw = run('/usr/bin/ffprobe', ['-v', 'error', '-protocol_whitelist', 'file,pipe',
      '-show_streams', '-show_format', '-of', 'json', INPUT], context).stdout;
    if (raw.length > 24576) throw Error('PROBE_METADATA_LIMIT');
    value.probe = JSON.parse(raw.toString('utf8'));
    for (const name of ['ffmpeg', 'ffprobe']) {
      value.tools[name] = run(`/usr/bin/${name}`, ['-version'], context).stdout.toString('utf8').split('\n')[0];
    }
    value.samples = request.samples.map(sample => sampleFrame(sample, value.probe, context));
    if (sourceHash(context) !== request.sourceSha256) throw Error('SOURCE_CHANGED_DURING_ANALYSIS');
    value.status = value.samples.every(row => row.status === 'sampled') ? 'complete' : 'partial';
  } catch (error) { value.status = 'failed'; value.error = String(error.message).slice(0, 160); }
  value.timing.elapsedMs = Math.round(clock() - started);
  return value;
}

function main() {
  let value;
  try { value = analyze(JSON.parse(process.argv[1])); }
  catch (error) { value = {status: 'failed', error: String(error.message).slice(0, 160)}; }
  const raw = JSON.stringify(value) + '\n';
  if (Buffer.byteLength(raw) > 65536) throw Error('RESULT_SIZE_LIMIT');
  fs.writeFileSync('/scratch/result.json.tmp', raw, {flag: 'wx', mode: 0o600});
  fs.renameSync('/scratch/result.json.tmp', '/scratch/result.json');
  setTimeout(() => {}, 30000);
}

module.exports = {analyze, supported, statistics, sampleFrame, validate, frameFacts, supportedFrame};
if (!module.parent) main();
