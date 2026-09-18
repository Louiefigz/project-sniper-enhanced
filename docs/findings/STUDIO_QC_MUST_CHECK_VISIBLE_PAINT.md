# Studio QA must check visible output, not text presence

## What the real-footage trial exposed

On September 9, 2026, a C0679 Studio draft contained 57 graphics over an
11-minute-24-second video. The initial browser probe checked every graphic,
captured a frame, and checked visibility at 114 window boundaries. It reported
`automated-visibility-and-media-checks-passed` after 42.877 seconds.

Independent review of the saved frames contradicted that result. Among the
31 body cards reviewed separately, ten statement cards displayed only their
navy background: graphics 27, 30, 33, 37, 41, 47, 50, 52, 54, and 57.
Their expected words existed in the DOM. They were not visible in the picture.

The draft's plan was `edit_plan.v2.json`, SHA-256
`d1940e78434c3747e69cb2d4916e066245efd9fa154424b300b24aa0756dd1bd`.
The failed manual review and screenshots were retained in the private trial
directory under `native-visual-qc-v2-repeat/` and `body-visual-review.v2.json`.
This finding does not certify the subsequent runtime repair or the final draft.

## Why the check gave the wrong answer

The probe walked text nodes and examined the text node's immediate parent:

```javascript
const style = getComputedStyle(textNode.parentElement);
const appearsVisible = style.visibility === "visible"
  && style.display !== "none"
  && Number(style.opacity) >= 0.05;
```

That does not prove that the text is painted. An ancestor can hide or fade the
entire subtree while a descendant still reports `opacity: 1` and a nonempty
bounding rectangle. A timed card's background can remain visible while its
content container is hidden. A top-level card-window check misses that case.

The runtime cause was then established from actual ancestor styles, clip timing,
and tween targets. The SDK removed `data-duration` from the mounted inner
composition root. The statement template read `root.dataset.duration || 4`, so
longer cards built a four-second timeline and exited at 3.85 seconds. For graphics
20 and 27, the card's own container was visible, but its `#sc-stage` ancestor had
opacity zero and was hidden. Every inspected tween target belonged to the correct
instance: duplicate-selector binding was not the cause.

A duration repair must preserve the authored/live host window in the mounted
preview, retain standalone behavior, and still respond correctly when the user
changes a card's duration. Merely substituting an unconditional constant can
repair one screenshot while breaking the next edit.

## What a useful check needs

1. Verify the correct card host is active at the intended review time.
2. Walk ancestors through that host and reject hidden display, visibility,
   content visibility, or an effectively invisible opacity chain.
3. Check actual layout bounds and clipping. A rectangle alone proves layout,
   not paint; masking, transforms, and covering elements can still hide it.
4. Inspect the browser's rendered output. Preserve card screenshots and compare
   expected text with the visible picture, especially for repeated templates.
5. Sample later instances as well as the first one. Fixed internal clip timing
   can behave differently after the first minute.
6. Retain failing results. A stronger retry is new evidence; it does not turn
   the earlier false positive into a valid pass.

Capture the visible preview rectangle after the Studio iframe's CSS scaling.
Capturing a logical 1920×1080 element without accounting for an outer transform
can save a small preview plus unrelated Studio UI and black margins instead of
a useful card image.

## Separate the claims

- **DOM content exists:** the expected words were constructed.
- **Card window is active:** the intended top-level graphic is scheduled.
- **Content is visible:** the actual text or diagram is painted and readable.
- **Playback works:** media and animation advance correctly over time.
- **Editorial approval:** a person accepts the content and timing.

None of these statements substitutes for the next. In this trial, source-derived
audio/video decoding and clock checks had already passed while some graphics
were still visually blank.

## When not to reject a frame

Do not fail an intentionally empty lead-in, a staged build before its first
content landing, or a decorative oversized watermark merely because part of
its box crosses the canvas. Sample at a time when the authored content should
be readable, and distinguish ornamental bleed from clipped instructional text.
The large `#02` background in graphic 31 was intentional; its foreground title
and subtitle were visible and readable.
