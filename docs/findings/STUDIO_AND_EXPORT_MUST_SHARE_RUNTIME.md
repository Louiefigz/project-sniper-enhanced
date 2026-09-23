# Studio and export must share the qualified runtime

## What failed

The September 15 pricing Short passed native export, encoded-frame comparison
and complete audio/video decoding. Chrome Studio playback was checked, but the
operator's Codex in-app Studio view showed future captions and graphics at the
opening and played choppy sound. All media was already loaded. Waiting for a
transfer could not fix it.

The two paths used different runtime implementations:

- Native export used `studio/native_runtime.py`, the existing hash-qualified
  local adaptation of HyperFrames 0.8.31.
- `studio/managed_preview.py` launched the stock installed CLI.

The adaptation already handled same-document HTML and media elements whose
JavaScript constructor identity differs in an embedded browser. Stock timing
code skipped valid elements when an `instanceof HTMLElement` check failed. The
same class of check is used by audio scheduling. Raw media synchronization still
ran, repeatedly moving the soundtrack forward by small amounts.

## Evidence

Temporary diagnostics in the editable project captured these facts in the
affected browser, without changing the sealed project or exported MP4:

- The framework player existed, was ready and reported the correct 55.32-second
  duration. Missing player initialization was ruled out.
- Real caption/graphic `HTMLDivElement` nodes had the HTML namespace but failed
  the runtime's constructor check. Their inline visibility remained unset.
- One uninterrupted 15.5474-second playback interval produced 90 audio seeks,
  90 `waiting` events and 90 completed seeks.
- The audio setter's stack identified SDK `Gl` → `He` → `Is`. Example correction:
  54.889839 seconds to 54.943900 seconds, about 54 milliseconds.

The problem was a live playback failure. Valid audio samples, codec metadata,
duration and loudness measurements cannot establish smooth browser playback.

## Shared repair

Managed preview now resolves the existing qualified runtime and launches that
runtime's `dist/cli.js`. A live server is reused only when its verified process
identity names the exact current runtime path. Stock or older managed servers
are replaced through the existing ownership, cleanup and resource-admission
path. A corrupt runtime refuses before replacement. Explicit adoption remains
available to register an identified old server for managed cleanup.

This reuses the export compatibility implementation. It does not add clip
visibility masks, relax audio synchronization tolerances, patch the installed
package, transcode the source or render another MP4.

## When this diagnosis does not apply

Do not attribute every audio stutter to constructor identity. A missing asset,
unsupported codec, actual source edit discontinuity, decoder overload, or
insufficient timeline duration needs its own evidence. Read the runtime state,
inspect active versus inactive clips and measure uninterrupted playback events
before selecting a fix.

Browser handoff must identify the browser tested. Verify opening, middle and
ending scenes, forward/backward seeks and continuous playback through cuts.
Record listening separately from transport and encoded-signal checks. The
pricing Short's measured before/after evidence lives in its
`IN-APP-PLAYBACK-REVIEW.json`; it does not grant subjective listening approval.
