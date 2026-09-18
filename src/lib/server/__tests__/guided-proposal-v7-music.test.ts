import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { assertProposalClauseCoverage } from "@/lib/producer/contracts/treatment-proposal-v2";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { parseCurrentTreatmentProposal as parseThroughV6 } from "@/lib/producer/contracts/treatment-proposal-v6";
import { GUIDED_MUSIC_GAP_DB, parseProposalMusicSelection, parseTreatmentProposalV7,
  parseCurrentTreatmentProposal, proposalV7ValidationView } from "@/lib/producer/contracts/treatment-proposal-v7";
import { applyGuidedMusicOperations, assertGuidedMusicCandidate, guidedMusicPolicy } from "../guided-proposal-music";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { buildProposalPrompt, runProposalBrain } from "../guided-proposal-compiler";
import { GUIDED_CAPTION_CONFIG_FILES, guidedCaptionPolicy } from "../guided-proposal-captions";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";

type Row = Record<string, unknown>;
const RAW = "Use the admitted TEST music bed beneath the unchanged dialogue.";

/** TEST ONLY metadata fixture, never an actual track, creator selection or quality approval. */
function selection(patch: Row = {}): Row {
  return { schemaVersion: 1, assetId: "music-1", gapDb: 11, duck: true, ...patch };
}

/** TEST ONLY full-program operation with every unrelated field explicitly null. */
function operation(patch: Row = {}): Row {
  return { type: "music-bed-full-program", clauseIndex: 0, beatIndex: null, catalogKind: null, variables: null,
    grade: null, startAnchor: null, endAnchorExclusive: null, presentation: null, captions: null, reframe: null,
    reason: "Keep the TEST bed below the unchanged dialogue across the full program.", music: selection(), ...patch };
}

/** TEST ONLY closed request; real source and execution checks belong to the caller. */
function proposal(patch: Row = {}): Row {
  return { schemaVersion: 7, summary: "TEST ONLY full-program music contract.", graphicsStyle: "cutaway-only",
    graphicsStyleRationale: "TEST ONLY retain all accepted picture and source decisions.",
    clauses: [{ start: 0, end: RAW.length, quote: RAW, disposition: "supported", rationale: "TEST ONLY explicit bed selection.", operationIndices: [0] }],
    beats: [{ startAnchor: 0, endAnchorExclusive: 1, purpose: "opening", summary: "TEST ONLY whole program.", supportsBeatIndices: [] }],
    operations: [operation()], beatDecisions: [], hookSeamDecisions: [], openingEndAnchor: 1, continuityEndAnchor: 1,
    audioPolicy: "preserve-full-program", colorPolicy: "preserve", ...patch };
}

test("V7 keeps actual music payload, clause indices and original request without mutating inputs", () => {
  const raw = proposal(), before = structuredClone(raw), parsed = parseTreatmentProposalV7(raw);
  assertProposalClauseCoverage(parsed, RAW);
  assert.deepEqual(raw, before); assert.equal(parsed.operations[0].type, "music-bed-full-program");
  assert.deepEqual(parsed.operations[0].music, selection());
  const view = proposalV7ValidationView(parsed);
  assert.equal(view.schemaVersion, 6); assert.equal(view.operations[0].type, "preserve-cut");
  assert.equal(Object.hasOwn(view.operations[0], "music"), false);
  assert.deepEqual(view.clauses, parsed.clauses); assert.deepEqual(parsed.operations[0].music, selection());
});

test("V7 is explicit only: no historical parser opening or current-default activation", () => {
  assert.equal(CURRENT_TREATMENT_PROPOSAL_VERSION, 5);
  assert.throws(() => parseThroughV6(proposal()));
  assert.deepEqual(parseCurrentTreatmentProposal(proposal()), parseTreatmentProposalV7(proposal()));
  const view = proposalV7ValidationView(parseTreatmentProposalV7(proposal()));
  assert.deepEqual(parseCurrentTreatmentProposal(view), view);
  assert.throws(() => parseCurrentTreatmentProposal(proposal({ schemaVersion: 8 })));
  assert.throws(() => parseTreatmentProposalV7({ ...view, schemaVersion: 7 }));
});

test("music fields reject coercion, arbitrary paths, downloads, variants and invented authority", () => {
  const bad = [{ schemaVersion: "1" }, { schemaVersion: true }, { assetId: [] }, { assetId: " " },
    { assetId: "x".repeat(129) }, { gapDb: true }, { gapDb: "11" }, { gapDb: NaN }, { gapDb: Infinity },
    { gapDb: 2.99 }, { gapDb: 40.01 }, { duck: false }, { duck: 1 }, { path: "/private/music.wav" },
    { vibe: "download anything" }, { offset: 1 }, { variants: ["short"] }, { licenseApproved: true }];
  for (const patch of bad) assert.throws(() => parseProposalMusicSelection(selection(patch)));
  for (const gapDb of [3, 11, 40]) assert.equal(parseProposalMusicSelection(selection({ gapDb })).gapDb, gapDb);
});

test("every operation needs explicit music/null and music never carries unrelated instructions", () => {
  const { music: _music, ...missing } = operation(); void _music;
  const invalid = [missing, operation({ music: null }), operation({ type: ["music-bed-full-program"] }),
    operation({ type: "preserve-cut" }), operation({ reason: "short" }), operation({ beatIndex: 0 }),
    operation({ startAnchor: 0 }), operation({ endAnchorExclusive: 1 }), operation({ catalogKind: "stat-card" }),
    operation({ variables: [] }), operation({ grade: "warm" }), operation({ presentation: {} }),
    operation({ captions: {} }), operation({ reframe: {} }), operation({ audioGain: 2 }), operation({ fulfilled: true })];
  for (const row of invalid) assert.throws(() => parseTreatmentProposalV7(proposal({ operations: [row] })));
  assert.throws(() => parseTreatmentProposalV7(proposal({ approval: true })));
  assert.throws(() => parseTreatmentProposalV7(proposal({ audioPolicy: "replace-dialogue" })));
});

test("duplicate and conflicting full-program beds never become last-writer-wins", () => {
  for (const music of [selection(), selection({ assetId: "music-2" }), selection({ gapDb: 14 })]) {
    assert.throws(() => parseTreatmentProposalV7(proposal({ operations: [operation(), operation({ music })] })), /only one/);
  }
  const preserve = operation({ type: "preserve-cut", music: null, reason: null });
  assert.equal(parseTreatmentProposalV7(proposal({ operations: [preserve] })).operations[0].music, null);
});

test("V7 closed JSON schema retains historical definitions and exact required payload keys", () => {
  const schema = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v7.schema.json", "utf8"));
  const old = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v6.schema.json", "utf8"));
  const parsed = parseTreatmentProposalV7(proposal());
  assert.equal(schema.properties.schemaVersion.const, 7);
  assert.deepEqual([...schema.required].sort(), Object.keys(parsed).sort());
  assert.deepEqual([...schema.$defs.operation.required].sort(), Object.keys(parsed.operations[0]).sort());
  assert.deepEqual([...schema.$defs.musicSelection.required].sort(), Object.keys(selection()).sort());
  for (const key of Object.keys(old.$defs).filter((key) => key !== "operation")) assert.deepEqual(schema.$defs[key], old.$defs[key]);
  const rows = [proposal(), proposal({ schemaVersion: 6 }), proposal({ extra: true }),
    ...[{ duck: 1 }, { gapDb: true }, { gapDb: 2 }, { path: "/tmp/music.wav" }].map(patch =>
      proposal({ operations: [operation({ music: selection(patch) })] }))];
  const output = execFileSync(pythonInterpreter(), ["scripts/producer/contracts/schema_validator.py", "--batch"], {
    input: JSON.stringify(rows.map(document => ({ schema: "treatment-proposal-v7.schema.json", document }))), encoding: "utf8",
    timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.deepEqual(JSON.parse(output).map((row: { valid: boolean }) => row.valid), [true, false, false, false, false, false, false]);
});

test("music gap bounds match the existing plan linter without changing mixer behavior", () => {
  const output = execFileSync(pythonInterpreter(), ["-c", "import json; from plan_lint_audio import GAP_DB_MIN,GAP_DB_MAX; print(json.dumps([GAP_DB_MIN,GAP_DB_MAX]))"], {
    cwd: "scripts/producer", encoding: "utf8", timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.deepEqual(JSON.parse(output), [GUIDED_MUSIC_GAP_DB.minimum, GUIDED_MUSIC_GAP_DB.maximum]);
});

/** TEST ONLY immutable-admission-shaped metadata; no filesystem observations are mocked as real. */
function musicFixture() {
  const plan = { planVersion: 3, target: { mode: "longform", scope: "trim", width: 1920, height: 1080,
    fps: 30, music: true, lanes: { graphics: "off", captions: "off", motion: "off" } },
    cutTrack: [{ sourceId: "raw-1", start: 0, end: 16, speed: 1 }], cutDecisions: { removals: [] } };
  const row = { id: "music-1", path: "/private/TEST/snapshot.wav", originalPath: "/private/TEST/original.wav",
    source: "library", sourceSha256: "a".repeat(64), sourceSizeBytes: 8000, admissionReceiptPath: "/private/TEST/admission.json",
    admissionReceiptSha256: "b".repeat(64), duration: 4, licensed: null };
  const manifest = { music: [row] };
  const evidence = { schemaVersion: 7, target: plan.target, frameRate: "30/1", totalFrames: 480,
    anchors: [0, 480], cleanEnds: [480], occurrences: [], catalog: [], introSeams: [], hookWindowS: 60,
    segments: [{ index: 0, sourceId: "raw-1", startFrame: 0, endFrameExclusive: 480, text: "TEST ONLY" }],
    timelineMapHash: "c".repeat(64), graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [] } },
    captionPolicy: guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map(name => ({ name, sha256: "d".repeat(64) }))),
    musicPolicy: guidedMusicPolicy(plan, manifest) } as unknown as ProposalEvidence;
  const cut = { plan: { value: plan }, manifest: { value: manifest }, job: { ctx: { intent: { music: true } } } } as unknown as AcceptedGuidedCut;
  return { plan, manifest, row, evidence, cut };
}

test("music policy is exact bounded metadata, excludes builtins and never converts license fields to approval", () => {
  const f = musicFixture(), before = structuredClone(f.manifest), policy = guidedMusicPolicy(f.plan, f.manifest);
  assert.deepEqual(f.manifest, before); assert.equal(policy.assets.length, 1);
  assert.equal(policy.assets[0].rights, "unverified"); assert.equal(policy.acceptedMusicEnabled, true);
  assert.match(policy.scope, /not-source-rights-or-quality-approval/);
  assert.equal(Object.hasOwn(policy.assets[0], "path"), false);
  const manifest = { music: [{ id: "builtin-1", source: "builtin", licensed: true }, { ...f.row, licensed: true }] };
  const varied = guidedMusicPolicy(f.plan, manifest);
  assert.equal(varied.excludedBuiltinCount, 1); assert.equal(varied.assets[0].rights, "unverified");
  for (const music of [[f.row, f.row], Array.from({ length: 129 }, (_, index) => ({ ...f.row, id: `music-${index}` })),
    [{ ...f.row, sourceSizeBytes: true }], [{ ...f.row, duration: Infinity }], [{ ...f.row, sourceSha256: "forged" }],
    [{ ...f.row, admissionReceiptPath: "" }], [{ ...f.row, originalPath: null }]]) {
    assert.throws(() => guidedMusicPolicy(f.plan, { music }));
  }
});

test("pure music projection changes only the exact selected bed and retains all accepted inputs", () => {
  const f = musicFixture(), before = structuredClone(f.plan), parsed = parseTreatmentProposalV7(proposal());
  const result = applyGuidedMusicOperations({ plan: f.plan, manifest: f.manifest, proposal: parsed, policy: f.evidence.musicPolicy! });
  assert.deepEqual(f.plan, before);
  assert.deepEqual(result, { ...before, music: { enabled: true, assetId: "music-1", gapDb: 11, duck: true } });
  assertGuidedMusicCandidate({ accepted: f.plan, candidate: result, manifest: f.manifest, proposal: parsed });
  const changed = { ...result, music: { ...(result.music as Row), gapDb: 14 } };
  assert.throws(() => assertGuidedMusicCandidate({ accepted: f.plan, candidate: changed, manifest: f.manifest, proposal: parsed }), /actual V7/);
  (result.cutTrack as Row[])[0].end = 2; assert.equal(f.plan.cutTrack[0].end, 16);
});

test("music off, missing ownership, inherited music and unlisted assets block rather than overwrite", () => {
  const f = musicFixture(), parsed = parseTreatmentProposalV7(proposal());
  const { music: _enabled, ...withoutMusic } = f.plan.target; void _enabled;
  const plans = [{ ...f.plan, target: { ...f.plan.target, music: false } }, { ...f.plan, target: withoutMusic },
    { ...f.plan, target: { ...f.plan.target, music: 1 } }, { ...f.plan, music: null },
    { ...f.plan, music: { enabled: false } }, { ...f.plan, music: { enabled: true, assetId: "music-2" } }];
  for (const plan of plans) {
    const before = structuredClone(plan);
    assert.throws(() => applyGuidedMusicOperations({ plan, manifest: f.manifest, proposal: parsed, policy: guidedMusicPolicy(plan, f.manifest) }));
    assert.deepEqual(plan, before);
  }
  const manifest = { music: [{ id: "music-1", source: "builtin", licensed: true }] };
  assert.throws(() => applyGuidedMusicOperations({ plan: f.plan, manifest, proposal: parsed, policy: guidedMusicPolicy(f.plan, manifest) }), /no builtin/);
});

test("rehashed or transplanted music metadata is not accepted as the original evidence", () => {
  const f = musicFixture(), parsed = parseTreatmentProposalV7(proposal());
  const policy = f.evidence.musicPolicy!;
  for (const altered of [{ ...policy, acceptedMusicEnabled: false }, { ...policy, approved: true },
    { ...policy, assets: [{ ...policy.assets[0], sourceSha256: "f".repeat(64) }] }]) {
    assert.throws(() => applyGuidedMusicOperations({ plan: f.plan, manifest: f.manifest, proposal: parsed, policy: altered }), /differs/);
  }
  const preserve = parseTreatmentProposalV7(proposal({ operations: [operation({ type: "preserve-cut", music: null, reason: null })] }));
  const accepted = { ...f.plan, music: { enabled: false } };
  assert.deepEqual(applyGuidedMusicOperations({ plan: accepted, manifest: f.manifest, proposal: preserve, policy }), accepted);
  assert.throws(() => assertGuidedMusicCandidate({ accepted, candidate: f.plan, manifest: f.manifest, proposal: preserve }));
});

test("actual V7 candidate keeps the music operation and exact plan projection, without claiming execution", () => {
  const f = musicFixture(), output = proposal(), before = structuredClone(f.plan);
  const result = buildTreatmentCandidate({ cut: f.cut, output, evidence: f.evidence, rawIntent: RAW });
  assert.deepEqual(result.blockers, []); assert.ok(result.candidate); assert.ok(result.executionBindings);
  assert.equal(result.proposal.schemaVersion, 7); assert.equal(result.proposal.operations[0].type, "music-bed-full-program");
  assert.deepEqual(result.candidate.music, { enabled: true, assetId: "music-1", gapDb: 11, duck: true });
  assert.deepEqual(result.candidate.cutTrack, f.plan.cutTrack); assert.deepEqual(result.candidate.cutDecisions, f.plan.cutDecisions);
  assert.deepEqual(f.plan, before); assert.equal(Object.hasOwn(result, "executable"), false);
  assert.throws(() => buildTreatmentCandidate({ cut: f.cut, output, evidence: { ...f.evidence, schemaVersion: 6 }, rawIntent: RAW }), /exact versioned/);
  assert.throws(() => buildTreatmentCandidate({ cut: f.cut, output, evidence: { ...f.evidence, musicPolicy: undefined }, rawIntent: RAW }), /exact admitted-project/);
});

test("V7 candidate refuses both music operations and no-ops against mismatched accepted intent", () => {
  const f = musicFixture(), before = structuredClone(f.plan);
  for (const intent of [{ music: false }, {}]) {
    const cut = { ...f.cut, job: { ...f.cut.job, ctx: { ...f.cut.job.ctx, intent } } } as AcceptedGuidedCut;
    const preserve = proposal({ operations: [operation({ type: "preserve-cut", music: null, reason: null })] });
    for (const output of [proposal(), preserve]) {
      const result = buildTreatmentCandidate({ cut, output, evidence: f.evidence, rawIntent: RAW });
      assert.equal(result.candidate, null);
      assert.match(result.blockers[0].reason, /stored operator intent/);
    }
  }
  assert.deepEqual(f.plan, before);
});

test("V7 prompt and provider schema retain explicit limitations without a real provider invocation", async () => {
  const f = musicFixture(), prompt = buildProposalPrompt(RAW, f.evidence);
  assert.match(prompt, /music-bed-full-program/); assert.match(prompt, /accepted target already has music:true/);
  assert.match(prompt, /not a validation view/); assert.match(prompt, /proves neither legal rights/);
  const prior = process.env.SNIPER_BRAIN_PROVIDER; process.env.SNIPER_BRAIN_PROVIDER = "codex";
  try {
    await runProposalBrain({ prompt: "TEST ONLY no provider call", ctx: {} as AutoEditCtx, cwd: "/private/tmp", timeoutMs: 500,
      schema: { properties: { schemaVersion: { const: 7 } } } }, { codex: async input => {
        assert.equal(input.schema, "producer-treatment-proposal-v7"); return { message: "{}", stderr: "", ms: 1 };
      } });
  } finally { if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior; }
});

test("mixed music/crop/captions/graphics keep original indices and exact independent projections", () => {
  const f = musicFixture(), raw = RAW + " Crop raw-1 to [0.25,0,0.5,1] without tracking, caption every kept word, and show TEST crop.";
  const plan = { ...f.plan, target: { ...f.plan.target, mode: "short", scope: "light", width: 1080, height: 1920,
    lanes: { graphics: "auto", captions: "auto", motion: "off" } } };
  const crop = operation({ type: "reframe-manual-short", music: null,
    reframe: { schemaVersion: 1, sourceId: "raw-1", layout: "fill", crop: [0.25, 0, 0.5, 1], track: false },
    reason: "TEST ONLY explicitly specified crop, without inferred tracking." });
  const captions = operation({ type: "captions-full-program", music: null,
    captions: { schemaVersion: 1, preset: "producer-config-line-v1", coverage: "all-kept-transcript-words", suppression: "none" },
    reason: "TEST ONLY caption every kept word with the explicitly requested line preset." });
  const graphic = operation({ type: "catalog-graphic", music: null, beatIndex: 0, catalogKind: "TEST-portrait-card",
    variables: [{ name: "title", value: "TEST crop" }], startAnchor: 0, endAnchorExclusive: 1,
    presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
      baseTreatment: "preserve", rationale: "TEST ONLY explicit full native portrait canvas." } });
  const output = proposal({ operations: [operation(), crop, captions, graphic],
    clauses: [{ start: 0, end: raw.length, quote: raw, disposition: "supported",
      rationale: "TEST ONLY four expressly specified independent operations.", operationIndices: [0, 1, 2, 3] }] });
  const evidence = { ...f.evidence, target: plan.target, musicPolicy: guidedMusicPolicy(plan, f.manifest),
    catalog: [{ kind: "TEST-portrait-card", canvas: [1080, 1920], defaults: { title: "TEST" }, fields: ["title"] }] };
  const cut = { ...f.cut, plan: { ...f.cut.plan, value: plan } };
  const result = buildTreatmentCandidate({ cut, evidence, output, rawIntent: raw });
  assert.deepEqual(result.blockers, []); assert.ok(result.candidate);
  assert.deepEqual(result.proposal.operations.map(row => row.type),
    ["music-bed-full-program", "reframe-manual-short", "captions-full-program", "catalog-graphic"]);
  assert.equal(result.executionBindings!.graphics[0].operationIndex, 3);
  assert.deepEqual(result.candidate.music, { enabled: true, assetId: "music-1", gapDb: 11, duck: true });
  assert.deepEqual(result.candidate.reframe, { layout: "fill", crop: [0.25, 0, 0.5, 1], track: false });
  assert.deepEqual(result.candidate.captions, { burn: true });
  assert.deepEqual(result.candidate.cutTrack, plan.cutTrack);
  assertGuidedMusicCandidate({ accepted: plan, candidate: result.candidate, manifest: f.manifest, proposal: parseTreatmentProposalV7(output) });
});
