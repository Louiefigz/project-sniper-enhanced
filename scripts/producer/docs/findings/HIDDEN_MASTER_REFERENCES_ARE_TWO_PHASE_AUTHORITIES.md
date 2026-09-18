# A hidden master reference is a two-phase authority

## The incident

The editable Palmier product needs the approved `final.mp4` inside the same
timeline as a comparison reference, but that reference must never contribute
picture or sound. The obvious implementation was to add the master already
hidden and muted.

Palmier's current exposed operation vocabulary does not make that atomic:

1. `add_clips` can add the exact full-window video and auto-create its linked
   video/audio track pair, but it has no hidden/muted placement fields.
2. `manage_tracks` can then set the video track to `hidden + syncLocked` and
   the audio track to `muted + syncLocked`.

Treating the first accepted call as success creates a dangerous interval: the
master is visibly and audibly stacked over the editable build until the second
call lands. Treating two accepted calls as success is still insufficient,
because an accepted editor call is not a complete timeline readback.

## The production rule

The reference is a state machine, not a clip:

```text
approved master bytes
  → exact import
  → provisional dedicated linked track pair
  → no other mutation is allowed
  → hide video + mute audio + sync-lock both
  → fresh complete readback
  → ready
```

The provisional state is explicitly `disable-required`. While it exists, the
only authorized next mutation is the exact `manage_tracks` call derived from
the just-read dynamic track indices. QC, stage completion, and every unrelated
mutation remain blocked.

The ready state proves all of the following from a complete readback:

- one video clip has the approved master SHA-256 and exact `[0, endFrame)`
  window;
- its linked audio clip identity is unchanged;
- the video and audio occupy a dedicated pair rather than shared tracks;
- the video track is hidden and sync-locked;
- the audio track is muted and sync-locked;
- the master `mediaRef` occurs exactly once;
- no unknown clip or track edit property appeared;
- project FPS still matches the bound integer timebase.

Track indices are refreshed from each later complete readback because indices
are positions, not identities. The clip ID, linked-audio ID, and mediaRef are
immutable. Pre-mutation guards reject those identities anywhere in
`clipId`, `clipIds`, split/move rows, remove rows, or `add_clips` entries, and
also reject any operation targeting either currently resolved reference track.
The full post-mutation invariant remains the second line of defense.

## Exact rate means exact rational

Rounding both sides made `30000/1001` and `30/1` look equal. They are not equal.
The approved master now retains canonical `r_frame_rate` from ffprobe, and the
reference worklist binds that rational.

Palmier's current complete timeline readback exposes only a scalar project
`fps`, not a numerator/denominator authority. Therefore this release accepts
only an exactly integral project rate and compares the master rational to
`N/1`. A `30000/1001` master in a project reporting `30` fails closed. That is
less permissive than guessing and more honest than claiming exact-rate parity
from rounded data.

## QC must reopen evidence, not trust state summaries

The same Desktop path now labels its QC authority `desktop-build` and binds the
current plan, manifest, gates, operation manifest, candidate fingerprint, and
optional revision bytes. Audit B runs the existing full-stream editable parity
contract for both `live-build` and `desktop-build`.

Approval reopens and rehashes the canonical candidate export, deterministic
audit artifact, review frames, approved master, editable-parity receipt, and
any approximation approval. It also recomputes Desktop input authority from
the current artifact bytes. A hash copied into mutable Desktop state is not
accepted as proof of a missing or changed file.

Local adversarial coverage currently includes:

- **10** exact-reference contract tests;
- **4** Desktop hook/reconcile/QC integration tests;
- **3** approval-closure tests for a missing export, mutated audit, and missing
  parity receipt;
- explicit rejection of `30000/1001` master rate versus project `30`.

These are production-path local contracts. They do **not** claim a connected
Palmier session has yet completed the two mutations, disconnected between
them, recovered, exported, and passed full short/long retained qualification.

## The principle

When safety flags live in a second API call, the interval between calls is a
first-class authority state. Make it non-promotable, reserve the next
operation, and require a complete readback before naming the result safe.

Likewise, a QC state object is an index into evidence, not the evidence itself.
Approval must reopen the current bytes and re-run every available validator.

## When not to use this protocol

- Do not use it if the editor cannot provide a complete post-mutation
  readback. Keep the exact master on a separate comparison timeline instead.
- Do not use it for a silent master; there is no audio route to prove muted.
- Do not use it for a fractional-rate Palmier project until Palmier exposes an
  exact project rational or equivalent authoritative timebase.
- If Palmier later supports atomic add-with-hidden/muted placement, replace the
  provisional interval with that atomic operation, but retain fresh readback,
  identity immutability, and approval-time evidence revalidation.
- Do not call the local contract connected qualification. That requires
  retained real-session mutation, disconnect/recovery, export, and QC evidence.
