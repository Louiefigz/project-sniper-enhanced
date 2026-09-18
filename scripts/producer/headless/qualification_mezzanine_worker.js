"use strict";

// Runs only inside the approved renderer image. The host never asks its own
// ffmpeg/ffprobe installation to parse an over-cap external source.
const child = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");

const SOURCE = "/input/source";
const OUTPUT = "/output/qualified.mp4";
const RESULT = "/output/result.json";
const FFMPEG = "/usr/bin/ffmpeg";
const FFPROBE = "/usr/bin/ffprobe";
const CAP_BYTES = Number(process.argv[1]);
const MAX_SOURCE_BYTES = Number(process.argv[2]);
const TIMEOUT_MS = Number(process.argv[3]) * 1000;
const TARGET_FPS = Number(process.argv[4]);
const AUDIO_BPS = 192000;
let failureContext = null;

function fail(message) {
  const text = String(message && message.message ? message.message : message);
  publish({schemaVersion: 1, ok: false, code: "QUALIFICATION_REJECTED",
    message: text.slice(-800), details: failureContext});
}

function publish(value) {
  const temporary = `${RESULT}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value)}\n`,
    {encoding: "utf8", flag: "wx", mode: 0o600});
  fs.renameSync(temporary, RESULT);
  setTimeout(() => {}, 30000);
}

function run(program, argv, timeout = TIMEOUT_MS,
  maxBuffer = 8 * 1024 * 1024) {
  const result = child.spawnSync(program, argv, {
    encoding: "utf8", timeout, maxBuffer,
    env: {PATH: "/usr/bin:/bin", LANG: "C.UTF-8", LC_ALL: "C.UTF-8",
      TZ: "UTC", TMPDIR: "/scratch"},
  });
  if (result.error) throw result.error;
  const stderr = String(result.stderr || "");
  if (result.status !== 0 || stderr.trim() !== "") {
    throw new Error(`${program} exited ${result.status}: ${
      String(stderr || result.stdout).slice(-600)}`);
  }
  return String(result.stdout);
}

function sha256File(path) {
  const info = fs.statSync(path);
  if (!info.isFile() || info.size <= 0 || info.size > 512 * 1024 * 1024) {
    throw new Error(`tool binary is not one bounded file: ${path}`);
  }
  return {sha256: crypto.createHash("sha256")
    .update(fs.readFileSync(path)).digest("hex"), sizeBytes: info.size};
}

function toolFact(path) {
  const resolvedPath = fs.realpathSync(path);
  const versionArgv = [resolvedPath, "-version"];
  const versionOutput = run(resolvedPath, ["-version"], 15000);
  return {path, resolvedPath, ...sha256File(resolvedPath), versionArgv,
    versionOutput, versionOutputSha256: crypto.createHash("sha256")
      .update(versionOutput, "utf8").digest("hex")};
}

function probe(path, includeFrames = false) {
  const argv = ["-v", "error", "-count_frames", "-count_packets",
    "-show_streams", "-show_format"];
  if (includeFrames) argv.push("-show_frames", "-show_entries",
    "stream:format:frame=media_type,pts,pkt_pts,best_effort_timestamp,"
      + "duration,pkt_duration,nb_samples,interlaced_frame,top_field_first");
  argv.push("-of", "json", path);
  return {argv: [FFPROBE, ...argv],
    document: JSON.parse(run(FFPROBE, argv, TIMEOUT_MS, 64 * 1024 * 1024))};
}

function integer(value, label) {
  if (!/^[1-9][0-9]*$/.test(String(value || ""))) {
    throw new Error(`${label} is not a positive integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) throw new Error(`${label} is too large`);
  return parsed;
}

function rate(value, label) {
  const match = /^([1-9][0-9]*)\/([1-9][0-9]*)$/.exec(String(value || ""));
  if (!match) throw new Error(`${label} is not one positive rational rate`);
  const numerator = integer(match[1], `${label} numerator`);
  const denominator = integer(match[2], `${label} denominator`);
  return {numerator, denominator, text: `${numerator}/${denominator}`};
}

function sameRate(left, right) {
  return left.numerator * right.denominator ===
    right.numerator * left.denominator;
}

function frameInteger(row, names, label) {
  const values = names.filter(name => row[name] !== undefined)
    .map(name => nonNegativeInteger(row[name], `${label} ${name}`));
  if (values.length < 1 || values.some(value => value !== values[0])) {
    throw new Error(`${label} fields are missing or disagree`);
  }
  return values[0];
}

function roundedRatio(numerator, denominator) {
  if (!Number.isSafeInteger(numerator) || !Number.isSafeInteger(denominator) ||
      denominator <= 0) throw new Error("frame conversion exceeds exact integers");
  return Math.floor((numerator + Math.floor(denominator / 2)) / denominator);
}

function colorDecision(video, fpsText, targetFrames) {
  const tags = {range: video.color_range || "unknown",
    space: video.color_space || "unknown",
    transfer: video.color_transfer || "unknown",
    primaries: video.color_primaries || "unknown",
    pixelFormat: video.pix_fmt || "unknown"};
  const hdr = ["smpte2084", "arib-std-b67"].includes(tags.transfer) ||
    tags.primaries === "bt2020";
  if (tags.range !== "tv") {
    throw new Error("source lacks an exact limited-range color declaration");
  }
  const geometry = `scale=1920:1080:force_original_aspect_ratio=decrease:` +
    `flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,` +
    `setsar=1,fps=fps=${fpsText}:start_time=0:round=near,` +
    `trim=end_frame=${targetFrames},setpts=PTS-STARTPTS,format=yuv420p`;
  if (hdr) {
    const filter = "zscale=t=linear:npl=100,format=gbrpf32le," +
      "zscale=p=bt709,tonemap=tonemap=hable:desat=0," +
      `zscale=t=bt709:m=bt709:r=tv,${geometry}`;
    return {hdrDetected: true, mode: "tone-map-hdr-to-bt709-sdr",
      sourceTags: tags, targetTags: targetTags(), filter};
  }
  const extendedBt709 = tags.space === "bt709" &&
    tags.transfer === "iec61966-2-4" && tags.primaries === "bt709";
  if (extendedBt709) {
    const filter = "zscale=t=linear:npl=100,format=gbrpf32le," +
      "zscale=p=bt709:t=bt709:m=bt709:r=tv," + geometry;
    return {hdrDetected: false,
      mode: "normalize-xvycc-bt709-to-bt709-sdr",
      sourceTags: tags, targetTags: targetTags(), filter};
  }
  if (![tags.space, tags.transfer, tags.primaries].every(
      value => value === "bt709")) {
    throw new Error("SDR source lacks an exact BT.709 color declaration");
  }
  return {hdrDetected: false, mode: "retain-bt709-sdr",
    sourceTags: tags, targetTags: targetTags(), filter: geometry};
}

function targetTags() {
  return {range: "tv", space: "bt709", transfer: "bt709",
    primaries: "bt709", pixelFormat: "yuv420p"};
}

function sourceFacts(probeResult) {
  const streams = probeResult.document.streams || [];
  const videos = streams.filter(row => row.codec_type === "video");
  const audios = streams.filter(row => row.codec_type === "audio");
  const format = probeResult.document.format || {};
  if (videos.length !== 1 || audios.length !== 1) {
    throw new Error("qualification requires exactly one video and one audio stream");
  }
  if (!String(audios[0].codec_name || "").startsWith("pcm_")) {
    throw new Error("qualification source audio must be exact PCM");
  }
  const sizeBytes = integer(format.size, "source size");
  if (sizeBytes <= CAP_BYTES || sizeBytes > MAX_SOURCE_BYTES) {
    throw new Error("source is not strictly over-cap and within qualification bounds");
  }
  const video = videos[0], sourceRate = rate(video.r_frame_rate, "source rate");
  const average = rate(video.avg_frame_rate, "source average rate");
  if (!sameRate(sourceRate, average)) throw new Error("source is not exact CFR");
  const frames = integer(video.nb_read_frames || video.nb_frames,
    "source decoded frame count");
  if (video.nb_frames && integer(video.nb_frames, "source declared frames") !== frames) {
    throw new Error("source declared and decoded frame counts disagree");
  }
  const durationSeconds = Number(format.duration);
  const frameDuration = frames * sourceRate.denominator / sourceRate.numerator;
  if (!Number.isFinite(durationSeconds) ||
      Math.abs(durationSeconds - frameDuration) > 1 / (sourceRate.numerator /
        sourceRate.denominator)) {
    throw new Error("source duration differs from its exact frame clock");
  }
  const clock = sourceFrameClock(probeResult.document, video, sourceRate, frames);
  const audioClock = sourceAudioClock(
    probeResult.document, audios[0], sourceRate, frames);
  return {sizeBytes, durationSeconds, width: integer(video.width, "source width"),
    height: integer(video.height, "source height"), videoCodec: video.codec_name,
    audioCodec: audios[0].codec_name, audioSampleRate: audios[0].sample_rate,
    audioChannels: audios[0].channels, sourceRate, frames, video, clock,
    audioClock};
}

function cadenceDecision(source) {
  const numerator = source.frames * TARGET_FPS * source.sourceRate.denominator;
  const denominator = source.sourceRate.numerator;
  const targetFrames = roundedRatio(numerator, denominator);
  const sourceDuration = source.frames * source.sourceRate.denominator /
    source.sourceRate.numerator;
  const targetDuration = targetFrames / TARGET_FPS;
  return {mode: "declared-palmier-integer-rate-approximation",
    approvalPolicy: "sniper-palmier-project-rate-v1",
    sourceRate: source.sourceRate.text, targetRate: `${TARGET_FPS}/1`,
    sourceFrames: source.frames, targetFrames,
    frameRounding: "nearest-target-frame-half-up",
    sourceDurationSeconds: sourceDuration,
    targetDurationSeconds: targetDuration,
    durationDeltaSeconds: targetDuration - sourceDuration};
}

try {
  if (!Number.isSafeInteger(CAP_BYTES) || !Number.isSafeInteger(MAX_SOURCE_BYTES) ||
      !Number.isSafeInteger(TIMEOUT_MS) || ![24, 25, 30, 50, 60].includes(TARGET_FPS)) {
    throw new Error("qualification worker limits are invalid");
  }
  const tools = {ffmpeg: toolFact(FFMPEG), ffprobe: toolFact(FFPROBE)};
  const sourceHashBefore = mediaHash(SOURCE);
  const sourceProbe = probe(SOURCE, true);
  const sourceStreams = sourceProbe.document.streams || [];
  const sourceFrames = sourceProbe.document.frames || [];
  failureContext = {sourceProbeDiagnostics: {
    streamTypes: sourceStreams.map(row => row.codec_type),
    videoFieldOrder: (sourceStreams.find(
      row => row.codec_type === "video") || {}).field_order || "not-reported",
    decodedVideoFrames: sourceFrames.filter(
      row => row.media_type === "video").length,
    decodedAudioFrames: sourceFrames.filter(
      row => row.media_type === "audio").length,
  }};
  const source = sourceFacts(sourceProbe);
  failureContext = {
    source: {
      sizeBytes: source.sizeBytes, durationSeconds: source.durationSeconds,
      width: source.width, height: source.height,
      videoCodec: source.videoCodec, audioCodec: source.audioCodec,
      audioSampleRate: source.audioSampleRate,
      audioChannels: source.audioChannels, rate: source.sourceRate.text,
      frames: source.frames, ...source.clock, sourceAudio: source.audioClock,
    },
    colorTags: {
      range: source.video.color_range || "unknown",
      space: source.video.color_space || "unknown",
      transfer: source.video.color_transfer || "unknown",
      primaries: source.video.color_primaries || "unknown",
      pixelFormat: source.video.pix_fmt || "unknown",
    },
  };
  if (sourceHashBefore.sizeBytes !== source.sizeBytes) {
    throw new Error("source probe size differs from mounted-byte hash");
  }
  const cadence = cadenceDecision(source);
  const color = colorDecision(
    source.video, cadence.targetRate, cadence.targetFrames);
  const audio = audioDecision(cadence);
  const transcode = ffmpegArgv(cadence, color, audio);
  run(FFMPEG, transcode.args);
  const sourceHashAfter = mediaHash(SOURCE);
  if (sourceHashAfter.sha256 !== sourceHashBefore.sha256 ||
      sourceHashAfter.sizeBytes !== sourceHashBefore.sizeBytes) {
    throw new Error("mounted source changed during qualification");
  }
  const outputProbe = probe(OUTPUT, true);
  const audioFrames = decodedAudioSamples(
    outputProbe.document, outputProbe.argv);
  const output = validateOutput(outputProbe, audioFrames, cadence, audio);
  publish({schemaVersion: 1, ok: true, tools,
    sourceProbe: {argv: sourceProbe.argv, facts: {
      sizeBytes: source.sizeBytes, durationSeconds: source.durationSeconds,
      width: source.width, height: source.height, videoCodec: source.videoCodec,
      audioCodec: source.audioCodec, audioSampleRate: source.audioSampleRate,
      audioChannels: source.audioChannels, sha256: sourceHashBefore.sha256,
      postTranscodeSha256: sourceHashAfter.sha256,
      rate: source.sourceRate.text, frames: source.frames, ...source.clock,
      sourceAudio: source.audioClock}},
    cadenceDecision: cadence, colorDecision: color, audioDecision: audio,
    transcode: {argv: transcode.argv,
      maxVideoBitrateBps: transcode.maxVideoBitrateBps},
    outputProbe: {argv: outputProbe.argv,
      audioDecodeArgv: audioFrames.argv, facts: output}});
} catch (error) {
  fail(error);
}
