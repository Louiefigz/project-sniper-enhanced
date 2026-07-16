# THE PIPELINE — footage in, approved Sniper final out

**This is the canonical statement of where PROJECT SNIPER is going.** Every other
doc (skills, CLAUDE.md, READMEs) points here. If another doc contradicts this
one, this one wins — fix the other doc.

> **The doctrine in one sentence:** upload raw footage into **PRODUCER**, choose
> a Short style or Long lane checklist, let the controller author, independently
> review, gate, render, and QC an approved Sniper final, then mirror that exact
> approved master into **Palmier Pro** when more manual control is wanted.

```
raw footage
    │  upload / ingest (the /producer tab)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ PRODUCER — intent card                                       │
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
│ PALMIER — canonical managed working timeline                  │
│  approved exact master may seed one verified shadow clip      │
│  manual edits advance the head; AI edits a full-copy candidate│
│  capability report labels native vs flattened controls       │
└─────────────────────────────────────────────────────────────┘
```

## Stage 1 — Upload into PRODUCER

Footage (1..N files or a folder) enters through the `/producer` tab. The
**intent card** captures the job up front (stored in `project.json` `intent`,
prefills Auto-edit). Vocabulary source of truth:
`scripts/producer/edit_scope.py`, mirrored by
`src/lib/producer/intent-presets.ts` (drift-tested).

### Shorts (9:16) — pick a style

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

No styles here (grammars are shorts-measured). Instead the operator checks
exactly the items they want; the card derives the smallest covering scope +
`"off"` overrides (`edit_scope` semantics):

- **The lanes** (each independently on/off): `motion` · `graphics` ·
  `transitions` · `captions` · `broll` · `credibility`
- **Plus**: music bed (assemble-time, ducked; default OFF — house rule) and
  dialogue cleanup (`voice` / `voice-rnn` / `voice-strong` / `separate`)
- **Full workflow** = scope `produced`/`full` (every lane on).
  **Just certain items** = check only what you want; the base cut
  (pauses/retakes/cold-open + reframe + −14 LUFS master) is ALWAYS on and is
  not a lane.
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

## Stage 4 — Palmier Pro becomes the canonical working timeline

Palmier is an explicit destination after Sniper approval. **Update Palmier
mirror** requires the durable managed-quality marker and a current schema-v2
approval whose authority digest, plan/manifest/final hashes, assembly proof,
Audit B evidence, sampled frames, planning reviews, and both rendered critics
verify.

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
boundary and invalidates older approval. A governed AI request reads that exact
head, creates a full-copy candidate, applies the scoped delta, and may promote
it only after deterministic/rendered QC and an unchanged-parent check. There is
no product-level "Reclaim Sniper" path and no lossy Palmier→`edit_plan.json`
translation.

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
| Palmier authority | ✅ opening is non-mutating; manual readback becomes the working head; stale Sniper plans cannot overwrite it; native candidate QC/promotion remains explicitly tracked in `PALMIER_CANONICAL_IMPLEMENTATION_STATE.md` |
| Live verification of this exact current tree | ⚠️ not claimed by these offline changes; running live MCP/render tests requires an intentional user-project exercise |

The older C0679/C0666 results remain historical evidence for earlier versions,
not proof of this current policy. Current verification in this change is
offline/unit/build verification only.
