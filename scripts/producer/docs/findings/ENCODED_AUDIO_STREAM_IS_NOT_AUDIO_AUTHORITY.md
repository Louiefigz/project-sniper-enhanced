# One encoded audio stream is not audio-route authority

## Assertion

An exported file with one audio stream does **not** prove that an editor
timeline had one audible audio route.

## The incident

Palmier QC correctly rejected exports without exactly one encoded video stream,
one encoded audio stream, and a full `ffmpeg -xerror` decode. Documentation then
described that result as “one audio authority.”

That overclaimed what the evidence measured. Two audible tracks can be mixed by
the editor into the same single encoded output stream. `ffprobe` sees the
container after that mix; it cannot reconstruct which timeline routes were
audible.

## Evidence

- `palmier/native_qc_export.py` now records `audioStreamCount`, not
  `audioAuthorityCount`.
- `palmier/desktop_audio_authority.py` measures the current timeline separately
  and binds its receipt to the candidate fingerprint.
- The two-audible-route fixture fails even though its hypothetical export would
  still contain one audio stream.
- Editable-stem mode currently blocks with
  `routing-readback-unsupported`: Palmier readback does not expose enough
  stem-role/output-bus routing to prove the route.
- Mastered-stereo mode is production-reachable in the local Desktop worklist.
  It derives a hash-bound 48 kHz stereo PCM WAV from the trusted approved
  `final.mp4`, imports and places exactly one full-length standalone audio clip
  on a clean dedicated track, and derives the routing mutation from fresh
  timeline readback.
- The route becomes authoritative only after complete before/after readback
  proves the exact placement and routing deltas, every other content-bearing
  route muted, the mastered route audible, and the separate hidden Exact Master
  still hidden/muted/locked.
- The local production contract and adversarial fixtures are not connected
  Palmier short/long qualification evidence.

## Principle

Name receipts after the layer they observe:

```text
timeline readback  → audible-route authority
encoded container → stream count
full decode        → decodability
```

None of those facts implies either of the others.

## Implementation rule

Desktop export and approval require both:

1. a fresh, fingerprint-bound `audioRouteAuthority` receipt proving the selected
   timeline route; and
2. exactly one encoded output audio stream plus a full mapped A/V decode.

If route readback is incomplete, the selected mode has no admitted writer, or
the bound media/route is stale, stop before export. Never infer a pass from
stream count, loudness, or audible playback alone.

## When not to use this split

Do not add a route-authority receipt to a renderer that owns one deterministic
audio graph directly and already proves that graph from sealed inputs. The
separate receipt is needed at an editor boundary where multiple mutable routes
can collapse into one output stream.
