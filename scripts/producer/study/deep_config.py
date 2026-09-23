#!/usr/bin/env python3
"""deep_config — shared thresholds for the DEEP STUDY extractor (data catalog).

Every measurable knob the deep passes share lives here, mirroring the
producer_config convention (change a threshold here, never inline). Values are
calibrated against the same signals the repo's earlier studies proved out:
frame-diff d-metric (mean-abs-diff, 0-255), ORB similarity scale (~0.1% noise
floor on a locked camera — see zoom_detect.DEFAULT_CFG), phase correlation,
YDIF==0 freeze spans and diff-mask region growth.
"""

DEEP = {
    # ---- P2 signals -------------------------------------------------------
    "analysis_width": 320,        # gray decode width for the signals pass
    "window_width": 640,          # gray decode width for event windows (ORB)
    "dark_luma": 40,              # pixel < this = "dark" for darkFrac
    "bright_luma": 215,           # pixel > this = "bright" for brightFrac
    "freeze_eps": 0.02,           # d <= this = frozen (YDIF==0 analogue)
    "freeze_min_frames": 6,       # shortest freeze span reported
    "face_min_size_frac": 0.08,   # Haar minSize as a fraction of frame width

    # ---- P3 event detection ----------------------------------------------
    "impulse_abs_min": 3.0,       # d floor for a 1-frame change-point
    "impulse_rel": 4.0,           # ... or this x rolling-median d, whichever wins
    "run_abs_min": 1.0,           # d floor for a sustained-motion run
    "run_rel": 2.5,               # ... or this x rolling-baseline d
    "run_min_frames": 3,          # shortest classified run
    "baseline_window": 121,       # rolling-baseline window (frames, ~4s@30)
    "baseline_pct": 20,           # LOW percentile of d = the quiet baseline —
                                  # a median rises INSIDE a 20-30 frame motion
                                  # and swallows the run it should expose
    "global_frac": 0.55,          # changed-pixel coverage >= this = whole-frame
    "panel_frac": 0.22,           # changed region >= this of frame = panel
    "graphic_min_cov": 0.004,     # smallest changed region worth an event
    "diff_thresh": 28,            # |a-b| per pixel above this counts as changed
    "min_component_frac": 0.0015, # connected components smaller than this drop
    "flash_luma_min": 48.0,       # luma spike above neighbours = flash
    "flash_settle_cov": 0.25,     # pre/post coverage under this = flash, not cut
    "fade_luma_min": 22.0,        # monotonic luma ramp >= this = fade candidate
    "sweep_min_cov": 0.04,        # a sweep must end covering >= this
    "sweep_dip_tol": 0.03,        # coverage may dip this much and stay monotonic
    "sweep_settle_frac": 0.98,    # frames counted until coverage hits this x final
    "zoom_scale_min": 0.03,       # |scale-1| across a run/cut = zoom (ORB-backed)
    "zoom_min_inliers": 12,       # ORB inliers below this = scale untrusted
    "pan_min_px": 8.0,            # cumulative |phase shift| at analysis width
    "pan_scale_tol": 0.02,        # pan requires |scale-1| under this
    "edge_energy_ratio": 1.15,    # bbox edge-energy after/before >= this = "in"
    "window_pad_frames": 3,       # settled frames decoded either side of a span

    # ---- P3 cuts / punches (faceWidthFrac step across a boundary) ---------
    "cut_min_cov": 0.25,          # face-step impulse coverage floor for a cut
    "punch_facew_min": 0.10,      # |faceW step|/preW >= this = punch/jump cut
                                  # (smallest real punch in the grammar ~12%;
                                  # a graphics-clear reads ~9% via Haar drift)
    "punch_plateau_frac": 0.5,    # pre/post windows must be settled vs step
    "face_guard_frames": 1,       # frames skipped either side of the boundary
    "face_settle_frames": 6,      # settled frames sampled for step medians
    "face_present_min": 0.7,      # facePresent fraction needed to trust a span
    "face_glide_min": 0.08,       # |faceX drift| across a run = glide (pan)
    "face_zoom_min": 0.08,        # |faceW drift|/preW across a run = face zoom
    "face_axis_ratio": 1.25,      # glide wins when |dX| >= ratio * |dW|/preW
    "scdet_force_frames": 3,      # a scdet cut missing within this = synthesize

    # ---- P3 step vs eased --------------------------------------------------
    "step_max_frames": 3,         # active motion <= this = STEP, never eased
    "ease_min_frames": 5,         # easing fits only on active runs >= this
    "active_lo": 0.08,            # active span = progress crossing lo..hi
    "active_hi": 0.92,

    # ---- P3 sweep gates ----------------------------------------------------
    "sweep_min_growth_frames": 5, # monotonic growth must span >= this
    "sweep_max_step_frac": 0.5,   # one-frame cov jump >= this x final = step

    # ---- P3 pop scan (localized instant appearances, freeze-sided) --------
    "pop_min_cov": 0.004,         # smallest frozen-changed component = a pop
    "pop_max_frames": 2,          # appearance <= this = pop
    "pop_build_max_frames": 12,   # candidate chain <= this = build; else run
    "pop_freeze_thresh": 12,      # |a-b| <= this = pixel FROZEN (codec noise)
    "pop_translate_ncc": 0.75,    # patch matches pre-frame hood = moved, not new
    "pop_translate_inflate": 2.5, # neighbourhood searched for the translation
    "pop_swap_frac": 0.5,         # frozen both sides >= this ratio = SWAP (in)
    "pop_dilate_frac": 0.02,      # mask dilation (merges glyphs into one blob)
    "pop_min_px": 8,              # tight-bbox min side (analysis px) — the
                                  # translation check needs 8px patches, so
                                  # thinner slivers are unverifiable jitter
    "pop_caption_max_h": 0.045,   # caption-scale pops suppressed under this h
    "pop_caption_band": (0.45, 0.80),  # ...when bbox y-center sits in this band
    "pop_cut_guard_frames": 3,    # no pops this close to a cut/flash boundary

    # ---- P3 chrome channel (designed panels/rails/takeovers in runs) ------
    "chrome_block_px": 32,        # block size at window width for flatness
    "chrome_flat_std": 14.0,      # block std under this = flat (chrome fill)
    "chrome_min_cov": 0.04,       # flat cluster must cover >= this of frame
    "chrome_delta_min": 18.0,     # cluster mean |post-pre| >= this = changed
    "chrome_edge_min": 25.0,      # cluster must carry glyph/border edge energy
    "chrome_bright_luma": 175.0,  # chrome fills are near-extreme: cluster
    "chrome_dark_luma": 75.0,     # median >= bright or <= dark (a sweater
                                  # or wall is mid-toned and flat — not chrome)
    "chrome_match_settle": 0.9,   # match-to-end fraction counted as arrived
    "chrome_out_lead_frames": 2,  # out must diverge this before in-coverage
    "chrome_vis_lo": 0.02,        # visible-growth span: progress crossing
    "chrome_vis_hi": 0.97,        # lo..hi = the hand-countable sweep frames

    # ---- P3 event dedup ----------------------------------------------------
    "dedup_frames": 6,            # same-family events this close are candidates
    "dedup_iou": 0.35,            # ...and merged when bbox IoU >= this

    # ---- P3 in/out verdict -------------------------------------------------
    "inout_extreme_ratio": 1.3,   # extreme-pixel frac ratio that decides in/out
    "inout_extreme_min": 0.02,    # ...with at least this absolute fraction
    "inout_extreme_bgmax": 0.35,  # lesser side must read footage-like (mid-tone)
    "inout_edge_max_area": 0.15,  # bbox area under this = edge-primary verdict

    # ---- P4 text / captions -----------------------------------------------
    "ocr_conf_min": 40,           # tesseract word confidence gate (regions)
    "caption_conf_min": 60,       # stricter gate for full-band caption OCR —
                                  # busy footage OCRs low-conf junk that would
                                  # otherwise fake caption turnover
    "ocr_psm_region": 6,          # tesseract PSM for event-region crops
    "ocr_psm_band": 11,           # sparse-text PSM for caption band slices
    "ocr_upscale": 2,             # crops upscale by this before OCR — ~22px
                                  # glyphs alone on a busy bg are unreadable
                                  # at 1x (measured; boxes mapped back)
    "ocr_bbox_pad_frac": 0.25,    # event bbox padding before OCR
    "text_window_s": 3.0,         # per-event OCR window cap after graphic-in
    "max_ocr_frames": 90,         # per-event frame cap (sampled beyond)
    "caption_fps": 2.0,           # full-video caption sampling rate
    "caption_ocr_width": 960,     # captions OCR at most this wide
    "caption_merge_ratio": 0.85,  # difflib ratio to merge consecutive cue texts
    "karaoke_color_delta": 60.0,  # per-word RGB shift = karaoke highlight
    "text_color_delta": 60.0,     # pixel-vs-bg distance that makes a text pixel
    "caption_chrome_max_frac": 0.06,  # UI-CHROME GATE (LL-012): reject the
                                  # caption verdict when >= this fraction of
                                  # cues read as UI chrome / file paths.
                                  # Sniper design parameter: the synthetic
                                  # screen-share fixtures in
                                  # tests/test_study_deep.py measure 0.125 /
                                  # 0.175 and the synthetic genuine caption
                                  # lines 0.000 — a 2x margin both sides.

    # ---- P5 word lock ------------------------------------------------------
    "word_lock_tol_s": 0.15,      # mirrors MOTION["word_lock"] (150ms)

    # ---- P6 semantics harness ----------------------------------------------
    "semantics_max_events": 24,   # bounded: never more micro-calls than this
    "semantics_timeout_s": 120,   # per-event claude -p timeout
}

# UI-CHROME WORDLIST (LL-012, data catalog) — tokens that mark a "caption"
# cue as editor/app chrome or a filename, not speech: app-panel labels and
# file-extension / colorimetry tokens that a speaker practically never says
# as a whole caption. Speakable UI words ("effects" / "transitions" /
# "color" / "timeline" / "import") are deliberately ABSENT — genuine
# captions of an editing walkthrough DO say them (pinned by the synthetic
# GENUINE list in tests/test_study_deep.py). Membership is arithmetic
# (lowercased alnum token in set), never regex semantics.
UI_CHROME_TOKENS = frozenset({
    # app-chrome panel and dialog labels
    "stickers", "aspect", "ratio", "projects", "users", "movies",
    "stock", "download", "resolution", "fps", "file", "files",
    # file-extension / colorimetry tokens
    "mov", "mp4", "wav", "png", "jpg", "jpeg", "webm", "sdr", "hdr",
})
