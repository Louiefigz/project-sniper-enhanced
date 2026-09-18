import assert from "node:assert/strict";
import { test } from "node:test";
import { assertGuidedMusicIntent, guidedMusicPolicy } from "../guided-proposal-music";
import { assertStoredProposalEvidence, buildProposalEvidence, type ProposalEvidence } from "../guided-proposal-evidence";
import { openingMediaAuthority } from "../guided-opening-media-input";
import type { OpeningReadiness } from "../guided-opening-authority";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { layoutProposal } from "@/lib/producer/__tests__/_presenter-layout-fixture";
import { historicalNoPresenterProposal } from "./_guided-opening-v8-no-presenter-fixture";

/** TEST ONLY intentionally incomplete fixtures expose whether refusal precedes all pipeline work. */
function authorityFixture(target: Record<string, unknown>, intent: unknown) {
  const cut = { plan: { value: { target } }, job: { ctx: { intent } } } as unknown as AcceptedGuidedCut;
  const staged = { ctx: {} as AutoEditCtx, manifest: {}, graphicsAdvice: {} };
  return { cut, staged };
}

/** Closed no-presenter TEST metadata reaches intent screening; no actual draft or media authority exists. */
function openingFixture(target: Record<string, unknown>, intent: unknown): OpeningReadiness {
  const { cut } = authorityFixture(target, intent);
  return { ...cut, manifest: { value: {} }, result: { candidate: structuredClone(cut.plan.value),
    proposal: historicalNoPresenterProposal(layoutProposal(), 7) } } as unknown as OpeningReadiness;
}

test("locked target music is a strict mirror, never independent operator authority", () => {
  for (const [target, intent] of [[{}, {}], [{ music: false }, {}], [{}, { music: false }],
    [{ music: false }, { music: false }], [{ music: true }, { music: true }]]) {
    const plan = { target }, before = structuredClone({ plan, intent });
    assert.doesNotThrow(() => assertGuidedMusicIntent(plan, intent));
    assert.deepEqual({ plan, intent }, before);
  }
  for (const [target, intent] of [[{}, { music: true }], [{ music: true }, {}],
    [{ music: false }, { music: true }], [{ music: true }, { music: false }]]) {
    const plan = { target }, before = structuredClone(plan);
    assert.throws(() => assertGuidedMusicIntent(plan, intent), /stored operator intent/);
    assert.deepEqual(plan, before);
  }
  for (const invalid of [1, 0, "true", "false", null, [], {}, undefined]) {
    assert.throws(() => assertGuidedMusicIntent({ target: { music: invalid } }, {}), /actual boolean/);
    assert.throws(() => assertGuidedMusicIntent({ target: {} }, { music: invalid }), /actual boolean/);
    assert.throws(() => guidedMusicPolicy({ target: { music: invalid } }, {}), /actual boolean/);
  }
  for (const intent of [undefined, null, false, []]) {
    assert.throws(() => assertGuidedMusicIntent({ target: {} }, intent), /operator intent/);
  }
});

test("fresh and historical V7 evidence reject context mismatch before any pipeline, catalog or media work", async () => {
  for (const [target, intent] of [[{}, { music: true }], [{ music: true }, { music: false }]]) {
    const { cut, staged } = authorityFixture(target, intent), before = structuredClone(cut);
    await assert.rejects(buildProposalEvidence(cut, staged, { version: 7 }), /stored operator intent/);
    assert.throws(() => assertStoredProposalEvidence(cut, { schemaVersion: 7 } as ProposalEvidence, staged), /stored operator intent/);
    assert.deepEqual(cut, before);
  }
  const { cut, staged } = authorityFixture({ music: true }, { music: true });
  await assert.rejects(buildProposalEvidence(cut, staged, { version: 7 }), /pinned pipeline/);
  // Historical classes retain their existing checks, not a newly imposed music mirror.
  const old = authorityFixture({}, { music: true });
  await assert.rejects(buildProposalEvidence(old.cut, old.staged, { version: 6 }), /pinned pipeline/);
});

test("V7 owner intake independently rejects stale music intent before opening preparation", () => {
  for (const [target, intent] of [[{}, { music: true }], [{ music: true }, {}]]) {
    const opening = openingFixture(target, intent), before = structuredClone(opening);
    assert.throws(() => openingMediaAuthority(opening), /stored operator intent/);
    assert.deepEqual(opening, before);
  }
  const opening = openingFixture({ music: true }, { music: true });
  assert.throws(() => openingMediaAuthority(opening), /clean isolated TREATMENT_DRAFT/);
  assert.throws(() => openingMediaAuthority({ ...opening, manifest: undefined } as unknown as OpeningReadiness), /original manifest/);
});
