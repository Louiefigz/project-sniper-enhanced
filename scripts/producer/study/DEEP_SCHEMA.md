# DEEP_SCHEMA — the canonical `deep_study.json`

Produced by `study/study_deep.py <video> <out_dir> [--fps N] [--meticulous] [--semantics]
[--transcript words.json|captions.vtt] [--skip-captions]`. One JSON per
reference video;
every field below is DETERMINISTIC (pixels/audio/arithmetic) except the
opt-in `semantics` block. All times are seconds from video start; all bboxes
are frame-normalised `[x, y, w, h]` in `[0,1]`; frame indices are at the
analysis fps (`params.fps`), so `t = frame / params.fps`.

```jsonc
{
  "video": "/abs/path.mp4",
  "generatedAt": "2026-07-10T00:00:00+00:00",
  "params": { "fps": 30.0, "semantics": false, "meticulous": true },
  "source": { "width": 1080, "height": 1920, "fps": 30.0, "durationS": 58.2 },

  // P1 — study_video fingerprint (run automatically when absent)
  "fingerprint": { "path": "<out_dir>/fingerprint.json" },

  // P2 — per-frame MOTION SIGNALS (parallel arrays, frame i at i/fps)
  "signals": {
    "fps": 30.0, "frameCount": 1746,
    "analysisWidth": 320, "analysisHeight": 568,
    "d": [0.0, ...],          // mean-abs-diff vs previous frame (0-255)
    "luma": [...],            // global mean luma
    "darkFrac": [...],        // fraction of pixels < 40
    "brightFrac": [...],      // fraction of pixels > 215
    "panDx": [...],           // phaseCorrelate shift prev→cur, px at analysisWidth
    "panDy": [...],           //   (sign = CONTENT motion: negative dx = left)
    "panResp": [...],         // phase-correlation response (confidence)
    "faceX": [...],           // largest Haar face center-x, normalised (0 = none)
    "faceWidthFrac": [...],   // face width / frame width — the ZOOM PROXY
    "facePresent": [0|1, ...]
  },

  // P2 — freeze runs (the YDIF==0 analogue: d <= freeze_eps spans)
  "freezes": [ { "startFrame": 225, "frames": 15, "t": 7.5, "durationS": 0.5 } ],

  // P3 — unified event list, time-sorted, stable ids. Co-occurring moves
  // are SEPARATED (a rail sweep-in + face glide + lower-third out = three
  // events, synced); one detection tier may emit several events.
  "events": [
    {
      "id": "ev-001",
      "t": 3.0, "frame": 90,
      "type": "cut",           // cut | zoom-in | zoom-out | pan | panel-in |
                               // panel-out | graphic-in | graphic-out |
                               // freeze | flash
      "durationFrames": 1,     // 1 = instant (impulse); N = animated run
      "bbox": [0.1, 0.2, 0.5, 0.2] | null,   // changed-region bbox (per
                                             // component, never conflated)
      "coverage": 0.94 | null, // changed-pixel fraction of the frame
      "magnitude": 43.2,       // cut/flash: d or Δluma · zoom: |scale-1| ·
                               // pan: px at SOURCE width · sweep/graphic:
                               // coverage · freeze: frames
      "transition": {          // boundary classifier (null for non-boundaries)
        "class": "hard-cut" | "sweep" | "fade" | "flash" | "pop",
        "direction": "from-left" | "from-right" | "from-top" | "from-bottom" | null,
        "frames": 18           // boundary length; sweeps: VISIBLE growth
                               // frames; pops: 1-2; jump-cut steps: 1-3
      } | null,
      "easing": {              // least-squares fit over the ACTIVE span of a
                               // multi-frame motion (never over settle pads)
        "bestFit": "linear" | "power2-out" | "power3-out" | "bell",
        "r2": 0.99,
        "fits": { "linear": 0.71, "power2-out": 0.95, "power3-out": 0.99, "bell": 0.62 }
      } | null,
      "detail": {}             // type-specific: cut {punch: "in"|"out",
                               // dScalePct, preW, postW, scaleSource:
                               // "faceW"|"orb"} · zoom {scale, inliers} ·
                               // pan {dxPx, dyPx, direction} or {faceGlide,
                               // fromX, toX, direction} · freeze {durationS}
                               // · pop-scan events {source: "pop-scan"}
    }
  ],
  "unclassifiedRuns": 0,       // motion spans no classifier could name (loud)

  // P4 — text (tesseract; local, deterministic)
  "text": {
    "graphics": [              // one row per graphic-in / panel-in event
      {
        "eventId": "ev-003", "t": 1.0,
        "text": "HELLO WORLD",
        "bbox": [0.2, 0.35, 0.6, 0.3],   // the event's changed region
        "heightFracH": 0.11,             // median word height / frame height
        "textColor": "#f4f4f4", "bgColor": "#141414",
        "words": [             // per-word APPEARANCE timing (OCR frame diff)
          { "word": "HELLO", "t": 1.0, "bbox": [0.22, 0.4, 0.2, 0.1] }
        ]
      }
    ],
    "states": [                // one full-frame OCR per fingerprint state
      { "stateIndex": 0, "tStart": 0.0, "text": "...", "wordCount": 4 }
    ],
    "captions": {              // caption-system stats (full-video sampling)
      "detected": true,
      "positionBand": "bottom",          // top | middle | bottom
      "cues": 42, "cuesPerMin": 24.5, "wordsPerCueMean": 3.1,
      "karaoke": true,                   // per-word colour change on stable text
      "sampledFps": 2.0,
      "cueTexts": ["first 40 cue strings..."]
      // UI-CHROME REJECTION (LL-012): when >= caption_chrome_max_frac of
      // cues read as UI chrome / file paths (screen-share footage), the
      // readout is {"detected": false, "rejected": "ui-chrome",
      // "chromeCueFrac": 0.13, "positionBand", "cues", "cueTexts", ...}
    }
  },

  // P5 — word-locked-seam stats (planner/word_lock arithmetic, reused).
  // Words come from --transcript (JSON or YouTube-style .vtt), the cached
  // transcript.json, a SIBLING <stem>*.vtt next to the video (no API;
  // meta carries "source": "vtt-sibling"), or Deepgram (LL-013).
  "wordLock": {
    "transcriptPath": "<out_dir>/transcript.json",   // or {"skipped": reason}
    "words": 214, "toleranceS": 0.15,
    "events": [ { "eventId": "ev-001", "t": 3.0, "type": "cut", "dtS": 0.02 } ],
    "medianAbsDtS": 0.03,
    "within150msPct": 82.4
  },

  // P6 — OPT-IN agent micro-layer (--semantics); {"ran": false} otherwise
  "semantics": {
    "ran": true, "eventsConsidered": 7,
    "events": [
      { "eventId": "ev-003", "t": 1.0, "type": "graphic-in",
        "kindGuess": "stat-card", "stylingTokens": ["serif", "cream"],
        "layout": "centered card, two lines",
        "frames": ["<out_dir>/events/ev-003_in.jpg", "..."] }
      // a malformed reply records {"eventId", "error": "..."} instead
    ]
  }
}
```

## Verdict rules worth knowing

- **Detection is three-tier**: 1-frame d spikes standing `2.5x` clear of both
  neighbours are impulses; sustained elevated spans are runs; and a POP SCAN
  (deep_pops) sweeps every frame for localized instant graphics the global
  d-metric cannot see (a keyword pop reads d≈3-4 on a talking head's ≈2
  floor). Pop evidence is PER-PIXEL FREEZE restricted to extreme-luma pixels:
  rendered chrome is pixel-frozen on one side of its boundary while body sway
  keeps moving and is mid-toned. A shirt logo that merely MOVED is rejected
  by a translation match; caption-slot word swaps by the caption-band gate.
  Thresholds: `study/deep_config.py` (never inline).
- **Cuts are anchored twice**: d-spike boundaries classify them (whole-frame
  coverage, or a settled faceWidthFrac step >= `punch_facew_min`), and any
  ffmpeg-scdet cut the classifiers never touched is re-classified loudly. An
  scdet hit with no re-frame evidence is a GRAPHICS CLEAR, not a cut. Punch
  magnitude/direction (`detail.dScalePct`) comes from the Haar faceW step
  across the boundary — never ORB across a cut (91% error, acid-measured) —
  with ORB as the faceless fallback.
- **Step vs eased** (deep_easing.classify_motion): a motion whose progress
  crosses 8%→92% within <= `step_max_frames` (3) is a STEP — it classifies
  as a jump/punch CUT, never an eased zoom/pan. Easing fits need an active
  span >= `ease_min_frames` (5) and fit over the active span only.
- **Runs separate by region/signal family** (one run → several events): the
  FACE channel (jump-cut step / glide pan / face zoom from the P2 Haar
  track — a lateral slide-to-PIP is a pan by dominant axis, not a zoom), the
  CHROME channel (flat, near-extreme-luma, glyph-bearing clusters get their
  OWN arrival/departure timelines — a departing lower-third under an
  arriving rail is a separate out event when it diverges before the rail
  reaches it), then the faceless ORB/phase/sweep probes.
- **Sweeps need real growth**: monotonic, >= `sweep_min_growth_frames` (5),
  and no single frame contributing >= half the final coverage (a hard cut
  followed by drift is a step, not a sweep). `transition.frames` counts the
  VISIBLE growth (progress 2%..97%), matching hand-counted GT.
- **in vs out** for graphics/panels: extreme-luma fraction first (chrome is
  high-contrast; only decisive when the lesser side reads footage-like),
  then edge energy for text-scale regions / texture-std for panel-scale.
  Freeze-sided pops carry their own verdict (which side was frozen); frozen
  BOTH sides = an in-place swap = "in". Known failure mode: a mid-toned
  graphic busier than the footage under it — the `--semantics` layer is the
  override, never a code fallback.
- **Multi-frame global boundaries** that match neither channel nor sweep nor
  fade nor flash default to `cut` with `transition.class: "hard-cut"` and
  the run's frame count (e.g. a whip-pan boundary).
- **Freezes** are both a top-level `freezes[]` array (raw spans) and `freeze`
  events (so word-lock covers them).
- `unclassifiedRuns > 0` means motion happened that no rule could name — look
  at the signals arrays around it before trusting the study. Runs that start
  on an already-emitted cut/flash boundary are its settle, not unclassified.
