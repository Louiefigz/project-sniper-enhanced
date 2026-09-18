> Authored 2026-07-14 from the measured job journals + a 21-agent code teardown.
> THE rebuild spec: why the GUI takes hours for bare-minimum output, why Palmier
> stays empty, why template selection is narrow — and the P0/P1/P2 punch list.
> Companion to docs/palmier/PALMIER_LIVE_BUILD_SPEC.md.

# Why the bare minimum takes hours: PRODUCER auto-edit teardown and rebuild spec

**TL;DR.** The pipeline is not slow because editing is slow — the measured MCP work to place an entire cut track in Palmier is **~190 ms**, a cached graphic commit is **~130 ms**, and the same edit hand-driven over Palmier MCP took **~15 minutes including graphics**. The pipeline is slow because it is a **serial chain of 8+ cold 20–30-minute-capped LLM spawns**, gated so that **nothing is visible anywhere until everything passes**, wrapped in **all-or-nothing transactions that discard 100% of completed work on any single defect**, with **retry semantics that erase the journal and re-author from scratch**. Across the measured day: ~2.1 hours of attempts (33.2 + 4.8 + ~80 + 7.3 min), **0 final.mp4, 0 elements ever retained in Palmier**. Effective discard ratio: ~100%.

---

## 1. Where the hours actually go

### The serial spawn chain (produced scope, happy path)

Minimum clean run = **8 LLM spawns in 6 serial LLM stages** + ~13 deterministic Python gate runs + 1 render + 3 Palmier pushes. Serial timeout budget ≈ **155 min**; observed-rate wall clock ≈ **24–30 min** best case (≈50 min when visual authoring runs at its measured 26.4 min). Typical run with one cut revision + one planning revision + one QC repair = **19 spawns / 14 serial stages ≈ 55–100 min**. Every spawn on the default (legacy) provider is a **cold `claude -p`** — no `--resume`, no `--effort`, re-reading SKILL.md + FAILURE_LEDGER.md + plan + manifest + transcripts from scratch each time (`brain-review-process.ts:44-64`, `revision-prompt.ts:31-34`); only authoring gets session reuse and effort pins (`authoring.ts:73-95`).

| Stage | Spawns | Cap | Measured | Serial? | Discarded on failure? |
|---|---|---|---|---|---|
| Cut authoring | 1 LLM | 30 min | 3.5–4 min (26.4 min once) | yes | Timeout discards all (no mid-flight draft checkpoint); Retry re-authors unless a cut-approval receipt exists (`authoring-stage.ts:227-235`) |
| Cut review | 2 critics ∥/batch, cap 6 rounds, 2 clean required | 20 min each | ~3.3 min | yes (after author) | Round/clean progress is **memory-only** (`cut-review-loop.ts:158-169`); interrupt re-pays every round |
| Visual authoring | 1 LLM | 30 min | ~4 min | yes | Invalidated on resume without receipt; 26.4-min plan invalidated across run 1's 4 attempts |
| Planning gates | 6–7 Python (5-min cap each) | ~35 min budget | seconds–minutes | yes, before every critic batch | Re-run in full every batch |
| Planning critics | 2 ∥/batch (4-round cap, 2 clean required) | 20 min each | 6.3 / 3.5 min | yes | Any material issue **zeroes clean credit** (`planning-loop.ts:214-217`) |
| Planning revision | 1 LLM per dirty round | 20 min | 2.8 min and **14.8 min** | yes | Zeroes clean rounds (`planning-loop.ts:139-149`); burns 1 of 4 rounds |
| Render (assemble) | 1 | **unbounded** | ~3 min | yes | Fully re-run per QC repair |
| Audit B | 1 Python | **no timeout at all** (`audit-gate.ts:57-83`) | ~2 min | yes | — |
| QC lens critics | 2 ∥ | 20 min each | 5–20 min | yes | — |
| QC repair | 1 LLM per finding, ≤3 render rounds | 20 min | — | yes | Invalidates to `plan_authored`/round 0 → **re-pays planning + render + QC in full**: 15–30 min per finding (`quality-loop.ts:256-262`) |
| Palmier checkpoint | subprocess | 10 min | ~24 s (~0.5–2 s MCP) | yes | **Failure kills the entire job** in the live WIP (`palmier-checkpoints.ts:173-177, 231-235`) |

### The four compounding multipliers

**M1 — One QC finding restarts the whole tail (F1, CONFIRMED).** A material finding spawns a 20-min-capped revision, then invalidates back to `plan_authored` with `planningRound: 0` and wipes every hash (`quality-loop.ts:256-262`, `auto-edit-job-store.ts:213-232`). The pipeline re-runs: full gate bundle → 2 fresh clean critic rounds → full re-render → full 2-critic QC. **No QC finding is ever fixed incrementally against the existing candidate** — the only non-approve exit from a QC round is `repairCandidate`. ≈15–30 min per finding, up to 3 candidate renders, then hard death.

**M2 — The planning round budget is arithmetically near-unwinnable (F2, CONFIRMED).** `MAX_PLANNING_REVIEW_ROUNDS=4`, produced scope needs 2 clean, any material issue resets clean credit to 0, and a 2-wide critic batch burns 2 rounds at once (`round-policy.ts:3,13-15`; `planning-loop.ts:201-224`). On the critic path **exactly one revision cycle can ever succeed** (batch1 dirty → revise → batch2 must be 2/2 clean or `max_rounds_exhausted` — thrown *after* the revision was paid for). Worse: the loop never checks whether remaining budget ≥ required cleans, so at round 3/clean 0 it still pays a revision into a mathematically dead width-1 round-4 batch. The measured run was interrupted at round 2 / clean 0 with **17.6 min of revisions already sunk on a path the current code makes strictly unwinnable**.

**M3 — Deterministic gate failures cost LLM time (F4).** A gate lint that already knows exactly what's wrong is fed to a full 20-min-capped revision writer as a synthetic dirty round (`planning-review-batch.ts:81-114`). Journal-confirmed: the **14.8-minute revision followed a `planning_gate_bundle ok:false` with zero critic spawn** (review ms=0). A mechanical verdict cost 14.8 min of model time and 1 of 4 planning rounds.

**M4 — Retry destroys everything (D1/D2, CONFIRMED).** A fresh Retry over a dead journal writes `freshJob` — attempts 1, events [], clean rounds 0 — atomically clobbering the prior journal and **truncating the worker log to zero** (`auto-edit-job-store.ts:82-88`, `auto-edit-job-builders.ts:39-65`, `auto-edit-log.ts:40-47`). The saved-plan bootstrap is explicitly disabled whenever *any* journal exists (`launch.ts:45`). This is exactly run -3: **an ~80-min attempt's journal overwritten by a 7.3-min retry that re-paid authoring + cut review the 80-min run had already done.** Resume 409s after *any* intent change — the requestKey hashes the full ctx including intent, rebuilt from the *current* stored intent, so even resubmitting the original intent fails (`auto-edit-job-store.ts:69-73`, `launch.ts:61-69`) — and for interrupted runs the UI offers *only* the permanently-409ing Resume button (`stage-actions.tsx:233`). On top of that, the authority digest hashes the **live pipeline source tree** — one code edit or intent touch mid-run kills the job and zeroes clean rounds + candidate reuse on resume (D8, `auto-edit-authority-snapshot.ts:151-174`).

**Net measured economics:** work that survived on disk but was never reused by any retry path: `edit_plan.json` + snapshots, the cut-approval receipt, all review JSONs, rendered candidates under an orphaned `.sniper-qc/<token>/`. Deliverables across the day: **zero**. The pipeline's *best* case (~25–30 min) already loses to the ~15-min manual MCP session; its typical case loses by 4–6×.

---

## 2. Why Palmier stays empty and inconsistent

**The model is a full rebuild inside an all-or-nothing transaction (PAL-1, CONFIRMED).** Every checkpoint: create a brand-new **empty** shadow timeline (`shadow.py:208-219`) → re-place **every** cut/keyframe/overlay/text from scratch (`sync.py:165-188`) → verify the **whole** timeline (`verify.py:290-324`) → on *any* exception, restore the human timeline, rename the shadow `-FAILED`, and abandon it (`checkpoint.py:251-258`). Zero delta reuse between checkpoints — reuse is only an exact sha256 match on (stage, round, planHash, manifestHash, mediaHash). Only media imports and graphics renders (content-hash caches) survive.

**Measured proof (PAL-2, CONFIRMED).** In run 20260713 all three checkpoints **fully built the shadow in ~0.5 s of MCP work** — cuts placed, keyframes set, overlays placed, all succeeding — then verification threw the identical deterministic error three times (`trimStartFrame 366, expected 367`, a 23.976→24 fps conform off-by-one that the run-time verifier checked at `abs_tol=1e-6`) and **discarded 100% of the placed clips, three times**. The ±1-frame tolerance was patched into the live tree ~12 minutes *after* the burn, uncommitted — the whack-a-mole pattern: patch each verifier tolerance post-mortem, keep the discard-everything architecture.

**Checkpoints only fire at boundaries (PAL-3, CONFIRMED).** Exactly four sites: first-clean planning round, post-QC-repair, post-render, approved mirror. Nothing fires during authoring, critic rounds, or the 14.8-min revision. Earliest possible artifact ≈ minute 10 — and it was then discarded.

**~40 distinct discard triggers**, in four classes (PAL-5/6/7):
- **Pre-build** (Palmier stays stale): lock busy, wrong project focused, workspace not managed-draft, `ownership=palmier`, sidecar unreadable, baseline-guard supersede, plan-hash staleness, media import timeout.
- **Lane-prep vetoes** (one bad element kills all): first failing graphic render aborts the checkpoint; **the transitions lane raises by design, so a full-workflow Long can *never* publish a plan checkpoint** (`checkpoint_plan.py:147-159`); one unmappable motion row aborts.
- **Build+verify** (placed clips destroyed): duplicate clip id, 1-frame conform, per-lane count mismatch, seam gap, keyframe diff, any operator touch during the verify CAS window.
- **Failure semantics flipped to job-fatal** (D3/QC-2, CONFIRMED): in the live WIP, a "non-authoritative" courtesy checkpoint (`checkpoint.py:2,57`) that returns anything but `checkpoint_ready` **throws and kills the whole run** — including benign `checkpoint_waiting` from a busy flock. And the clean critic round is persisted *after* the publish (D4), so a checkpoint failure also discards the 6–20-min review that preceded it.

**The permanent mute (D11):** one human edit in Palmier flips `ownership=palmier` and silently skips every subsequent checkpoint *and the final approved mirror* forever, with no operator-visible unmute.

**The bitter irony (PAL-8):** a correct per-element primitive already exists in the repo — `native_delta._apply_operation` is CAS-per-operation with before/after fingerprint receipts, quarantines partial builds instead of deleting them, and can resume a visible partial timeline. It is fenced away from every produced edit: any intent with graphics/transitions/credibility routes to the governed all-or-nothing path (`palmier-primary-selection.ts:140-145`). **The operator's real jobs can never use the incremental machinery that exists.**

---

## 3. Why the templates are wrong

The brain **does** see the full 46-kind catalog every authoring round (TPL-1 — one line per `COMPS_CATALOG` entry, `authoring-prompt.ts:294-295`). The narrowness is everything downstream of the menu:

1. **Two contradictory authorities in one prompt (TPL-2, CONFIRMED).** Line 292 commands picking *every* graphicsTrack kind from `card_form_map` — 9 information shapes covering only **26 of 46 kinds**. **20 kinds are in no family** and thus dead vocabulary on the automatic path, including 3 of the 4 Angela pack comps, `jaden-shout-lockup`, all transition punctuation (color-wash/glitch-hit/stinger-wipe), and all 4 primitives. 43% of the renderable library cannot be selected.

2. **The real vocabulary is 2–5 kinds per beat, hard-gated (TPL-3, CONFIRMED).** `intro_semantic_binding` rejects any kind outside `compatibleKinds`, built from hand-frozen per-trigger tuples filtered to wide-canvas + gate-executable: **union of 18 reachable kinds total**; evidence beats get **exactly 2** (portrait comps like `angela-receipt-cell`/`stat-card`/`versus-split` are structurally unreachable for longform). The prompt then says "Start from that assignment" — and the real plan matched the deterministic `recommendedAssignment` **7/8**. The allocator, not the brain, picks templates.

3. **The "semantic beats" are overfit to this one video (TPL-4, CONFIRMED, blocker).** `_CUE_SPECS` is 6 hardcoded phrase groups **copied verbatim from this video's transcript** (including a literal 6-word sentence). On other footage they mostly won't fire, and if <4 first-minute beats result, both hard gates dead-end the run with "insufficient transcript beats… never lower the floor" — the prompt explicitly instructs the brain to stop. A designed dead-end, matching the operator's b-roll-gate experience.

4. **Variety pressure is mathematically inert (TPL-5).** Cross-project novelty requires a kind in ≥3 of the last 8 **QC-approved + Palmier-mirror-verified** projects. Since no run has ever reached QC approval and every Palmier push failed, all 6 captured histories show `projectCount=0, overusedKinds=[]` — the machinery costs prompt steps and one Python gate spawn per round and delivers zero pressure.

5. **The style packs the operator studied are machine-unreachable (TPL-8).** No planner trigger maps to the Angela pack or `jaden-shout-lockup`; a "Short · Angela" job proposes the same generic ~8 kinds. Across all 6 longform plans on disk, **only 14 distinct kinds have ever appeared**.

6. **The critic can't audit template fit (TPL-7).** It's ordered to flag "repeated familiar forms despite better alternatives," but its packet contains no catalog descriptions and no `graphics_proposal` — kinds are opaque strings; it cannot name a template it has never seen.

---

## 4. The target architecture

The operator's mandate, made concrete: **land everything upstream immediately, verify per element, bring QC down later as annotations, never discard completed work.**

### Incremental landing timeline
- **~4–8 min: cuts in Palmier.** Publish a `cut`-stage checkpoint immediately after `approveCut` (`authoring-stage.ts:247`) — the cut track is hash-final there, the deterministic transcript wall + 2 clean cut critics already passed, and cuts place in **190 ms** of MCP work. This precedes visual authoring entirely.
- **As each graphic renders: one commit each.** `checkpoint_plan.py:133` already emits per-graphic `checkpoint_graphic_ready`; commit there (~130 ms each, cache-hit detection exists) instead of batching into a boundary transaction.
- **Then keyframes, then texts**, each through the `_apply_operation` CAS envelope (read-active → one tool call → read-active → structural diff → receipt) lifted from `native_delta.py` into the governed Executor loop. No new MCP surface needed.

### Per-element commits, per-element verification
- **One persistent Sniper working timeline** per project (created once; `workingTimelineId` in `palmier.sync.json`) — delete new-shadow-per-checkpoint.
- **Element ledger sidecar** (`palmier.elements.json`): one row per element keyed by content identity (cuts: entry hash; graphics: the existing render `content_hash`; keyframes: parent-cut + property + rows hash), status `pending|placed|verified|failed|stale`, with receipts.
- **Verification splits**: `_verify_one` + `verify_properties` are *already per-clip* — run them inside each element's own CAS window and mark only that row. Global invariants (totalFrames, seam continuity) become a non-fatal **health report**, never a discard.
- **A failed element = a ledger row + warning event + skip.** `mark_failed`/`restore_human`/`-FAILED` renames are deleted from the working path. One 1-frame conform disagreement flags one clip "placed-unverified" and continues; it never unwinds N−1 good elements.
- **Revisions apply as ledger diffs**: `plan_refit` already remaps overlay/keyframe windows old→new; unchanged elementKey+window → untouched, moved → one `move_clips`, cut-away → remove that clip only. Non-rippling placement (explicit startFrame) so overlays never move twice. Manual-edit drift classifies **per element** ("stale-manual", protected) instead of flipping the whole workspace to a permanent ownership mute.

### QC comes down as annotations + fix-forward
- **Stays upstream (blocks landing of the specific artifact only):** `claims_contract` (fabricated numbers/CTAs — per-card, blocks one card, never the cut); `operator_intent` identity (mode/scope/reference — wrong-video class); the `transcript_cut` previsual wall; `plan_lint` identifier/range/overlap subset (unrenderable references can land nowhere).
- **Comes down as annotations:** hook density/front-load, hook-opens-dressed, entity→graphic and credibility-card obligations, transitions coverage, lane-coverage completeness, duration floors, title-card rules, template variety, reference conformance, Audit B pacing/loudness, both visual lens critics. `audit_render.py` already emits per-check, timestamped, machine-readable evidence — it needs an annotation sink (timeline markers / `findings[]` in the sidecar), not new checks.
- **Fix-forward, not rebuild:** findings patch only the flagged artifact through the existing surgical dispatch (graphics ≈18 s, audio ≈12 s re-renders — already shipped). A pacing annotation never triggers plan-wide re-review.
- **Doctrine holds (QC-7):** the render checkpoint *already* lands pre-QC media in Palmier, and drafts are *already* stamped `authoritative: false` while approval is a separate hash-locked ledger. The doctrine sentence changes from "a block prevents rendering" to "a block prevents **approval**." Every gate still runs, still fails closed — only the consequence attachment point moves.

### State machine

```
            cut passes cut-wall                 all elements landed,
            (transcript wall +                  Audit B + lenses run,
            plan_lint --cuts-only +             findings[] persisted
            intent identity)
  [queued] ────────────────────► [DRAFT-IN-PALMIER] ────────────────► [QC-ANNOTATED]
                                  authoritative:false                 "Draft + k findings
                                  "Draft (unreviewed) —               (m material)"
                                   n/N elements landed"                    │
                                        ▲                                  │ fix-forward passes /
                                        │  any edit (human or              │ human edits resolve
                                        │  fix-forward) moves that         │ material findings;
                                        │  ARTIFACT back to draft          │ clean-review quota met
                                        └──────────────────────────────    ▼
                                                                      [APPROVED]
                                                                      promoteApprovedCandidate +
                                                                      publishApprovedPalmierMirror
                                                                      (unchanged, hash-locked)
```

### Kept-work economics
Nothing re-authored (retroactive cut receipts on saved plans; journals archived, never clobbered; resume reconciles intent deltas instead of 409ing). Nothing re-rendered (extend the content-hash discipline that already works for media/graphics to timeline builds and QC candidates; pin `artifactToken` to the project so candidates survive fresh jobs). Failed elements skip, not discard. On block/exhaustion, promote the best rejected candidate to a labeled `draft.mp4` — the operator ships or opens it; QC verdicts become punchlist items, not terminal failures.

---

## 5. The punch list

Effort: **S** = flags/reorder, hours. **M** = days. **L** = new subsystem, ~week. **[DEL]** = deletes/simplifies existing complexity rather than adding.

### P0 — stop the bleeding (S batch; alone this gets cuts visible in Palmier at ~5–8 min and stops jobs dying)

| # | Change | Files | Effort |
|---|---|---|---|
| 1 | **Working checkpoints never throw** [DEL]: three-valued outcome (committed / warned / deferred-waiting); `checkpoint_waiting` requeues; only the approved mirror may fail loudly — and it fails the push, not the run | `palmier-checkpoints.ts:173-177, 231-235, 262-267` | S |
| 2 | **New checkpoint stage `cut`, fired right after `approveCut`** — the ≤5-min cut in Palmier | `authoring-stage.ts:247`; `palmier-checkpoints.ts:16`; `checkpoint_cli.py:22`; translate/executor unchanged | S |
| 3 | **Persist the clean round BEFORE the courtesy publish** [DEL] (publish consumes state, must never gate it) | `planning-clean-progress.ts:54-65` (swap order) | S |
| 4 | **Kill the journal clobber** [DEL of the re-author path]: archive dead journals on fresh launch; always bootstrap from a verifying on-disk `edit_plan.json` + cut receipt to `plan_authored` (the `reviewSavedPlan` branch already proves this works); wire it to the Retry button; stop truncating the worker log | `auto-edit-job-store.ts:82-88`; `launch.ts:41-50`; `auto-edit-job-builders.ts:39-65`; `stage-actions.tsx:233` | S |
| 5 | **Gate failures never spawn full revisions or burn critic rounds** [DEL]: route gate-only failures to a bounded low-effort schema-constrained fixer fed only the gate diagnostics; don't charge the round budget (kills the 14.8-min class) | `planning-review-batch.ts:81-114`; `planning-loop.ts:222` | S |
| 6 | **Fix the round arithmetic** [DEL]: count revision *cycles*, not critic spawns; refuse to pay a revision into a batch that cannot mathematically yield the required cleans; don't zero clean credit for revisions outside clean lanes | `round-policy.ts:3`; `planning-loop.ts:139-149, 201-224` | S |
| 7 | **`--effort medium` + session resume on critics/revisions** (parity with authoring); per-stage soft deadline well under 20 min | `brain-review-process.ts:44-64`; `brain-review-runner.ts:45,184-255` | S |
| 8 | Commit the two post-burn frame tolerances (±1 conform) currently sitting untracked; add a timeout to the Audit B spawn (10 min) | `verify_properties.py:23,62-63`; `verify.py:16`; `audit-gate.ts:57` | S |
| 9 | **Mint cut-approval receipts retroactively** when the deterministic wall passes on a saved plan, so resume never re-authors a valid plan; checkpoint authoring drafts mid-flight so a 30-min timeout can't discard 26 min of work | `authoring-stage.ts:97-118, 227-235`; `cut-approval.ts` | S |

### P1 — incremental landing + QC flip (M/L batch; completes the operator's mandate)

| # | Change | Files | Effort |
|---|---|---|---|
| 10 | **Gate stage tags** [DEL of the monolithic bundle]: `cut-wall` \| `item-wall` \| `annotation` in `planningGateCommands`; `plan_lint --cuts-only`; `operator_intent --stage cut`; run cut-wall before Stage-1 landing, `claims_contract._check_card` per graphic, everything else post-landing | `planning-gates.ts:109-130`; `plan_lint.py`; `operator_intent_contract.py` | S–M |
| 11 | **Per-element commit loop** over the `_apply_operation` CAS envelope + element ledger sidecar; per-graphic commit at `checkpoint_graphic_ready`; one persistent working timeline; delete `mark_failed`/shadow-rebuild from the working path [DEL] | new `palmier/element_commit.py`; `native_delta.py`; `executor.py`; `checkpoint_plan.py:133`; `shadow.py` | L |
| 12 | **Split verification** [DEL]: `verify_element` (pure reuse of `_verify_one`/`verify_properties`, fails one row) + `timeline_health` (report, never mutates) | `verify.py`; `verify_properties.py` | M |
| 13 | **Demote required-lane raises to omission rows** [DEL of the never-publishable full-workflow trap]: transitions guard, first-graphic-fails-all, unmappable motion rows → omissions with reasons (the unsupported-lane downgrade pattern already exists at `checkpoint_plan.py:219-229`) | `checkpoint_plan.py:48-95, 116-129, 147-159` | S |
| 14 | **QC annotation sink + fix-forward dispatcher**: audit/lens findings → timeline markers + `findings[]`; patch only the flagged artifact via surgical re-render; `block` promotes a labeled `draft.mp4` instead of throwing; pin `artifactToken` to the project; never `rmSync` a dir holding a rendered candidate [DEL of the repair-restarts-everything loop] | `quality-loop.ts:207-299`; `auto-edit-quality-artifacts.ts:43-52,165-175` | L |
| 15 | **Resume reconciliation**: intent delta invalidates only stages that read it (visual plan/planning review), never the cut spine or journal; scope the authority digest per stage (plan reviews ≠ every UI source file) [DEL of the authority-bomb kills] | `auto-edit-hash.ts:38-53`; `launch.ts:52-70`; `auto-edit-authority-snapshot.ts:151-174` | M |
| 16 | **Unmute after human edits**: `ownership=palmier` → reconcile-and-continue on a fork of the human head (machinery exists in `native_delta.py`/`fork_candidate`); one-click "resume Sniper checkpoints"; per-element drift classification instead of workspace-wide mute | `timeline_guard.py:101-119`; `checkpoint.py:110-118`; `timeline_authority.py:257-278` | M |
| 17 | Persist clean cut-review progress per cut-identity (digest already exists) so interrupts resume at the clean count | `cut-review-loop.ts:133-138, 158-169` | S |

### P2 — templates (fixes "not using the right templates")

| # | Change | Files | Effort |
|---|---|---|---|
| 18 | **Single selection authority** [DEL of the contradiction]: add shape/style metadata to `CompCatalogEntry`, *generate* `card_form_map` from the catalog so all 46 kinds belong to a family; delete the duplicated SKILL.md prose | `comps-catalog.ts`; `producer_config.py:1192-1219`; `SKILL.md:388-397` | M |
| 19 | **Style-pack injection**: when `intent.style` is Caleb/Jaden/Angela, inject that pack's kinds into the trigger maps and `compatibleKinds` pools (doctrine is already read; the plumbing isn't) | `graphics_planner_rules.py:44-65`; `intro_semantic_contract.py:48-64` | M |
| 20 | **Brain-nominated beats replace `_CUE_SPECS`** [DEL of the one-video overfit]: quoted word-spans validated deterministically against the kept transcript (the LLM-identifier-contract pattern already in use); <4 beats degrades to "author what the transcript supports + report shortfall" instead of a hard stop | `intro_semantic_cues.py:14-37`; `intro_semantic_binding.py:194-209` | M |
| 21 | **Unbrick usage history** [DEL of a no-op spawn per round]: seed the window from any project with a rendered `final.mp4`; skip the gate entirely while zero projects qualify | `template-usage-history.ts:80-141`; `planning-gates.ts` | S |
| 22 | Put `catalogPromptLines` + the run's `graphics_proposal.json` into the plan-critic packet with an explicit better-template question; widen per-shape pools (a 2-kind evidence pool guarantees repetition) | `plan-review-packet.ts:47-70`; `intro_semantic_contract.py:147-160` | S–M |

### Sequencing
Ship P0 as one batch — it is verifiable against a short MP4 with Palmier open in an afternoon, and by itself changes the operator's day from "hours, nothing" to "twice-reviewed cut visible in Palmier at ~5–8 min, jobs that finish." P1 items 10→11→12→14 in that order (each independently verifiable per `docs/HANDOFF.md`; gate check functions untouched, so `selftest.py` coverage carries). P2 can run in parallel with P1 — it touches the planner/catalog layer only.

The one-sentence verdict for the rebuild decision: **keep the gates, the evidence producers, the translator, the caches, and the approval ledger — they all work; delete the transaction boundaries (whole-timeline shadows, monolithic gate bundles, journal clobbers, invalidate-to-zero resets) that turn any single defect into hours of discarded work.**