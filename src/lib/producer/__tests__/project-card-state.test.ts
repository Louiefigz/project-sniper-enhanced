import assert from "node:assert/strict";
import {
  palmierActionLabel,
  projectCardPresentation,
  type ProjectCardStateInput,
} from "../project-card-state";

const input: ProjectCardStateInput = {
  origin: "raw",
  intent: { mode: "longform", scope: "produced", lanes: {} },
  stages: { ingested: true, transcribed: true, plan: true, base: true, final: true },
  run: null,
  palmier: {
    state: "no_workspace", canOpen: false, projectPath: null, projectId: null,
    timelineId: null, verified: false, authorityOrigin: null,
    detail: "No workspace.",
  },
  finalArtifact: { state: "approved", path: "/tmp/final.mp4", reason: null },
  segmentCount: 0,
  clipperFileCount: 0,
};

const sniperOnly = projectCardPresentation(input);
assert.equal(sniperOnly.label, "Finished");
assert.equal(sniperOnly.primary, "open_sniper");
assert.match(sniperOnly.available, /No current verified Palmier edit/);
assert.equal(palmierActionLabel(input.palmier, true), "Create Palmier workspace");

const mirror = projectCardPresentation({
  ...input,
  palmier: { ...input.palmier, state: "approved_mirror", canOpen: true, verified: true },
});
assert.equal(mirror.primary, "open_palmier");
assert.match(mirror.available, /verified Palmier edit/);

const approvedWorking = projectCardPresentation({
  ...input,
  stages: { ingested: true, transcribed: true, plan: false, base: false, final: false },
  finalArtifact: { state: "missing", path: null, reason: null },
  palmier: {
    ...input.palmier, state: "approved_working_head", canOpen: true,
    verified: true, approvalCurrent: true,
  },
});
assert.equal(approvedWorking.label, "Palmier edit approved");
assert.equal(approvedWorking.primary, "open_palmier");
assert.match(approvedWorking.available, /exact editable Palmier timeline/);
assert.equal(
  palmierActionLabel({ ...input.palmier, state: "approved_working_head" }, false),
  "Open approved Palmier timeline",
);

const manual = projectCardPresentation({
  ...input,
  palmier: { ...input.palmier, state: "manual_working_head", canOpen: true },
});
assert.equal(manual.label, "Palmier edit needs QC");
assert.equal(manual.primary, "open_palmier");

const candidate = projectCardPresentation({
  ...input,
  palmier: { ...input.palmier, state: "pending_candidate", canOpen: true },
});
assert.equal(candidate.label, "Palmier candidate needs review");
assert.match(candidate.safe, /Opening does not accept/);

const quarantinePalmier = {
  ...input.palmier, state: "quarantined_candidate" as const, canOpen: true,
};
const quarantine = projectCardPresentation({
  ...input,
  palmier: quarantinePalmier,
});
assert.equal(quarantine.label, "Palmier candidate stopped safely");
assert.equal(quarantine.primary, "open_palmier");
assert.match(quarantine.next, /Restore and verify/);
assert.equal(
  palmierActionLabel(quarantinePalmier, true),
  "Restore preserved Palmier parent",
);

const unapproved = projectCardPresentation({
  ...input,
  stages: { ...input.stages, final: false },
  finalArtifact: { state: "unapproved", path: "/tmp/final.mp4", reason: "QC failed." },
});
assert.equal(unapproved.label, "Rendered — QC not approved");
assert.equal(unapproved.primary, "stage");

const unapprovedMissingIntent = projectCardPresentation({ ...input, intent: null,
  stages: { ...input.stages, final: false },
  finalArtifact: { state: "unapproved", path: "/tmp/final.mp4", reason: "QC is not current." },
});
assert.match(unapprovedMissingIntent.next, /Choose Short or Long/);

const clipperInput: ProjectCardStateInput = {
  ...input,
  origin: "clipper",
  stages: { ingested: false, transcribed: false, plan: false, base: false, final: false },
  finalArtifact: { state: "missing", path: null, reason: null },
  clipperFileCount: 1,
};
const clipper = projectCardPresentation(clipperInput);
assert.equal(clipper.label, "Final Cut timeline ready");
assert.equal(clipper.primary, "reveal_clipper");

const segmenter = projectCardPresentation({
  ...clipperInput,
  origin: "segmenter",
  clipperFileCount: 0,
  segmentCount: 2,
});
assert.equal(segmenter.label, "Source clips ready");
assert.equal(segmenter.primary, "choose_segment");

console.log("project-card-state.test.ts: all assertions passed");
