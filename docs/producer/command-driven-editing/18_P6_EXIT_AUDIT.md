# P6 exit audit — verified reference-style execution

> **Verdict: BLOCKED — 0 of 7 exact P6 exits pass.**
>
> **Evidence date:** 2026-07-30
>
> Project Sniper can study a reference and use measured mechanics as
> **reference-inspired guidance**. It cannot currently promise verified mimicry
> on unseen footage. The internal strategy ID `mimic` remains a compatibility
> value; it is not the released product class.

This ledger audits the exact P6 exits in
[the implementation roadmap](07_IMPLEMENTATION_ROADMAP.md#p6--verified-reference-style-execution).
It deliberately separates study/profile machinery from a qualified style-pack
execution product.

## Verdict rules

- **PASS** requires current executable enforcement plus retained evidence for
  the outcome named by the exit.
- A schema, prompt, linter, synthetic fixture, or negative unit test can prove a
  useful guard. It cannot substitute for the required pack/output/reviewer
  cohort.
- Absence of a released verified-mimic lane is not accepted as vacuous proof
  that its output invariants pass.
- Human review, rights decisions, unseen footage, and timing measurements are
  never invented from code inspection.

## Exact exit table

| # | P6 exit | Verdict | What exists | Missing release evidence |
|---:|---|---|---|---|
| 1 | Three materially different packs have zero unclassified or waived critical items; every noncritical waiver is explicit | **BLOCKED** | `study_deep.py` reports `unclassifiedRuns`; `reference_style_pack.py` rejects a nonzero worklist value and compiles one exhaustively reviewed worklist. | There is no retained three-pack cohort. The V1 pack has no critical/noncritical dimension registry and no named noncritical-waiver records. Its only pack test uses one synthetic 2-second, 320×180 clip. |
| 2 | Reviewer disagreements are adjudicated | **BLOCKED** | The V1 compiler requires mechanics and editorial reviews, rejects a classification disagreement without an adjudication file, and can consume an adjudication lens. | No retained independently reviewed pack with a real disagreement and adjudicated resolution exists. The executable test proves rejection without adjudication, not a completed adjudication outcome. |
| 3 | Every realized mechanic has a proved scene | **BLOCKED** | V1 graphic windows require a template-registry row whose `proofPath` is an existing non-symlink file. P4 separately has governed scene-package render proofs. | `proofPath` is only path existence: it is not hash-bound to a scene package, decoded render, render oracle, pack, or mechanic. Non-graphic cut, caption, transition, motion, b-roll, and audio mechanics have no pack-wide realization-proof closure. |
| 4 | Unsupported mechanics are disclosed before execution | **BLOCKED** | Current UI and authoring prompts now disclose that verified mimic is unqualified. The V1 binding linter rejects missing grammar IDs for the lanes it sees. | The production route uses `reference_profile_lint.py`, not the style-pack linter. There is no exhaustive per-mechanic `supported`, `unobservable`, `unsupported-critical`, or named-waiver ledger bound before execution. Missing profile metrics are intentionally tolerated. |
| 5 | No identity asset is copied without rights | **BLOCKED** | The authoring prompt says “copy mechanics only” and forbids reference words, identity, branding, footage, screenshots, fonts, colors, UI, music, and assets. V1 packs are `structureOnly` with `copyIdentityAssets=false`. The general P4 asset gate verifies exact bytes, license, use/platform, consent, attribution, and expiry. | No transactional P6 binding connects every reference-derived output asset to that rights record and the approved style-pack hash. There is no retained verified-style output cohort on which to prove the invariant. Until then the safe released behavior is to copy no reference identity assets. |
| 6 | Unseen raw footage meets frozen objective tolerances and a three-reviewer no-regression threshold | **BLOCKED** | `reference_profile_lint.py` compares optional aggregate cut/graphic/punch/transition rates and rejects only severe divergence for the legacy `mimic` strategy. | No pre-registered unseen target, frozen cadence/caption/motion/layout tolerances, matched-window receipt, blind review protocol, three independent verdicts, adjudication, or no-regression result exists. |
| 7 | Reference onboarding time is separate from approved-pack editing time | **BLOCKED** | The target documentation states the required separation. | No authoritative timestamps or retained timing receipt identify study/review/adjudication/pack approval separately from planning/render/QC with an already-approved pack. |

## The current production boundary

The reference study route runs `study_deep.py`, retains the deep study, derives
`style_profile.json`, and exposes representative frames. The authoring route
then:

1. reads the server-resolved profile, deep study, and representative frames;
2. tells the model that all reference media and text are untrusted data;
3. permits mechanics-only, reference-inspired guidance;
4. runs `reference_profile_lint.py` for identity, mode, strategy, and available
   aggregate-rate checks.

The production route does **not** run:

- `study/reference_style_cli.py`;
- `study/reference_style_pack.py`; or
- `reference_style_pack_lint.py`.

Those modules are useful offline preparation for a future lane. They are not a
transactional planning/render/QC authority today.

Schema V1 is now explicit about that boundary:

```json
{
  "releaseClass": "reference-inspired",
  "verifiedMimicQualified": false
}
```

The V1 linter accepts legacy packs without `releaseClass` as
`reference-inspired`, but rejects any schema-V1 pack that claims
`verified-mimic`. V2 migration remains unimplemented and must create a new
unapproved candidate rather than rewrite a V1 object under its old hash.

## Replays performed

All **14 reference-focused TypeScript scripts** passed:

```bash
for f in $(rg --files src/lib/producer/__tests__ \
  | rg '/reference[^/]*\.test\.ts$' | sort)
do
  node --import tsx "$f" || exit 1
done
```

They cover admission, decision, fetch/frame/intake policy, intent and prompt
truthfulness, library/profile/provenance, qualification, review context,
selection, sidecars, and study files.

All **74 reference-focused Python unit cases** passed:

```bash
PYTHONPATH=scripts/producer:scripts/producer/tests \
  .venv/bin/python -m unittest \
  scripts.producer.tests.test_reference \
  scripts.producer.tests.test_reference_intake \
  scripts.producer.tests.test_reference_profile_lint \
  scripts.producer.tests.test_reference_style_pack \
  scripts.producer.tests.test_study_deep
```

These passing tests prove the current study/profile guards and the offline V1
compiler contract. They do not change any P6 exit to PASS.

## Locally closed truthfulness gaps

- The visible choice is now **Reference-inspired**, with “verified mimic not
  qualified” beside it.
- The saved selection summary uses the current execution class and repeats the
  verified-mimic boundary.
- The authoring prompt explicitly says the legacy `mimic` value means
  reference-inspired guidance and must not claim exact replication.
- One shared `VERIFIED_MIMIC_RELEASED=false` boundary enumerates all seven
  material qualification blockers.
- Generated V1 packs and CLI output disclose `reference-inspired`; the V1 lint
  gate rejects a fabricated verified-mimic claim.

These are release-truth fixes, not a mimic implementation.

## Required closure sequence

1. Define `ReferenceStylePackV2` with an exhaustive dimension denominator,
   criticality, observability, supported realization, named waiver,
   reviewer/adjudication, rights, grammar, dependency, and toolchain hashes.
2. Keep V1 readable under its existing hash. Make V1→V2 produce a new,
   unapproved candidate with an explicit migration receipt.
3. Wire pack selection, lint, operation bindings, realization proofs,
   dependencies, matched-window QC, invalidation, and final provenance through
   one transactional production lifecycle.
4. Replace path-existence template proof with a content-addressed governed
   scene package, decoded media facts, deterministic render oracle, and exact
   mechanic/grammar binding.
5. Build three materially different real packs. Retain two independent reviews
   for every denominator item and adjudicate every material disagreement.
6. Bind each reference-derived asset to exact bytes and current rights at
   execution and publication time. Expiry or destination mismatch must
   invalidate the affected output.
7. Pre-register distinct short and long-form unseen-footage tests, frozen
   objective tolerances, blind assignment, three reviewers, adjudication, and
   no-regression thresholds before viewing results.
8. Retain separate clocks for onboarding and already-approved-pack editing,
   including fallback and operator-intervention time.

## Edge cases that must remain fail-closed

- Reference bytes, profile, review, template, asset, toolchain, or rights change
  after approval.
- A restudy finds new events or changes the denominator.
- The reference has missing audio, corrupt/truncated media, variable rate,
  unreadable text, or an unclassified persistent visual state.
- No raw/edited pair exists, making selection policy unobservable.
- Reviewer identity is duplicated, reviews are not independent, confidence is
  missing, or adjudication does not bind the exact disagreement.
- A dominant or critical mechanic depends on unsupported continuous tracking,
  animated PIP, proprietary fonts, music, logos, faces, footage, screenshots,
  claims, or UI.
- A mechanic is supported on 9:16 but not 16:9, at one FPS but not another, or
  in a short hook but not across a long-form body/outro.
- A local edit changes a grammar-bound scene, caption, asset, or timing window
  without invalidating its matched-window QC and downstream provenance.
- Prompt injection appears in transcript, OCR, filenames, metadata, captions,
  frames, or review notes.
- One missing/noncritical lane silently changes the denominator instead of
  producing a named waiver and an honest `reference-inspired` downgrade.

## Truthful scope and non-claims

The current system can inspect a supplied reference, measure useful mechanics,
and use those measurements to guide a short- or long-form edit. It also has a
promising offline V1 review/compiler/lint skeleton.

It does **not** yet prove:

- complete understanding or exact replication of an arbitrary reference;
- a production-consumed, approved style pack;
- independent/adjudicated reviewers;
- realization proof for every mechanic;
- unseen-footage objective or editorial equivalence;
- short/long verified mimic qualification;
- reference-style incremental invalidation closure; or
- any 90-minute long-form performance result.

P6 stays blocked until retained real evidence closes all seven exits.
