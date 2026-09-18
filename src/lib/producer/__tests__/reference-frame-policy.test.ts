import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { sanitizeRepresentativeFrames } from "../../../app/api/_lib/reference-frame-policy";
import type { ReferenceStyleProfile } from "../../../app/api/_lib/reference-types";

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "reference-frames-"));
const study = path.join(dir, "study");
fs.mkdirSync(study);
const inside = path.join(study, "frame.jpg");
const outside = path.join(dir, "secret.png");
const wrong = path.join(study, "payload.txt");
const nested = path.join(study, "states", "relative.jpg");
fs.mkdirSync(path.dirname(nested));
fs.writeFileSync(inside, "image");
fs.writeFileSync(nested, "image");
fs.writeFileSync(outside, "secret");
fs.writeFileSync(wrong, "not image");
const profile = {
  schemaVersion: 1,
  referenceId: "ref_test",
  source: { video: "/tmp/ref.mp4", sha256: "", width: null, height: null,
    fps: null, durationS: null, aspect: null },
  representativeFrames: [inside, `${path.basename(study)}/states/relative.jpg`, outside, wrong],
} as ReferenceStyleProfile;
assert.deepEqual(sanitizeRepresentativeFrames(profile, study).representativeFrames,
  [fs.realpathSync(inside), fs.realpathSync(nested)]);
fs.rmSync(dir, { recursive: true, force: true });

console.log("reference-frame-policy.test.ts: all assertions passed");
