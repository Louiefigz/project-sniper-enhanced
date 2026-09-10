// Concatenated with qualification_mezzanine_worker.js before the approved
// image starts Node. Keep this file declaration-only.
function mediaHash(path) {
  const descriptor = fs.openSync(path,
    fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const before = fs.fstatSync(descriptor, {bigint: true});
    if (!before.isFile() || before.nlink !== 1n ||
        before.size <= BigInt(CAP_BYTES) ||
        before.size > BigInt(MAX_SOURCE_BYTES)) {
      throw new Error("source is outside its immutable qualification bounds");
    }
    const digest = crypto.createHash("sha256");
    const buffer = Buffer.allocUnsafe(8 * 1024 * 1024);
    let size = 0n;
    while (true) {
      const read = fs.readSync(descriptor, buffer, 0, buffer.length, null);
      if (read === 0) break;
      digest.update(buffer.subarray(0, read));
      size += BigInt(read);
    }
    const after = fs.fstatSync(descriptor, {bigint: true});
    const fields = ["dev", "ino", "size", "mtimeNs", "ctimeNs"];
    if (size !== before.size ||
        fields.some(field => before[field] !== after[field])) {
      throw new Error("source changed during in-container hashing");
    }
    return {sha256: digest.digest("hex"), sizeBytes: Number(size)};
  } finally {
    fs.closeSync(descriptor);
  }
}

function nonNegativeInteger(value, label) {
  if (!/^(0|[1-9][0-9]*)$/.test(String(value))) {
    throw new Error(`${label} is not a non-negative integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) throw new Error(`${label} is too large`);
  return parsed;
}

function rotationDegrees(video) {
  const values = [];
  if (video.tags && video.tags.rotate !== undefined) values.push(video.tags.rotate);
  for (const row of video.side_data_list || []) {
    if (row.rotation !== undefined) values.push(row.rotation);
  }
  const parsed = values.map(value => Number(value));
  if (parsed.some(value => !Number.isFinite(value) || value !== 0)) {
    throw new Error("qualification source rotation must be exactly zero");
  }
  return 0;
}

function sourceFrameClock(document, video, sourceRate, frameCount) {
  const timeBase = rate(video.time_base, "source time base");
  const stepNumerator = sourceRate.denominator * timeBase.denominator;
  const stepDenominator = sourceRate.numerator * timeBase.numerator;
  if (stepNumerator % stepDenominator !== 0) {
    throw new Error("source frame step is not integral in its time base");
  }
  const step = stepNumerator / stepDenominator;
  const frames = (document.frames || []).filter(
    row => row.media_type === "video");
  const fieldOrder = video.field_order || "not-reported";
  const allowedFieldOrders = ["progressive", "unknown", "not-reported"];
  if (frames.length !== frameCount || !allowedFieldOrders.includes(fieldOrder) ||
      nonNegativeInteger(video.start_pts, "source start pts") !== 0) {
    throw new Error("source video clock or scan authority is inconsistent");
  }
  for (let index = 0; index < frames.length; index += 1) {
    const row = frames[index];
    if (frameInteger(row, ["pts", "pkt_pts", "best_effort_timestamp"],
          "source frame pts") !== index * step ||
        frameInteger(row, ["duration", "pkt_duration"],
          "source frame duration") !== step ||
        nonNegativeInteger(row.interlaced_frame,
          "source interlaced flag") !== 0 ||
        nonNegativeInteger(row.top_field_first,
          "source top-field-first flag") !== 0) {
      throw new Error("source decoded frame clock is not exact progressive CFR");
    }
  }
  return {timeBase: timeBase.text, firstPts: 0,
    lastPts: (frameCount - 1) * step, frameStepPts: step,
    zeroBasedEpoch: true, progressive: true,
    streamFieldOrder: fieldOrder, decodedProgressiveFrames: frames.length,
    rotationDegrees: rotationDegrees(video)};
}

function sourceAudioClock(document, audio, sourceRate, videoFrames) {
  const sampleRate = integer(audio.sample_rate, "source audio sample rate");
  const timeBase = rate(audio.time_base, "source audio time base");
  const frames = (document.frames || []).filter(
    row => row.media_type === "audio");
  if (sampleRate !== 48000 || audio.channels !== 2 ||
      timeBase.text !== "1/48000" ||
      nonNegativeInteger(audio.start_pts, "source audio start pts") !== 0 ||
      frames.length < 1) {
    throw new Error("source audio clock authority is unsupported");
  }
  let nextPts = 0;
  let lastPts = 0;
  for (const row of frames) {
    const pts = frameInteger(
      row, ["pts", "pkt_pts", "best_effort_timestamp"],
      "source audio frame pts");
    const samples = integer(row.nb_samples, "source audio frame samples");
    if (pts !== nextPts ||
        frameInteger(row, ["duration", "pkt_duration"],
          "source audio frame duration")
        !== samples) {
      throw new Error("source audio frames are not sample-contiguous");
    }
    lastPts = pts;
    nextPts += samples;
  }
  const timeline = integer(audio.duration_ts, "source audio duration samples");
  const sourceDuration = nextPts / sampleRate;
  const videoDuration = videoFrames * sourceRate.denominator /
    sourceRate.numerator;
  const delta = sourceDuration - videoDuration;
  const maximum = sourceRate.denominator / sourceRate.numerator;
  if (timeline !== nextPts || Math.abs(delta) > maximum) {
    throw new Error("source audio does not cover the video program clock");
  }
  return {codec: audio.codec_name, sampleRate, channels: audio.channels,
    timeBase: timeBase.text, firstPts: 0, lastPts, lastEndPts: nextPts,
    timelineSamplesPerChannel: timeline,
    decodedSamplesPerChannel: nextPts,
    durationSeconds: sourceDuration,
    videoDurationDeltaSeconds: delta,
    absoluteVideoDeltaWithinOneSourceFrame: true,
    contiguousFromZero: true};
}

function decodedAudioSamples(document, argv) {
  const frames = (document.frames || []).filter(
    row => row.media_type === "audio");
  if (frames.length < 1) throw new Error("output audio decoded no frames");
  let samples = 0;
  for (const frame of frames) {
    samples += integer(frame.nb_samples, "decoded audio frame samples");
    if (!Number.isSafeInteger(samples)) {
      throw new Error("decoded audio sample count is too large");
    }
  }
  return {argv, samplesPerChannel: samples};
}

function audioDecision(cadence) {
  const programSamples = cadence.targetFrames * (48000 / TARGET_FPS);
  const presentationQuantum = 48;
  const timelineSamples = Math.ceil(
    programSamples / presentationQuantum) * presentationQuantum;
  if (!Number.isSafeInteger(programSamples) || programSamples <= 0 ||
      !Number.isSafeInteger(timelineSamples)) {
    throw new Error("target audio sample clock is not exact");
  }
  const filter = "aresample=48000:async=0:first_pts=0," +
    `atrim=end_sample=${programSamples},apad=whole_len=${timelineSamples},` +
    `atrim=end_sample=${timelineSamples},asetpts=N/SR/TB`;
  return {mode: "full-program-with-bounded-silent-aac-tail",
    sampleRate: 48000, channels: 2,
    programSamplesPerChannel: programSamples,
    targetTimelineSamplesPerChannel: timelineSamples,
    presentationQuantumSamples: presentationQuantum,
    silentTailSamplesPerChannel: timelineSamples - programSamples,
    programDurationSeconds: programSamples / 48000,
    targetTimelineDurationSeconds: timelineSamples / 48000, filter};
}

function outputVideoFacts(document, video, cadence) {
  const actualRate = rate(video.r_frame_rate, "output rate");
  const average = rate(video.avg_frame_rate, "output average rate");
  const expectedRate = rate(cadence.targetRate, "target rate");
  const frames = integer(video.nb_read_frames || video.nb_frames, "output frames");
  const clock = sourceFrameClock(
    document, video, expectedRate, cadence.targetFrames);
  const videoDurationTs = integer(video.duration_ts, "output video duration");
  const videoStartPts = Number(video.start_pts);
  const videoDurationSeconds = Number(video.duration);
  const validClock = video.time_base === `1/${TARGET_FPS}` &&
    videoStartPts === 0 && videoDurationTs === cadence.targetFrames &&
    Number.isFinite(videoDurationSeconds) &&
    Math.abs(videoDurationSeconds - cadence.targetDurationSeconds) <= 0.0000005;
  const valid = video.codec_name === "h264" && video.profile === "High" &&
    video.level === 42 && video.width === 1920 && video.height === 1080 &&
    video.pix_fmt === "yuv420p" && video.sample_aspect_ratio === "1:1" &&
    video.color_range === "tv" &&
    clock.progressive === true && clock.rotationDegrees === 0 &&
    ["bt709"].every(value => video.color_space === value &&
      video.color_transfer === value && video.color_primaries === value) &&
    sameRate(actualRate, expectedRate) && sameRate(average, expectedRate) &&
    frames === cadence.targetFrames && validClock;
  const facts = {codec: video.codec_name, profile: video.profile,
    level: video.level, width: video.width, height: video.height,
    pixelFormat: video.pix_fmt, sampleAspectRatio: video.sample_aspect_ratio,
    rate: actualRate.text, timeBase: video.time_base, startPts: videoStartPts,
    durationFrames: videoDurationTs, durationSeconds: videoDurationSeconds,
    frames, colorRange: video.color_range, colorSpace: video.color_space,
    colorTransfer: video.color_transfer, colorPrimaries: video.color_primaries};
  Object.assign(facts, clock);
  return {valid, facts};
}

function outputAudioFacts(audio, audioFrames, cadence, decision) {
  const audioDurationTs = integer(audio.duration_ts, "output audio duration");
  const audioStartPts = Number(audio.start_pts);
  const audioDurationSeconds = Number(audio.duration);
  const decodedSamples = audioFrames.samplesPerChannel;
  const programSamples = decision.programSamplesPerChannel;
  const timelineSamples = decision.targetTimelineSamplesPerChannel;
  const silentTail = timelineSamples - programSamples;
  const codecPadding = decodedSamples - timelineSamples;
  const valid = audio.codec_name === "aac" && audio.sample_rate === "48000" &&
    audio.channels === 2 && audio.time_base === "1/48000" &&
    audioStartPts === 0 && audioDurationTs === timelineSamples &&
    Number.isFinite(audioDurationSeconds) &&
    Math.abs(audioDurationSeconds - decision.targetTimelineDurationSeconds)
      <= 0.0000005 &&
    silentTail === decision.silentTailSamplesPerChannel &&
    silentTail >= 0 && silentTail < decision.presentationQuantumSamples &&
    decodedSamples >= timelineSamples && codecPadding >= 0 && codecPadding < 1024;
  const facts = {codec: audio.codec_name,
    sampleRate: Number(audio.sample_rate), channels: audio.channels,
    timeBase: audio.time_base, startPts: audioStartPts,
    programSamplesPerChannel: programSamples,
    timelineSamplesPerChannel: audioDurationTs,
    timelineDurationSeconds: audioDurationSeconds,
    decodedSamplesPerChannel: decodedSamples,
    decodedDurationSeconds: decodedSamples / 48000,
    silentTailSamplesPerChannel: silentTail,
    codecPaddingSamplesPerChannel: codecPadding, fullProgramCoverage: true};
  return {valid, facts};
}

function ffmpegArgv(cadence, color, audio) {
  const duration = cadence.targetDurationSeconds;
  const budget = Math.floor((CAP_BYTES * 0.80 * 8 / duration) -
    AUDIO_BPS - 128000);
  const maxVideoBps = Math.min(40000000, budget);
  if (!Number.isSafeInteger(maxVideoBps) || maxVideoBps < 4000000) {
    throw new Error("output byte budget cannot retain qualification quality");
  }
  const argv = ["-nostdin", "-hide_banner", "-v", "error", "-xerror",
    "-threads", "4", "-filter_threads", "4", "-i", SOURCE,
    "-map", "0:v:0", "-map", "0:a:0", "-vf", color.filter,
    "-vsync", "cfr", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
    "-maxrate", String(maxVideoBps), "-bufsize", String(maxVideoBps * 2),
    "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.2",
    "-color_range", "tv", "-colorspace", "bt709", "-color_trc", "bt709",
    "-color_primaries", "bt709", "-video_track_timescale", String(TARGET_FPS),
    "-af", audio.filter, "-c:a", "aac", "-b:a", String(AUDIO_BPS),
    "-ar", "48000", "-ac", "2", "-map_metadata", "-1", "-map_chapters", "-1",
    "-metadata", "creation_time=1970-01-01T00:00:00Z",
    "-movflags", "+faststart+use_metadata_tags", "-n", OUTPUT];
  return {argv: [FFMPEG, ...argv], args: argv, maxVideoBitrateBps: maxVideoBps};
}

function validateOutput(result, audioFrames, cadence, audioDecisionValue) {
  const streams = result.document.streams || [];
  const videos = streams.filter(row => row.codec_type === "video");
  const audios = streams.filter(row => row.codec_type === "audio");
  const format = result.document.format || {};
  if (streams.length !== 2 || videos.length !== 1 || audios.length !== 1) {
    throw new Error("qualified output does not contain exactly one A/V pair");
  }
  const video = outputVideoFacts(result.document, videos[0], cadence);
  const audio = outputAudioFacts(
    audios[0], audioFrames, cadence, audioDecisionValue);
  const sizeBytes = integer(format.size, "output size");
  const durationSeconds = Number(format.duration);
  const expectedDuration = Math.max(
    cadence.targetDurationSeconds,
    audioDecisionValue.targetTimelineDurationSeconds);
  if (!video.valid || !audio.valid || sizeBytes > CAP_BYTES ||
      !Number.isFinite(durationSeconds) ||
      Math.abs(durationSeconds - expectedDuration) > 0.0000005) {
    throw new Error("qualified output failed its exact stream profile");
  }
  return {sizeBytes, durationSeconds, video: video.facts, audio: audio.facts};
}
