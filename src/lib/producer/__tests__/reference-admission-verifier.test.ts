import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  validAdmittedReference,
} from "../../../app/api/_lib/reference-admission-verifier";
import {
  admitReferenceVtt,
} from "../../../app/api/_lib/reference-sidecar";

function sha(value: Buffer | string): string {
  return crypto.createHash("sha256").update(value).digest("hex");
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "reference-authority-"));
try {
  const media = Buffer.from("proved reference bytes");
  const video = path.join(dir, `${sha(media)}.media`);
  fs.writeFileSync(video, media);
  const receipt = {
    schemaVersion: 1,
    policy: "sniper-external-media-probe-v2",
    snapshot: {
      path: video,
      sha256: sha(media),
      sizeBytes: media.length,
    },
    limits: {
      max_bytes: 2 * 1024 ** 3,
      max_width: 8192,
      max_height: 8192,
      max_frames: 500_000,
      max_duration_seconds: 3600,
      max_streams: 32,
      max_decode_seconds: 1200,
    },
    image: { Id: `sha256:${"c".repeat(64)}` },
    isolation: {
      imageId: `sha256:${"c".repeat(64)}`,
      containerId: "d".repeat(64),
      networkMode: "none",
      nonrootUser: "501:20",
      readonlyRoot: true,
      mountSource: video,
    },
    network: { schemaVersion: 1, hostDecoyPositive: true },
    decoded: {
      schemaVersion: 1,
      ok: true,
      decoded: true,
      facts: {
        mediaKind: "timed-media",
        durationSeconds: 12,
        sizeBytes: media.length,
        videoStreams: 1,
        audioStreams: 1,
        streamCount: 2,
        declaredFrames: 360,
        width: 1920,
        height: 1080,
      },
    },
  };
  const receiptBytes = Buffer.from(`${JSON.stringify(receipt)}\n`);
  const receiptHash = sha(receiptBytes);
  const receiptDir = path.join(dir, ".sniper-reference-admission");
  fs.mkdirSync(receiptDir);
  const receiptPath = path.join(receiptDir, `${receiptHash}.json`);
  fs.writeFileSync(receiptPath, receiptBytes);
  const admission = {
    schemaVersion: 1,
    policy: "sniper-reference-media-admission-v1",
    snapshotPath: video,
    snapshotSha256: sha(media),
    sizeBytes: media.length,
    mediaKind: "timed-media",
    durationSeconds: 12,
    receiptPath,
    receiptSha256: receiptHash,
  };
  fs.writeFileSync(
    path.join(dir, "reference-source.json"),
    `${JSON.stringify({ kind: "local", admission })}\n`,
  );
  assert.equal(validAdmittedReference(video), true);

  // Exercise the current writer's receipt and reject unknown policies with valid hashes.
  const sourcePath = path.join(dir, "reference-source.json");
  const originalSource = fs.readFileSync(sourcePath);
  for (const [policy, expected] of [["sniper-external-media-probe-v3", true],
    ["sniper-external-media-probe-v4", false]] as const) {
    const bytes = Buffer.from(`${JSON.stringify({ ...receipt, policy })}\n`);
    const hash = sha(bytes), file = path.join(receiptDir, `${hash}.json`);
    fs.writeFileSync(file, bytes);
    fs.writeFileSync(sourcePath, JSON.stringify({ kind: "local", admission: {
      ...admission, receiptPath: file, receiptSha256: hash,
    } }));
    assert.equal(validAdmittedReference(video), expected);
    fs.appendFileSync(file, "tamper");
    assert.equal(validAdmittedReference(video), false);
  }
  fs.writeFileSync(sourcePath, originalSource);

  // Native (v4) receipts: accepted only with the approved jail template/launcher and three attested runs on this snapshot.
  const approval = JSON.parse(fs.readFileSync(path.join(process.cwd(),
    "scripts/producer/headless/native_media_runtime_approval.json"), "utf8")) as { approved: Array<Record<string, string>> };
  const jail = approval.approved[0], generated = "a".repeat(64);
  const tools = { ffprobe: { path: "/opt/homebrew/Cellar/ffmpeg/8.0/bin/ffprobe", sha256: "e".repeat(64), version: "ffprobe version 8.0" },
    ffmpeg: { path: "/opt/homebrew/Cellar/ffmpeg/8.0/bin/ffmpeg", sha256: "f".repeat(64), version: "ffmpeg version 8.0" } };
  const run = (decoder: string, input = video) => ({ sandboxed: true, decoder, input, profileSha256: generated, memoryMiB: 768,
    pid: 1, mode: decoder === "/dev/null" ? "inspect" : "exec",
    rlimits: { RLIMIT_CORE: [0, 0], RLIMIT_CPU: [10, 15], RLIMIT_FSIZE: [0, 0], RLIMIT_NOFILE: [256, 256] } });
  const common = Object.fromEntries(Object.entries(receipt).filter(([key]) => !["image", "network", "isolation"].includes(key)));
  const runs = [run("/dev/null"), run(tools.ffprobe.path), run(tools.ffmpeg.path)];
  const native = { ...common, policy: "sniper-external-media-probe-v4-native",
    runtime: { kind: "macos-seatbelt", policy: "sniper-native-media-jail-v2", profileTemplateSha256: jail.profileTemplateSha256,
      profileSha256: generated, launcherSha256: jail.launcherSha256, platform: { system: "Darwin" }, tools,
      closureSha256: "d".repeat(64), closureCount: 93, openedPathCount: 216 },
    isolation: { kind: "macos-seatbelt", policy: "sniper-native-media-jail-v2", profileSha256: generated,
      network: "denied", processCreation: "denied", writes: "/dev/null only", otherProcesses: "denied",
      watchdog: "footprint+cpu", memoryMiB: 768, jailRuns: runs } };
  const variants: Array<[string, Record<string, unknown>, boolean]> = [
    ["approved native", native, true],
    ["unapproved template", { ...native, runtime: { ...native.runtime, profileTemplateSha256: "0".repeat(64) } }, false],
    ["missing inspection", { ...native, isolation: { ...native.isolation, jailRuns: runs.slice(1) } }, false],
    ["wrong memory cap", { ...native, isolation: { ...native.isolation, memoryMiB: 4096 } }, false],
    ["unconfined run", { ...native, isolation: { ...native.isolation,
      jailRuns: [runs[0], runs[1], { ...runs[2], sandboxed: false }] } }, false],
    ["run on another input", { ...native, isolation: { ...native.isolation,
      jailRuns: [runs[0], run(tools.ffprobe.path, "/elsewhere.media"), runs[2]] } }, false],
    ["no watchdog", { ...native, isolation: { ...native.isolation, watchdog: "none" } }, false],
    ["extra key", { ...native, network: { schemaVersion: 1, hostDecoyPositive: true } }, false],
  ];
  for (const [label, value, expected] of variants) {
    const bytes = Buffer.from(`${JSON.stringify(value)}\n`);
    const hash = sha(bytes), file = path.join(receiptDir, `${hash}.json`);
    fs.writeFileSync(file, bytes);
    fs.writeFileSync(sourcePath, JSON.stringify({ kind: "local", admission: { ...admission, receiptPath: file, receiptSha256: hash } }));
    assert.equal(validAdmittedReference(video), expected, label);
  }
  fs.writeFileSync(sourcePath, originalSource);

  const sourceVtt = path.join(dir, "source-input.vtt");
  const admittedVtt = path.join(dir, `${path.parse(video).name}.en.vtt`);
  const vttBytes = "WEBVTT\n\n00:00.000 --> 00:01.000\n<c>Hello</c>\n";
  fs.writeFileSync(sourceVtt, vttBytes);
  const transcript = admitReferenceVtt(sourceVtt, admittedVtt);
  fs.writeFileSync(
    path.join(dir, "reference-source.json"),
    `${JSON.stringify({ kind: "local", admission, transcripts: [transcript] })}\n`,
  );
  assert.equal(validAdmittedReference(video), true);
  fs.appendFileSync(admittedVtt, "tamper");
  assert.equal(validAdmittedReference(video), false);
  fs.writeFileSync(admittedVtt, vttBytes);
  assert.equal(validAdmittedReference(video), true);

  const legacy = path.join(dir, "legacy.mp4");
  fs.copyFileSync(video, legacy);
  assert.equal(validAdmittedReference(legacy), false);

  fs.appendFileSync(video, "tamper");
  assert.equal(validAdmittedReference(video), false);
  fs.writeFileSync(video, media);
  fs.appendFileSync(receiptPath, "tamper");
  assert.equal(validAdmittedReference(video), false);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

const librarySource = fs.readFileSync(
  path.join(process.cwd(), "src/app/api/_lib/reference-library.ts"),
  "utf8",
);
assert.match(librarySource, /\.filter\(validAdmittedReference\)/);

console.log("reference-admission-verifier.test.ts: all assertions passed");
