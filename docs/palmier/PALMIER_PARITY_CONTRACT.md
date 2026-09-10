# Palmier visual-mirror and editability contract

**Status:** enforced for approved exact-master publication and flat-mirror
fidelity proof. That path is release-safe. It is not evidence that editable or
hybrid Palmier delivery is qualified. The native candidate/promotion protocol
is wired and production-callable locally, but remains isolated and P5-blocked
pending representative connected short/long proof. Within that experimental
workflow, Palmier authority follows `PALMIER_CANONICAL_WORKFLOW.md`; Sniper's
master is a reviewed seed/export, not permission to overwrite a newer Palmier
revision.

## Product invariant

Two independent truths must never be collapsed into one gate:

1. **Visual/audio fidelity** — the Palmier mirror must contain the approved
   Sniper master exactly. Stale, unapproved, malformed, or unverified state
   fails closed.
2. **Native editability** — parity findings explain which concepts Palmier can
   manipulate as native controls. A flattened concept is a capability limit,
   not permission to omit it from the mirror.

| Status | Palmier editing meaning | May an approved visual master mirror? |
|---|---|---|
| `exact` | Native Palmier control exists and is readback-verifiable | Yes |
| `approximate` | A related native control exists but its behavior differs | Yes; exact pixels remain in the master clip |
| `baked` | Pixels/audio are exact but internal controls are flattened | Yes; label the limit |
| `unsupported` | No native plan-level control exists | Yes when the plan shape is known; label the limit |

`fullyEditable` remains the strict capability summary: it is true only when
every finding is `exact`. `mirrorReady` is the sync gate: it is true when the
plan is known and well-formed and an approved exact master can be mirrored.
Unknown lanes and malformed known lanes set `blocksSync: true` and fail closed.

## Delivery is the mirror — do NOT hand-build a plan in Palmier

Every Palmier plan-push delivers the rendered master via
`scripts/producer/palmier/push.py <plan> <manifest> --export <final.palmier.mp4>`
(a byte-copy of the QC-approved `final.mp4`). **Composing/placing clips or comps
directly over the Palmier MCP for a plan-push is prohibited** — it bypasses the
render pipeline, so none of the baked composition doctrine (face-recompose,
transitions, eased-zoom motion, gap-fill continuity, reframe) is applied. The
three symptoms of a hand-build are exactly: an off-centre subject beside a
graphic, a mid-timeline black frame, and no smooth transitions. The in-house
render is gapless by construction; a black frame can only come from a hand-build.

## Composition-doctrine coverage per aspect × path

The rendered master carries the full doctrine for both aspects; the flat
**mirror** copies the approved file exactly. The **native-translate** path
(editable clips) is an isolated experimental option that drops or approximates
several lanes and is P5-blocked. Never make it the default or present it as a
qualified handoff.

| Lane | Longform (16:9) mirror | Shortform (9:16) mirror | Native-translate (editable) |
|---|---|---|---|
| Recompose / vertical framing | bounded recompose windows are baked | bounded face selection is baked, with center-crop or blur-pad fallback; **not continuous subject tracking** | longform: only if a `role:"recompose"` window is folded in; **shortform: MISSING** (blocked at sync) |
| Transitions | baked | baked | **errors** (Palmier has no native primitive) |
| Eased-zoom motion | baked | baked | native scale/position keyframes ✓ (the one clean lane) |
| Gap-fill / continuity | baked (gapless by construction) | baked | native cuts tile frame-contiguous |
| Full-frame cutaway graphics | baked | baked | placed as overlay clips, base not recentered |
| Captions | **only if the plan sets `captions.burn: true`** — else a sidecar `.srt` the operator opens separately (longform default is `captions_burn: false`, sidecar/uploaded-CC preferred) | baked (karaoke burn, always) | warn-dropped (Palmier re-transcribes, loses word timing) |

**Longform captions in Palmier:** the mirror carries only the pixels of the MP4;
a longform `.srt` sidecar does not ride inside it. To make longform captions
visible in the Palmier mirror, set `captions.burn: true` on the plan's captions
config (`captions_ass.py` supports the 16:9 lower-centre geometry). The global
`captions_burn: false` longform default is intentional (selectable captions /
uploaded CC), so this is a per-plan opt-in, not a format flip.

There is no “continue with a stale/unapproved mirror” path.

## Mirror gates

1. **Current-plan gate** — the saved plan, manifest, stored operator intent,
   transcripts, reference study/frames/decision, renderer/templates, and QC
   policy are bound by the versioned authority digest.
2. **Approval gate** — managed projects require the durable quality-policy
   marker and a schema-v2 approval whose assembly proof, deterministic audit,
   sampled frames, clean planning reviews, two rendered-review lenses, and
   final bytes all verify. Missing/corrupt state never becomes legacy; only an
   explicit legacy marker can do that.
3. **Mirror-safety gate** — `plan_lint` and parity reject malformed or unknown
   plan state. Baked/approximate/known-unsupported capability findings do not
   block an exact master mirror.
4. **Palmier readback gate** — Sniper imports the approved master, creates a new
   shadow timeline with exactly one visible master clip, and verifies project,
   timeline, media reference, canvas, FPS, duration, frame count, and range.
5. **Publication gate** — `final.palmier.mp4` is an atomic byte-identical copy
   of approved `final.mp4`; metadata records the plan, authority, visual-master,
   publication, and audio hashes/proofs.
6. **Player gate** — the Palmier A/B toggle is enabled only while the saved plan
   hash, approval, readback proof, publication proof, and Sniper ownership are
   current. GUI edits disable it immediately.

## Ownership

This `sniper|palmier` field is the compatibility mirror-writer lease. Canonical
timeline authority is separately fingerprinted in
`palmier.timeline-authority.json`. A manual Palmier change advances that
authority and invalidates approval even if an older sidecar still says
`ownership: "sniper"`.

- `ownership: "sniper"` — the compatibility mirror publisher may create a
  fresh verified shadow only when the live canonical Palmier head has not
  advanced. Prior generated and human timelines are never overwritten.
- `ownership: "palmier"` — the compatibility mirror publisher is paused. This
  does not create a second product-level authority model; the live managed
  Palmier head is canonical in either case.
- Opening Palmier changes neither field. A detected manual change advances the
  canonical working-head record and invalidates stale approval automatically.
- The current UI deliberately exposes no take-control/reclaim ceremony.

There is deliberately no lossy Palmier→`edit_plan.json` synchronization. The
native candidate path reads Palmier directly, forks the current timeline, and
applies a governed delta. Its local executor/QC/promotion protocol exists, but
the editable result remains experimental until the connected P5 cohort passes.
Manual Palmier revisions block the legacy plan writer rather than being
flattened or erased.

**Ownership note (code vs UI):** the code still enforces a compatibility lease
— sync refuses to sync when `ownership == "palmier"`
(`scripts/producer/palmier/sync.py:240-247`) and
`scripts/producer/palmier/ownership.py` still ships `--handoff`/`--reclaim`.
The native candidate and guarded promotion path are now wired, but the current
UI exposes no general take-control/reclaim ceremony and connected qualification
is open. Treat the lease as an internal compatibility mechanism, not proof of a
released editable workflow.

## What arrives in Palmier

The visible verified timeline contains one clip: the approved Sniper master.
This is the only primitive that guarantees that graphics, animations, captions,
reframes, transitions, b-roll, color, dialogue finishing, music, and every
other rendered pixel/sample match the GUI preview.

Sniper also preserves component assets best-effort as non-visible Palmier
library media: original sources and transcripts, selected b-roll/music,
rendered graphics, and declared caption/title/SFX artifacts. The sidecar records
every preserved item and every unsupported reason. Presence in the library does
not imply a natively reconstructed component timeline.

## Persistent proof

`palmier.sync.json` schema v4 records:

- `ownership`, `mirrorMode: "visual-master"`, and exact master facts;
- canonical `lastPushPlanHash`, parity/capability report, and component status;
- stable project identity, `latestTimelineId`, and unclobberable lineage;
- media bindings and diagnostic lane fingerprints;
- structural readback proof, including exact visual-master hash and timing.

`final.palmier.meta.json` proves byte-identical visual/audio publication.
`.sniper-quality-policy.json`, `.sniper-qc-approved.json`, and
`final.mp4.assembled.json` prove that the source master was current and approved.

## Adding native controls

A concept may move from baked/approximate/unsupported to `exact` only when one
change supplies deterministic validation, a native Palmier translation,
stable returned ids, readback of every content-affecting property, rollback
tests, and honest UI copy. Improving native editability must never replace or
weaken the exact visual-master mirror.
