import assert from "node:assert/strict";
import { parseReferenceDecision, validStoredReferenceDecision } from "../../../app/api/_lib/reference-decision";

const at = new Date("2026-07-12T12:00:00Z");
assert.equal(parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic" }, at).targetStyle, null);
assert.equal(parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "extend", targetStyle: "caleb" }, at).targetStyle, "caleb");
assert.equal(parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "new-style", candidateStyleName: "Quiet cards" }, at).candidateStyleName, "Quiet cards");
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "extend" }, at), /targetStyle/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "longform", strategy: "extend", targetStyle: "caleb" }, at), /shorts-only/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "extend", targetStyle: "unknown" }, at), /caleb/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic", targetStyle: "caleb" }, at), /extend-only/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic", candidateStyleName: "xx" }, at), /new-style-only/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "new-style", candidateStyleName: "x" }, at), /2 to 80/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "new-style", candidateStyleName: "Caleb" }, at), /outside Caleb/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic", extra: true }, at), /unknown/);
const stored = parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic" }, at);
assert.equal(validStoredReferenceDecision(stored, "ref_1"), true);
assert.equal(validStoredReferenceDecision({ ...stored, strategy: "bogus" }, "ref_1"), false);
assert.equal(validStoredReferenceDecision({ ...stored, targetStyle: "caleb" }, "ref_1"), false);
assert.equal(validStoredReferenceDecision({ ...stored, extra: true }, "ref_1"), false);

console.log("reference-decision.test.ts: all assertions passed");
