# An HTTP 200 is not a working video-editor preview

## What happened

On 2026-09-06, the Elements gallery's runtime/CSS optimization passed route tests but displayed an empty statement card in the actual Sniper UI. The standalone HyperFrames Studio view worked, which initially made the asset-serving implementation look healthy.

The two surfaces use different browser security contexts. Studio serves its staged project normally. Elements uses an opaque `sandbox="allow-scripts"` iframe. Its newly externalized runtime requests encountered Sniper's local-request checks and `Cross-Origin-Resource-Policy: same-origin`. A successful direct API test did not reproduce those browser conditions. GSAP never initialized, so the card's script failed before creating its text.

## The correction

Keep the opaque sandbox and local-request boundary. Inline only the fixed, audited runtime/CSS dependencies, escaping script/style closing tags. Test referenced icon/image transport independently; JavaScript, CSS, image elements and synchronous SVG XHR do not necessarily behave identically.

Add a narrow parent/iframe health protocol bound to the current iframe window and a per-document nonce. Latch script errors that occur before the parent's handshake. A registered timeline is useful initialization evidence but must not hide another script failure, and is not proof of correct animation or readable content.

All 53 generated documents subsequently had no external runtime/CSS dependencies and all inline scripts parsed. Four route tests passed in 0.807s. Only the actual browser remount established that the statement text appeared. Visual inspection then caught a second defect: a dark catalog accent overrode the template's intentionally light accent. Unit tests had not established that readability either.

## What to measure

Record request size and latency, but qualify the actual delivery surface before calling a reduction an improvement. The large shared-CSS byte reduction was real at the route level; it was withdrawn as a realized performance benefit because that version did not function in the gallery.

Use three distinct checks: route/resource correctness, real browser runtime/playback, and visual/auditory quality of the produced media. A pass in one must not stand in for the others.

## When not to use this approach

Do not inline arbitrary user-selected local files or create a generic network relay. Do not add `allow-same-origin` merely to make a broken preview fetch succeed. Fixed dependency inlining is a correctness baseline, not automatically the best long-term bandwidth strategy. A parent-fetched, content-keyed hydration cache may improve repeated loads later, but it needs its own invalidation, security and actual-browser tests.
