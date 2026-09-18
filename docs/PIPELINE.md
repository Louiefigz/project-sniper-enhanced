# THE PIPELINE — footage in, approved Sniper final out

**This is the canonical statement of where PROJECT SNIPER is going.** Every other
doc (skills, CLAUDE.md, READMEs) points here. If another doc contradicts this
one, this one wins — fix the other doc.

## Latest operator direction — September 9, 2026

**September 16 long export reliability:** new eligible native landscape edits
use the [shared long exporter](producer/NATIVE_LONG_EXPORT.md), including early
audio and full-context encoded seam checks, future disk allocation, frame-based
deadlines, bounded capacity waiting and separately reusable picture/media stages.
Use the shared command instead of a dated per-video export wrapper. The pinned
native runtime now uses exclusive video end times to prevent an outgoing frame
from appearing on the exact next cut. Keep current source/approval history and
the required editorial, listening, full-output and Studio reviews.

The public `studio/native_export.py` command selects the declared Short/Long
adapter. Shared owner and native SDK entry points enforce that route, current
recorded prebuild review and long seam checks. Compatible long attempts are
discovered automatically, including across output parents. The compatibility
HTTP render/assemble URLs enter the saved-plan Auto Edit review/QC controller.
See the [workflow enforcement audit](producer/WORKFLOW_ENFORCEMENT_AUDIT_2026-09-16.md)
for tested boundaries, intentional compatibility changes and remaining limits.

**September 15 review handoff correction:** Shorts, long-form and revisions
default to both a visible local encoded-video review and the matching editable
HyperFrames Studio project. Follow the shared
[handoff requirement](producer/STUDIO_REVIEW_LANE.md#required-review-handoff-local-playback-and-studio)
for opening, verification and keeping both views current after adjustments.

**September 16 visual-storytelling correction:** all future Shorts and long-form
work must plan, within its requested treatment and enabled lanes, varied real footage, smooth presenter/layout continuity, purposeful
full-screen and simultaneous footage, contextual products, complete business
beat coverage and readable brand/destination holds before assembly. Follow the
[standing directing requirements](producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md#standing-directing-requirements-september-16-2026).
The shared author/reviewer module `src/lib/producer/visual-storytelling.ts` carries
these criteria into existing automated revision gates. Native agent-led assembly
must resolve the same material issues against the current candidate before
handoff. Independent strategy and continuous-motion review remain distinct from
technical render checks; neither prompts nor CLI checks guarantee editorial quality.
New native Short builds additionally reject missing, failed or stale full-plan
prebuild reviews before direct/guided assembly. See the same prebuild document
for the recorded-review trust boundary and the separate native long-form scope.

The explicit performance goal is a completely edited 10-minute video delivered
in **120 minutes or less without sacrificing quality**. Count source review,
creative planning, editing, rendering, whole-video review and required repairs
in elapsed delivery time; deliver both the final video and editable HyperFrames
project. Time and quality must pass on the same full edit. Record actual input
and output durations and pre-existing episode work; a prepared rerender or short
sample is not a full-edit benchmark. Current C0679 development has exceeded the
time target and must remain recorded as such while the full edit is finished.

Agent-selected transition effects come from the HyperFrames catalog by default,
including an unspecific request such as "we need a transition here." Agent-selected
graphics and animation templates are catalog-first too: inspect the complete
catalog and choose the mechanism for the narration, using current native SDK
authoring. Do not silently substitute old Sniper/Nateherk/Jaden presets or a
hand-built equivalent because it is familiar. Those studies are references only.
User-supplied designs, including Claude-created presentation/animation designs,
are an explicit alternative to incorporate and animate as requested.

When the operator explicitly targets a particular reference shot/style, preserve
its inspected shot-to-catalog choices in the
[shared reference reuse map](producer/REFERENCE_SHOT_REUSE.md). Prefer existing
pieces, configuration and composition; justify bounded custom work by the target's
specific capability or quality gap. The optional native preflight/export binding
checks planning evidence for Short and Long. Ordinary inspiration does not activate
reference matching, and map readiness does not approve visual similarity or execution.

For the active C0679 work, fresh native HyperFrames composition replaces the old
visual-plan baseline and the legacy graphics-only/mandatory-port restrictions
described below. Retain source/cut evidence and verified audio; verify actual
native preview/export before claiming readiness. The older stage descriptions
document the existing Sniper route, not a requirement to force this new work
through it. See [the current native direction](producer/C0679_NATIVE_HYPERFRAMES_DIRECTION_2026-09-09.md).

Current priority: finish the actual edit and dependable native review/revision/
export workflow. Qualifying complete one-shot automation follows that delivery;
do not make autonomous orchestration a prerequisite that delays the current edit.
Both delegated and collaborative modes remain required, with shared quality goals.

The [September 9 end-to-end optimization audit](producer/C0679_END_TO_END_OPTIMIZATION_AUDIT_2026-09-09.md)
records the failed full exports, resource protection, creative/workflow
improvements, open playback qualification and a proposed 120-minute stage budget.
That budget is an acceptance target, not a measured delivery estimate.

> **The doctrine in one sentence:** ingest raw footage into **PRODUCER**, choose
> a Short style or Long lane checklist, let the controller author, independently
> review, gate, render, and QC an approved Sniper final, take manual control of
> the graphics layer in the **Studio review lane** (open → edit → sync →
> assemble), and optionally mirror that exact approved master into **Palmier
> Pro** as one flat clip (legacy export). Native editable/hybrid Palmier
> delivery is an isolated experiment, not a release-qualified substitute for
> that exact-master path.

**Primary interactive path:** give the brief to the Producer skill in Codex or
Claude Code, use the existing local stage CLIs, and review/adjust graphics in
HyperFrames Studio. The custom `/producer` page is optional compatibility UI,
not a prerequisite. Preserve the same stored intent, admission, independent
review, approval and whole-output QC on both paths. Use subscription-backed
agent tools and local processing; no paid fallback without explicit approval.

```
raw footage
    │  local skill / CLI ingest (or optional /producer tab)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PRODUCER — stored brief / optional intent card                │
│                                                              │
│  SHORT (9:16)                LONG (16:9)                     │
│  pick a STYLE:               pick your ITEMS (checklist):    │
│   · Caleb light               ☑ motion      ☑ captions       │
│   · Jaden produced            ☑ graphics    ☑ broll          │
│   · Angela involved           ☑ transitions ☑ credibility    │
│   (+ generics: Light short,   ☑ music bed   ☑ audio enhance  │
│    Produced short, Trim only, → full workflow = all checked  │
│    talking-head pace)         → or just certain items        │
└─────────────────────────────────────────────────────────────┘
    │  initial edit_plan.json
    │  → stored-intent gate + deterministic gates
    │  → fresh independent plan critic(s) + bounded revision
    ▼
┌─────────────────────────────────────────────────────────────┐
│ SNIPER — isolated render candidates                          │
│  Audit B · composition critic · editorial critic             │
│  repair → re-gate → re-render, or approve and promote        │
└─────────────────────────────────────────────────────────────┘
    │  approved final.mp4 + hash-matched QC approval
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PALMIER — safe delivery + experimental native candidate       │
│  approved exact master → one verified flat shadow clip        │
│  local native candidate/CAS protocol is production-callable   │
│  connected short/long editable qualification remains open     │
└─────────────────────────────────────────────────────────────┘
```

## Stage 1 — Ingest into PRODUCER

Footage (1..N files or a folder) enters through the local ingest CLI or optional
`/producer` tab. The conversation brief or **intent card** captures the job up
front (stored in `project.json` `intent`, prefills Auto-edit). Do not re-ask
answered choices or change scope merely to waive a gate. Vocabulary source of truth:
`scripts/producer/edit_scope.py`, mirrored by
`src/lib/producer/intent-presets.ts` (drift-tested).

### Shorts (9:16) — pick a style

For current native Shorts, follow the [request and execution workflow](producer/NATIVE_SHORTS_WORKFLOW.md).
The user can describe a treatment or ask the agent to choose from the footage
and reference library. Strategy and source-first supporting-footage scouting
precede assembly. The optional app prepares the same local brief as the CLI;
the conversational agent owns editorial decisions. Export uses the shared
native canvas, monitored runtime and long-form audio/timing utilities.
After passage selection, [prepare the selected media first](producer/NATIVE_SHORTS_WORKFLOW.md#prepare-the-selected-media-first).
Direct native Short builds now stage small source sections and preserve original
transcript/cut clocks through a verified mapping. The original recordings remain
source evidence. Native long-form has the explicit preparation path below;
stored-guided automation remains separate integration work.

For shorts extracted from long footage, use Producer's
[long-form to finished shorts workflow](producer/PRODUCER_README.md#long-form-to-finished-shorts):
compare source-bound standalone moments, trim only the selected ranges, then
apply the adopted visual-storytelling guidance. Topic segmentation is optional;
ranked selection precedes graphic production and intermediate clip exports.

Measured style grammars (each has a studied doc + a `pacing_<style>` lint
profile):

| Preset | Scope | Grammar doc |
|---|---|---|
| **Caleb light** | light | `docs/studies/CALEB_STYLE.md` — restraint pole, whisper cues |
| **Jaden produced** | produced | `docs/studies/JADEN_STYLE.md` — breath-gap punch-cuts, two-layer text |
| **Angela involved** | full | `docs/studies/ANGELA_STYLE.md` — lime takeover-deck slideware |

Plus the generic presets (**Light short · Produced short · Trim only**) and the
**talking-head pace** toggle (slow, sustained graphics — paces like longform).

### Longs (16:9) — a checklist of items

For a reference-driven long-form edit, the local agent can now
[prepare a complete 16:9 strategy packet](producer/REFERENCE_SHOT_REUSE.md#prepare-a-169-long-form-strategy-session)
with `native-short.ts prepare-longform`. It reuses the Shorts research library,
complete catalog index, selected full reference study and saved inspected matches.
Whole-video structure and shot planning remain editorial work; the packet does
not impose an educational genre or transfer Shorts pacing/geometry. Check the
packet again before reusing it in another reasoning session.

For native projects referencing longer source recordings, use
[selected-footage preparation](producer/NATIVE_LONG_SELECTED_SOURCES.md) after
passage selection and before preview/render work. It writes a separate project
and preserves the authored timeline and complete-program narration. Existing
cut-base projects and qualified long-form export packages keep their working path.

No styles here (grammars are shorts-measured). Instead the operator checks
exactly the items they want; the card derives the smallest covering scope +
`"off"` overrides (`edit_scope` semantics):

- **The lanes** (each independently on/off): `motion` · `graphics` ·
  `transitions` · `captions` · `broll` · `credibility`
- **Plus**: music bed (assemble-time, ducked; default OFF — house rule) and
  dialogue cleanup (`voice` / `voice-rnn` / `voice-strong` / `separate`)
- **Full workflow** = scope `produced`/`full` (every lane on).
  **Just certain items** = check only what you want; the base cut
  (pauses/retakes/cold-open + bounded reframe + −14 LUFS master) is ALWAYS on
  and is not a lane. Vertical reframe uses bounded face selection when
  available, then center-crop or blur-pad fallback; it is not continuous
  subject tracking.
- Scope ladder: `trim` → `light` → `produced` → `full`; per-lane directives
  (`off`/`operator`/`auto`) always beat the scope.

### Optional reference authority

The reference library accepts a local polished video or an allowlisted
YouTube/Instagram/TikTok URL. Intake starts `study_deep.py` automatically and
produces two layers of evidence:

- `deep_study.json` — raw deterministic pixel/audio/timing measurements;
- `style_profile.json` — the bounded mechanics contract plus source SHA-256.

Aspect supplies only a **Short/Long suggestion**. The operator must confirm the
mode and persist one strategy in `reference.json`: `mimic`, `extend` (a closed
Caleb/Jaden/Angela short grammar), or `new-style` (a provisional name tied to
this reference). Auto-edit accepts the reference only when the submitted intent
still matches that server-side decision. The authored plan must carry
`target.referenceId`, `target.referenceStrategy`, and the confirmed mode; the
controller reruns `reference_profile_lint.py` with the complete planning gate
bundle on every independent review round.

Identity, mode, strategy, and closed-style pacing mismatches fail. Measured
event-rate differences normally warn so creative variance remains possible; a
literal `mimic` requires every engagement lane to remain automatic and also
fails on material 5× divergence. Reference text,
filenames, OCR, and frames are untrusted media data: mechanics may transfer;
words, branding, creator identity, assets, fonts/colors, footage, UI, and music
may not. A single `new-style` reference never mutates the closed style catalog.

`mimic` is currently a planning-vocabulary label, not a verified reproduction
claim. The P6 reference-mimic qualification cohort is **0/7**. Until those
projects pass, describe this feature as **reference study/profile guidance**:
measured mechanics can guide a reference-inspired edit, but an exact style match
or complete replication is not promised.

## Stage 2 — The brain authors the plan, the gates guard it

The producer skill reads transcripts, runs the proposers, and authors the first
`edit_plan.json` — the **determinism boundary** (same plan → byte-identical
output). That first author is not the approval authority.

The detached controller owns a bounded review loop:

1. Re-run the complete transcript-aware gate bundle in parallel:
   `operator_intent_contract.py`, `plan_lint.py` (+ motion/audio/reframe/smooth),
   `hook_contract.py`, `claims_contract.py`, and optional
   `reference_profile_lint.py`.
2. `operator_intent_contract.py` compares `target.mode`, `target.scope`, resolved
   lane ownership, reference identity, music/audio finish, and unconditional
   lane coverage against the validated `project.json` intent supplied by the
   controller. The plan cannot silently downgrade the user's selection.
3. Start a fresh, read-only critic process that reviews narrative, restraint,
   timing, geometry, grounding, destination fidelity, and reference mechanics.
4. Persist the structured verdict. Material issues go to a separate writer,
   which must account for every issue and actually change the plan. Snapshot,
   re-run every deterministic gate, and obtain another fresh critique.

Trim/light require at least one independent audit round. Produced/full require
at least two; every scope caps at four. The final round must have no material
issue and every gate must pass. A block or exhausted cap prevents rendering.

## Stage 3 — Render isolated candidates and fail-closed QC

The reviewed plan renders through the in-house `assemble.py`/ffmpeg authority,
but not directly into the public `final.mp4`. Each attempt lands at
`<producer>/.sniper-qc/<token>/round-N/final.mp4` with an assembled-authority
proof and copied audit inputs.

Each candidate must pass all of:

- deterministic Audit B, including readable review-frame evidence and
  measurable graphics placements when graphics exist;
- a fresh composition critic over the extracted frames and machine report;
- a separate fresh editorial critic over the same rendered evidence.

Plan-repairable material issues invoke a separate writer, invalidate the
reviewed authority, re-run the entire planning loop and gate bundle, and render
another isolated candidate. The render/QC loop caps at three candidates.
Missing evidence or a system-level block fails closed instead of approving or
blindly retrying.

Only an all-pass candidate is promoted to `<producer>/final.mp4`. Promotion
writes `.sniper-qc-approved.json` last, binding the approved plan hash, manifest
hash, final bytes, QC round, and review artifacts. Project status and resume do
not treat an unapproved candidate or arbitrary `final.mp4` as finished.

The bounded planning/QC controller is implemented in the current tree. This
document does not claim a new live render/E2E exercise for it; the older C0679
evidence below is explicitly historical.

## Stage 3.5 — Studio review lane (manual control)

Manual control of the graphics layer now defaults to the **Studio review
lane**, upstream of any mirror: `scripts/producer/studio/studio_review.py
open <producer_dir>` turns `edit_plan.json` + the graphics-free
`base_final.mp4` into a HyperFrames Studio timeline (preview surface only —
`hyperframes render` remains the sole render use, and footage never re-encodes
in a browser); the operator or agent edits graphics there;
`studio_review.py sync <producer_dir> --apply` folds the edits back into
`edit_plan.json` (plan_lint-gated, backup written, manifest rebaselined); and
`assemble.py --auto-base` rebuilds only invalidated stages; timing must be
measured on the actual source, plan, tools and cache state. The generator
refuses to overwrite unsynced Studio edits without `--force`. Reference:
`docs/producer/STUDIO_REVIEW_LANE.md`.

## Stage 4 — Approved Palmier mirror and native-candidate boundary

Palmier is an explicit, **optional legacy** destination after Sniper approval —
for operators who want a pro NLE for footage-level polish. The release-safe path
is the approved `final.mp4` plus **Update Palmier mirror**. That mirror requires
the durable managed-quality marker and a current schema-v2 approval whose
authority digest, plan/manifest/final hashes, assembly proof, Audit B evidence,
sampled frames, planning reviews, and both rendered critics verify.

The mirror timeline contains exactly one visible clip: approved `final.mp4`.
Palmier readback proves the master media identity, canvas, FPS, duration, frame
count, timeline range, and project/timeline identity. `final.palmier.mp4` is
published from exact master bytes. This keeps every graphic, animation,
caption, transition, reframe, b-roll shot, color decision, and audio sample
identical to the GUI preview.

**Deliver only via the mirror — for both aspects.** Every Palmier plan-push goes
through `scripts/producer/palmier/push.py <plan> <manifest> --export
<final.palmier.mp4>` (byte-copy of the QC-approved master, which carries the full
render-baked doctrine — face-recompose, transitions, motion, gap-fill, reframe —
for longform *and* shortform). **Hand-placing clips/comps directly over the
Palmier MCP for a plan-push is prohibited:** it bypasses the render pipeline, so
the subject sits off-centre beside a graphic, transitions vanish, and a
mid-timeline black frame can appear (the in-house render is gapless by
construction). Per-aspect coverage and the caption rule are tabulated in
[`PALMIER_PARITY_CONTRACT.md`](palmier/PALMIER_PARITY_CONTRACT.md). If a Palmier export
did NOT come through the mirror, run the safety-net
`scripts/producer/palmier/audit_export.py <export.mp4>` — it fails closed on a
mid-video black frame / continuity defect.

Parity still classifies each plan concept as `exact`, `approximate`, `baked`, or
`unsupported`, but these are native-editability labels. Known valid concepts do
not block the exact visual master; malformed and unknown plan state does.
Original sources/transcripts, selected b-roll/music, rendered graphics, and
declared caption/title/SFX artifacts are preserved best-effort as non-visible
library media with explicit per-component status.

Opening Palmier changes no state. Once a managed timeline exists, any manual
Palmier edit advances the canonical working head at the next reconciliation
boundary and invalidates older approval. The current tree contains a
production-callable native candidate protocol that reads that head, creates a
full-copy candidate, applies a scoped delta, and guards promotion with
deterministic/rendered QC plus an unchanged-parent check. That is local mechanism
evidence only: the editable/hybrid path is isolated and P5-blocked until
representative connected short and long projects qualify it. There is no
product-level "Reclaim Sniper" path and no lossy
Palmier→`edit_plan.json` translation.

See `docs/palmier/PALMIER_PARITY_CONTRACT.md` and
`docs/palmier/PALMIER_MIRROR_HANDOFF.md` for the complete state and proof contracts.

## Status (honest — update as it lands)

| Piece | Status |
|---|---|
| Intent card (Short/Long, known/provisional reference style, lane checklist) | ✅ shipped and drift-tested |
| Initial brain + bounded plan review | ✅ trim/light require one clean review; produced/full require two clean independent reviews of the same plan; at most four total rounds |
| Deterministic planning gates | ✅ stored intent, transcript-aware plan lint, hook, claims, and selected-reference gate every round |
| Isolated render/QC | ✅ Audit B + composition/editorial critics; at most three candidate renders; no public promotion without schema-v2 approval |
| GUI re-renders | ✅ `reviewSavedPlan:true` uses the same controller; stale preview/player/filmstrip/waveform/Reveal/Palmier states fail closed |
| Background jobs | ✅ project-scoped detached workers, real stage/remaining-work status, Stop & keep checkpoint, Resume, and safe navigation to another project |
| Authority chain | ✅ durable quality-policy marker + versioned input/pipeline digest + hash-bound review/audit/frame evidence; missing/corrupt never means legacy |
| Full-screen graphic geometry | ✅ own-screen comps scale to exact delivery pixels; aspect mismatch and non-full coverage fail; 4K PIP-hole geometry scales with the card |
| Palmier visual mirror | ✅ one exact approved-master clip, structural readback, byte-identical publication, capability legend, best-effort component library preservation |
| Palmier native candidate protocol | ⚠️ wired and production-callable with local candidate/QC/promotion contracts; editable/hybrid delivery remains isolated and P5-blocked pending a representative connected short/long cohort |
| Reference-inspired guidance | ⚠️ study/profile gates exist; verified mimic remains P6 **0/7**, so no exact-match or replication claim is release-qualified |
| Live verification of this exact current tree | ⚠️ not claimed by these offline changes; running live MCP/render tests requires an intentional user-project exercise |

The older C0679/C0666 results remain historical evidence for earlier versions,
not proof of this current policy. Current verification in this change is
offline/unit/build verification only.
