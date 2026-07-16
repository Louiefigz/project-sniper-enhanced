import assert from "node:assert/strict";
import {
  localIntakePreflight,
  MAX_REFERENCE_BYTES,
  MIN_FREE_BYTES,
  parseReferenceProbe,
} from "../../../app/api/_lib/reference-intake-policy";

assert.equal(localIntakePreflight(MAX_REFERENCE_BYTES, MIN_FREE_BYTES), null);
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

console.log("reference-intake-policy.test.ts: all assertions passed");
