# Vex implementation lessons for Project Sniper

Examined September 8, 2026. Vex revision: `5789b687ab1b054afb5c54a2f5b231ce02d86029`.

The useful reuse is a set of failure cases, architectural boundaries, and independently written acceptance tests. HyperFrames remains the selected engine. These observations do not propose importing Vex source, prompts, schemas, fixtures, or its application stack.

This review traced implementation and regression tests, then compared the relevant Sniper modules. It also executed a small, original-input probe of Vex's copy helpers and Sniper's existing label helper. It did **not** run Vex's complete test suite, render creator footage, or benchmark a complete job. A regression test describes a covered case; it is not evidence of production-wide reliability. Sniper's current [completion checklist](/Users/maintainer/ProjectSniperSource/docs/producer/REMAINING_WORK_COMPLETION_CHECKLIST.md:55) remains authoritative for unfinished integration and qualification.

## 1. Fit complete copy; do not cut words until they fit

Vex's label-fitting helper rejects text that exceeds its limits. Its display-copy check also rejects certain unfinished clauses and speech-recognition artifacts. Tests include an oversized sentence and dangling transcript fragments. This is a useful pre-render rejection boundary, although its English pattern rules cannot establish semantic completeness generally. [Implementation](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/visual_skill_graph.py#L877), [regressions](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_visual_copy_contract.py#L63).

**Confirmed Sniper helper issue:** [fill_list_spec](/Users/maintainer/ProjectSniperSource/scripts/producer/graphics_copy.py:27) uses [_cap](/Users/maintainer/ProjectSniperSource/scripts/producer/graphics_copy.py:153), which silently retains only the first six label words. The executed probe produced:

- Input: “Keep the original footage until the export passes review”
- Output: “Keep the original footage until the”
- Vex's separately executed check reported `trailing_fragment`.

This proves a helper-level defect, not that the complete Sniper pipeline will publish the fragment. Trace the active caller before changing it. Independently implement a structured “copy needs rewrite” result, have the existing reasoning step author a shorter complete label, then repeat grounding and fit checks. Rejecting a label must not silently discharge an explicitly requested visual treatment. Do not transplant Vex's phrase lists or replace Sniper's semantic reasoning with regex decisions.

**New regression:** a complete but oversized instruction must either remain complete after an approved rewrite or request repair; it must never become a truncated clause.

## 2. A number appearing in the transcript does not make it a statistic

Vex distinguishes version identifiers from measurements, requires metric context, and authorizes visible text for a particular fact/object binding. A string approved for one object cannot simply be moved onto another object. Tests cover version numbers wrongly promoted to metrics, cross-binding text substitution, and mutation of a previously validated copy contract. [Implementation](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/visual_copy_contract.py#L425), [binding regression](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_visual_copy_contract.py#L91).

The executed original-input probe rejected `3.6` as a measure in “The 3.6 and 3.7 models use the same architecture,” while accepting `80 ms` in “Latency fell from 120 ms to 80 ms.”

Sniper's [claims contract](/Users/maintainer/ProjectSniperSource/scripts/producer/claims_contract.py:1) already checks numeric/phrase grounding and explicitly assigns semantic faithfulness to the reasoning step. [Existing tests](/Users/maintainer/ProjectSniperSource/scripts/producer/tests/test_claims_contract.py:42) exclude names such as `GPT-5.6`. Preserve that division. The additional acceptance cases should distinguish numeric occurrence from the identity of the measured subject, unit, and relationship.

**New regressions:** a release number cannot become a speedup; swapping two correctly spelled chart labels must invalidate the affected claim; changing approved text must renew its semantic review.

## 3. Choose graphics around complete explanations and retain alternatives

Vex groups transcript cards using gaps, discourse transitions, topic overlap, and size limits. It selects strong episode representatives, avoids overlap and repeated semantic signatures, and retains reserve candidates. Tests exercise early/middle/late coverage and exclusion of previously failed opportunities. This is heuristic grouping, not demonstrated general discourse understanding. [Episode construction](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/visual_opportunity.py#L245), [selection](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/visual_opportunity.py#L1123), [coverage test](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_visual_opportunity.py#L122).

Sniper already preserves editorial obligations in its [intro semantic contract](/Users/maintainer/ProjectSniperSource/scripts/producer/graphics/intro_semantic_contract.py:1). Qualify the same principle across the requested body: record the explanation served, why a form was chosen, and what happens if it fails. An alternative should address the same obligation unless a changed plan explicitly resolves it.

Do not inherit Vex's duration-derived density target. Also, its top-level orchestration can retry planning **without** failure exclusions when all opportunities were blocked; failure memory is therefore not an unconditional whole-pipeline guarantee. [Fallback path](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tools/auto_visuals.py#L5241).

**New regression:** rejecting an early candidate should not erase a required later explanation or repeatedly regenerate identical failing inputs. Invalidate failure history only when a relevant input or capability changes.

## 4. Verify the graphic inside the final video

Vex checks composite duration, dimensions, audio presence, nonempty output, and visual similarity to the rendered asset. Its tests catch a missing full-screen replacement, lost audio, and duration drift. However, this checker only samples the midpoint of `replace` overlays at 48×27 pixels; it does not establish readable text, partial-overlay visibility, or presenter clearance throughout a transition. [Implementation](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tools/composite_qa.py#L52), [regressions](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_composite_qa.py#L27).

Sniper's [composite visual audit](/Users/maintainer/ProjectSniperSource/scripts/producer/audit/audit_composite_visual.py:1) already compares the composite with actual underlying footage and checks contrast/placement. Its [media checks](/Users/maintainer/ProjectSniperSource/scripts/producer/headless/composite_media_checks.py:1) include audio-stream hashing. Extend and qualify those existing paths; replacing them with Vex's midpoint comparison would lose coverage.

**New regressions:** a graphic visible only at midpoint; a presenter crossing a label during its hold; a caption covered by a presenter bubble; correct standalone graphics missing from the exported composite. Use actual entry, hold, and exit media evidence where the defect requires it.

## 5. Repairs must earn another attempt

Vex separates rendering from semantic publication decisions. Its director caps repair rounds, assesses improvement, stops unsuccessful progression, retains candidates, and selects among publication-ready results. Pairwise comparison reverses candidate order and handles inconsistent preferences. Tests exercise repaired candidates and preference-order effects. [Director](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/director.py#L158), [pairwise comparison](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/verifier.py#L350), [regressions](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_visual_repair.py#L163).

Sniper already has [private one-unit scene repair](/Users/maintainer/ProjectSniperSource/scripts/producer/graphics/scene_review_repair.py:1) and [retained body deadlines](/Users/maintainer/ProjectSniperSource/scripts/producer/guided_body_budget.py:1). Connect repair decisions to the original request budget and an explicit defect. A style improvement must not authorize changing a fact or an unrelated scene. Candidate tournaments are optional: they spend time and should require remaining budget and a material selection benefit.

**New regressions:** the same failing candidate stops; a prettier but factually worse candidate is rejected; restart does not create a fresh budget; late failure preserves the last accepted parent.

## 6. Keep source time and edited time distinct

Vex's stitched-transcript helper accumulates output offsets while retaining original source bounds and range identity. Its test maps source spans 0–2 and 10–12 seconds into a continuous 0–4-second result. [Implementation](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tools/auto_shorts.py#L2849), [test](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_auto_shorts.py#L345).

Sniper already does this through [compile_timeline](/Users/maintainer/ProjectSniperSource/scripts/producer/compile_timeline.py:219) and [output_words](/Users/maintainer/ProjectSniperSource/scripts/producer/graphics_planner.py:93). Reuse that authority for SDK changes, captions, graphic reveals, and cut-ripple revisions. Do not introduce another timestamp system.

**New integration regression:** remove a middle source passage, then change one graphic label. Source references, captions, and spoken reveal anchors must remain correct; unaffected media must retain its identity.

## 7. Protect good footage from unnecessary color changes

Vex estimates neutral midtones separately from saturated regions and skin-like pixels, penalizes excessive adjustment, and encourages continuity between similar shots. Tests include already balanced skin, screen recordings, and neighboring shots. These masks and synthetic fixtures are heuristics, not proof of comprehensive skin-tone or camera-format support. [Analysis and penalties](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/color_grading.py#L2250), [neutral mask](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/color_grading.py#L2390), [regressions](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_color_grading.py#L134).

Sniper's [current screening](/Users/maintainer/ProjectSniperSource/scripts/producer/color/statistics.py:56) already warns that average chroma is not a neutral reference. Preserve source/transform-history authority and qualify actual supported media before adding stronger correction. Good footage should be allowed to remain unchanged.

**New regressions:** saturated background with a neutral reference; diverse skin tones; already corrected material; readable screen capture; two similar adjacent shots that must not visibly flicker. Compare actual preview and export below graphics.

## 8. A rendered file is not yet a committed edit

Vex snapshots state before mutation, attempts restoration after failure, saves state through temporary-file replacement, and validates temporary exports before replacing the final file. Tests simulate operation-save failure and output-validation failure. [Mutation boundary](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tools/speed.py#L33), [state save](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/state.py#L138), [export](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/engine.py#L1609), [failure test](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/tests/test_tool_transaction_hardening.py#L91).

Sniper already tests [restoration after checkpoint failure](/Users/maintainer/ProjectSniperSource/scripts/producer/tests/test_palmier_sync_transaction.py:197) and [candidate-byte validation](/Users/maintainer/ProjectSniperSource/scripts/producer/tests/test_p2_cut_repair_promotion_gate.py:229). Apply those existing guarantees to the HyperFrames SDK adapter.

**New integration regression:** rendering succeeds but state publication fails; the approved parent, timeline, and selected output remain usable. Also test interruption during publication. Vex's tested in-process restoration should not be treated as proof of crash recovery or successful rollback when storage remains full.

## Limits that should not become Sniper defaults

- Vex can explicitly publish a degraded result when independent verification is unavailable and local checks pass. Preserve Sniper's applicable review requirements instead of weakening them on outage. [Unavailable-verifier policy](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/vex_visuals/verifier.py#L645).
- Vex's per-stage planning budget and repair-round caps do not themselves establish one durable complete-request deadline. Sniper's remaining global-budget work still needs qualification.
- Its lower-memory export retry classifier includes generic external-library errors, not only confirmed allocation failures. Learn conditional retry and preservation of the accepted output; independently classify actual host failures. [Classifier](https://github.com/AKMessi/vex/blob/5789b687ab1b054afb5c54a2f5b231ce02d86029/engine.py#L2048).

## Implementation order

1. Trace and fix the confirmed copy-truncation helper on the active route; add complete-copy and semantic-binding regression cases.
2. Apply existing private-candidate, timing, and publication guarantees to the disposable HyperFrames SDK adapter.
3. Qualify composite checks through moving presenter/caption/graphic states and exported output.
4. Integrate semantic coverage, alternatives, and no-progress repair decisions into the existing durable request budget.
5. Use Vex-inspired color failure scenarios in the existing source-aware finishing work.

These are additions to the active implementation task, not a replacement architecture or a claim that its current checklist is complete. The expected savings come from preventing avoidable failed renders and rebuilding only affected work; no end-to-end time reduction has been measured in this review.
