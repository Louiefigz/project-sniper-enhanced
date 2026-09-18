# Real website B-roll needs native pixels and a frame clock

September 11, 2026. Scope: local public website/GitHub scroll footage for the
agent-directed native Shorts route. This does not qualify arbitrary websites,
authenticated workflows or a standalone automatic editing service.

## What the tests revealed

Chrome 152's screencast returned 540×960 source frames for a viewport configured
as 540×960 at device scale 2. Encoding those frames to 1080×1920 did not restore
sharp text. Checking only the final MP4 dimensions would have missed the defect.
The capture tool now checks every source image's native width and height.

Full-resolution real-time acquisition was also inconsistent on the animated
Claude Code README. PNG yielded 94 frames in eight seconds; JPEG yielded 102.
Both were rejected by the motion sampling check. Capture performance should not
decide how smoothly an editorial scroll moves.

The final method moves the actual browser document to each intended scroll
position, waits for paint and captures native pixels. The 200 captured frames
are encoded on the eight-second, 25-fps output clock. The browser still supplies
the real page content, layout, logos and colors. This is timed B-roll, not a
measurement of live product execution speed. Embedded page animations can be
retimed by acquisition; do not use this method for latency/performance claims.

```js
const seconds = frame / plan.fps;
const p = Math.max(0, Math.min(1,
  (seconds - plan.holdStart) / (plan.duration - plan.holdStart - plan.holdEnd)));
const y = startY + (endY - startY) * p * p * (3 - 2 * p);
// Scroll the real page, await browser paint, then capture its native surface.
```

## Qualified results

| Actual public source | Output | Captured frames | Acquisition + encode + checks | Observed peak owned memory | Scroll |
| --- | --- | --- | --- | --- | --- |
| Claude Code feature page | 1080×1920, 8 s, 25 fps | 200 | 17.884 s | 0.566 GiB | 889 CSS px |
| anthropics/claude-code README → setup | 1080×1920, 8 s, 25 fps | 200 | 37.166 s | 0.978 GiB | 598 CSS px |

These are two measured attempts, not general timing guarantees. Resource
measurements are periodic observations. Both owner receipts verify cleanup and
unchanged pinned inputs/tools. Both files have exactly 200 encoded frames, no
audio and a successful full decode. Beginning/middle/end encoded frames were
visually inspected. The maximum scroll step was 12 CSS px for Claude and 8 for
GitHub; both include approximately 1.3 seconds of opening hold and 2 seconds of
result hold. Media outputs are about 0.56 MB and 0.74 MB respectively.

Artifacts under `artifacts/web-broll-2026-09-11/`:

- `claude-capture-04/capture.mp4`, SHA-256
  `f82b1f7af94a6525fe457fe867223cf325ab5851ea6332cb57f9492864f41c54`.
- `github-capture-05/capture.mp4`, SHA-256
  `b946f2937383db610224ce83a28f1602ae8ac8c56d40f61c3901ca2ecb1ca9d9`.
- Each folder retains `ASSET.json`, capture/supervision receipts, source frames,
  scroll evidence and encoded review frames. Earlier failed/degraded attempts
  remain available and are not the admitted final assets.
- `github-negative-01` rejects a missing target, exits unsuccessfully, verifies
  owned cleanup and emits no admitted asset.
- `integration-checks.json` records both real captures through the shared native
  writer/cold reader and a moving source window. Its primary source is a
  synthetic contract fixture; it is not a new rendered Short. The existing
  three review Shorts remain unchanged.

Verification: 18 focused JavaScript/TypeScript tests, two existing native runtime
regression tests, type-check and targeted ESLint passed. Coverage includes
identity/credential/private-host rejection, request method/host limits,
frame/hold budgets, changed receipts, incomplete supervision, source range
limits, real writer/cold reader, stored request authority and disabled B-roll.
No model or generation provider was called.

## Reuse and limits

Reuse NativeRun/NativeWorkLease for ownership, memory and cleanup. Keep public
acquisition separate from the offline render sandbox. Feed the frozen video
through the existing muted supporting-video path and retain receipt hashes.
The shared Short instructions tell the agent to consider verified public pages
when they help explain a brand/product/repository mention.

Inspect the intended section first. Avoid this method for login-protected pages,
CAPTCHAs, nested scroll panels, arbitrary click sequences, or claims about how
quickly a live product completes a task. Those need a different, explicitly
inspected recording workflow. A page that loads with broken images also needs
repair before capture: the early inspections exposed missing asset-host access,
which was corrected for the real sources before qualification.
