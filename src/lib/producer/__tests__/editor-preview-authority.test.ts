import assert from "node:assert/strict";
import {
  approvedOutputEvent,
  effectivePreviewAuthority,
  previewAuthorityMessage,
} from "../editor-preview-authority";

assert.equal(effectivePreviewAuthority(false, "checking"), "checking");
assert.equal(effectivePreviewAuthority(false, "current"), "current");
assert.equal(effectivePreviewAuthority(false, "unapproved"), "unapproved");
assert.equal(effectivePreviewAuthority(false, "stale"), "stale");
assert.equal(
  effectivePreviewAuthority(true, "current"),
  "stale",
  "an in-memory plan edit must immediately hide the previously approved video",
);

assert.equal(approvedOutputEvent({ event: "candidate_approved" }), false);
assert.equal(approvedOutputEvent({ event: "outputs", approved: true }), true);
assert.throws(
  () => approvedOutputEvent({ event: "outputs" }),
  /without QC approval/,
  "an ambiguous terminal event may never make the old preview current",
);
assert.match(previewAuthorityMessage("stale"), /out of date/i);
assert.match(previewAuthorityMessage("unapproved"), /review copy/i);

console.log("editor-preview-authority.test.ts: all assertions passed");
