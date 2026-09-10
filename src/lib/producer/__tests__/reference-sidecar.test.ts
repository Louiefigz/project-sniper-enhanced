import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  admitReferenceVtt,
  copyReferenceVtt,
  MAX_REFERENCE_VTT_BYTES,
  verifyReferenceVttAdmission,
} from "../../../app/api/_lib/reference-sidecar";
import { ReferenceMediaError } from "../../../app/api/_lib/reference-intake-policy";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "reference-vtt-"));
try {
  const source = path.join(dir, "source.vtt");
  const copied = path.join(dir, "copied.vtt");
  fs.writeFileSync(source, "WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n");
  assert.equal(copyReferenceVtt(source, copied), copied);
  assert.equal(fs.readFileSync(copied, "utf8"), fs.readFileSync(source, "utf8"));
  const admittedDestination = path.join(dir, "admitted.vtt");
  const admission = admitReferenceVtt(source, admittedDestination);
  assert.equal(
    verifyReferenceVttAdmission(admission, dir),
    admittedDestination,
  );
  fs.appendFileSync(admittedDestination, "tamper");
  assert.equal(verifyReferenceVttAdmission(admission, dir), null);

  const occupied = path.join(dir, "occupied.vtt");
  fs.writeFileSync(occupied, "keep me");
  assert.throws(
    () => copyReferenceVtt(source, occupied),
    ReferenceMediaError,
  );
  assert.equal(fs.readFileSync(occupied, "utf8"), "keep me");

  const symlink = path.join(dir, "linked.vtt");
  fs.symlinkSync(source, symlink);
  assert.throws(
    () => copyReferenceVtt(symlink, path.join(dir, "linked-copy.vtt")),
    ReferenceMediaError,
  );

  const oversized = path.join(dir, "oversized.vtt");
  fs.writeFileSync(oversized, "");
  fs.truncateSync(oversized, MAX_REFERENCE_VTT_BYTES + 1);
  assert.throws(
    () => copyReferenceVtt(oversized, path.join(dir, "oversized-copy.vtt")),
    ReferenceMediaError,
  );
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}

console.log("reference-sidecar.test.ts: all assertions passed");
