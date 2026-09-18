import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  localIntakePreflight,
  MAX_REFERENCE_BYTES,
  MIN_FREE_BYTES,
  parseReferenceProbe,
} from "../../../app/api/_lib/reference-intake-policy";
import {
  admitReferenceMedia,
  parseReferenceAdmission,
  REFERENCE_ADMISSION_TIMEOUT_MS,
} from "../../../app/api/_lib/reference-media-admission";

assert.equal(localIntakePreflight(MAX_REFERENCE_BYTES, MIN_FREE_BYTES), null);
assert.equal(REFERENCE_ADMISSION_TIMEOUT_MS, 25 * 60 * 1000);
assert.equal(localIntakePreflight(MAX_REFERENCE_BYTES + BigInt(1), MIN_FREE_BYTES)?.status, 413);
assert.equal(localIntakePreflight(BigInt(1), MIN_FREE_BYTES - BigInt(1))?.status, 507);

assert.deepEqual(parseReferenceProbe({
  streams: [{ codec_type: "video", width: 1920, height: 1080 }],
  format: { duration: "59.5" },
}), { width: 1920, height: 1080, durationS: 59.5 });
assert.throws(() => parseReferenceProbe({ streams: [], format: { duration: 10 } }), /video stream/);
assert.throws(() => parseReferenceProbe({
  streams: [{ codec_type: "video", width: 1920, height: 1080 }],
  format: { duration: 3600.1 },
}), /maximum/);

const store = fs.mkdtempSync(path.join(os.tmpdir(), "reference-admission-"));
try {
  const snapshotHash = "a".repeat(64);
  const receiptHash = "b".repeat(64);
  const snapshotPath = path.join(store, `${snapshotHash}.media`);
  const receiptDir = path.join(store, ".sniper-reference-admission");
  fs.mkdirSync(receiptDir);
  const receiptPath = path.join(receiptDir, `${receiptHash}.json`);
  fs.writeFileSync(snapshotPath, "video");
  fs.writeFileSync(receiptPath, "{}\n");
  const authority = {
    schemaVersion: 1,
    policy: "sniper-reference-media-admission-v1",
    snapshotPath,
    snapshotSha256: snapshotHash,
    sizeBytes: 5,
    mediaKind: "timed-media",
    durationSeconds: 10,
    receiptPath,
    receiptSha256: receiptHash,
  };
  assert.deepEqual(parseReferenceAdmission(authority, store), authority);
  assert.throws(() => parseReferenceAdmission(
    { ...authority, snapshotPath: path.join(store, "..", "escaped.media") },
    store,
  ), /malformed/);
  assert.throws(() => parseReferenceAdmission(
    { ...authority, unsupported: true }, store,
  ), /malformed/);
  assert.throws(() => parseReferenceAdmission(
    { ...authority, receiptPath: path.join(store, `${receiptHash}.json`) },
    store,
  ), /malformed/);
} finally {
  fs.rmSync(store, { recursive: true, force: true });
}

const admissionSource = fs.readFileSync(
  path.join(process.cwd(), "src/app/api/_lib/reference-media-admission.ts"),
  "utf8",
);
assert.match(admissionSource, /trackProcessTree\(spawn\(/);
assert.match(admissionSource, /terminateProcessTree\(child, 20_000\)/);
assert.match(fs.readFileSync(
  path.join(process.cwd(), "src/app/api/producer/references/route.ts"), "utf8",
), /maxDuration = 1800/);
const fetchRoute = fs.readFileSync(
  path.join(process.cwd(), "src/app/api/producer/references/fetch/route.ts"),
  "utf8",
);
assert.match(fetchRoute, /trackProcessTree\(spawn\(/);
assert.match(fetchRoute, /terminateProcessTree\(child, 10_000\)/);

async function cancellationClosesTheWorker(): Promise<void> {
  const cancelStore = fs.mkdtempSync(
    path.join(os.tmpdir(), "reference-admission-cancel-"),
  );
  try {
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(
      admitReferenceMedia(
        path.join(cancelStore, "missing.mp4"),
        cancelStore,
        controller.signal,
      ),
      /cancelled/,
    );
  } finally {
    fs.rmSync(cancelStore, { recursive: true, force: true });
  }
}

cancellationClosesTheWorker()
  .then(() => console.log("reference-intake-policy.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
