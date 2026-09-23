import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReferenceDecisionForm from "../../../components/producer/reference-decision";
import { referenceIntent, type ReferenceEntry } from "../../../components/producer/reference-types";
import { parseReferenceDecision, validStoredReferenceDecision } from "../../../app/api/_lib/reference-decision";

const at = new Date("2026-07-12T12:00:00Z");
assert.equal(parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic" }, at).targetStyle, null);
assert.equal(parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "new-style", candidateStyleName: "Quiet cards" }, at).candidateStyleName, "Quiet cards");
for (const mode of ["short", "longform"]) {
  assert.throws(() => parseReferenceDecision({ id: "ref_1", mode, strategy: "extend" }, at), /retired/);
  for (const targetStyle of ["restrained", "punch", "slideware", "unknown", ""]) {
    assert.throws(() => parseReferenceDecision({ id: "ref_1", mode, strategy: "extend", targetStyle }, at), /retired/);
    assert.throws(() => parseReferenceDecision({ id: "ref_1", mode, strategy: "mimic", targetStyle }, at), /retired/);
  }
}
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic", candidateStyleName: "xx" }, at), /new-style-only/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "new-style", candidateStyleName: "x" }, at), /2 to 80/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "new-style", candidateStyleName: "Restrained" }, at), /retired/);
assert.throws(() => parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic", extra: true }, at), /unknown/);
const stored = parseReferenceDecision({ id: "ref_1", mode: "short", strategy: "mimic" }, at);
assert.equal(validStoredReferenceDecision(stored, "ref_1"), true);
assert.equal(validStoredReferenceDecision({ ...stored, strategy: "bogus" }, "ref_1"), false);
assert.equal(validStoredReferenceDecision({ ...stored, targetStyle: "restrained" }, "ref_1"), false);
assert.equal(validStoredReferenceDecision({ ...stored, extra: true }, "ref_1"), false);
assert.equal(validStoredReferenceDecision({ ...stored, strategy: "extend", targetStyle: "restrained" }, "ref_1"), false);

Object.assign(globalThis, { React });
const entry: ReferenceEntry = {
  id: "ref_1", dir: "/TEST/reference", title: "TEST selected reference",
  video: "/TEST/reference/video.mp4", studied: true, status: { state: "ready" },
  profile: { suggestedKnownStyle: "restrained" },
  decision: { mode: "short", strategy: "extend", targetStyle: "restrained" },
};
assert.equal(referenceIntent(entry), null, "stored retired decisions cannot activate an edit");
const html = renderToStaticMarkup(React.createElement(ReferenceDecisionForm, {
  reference: entry, saving: false, onSave: async () => null,
}));
assert(!html.includes("Extend a style"));
assert(!html.includes("Decision saved."));
assert(html.includes("Save is required"), "retired stored decisions require an explicit current selection");
const current = { ...entry, decision: { mode: "short" as const, strategy: "mimic" as const } };
assert.equal(referenceIntent(current)?.strategy, "mimic");

console.log("reference-decision.test.ts: all assertions passed");
