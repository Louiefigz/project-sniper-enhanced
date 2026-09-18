/** Pure dependency selection; empty catalog is not a measured capability or ready edit. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { omittedProposalCatalog } from "../guided-proposal-evidence";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { buildTreatmentCandidate } from "../guided-proposal-candidate";
import { parseTreatmentProposalV6 } from "@/lib/producer/contracts/treatment-proposal-v6";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { RAW_V6_SHORT, v6ShortProposal } from "./_guided-v6-short-proposal";

function previsual() {
  return { planVersion: 3, target: { mode: "short", scope: "light", width: 1080, height: 1920,
    fps: 30, lanes: { captions: "auto", graphics: "off", motion: "off" } },
  cutTrack: [{ sourceId: "TEST-only", start: 0, end: 16, speed: 1 }], cutDecisions: { schemaVersion: 1, removals: [] } };
}

test("V6 exact graphics-off previsual exposes zero graphics authority and binds the full original target", () => {
  const plan = previsual(), before = structuredClone(plan), value = omittedProposalCatalog(6, plan);
  assert.ok(value); assert.deepEqual(value.catalog, []); assert.deepEqual(plan, before);
  assert.equal(value.catalogHash, canonicalJsonSha256({ schemaVersion: 1,
    kind: "explicit-graphics-off-proposal-catalog-omission", scope: "no-generated-graphics-no-measured-catalog-authority",
    targetHash: canonicalJsonSha256(plan.target) }));
  plan.target.fps = 24;
  assert.notEqual(omittedProposalCatalog(6, plan)?.catalogHash, value.catalogHash);
});

test("historical versions still require the original measured catalog", () => {
  for (const version of [2, 3, 4, 5]) assert.equal(omittedProposalCatalog(version, previsual()), null);
});

test("explicit V7 and V8 share only the same exact no-graphics dependency omission", () => {
  const plan = previsual();
  Object.assign(plan.target, { music: true });
  const before = structuredClone(plan), expected = omittedProposalCatalog(6, plan);
  assert.ok(expected); assert.deepEqual(expected.catalog, []);
  for (const version of [7, 8]) {
    assert.deepEqual(omittedProposalCatalog(version, plan), expected);
    assert.equal(omittedProposalCatalog(version, { ...plan, music: { enabled: true } }), null);
    assert.equal(omittedProposalCatalog(version, { ...plan, graphicsTrack: [] }), null);
    assert.equal(omittedProposalCatalog(version, { ...plan, target: { ...plan.target, lanes: { graphics: "auto" } } }), null);
  }
  assert.deepEqual(plan, before);
});

test("auto/operator/supplied/default and malformed graphics choices cannot borrow explicit-off omission", () => {
  for (const directive of ["auto", "operator", "OFF", false, null, ["off"], {}]) {
    const plan = previsual();
    (plan.target.lanes as Record<string, unknown>).graphics = directive;
    assert.equal(omittedProposalCatalog(6, plan), null);
  }
  const plan = previsual() as Record<string, unknown>;
  delete (plan.target as Record<string, unknown>).lanes;
  assert.equal(omittedProposalCatalog(6, plan), null);
});

test("inherited graphics or any expanded plan cannot bypass its original dependency authority", () => {
  for (const field of ["graphicsTrack", "titleCards", "reframe", "captions", "scenePackages", "unexpected"]) {
    for (const value of [null, [], {}, [{ kind: "agenda-slide" }]]) {
      assert.equal(omittedProposalCatalog(6, { ...previsual(), [field]: value }), null);
    }
  }
});

test("named Restrained base-kit conflict is not erased by graphics-off", () => {
  const plan = previsual();
  Object.assign(plan.target, { style: "restrained" });
  assert.equal(omittedProposalCatalog(6, plan), null);
});

test("actual V6 candidate compiler blocks a structurally valid graphic against omitted catalog authority", () => {
  const plan = previsual(), omitted = omittedProposalCatalog(6, plan);
  assert.ok(omitted);
  const evidence = { schemaVersion: 6, target: plan.target, ...omitted, frameRate: "30/1", totalFrames: 480,
    anchors: [0, 240, 480], cleanEnds: [480], introSeams: [], hookWindowS: 60,
    timelineMapHash: "a".repeat(64), graphicsAdvice: { "graphics_planner.py": { introSemanticBeats: [] } } };
  const input = { prompt: `INPUT_DATA_JSON\n${JSON.stringify({ evidence })}` } as ProposalBrainInput;
  const proposal = v6ShortProposal(input), extra = " Show a native portrait title card.";
  proposal.clauses.push({ start: RAW_V6_SHORT.length, end: RAW_V6_SHORT.length + extra.length, quote: extra,
    disposition: "supported", rationale: "TEST ONLY adversarial graphic request without catalog authority.", operationIndices: [2] });
  (proposal.operations as unknown[]).push({ type: "catalog-graphic", clauseIndex: 2, beatIndex: 0,
    catalogKind: "statement-card", variables: [{ name: "title", value: "TEST ONLY" }], grade: null,
    startAnchor: 0, endAnchorExclusive: 1, captions: null, reframe: null,
    reason: "TEST ONLY attempt to borrow a graphics-off catalog omission.",
    presentation: { schemaVersion: 1, anchor: "own-screen", placement: "full-canvas", compositeMode: "normal",
      baseTreatment: "preserve", rationale: "TEST ONLY request a native portrait card." } });
  assert.equal(parseTreatmentProposalV6(proposal).operations[2].type, "catalog-graphic");
  const before = structuredClone(plan);
  const result = buildTreatmentCandidate({ cut: { plan: { value: plan } } as unknown as AcceptedGuidedCut,
    rawIntent: RAW_V6_SHORT + extra, evidence: evidence as unknown as ProposalEvidence, output: proposal });
  assert.equal(result.candidate, null); assert.equal(result.executionBindings, undefined);
  assert.ok(result.blockers.some((row) => row.clauseIndex === 2 && /catalog kind.*unavailable/.test(row.reason)));
  assert.deepEqual(plan, before); assert.deepEqual(evidence.catalog, []);
});
