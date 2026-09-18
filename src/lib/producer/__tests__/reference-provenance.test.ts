import assert from "node:assert/strict";
import { assertStudyFresh } from "../../../app/api/_lib/reference-provenance";

const base = {
  videoMtimeMs: 10,
  deepMtimeMs: 20,
  profileMtimeMs: 30,
  recordedSha256: "a".repeat(64),
  currentSha256: "a".repeat(64),
};
assert.doesNotThrow(() => assertStudyFresh(base));
assert.throws(() => assertStudyFresh({ ...base, currentSha256: "b".repeat(64) }), /rerun study/);
assert.doesNotThrow(() => assertStudyFresh({
  ...base, deepMtimeMs: 40, currentSha256: "b".repeat(64),
}));
assert.throws(() => assertStudyFresh({
  ...base, recordedSha256: "", videoMtimeMs: 40, deepMtimeMs: 20,
}), /newer/);
assert.throws(() => assertStudyFresh({
  ...base, currentSha256: "b".repeat(64), videoMtimeMs: 50,
  deepMtimeMs: 40, profileMtimeMs: 30,
}), /newer/);

console.log("reference-provenance.test.ts: all assertions passed");
