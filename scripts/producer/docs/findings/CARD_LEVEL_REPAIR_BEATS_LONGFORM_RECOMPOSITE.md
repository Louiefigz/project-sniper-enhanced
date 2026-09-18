# Card-level repair beats long-form recomposite

## Finding

A rendered graphic can remain pixel-precise and still be editable at the card
level. Keep the renderer responsible for the pixels inside the card, keep the
card as a separate Palmier clip, and persist a stable mapping from plan graphic
id to Palmier clip id. A copy/style edit then changes one rendered asset and one
timeline element; video duration is no longer part of the repair cost.

This is proved as a local executor boundary, not as a released connected
Palmier product. The hybrid editable path remains P5-blocked and must stay
isolated/experimental. The safe publishing paths are the exact audited MP4 and
its approved one-clip flat mirror.

The wrong boundary is the final H.264 file. Replacing arbitrary encoded ranges
must account for GOPs, audio timestamps, transitions, color metadata, and seam
validation. The reliable boundary is the pre-rendered overlay clip.

## Implemented contract

The Desktop-native workflow now persists:

```text
graphic id → clip id + media ref + asset hash + frame window + track index
```

`desktop_cli.py advance ... --stage repair`:

1. Runs the normal deterministic plan gates.
2. Compares the new plan with the immutable prior plan snapshot.
3. Rejects cut, motion, timing, kind, anchor, or other structural changes.
4. Renders only graphics whose pixel-producing inputs changed.
5. Emits one content-addressed import plus one `replace-overlay` work item per
   changed card.
6. Uses the Pre/Post Palmier hooks to bind returned media/clip ids and verify
   that no unrelated clip was added or removed.

Unchanged graphics are not opened or re-proved. An offline long-plan test with
76 cards and one changed card calls the graphic renderer exactly once.

## Multi-item revision sets (2026-07-16)

Card repair now sits inside a broader, still fail-closed revision-set layer:

```text
revisionSetId
  → stable element id + expected version
  → content render/import OR native move/remove/text update
  → dependency dirty windows
  → ≤24-mutation pages with per-mutation receipts
```

Independent changes are rendered concurrently-capable but land sequentially
through the candidate fingerprint CAS. A stopped batch resumes at the first
unverified mutation page; an already verified page cannot replay. Final QC is
blocked until every page is complete, and any new revision clears stale QC and
review receipts.

The offline endurance contract uses a 14-minute, 50-card plan. Three pixel
changes, one move, one removal, and one addition resolve to exactly six element
operations. A separate executor test proves one pixel change plus one addition
creates exactly two renders, two imports, and two placements, while the
move/removal remain native. Cut-track changes calculate a full dependency
closure and fail into the broader rebuild path.

## Historical Palmier specimens (not product qualification)

The retained first-60 run proved substantial transport and mutation mechanics,
but failed later product-quality review. It took **56m48s**, remained
Palmier-QC-pending, lost per-word timing for seven karaoke captions, and
accepted a wrong 3840×2160 canvas for a requested 9:16 short. It is not
connected Palmier/P5 qualification.

The later warm recovery specimen changed `g-2jajjqng` from “One person
shop” to the transcript-grounded “Doing every single thing.” The repair plan
resolved from the content cache in **0.492s**; Claude imported, replaced, and
read back the card in **40.413s**. The authority recorded exactly two mutations,
but the candidate remained unapproved and QC-pending. This followed a
destructive stale-track attempt and is not an independent cold success.

```text
old clip CD0C6BFC → new clip C7E1AD28
track 3 → track 3
frames [8,146] → [8,146]
unrelated clip drift: 0
full renders touched: 0
```

The asset was already cached, so the live run created zero new media files but
selected exactly one proved card asset. A cache miss renders that one asset; a
cache hit should be faster and must not be mistaken for a missing render.

### Presenter-hole proof

An alpha hole is not a presenter implementation by itself. The in-house
compositor crops the live base into the hole before it applies the card, but a
Desktop NLE that receives only the alpha frame exposes whatever base pixels
happen to sit below that rectangle. In the first Palmier build, the registered
right-side hole therefore showed the blue wall while the centered speaker sat
outside it.

The Desktop renderer now maps only the card's output window back through the
cut spine, crops the same source-time presenter footage around measured
`faceCx`, fills the registered hole, and imports that isolated card window as a
single proved MOV. The live correction changed only this binding:

```text
element g-sv1rp2o0
source 51.551s–58.561s → output frames [883,1051]
old clip 13625773 → new clip 40DD3C98
other tracks/timing/full renders touched: 0
```

This keeps later copy/style repairs card-local while guaranteeing that every
future active `presenterFrame` reaches Palmier with a real presenter, not an
empty alpha promise.

## Edge cases

- **Palmier auto-replaces an overlapping clip:** accept only removal of the
  bound old clip and immediately advance the ledger to the new clip.
- **Palmier retains both clips:** mark the element `cleanup-required`; permit
  removal of only the recorded old clip, then verify convergence.
- **PostToolUse hook is interrupted:** `desktop_cli.py reconcile` reconstructs
  the ledger from candidate readback. Ambiguous duplicate imports require an
  explicitly inspected `--media-ref`; the override is accepted only when its
  media facts match the reserved asset.
- **Claude supplies MCP output as a bare content array:** parse both wrapped and
  bare content arrays before extracting `mediaRef`; otherwise a successful
  import is incorrectly paused as receipt-less.
- **30fps card media lands on a 24fps timeline:** render enough tail frames to
  cover the separately rounded start/end frame span. The first live attempt
  exposed 103 requested frames backed by only 102 project-available frames.
- **A hole-comp is sent to an NLE as alpha only:** the NLE does not run
  `graphics_stage`'s live presenter fill. Build a content-addressed isolated
  presenter-card asset from the exact cut-mapped source window, then replace
  only that card clip. Never assume the full-frame base is already under the
  hole's face crop.
- **Tracks are inserted above existing graphics:** never reuse the placement-era
  numeric track index. Immediately before a repair, resolve the current index
  from the ledgered clip id and verify media/window identity. The first live
  attempt proved that stale index `0` can later mean captions while the same
  graphic has moved to index `3`.
- **Repair copy is not spoken:** the normal claims gate blocks it before render.
  The acceptance phrase “Solo creator studio” was rejected, then replaced with
  a phrase present in the card’s transcript window.
- **A Palmier mutation reports failure:** the `PostToolUseFailure` hook now reads
  the candidate. It clears the reservation only when the fingerprint is
  unchanged; possible partial mutation pauses the authority.
- **A repair fails before mutation:** plan, gate, and worklist authority are
  immutable content-addressed files, so the previous working candidate remains
  valid.
- **The operator changes Palmier concurrently:** the fingerprint CAS stops the
  next mutation. Human truth is preserved rather than overwritten.
- **Graphic timing or presenter-layout structure changes:** fail the fast path.
  Those edits can affect recompose motion and need a broader governed revision.
- **Alpha/codec/duration mismatch:** `render_entry` must return its normal
  rendered-asset proof before a repair work item exists.
- **More than 24 mutations:** page the revision, persist every verified
  `mutationId`, and do not unlock the next page until the current page is fully
  read back.
- **A later revision repeats identical MCP arguments:** operation identity is
  scoped by `revisionSetId`, so a legitimate later edit is not mistaken for a
  replay of an older revision.
- **Two logical changes target one element:** reject the revision before render;
  normalization must produce exactly one final operation per lane/id.
- **A Palmier-only text banner leaks into `edit_plan.json`:** render hashes now
  exclude the legacy field, parity still blocks it, and new native text travels
  only in the governed revision-set sidecar.

## When not to use it

Do not use local revision for cut changes, presenter recomposition, caption
timing, audio changes, global look/reframe, or transitions. Those need proven
lane-specific delta semantics or a broader editable build. The final publishing
master is still rendered and fully audited once after the operator approves the
accumulated edits.
