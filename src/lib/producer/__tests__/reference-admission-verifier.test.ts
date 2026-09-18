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
