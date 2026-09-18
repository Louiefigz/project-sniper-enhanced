"""PRODUCER tunable defaults — every editorial + render number in one place.

DATA FILE (O(1) lookup): the 300-line logic limit does not apply.

Nearly all numbers here are practitioner heuristics, deliberately configurable
(see docs/producer/PRODUCER_PLAN.md §3.1 "Editorial doctrine" and the research honesty
flags). The few HARD anchors — TikTok's official 3–6s hook window and 5–10
words/sec caption pacing, −14 LUFS / −1.5 dBTP delivery, the YouTube encode
spec — should not be loosened without a reason written next to the change.

Sources: session research reports (platform specs / shorts editing / long-form
editing, 2026-07-04) captured in PRODUCER_PLAN.md §Research grounding.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Canvas + safe zones (1080x1920, safe across TikTok / Reels / Shorts at once)
# ---------------------------------------------------------------------------
CANVAS = {
    "width": 1080,
    "height": 1920,
    "fps_default": 30,          # CFR; match source when it is 24/25/30/50/60
    "pix_fmt": "yuv420p",
}

# Delivery canvas per aspect. CANVAS is the 9:16 default (back-compat); 16:9
# longform delivers landscape. Any aspect-derived geometry (captions) reads this
# so a 16:9 job stops inheriting the portrait frame.
CANVAS_BY_ASPECT = {
    "9:16": {"width": 1080, "height": 1920},
    "16:9": {"width": 1920, "height": 1080},
    "1:1":  {"width": 1080, "height": 1080},
}

# Caption layout per aspect: where the caption block sits (baseline = bottom edge
# of the lowest line, px from top), its side margins, and font. 9:16 = the existing
# portrait values; 16:9 = lower-CENTER third, larger + bold, matching the measured
# pro longform caption layer (docs/studies/MEASURED_EDIT_GRAMMAR.md §5). Before this, 16:9
# inherited baseline_max_y=1340 on a 1080-tall frame → captions landed mid-chest.
CAPTION_LAYOUT_BY_ASPECT = {
    "9:16": {"baseline_max_y": 1340, "y_band": (1150, 1340),
             "margin_l": 60,  "margin_r": 150, "font_size": 56},
    "16:9": {"baseline_max_y": 980,  "y_band": (860, 980),
             "margin_l": 240, "margin_r": 240, "font_size": 60},
    "1:1":  {"baseline_max_y": 940,  "y_band": (820, 940),
             "margin_l": 120, "margin_r": 120, "font_size": 56},
}

# The Hook Contract's obligation window per mode — the region it treats as "the
# hook" and enforces required elements within. Deliberately SEPARATE from
# MODES[*].hook_window_s: shorts=3s there is TikTok's PROPOSITION window and
# longform=30s is the zoom-cadence hook, both too small for the contract. The
# contract's hook is the front-loaded PRODUCTION region — ~the first several
# seconds of a short, ~60s of a longform (matches PRODUCTION_ENVELOPE_STUDY + the
# cadence lint's hook_s=60). Change coverage here, not by reusing hook_window_s.
HOOK_CONTRACT_WINDOW_S = {"short": 8.0, "longform": 60.0}

# Universal safe box = max UI margin per edge across all three platforms.
# Bottom is the binding + most fragile number (TikTok caption/CTA stack).
SAFE_BOX = {
    "top": 250,
    "bottom": 520,              # push to 560-600 for hard guarantees
    "left": 60,
    "right": 150,
}
# Right-side icon rails are asymmetric → true visual center sits left of 540.
VISUAL_CENTER_X = 495

# placement.scale band — an explicitly-placed graphic may be resized uniformly
# about its pin (stage_placement._explicit_offset + plan_lint_motion read the
# SAME band so lint and renderer can never drift). RASTER-QUALITY BOUND: comps
# raster at their authored canvas resolution, so DOWNSCALING (<1.0) resamples
# from surplus pixels and stays crisp, while UPSCALING interpolates pixels and
# softens — 1.5 is the ceiling where that softness is still invisible at
# delivery resolution. The floor keeps a shrunken graphic legible at all.
PLACEMENT_SCALE = {"min": 0.25, "max": 1.5}

# Comp-size plan-time measurement gate (graphics/comp_measure.py — Plan-Time
# Geometry Contract v3 build item #2, kills the LL-035 class at lint).
COMP_MEASURE = {
    # Per-comp wall-clock allowance. The budget is checked BETWEEN comps
    # (an in-flight hyperframes render is never killed); cold renders measure
    # ~10s on the reference machine, cache hits cost well under 1s.
    "per_comp_budget_s": 15.0,
    # A comp whose measured content spans >= this fraction of the canvas in
    # BOTH dimensions is a designed full-bleed treatment (wash/takeover bg),
    # not an LL-035 overflow — exempt from the SAFE_BOX fit check. LL-035
    # itself (one edge-to-edge ROW: full width, small height) still fails.
    "full_bleed_frac": 0.98,
    # plan_lint_comps rule (c): a hold-to-cut comp's outEnd counts as "on a
    # cut" when it lands within this of a cutTrack seam (or the output end).
    # One frame at 30fps (0.033s) plus slack for 2-decimal plan authoring.
    "seam_tol_s": 0.05,
}

# Plan-time geometry feasibility lint (planner/geometry_feasibility.py —
# geometry contract v3 build item #3, A1 proxy-mezzanine). WARN-with-evidence
# until the A3 margin ledger exists (item #4 flips severity_for calibrated).
GEOMETRY_FEASIBILITY = {
    # Proxy mezzanine downscale factor: the REAL cut_speed segment math onto
    # a smaller canvas. 0.5 keeps a 1080p source at 540p — plenty for the Haar
    # face sampler (min face 6% of frame height) at a fraction of the encode.
    "proxy_scale": 0.5,
    # Host-side sample count for the max punch scale over a graphic window
    # (via punch_in's pure mirrors — closed forms, samples only bound eases).
    "punch_samples": 9,
}

# A3 margin-calibration ledger (planner/geometry_calibration.py — geometry
# contract v3 build item #4). The margin is an EMPIRICAL residual quantile,
# never a chosen constant: geometry_feasibility / placement_verify verdicts
# stay WARN until the residual ledger clears BOTH floors below.
GEOMETRY_CALIBRATION = {
    "min_windows": 20,   # distinct (run, window) residual samples required
    "min_runs": 5,       # distinct runs those samples must span
    "quantile": 0.95,    # per-axis |residual| quantile → the clearance margin
}

# ---------------------------------------------------------------------------
# Mode presets — the shorts vs long-form doctrine
# ---------------------------------------------------------------------------
MODES = {
    "short": {
        # Dead air: cut gaps longer than this; keep a breath of padding so
        # cuts don't sound robotic. "aggressive" preset for fast explainers.
        "silence_gap_s": 0.7,
        "silence_gap_aggressive_s": 0.3,
        "cut_pad_s": 0.15,              # 0.1-0.3s window
        "filler_removal": "all",        # um/uh/false starts all go
        # Delivery speed. Research: 1.05-1.15 safe; ≤1.25 for authority voice.
        "speech_speed": 1.1,
        "speed_cap": 1.25,
        "speed_cap_filler": 1.5,        # marked filler stretches only
        # Duration. Completion rate >> length.
        "duration_target_s": (15, 40),
        "duration_floor_s": 12,
        "duration_hard_max_s": 180,     # valid Short everywhere
        "duration_discovery_max_s": 90, # cross-platform discovery sweet spot
        # Output geometry.
        "aspect": "9:16",
        "reframe_default": "face",      # face | center | blurpad
        # Captions burned always in shorts (best-evidenced lever).
        "captions_burn": True,
        "captions_style": "karaoke",
        # Hook must land on screen + in speech inside this window (TikTok
        # official: proposition ≤3s, hook ≤6s).
        "hook_window_s": 3.0,
        # B-roll density (Phase 2): one purposeful insert per 8-12s output.
        # LONE-insert cadence — a montage/proof-beat BURST is the exception
        # (BROLL["burst"]["short"]: up to 3 cutaways in 4s;
        # docs/studies/SHORTFORM_LESSONS.md §4, §9.2).
        "broll_min_spacing_s": 8.0,
        "broll_insert_s": (1.0, 2.0),
        "broll_insert_max_s": 5.0,
        # Ending: loop, CTA lives in the caption text, not the video.
        "ending_loop": True,
        # Visual-rhythm floors the upstream pacing coordinator lints against
        # (docs/studies/PACING_RHYTHM_STUDY.md: shorts median 17/min, ~2.7s shots, hook
        # ×2.0). Floors sit deliberately BELOW the medians — a WARN, not a wall.
        # This is the FAST/produced-reel tempo (default). A talking-head "yapping"
        # short paces far slower — see ``pacing_talking_head``, picked by
        # ``target.pace``.
        "pacing": {
            "min_changes_per_min": 12.0,   # below the 17/min median (range 13-20)
            "max_still_gap_s": 8.0,        # P1: shorts change every ~3s, none past ~8s
            "hook_front_load": 1.5,        # below the measured ×2.0 hook front-load
        },
        # TALKING-HEAD tempo: a continuous single-speaker take
        # (docs/studies/SHORTFORM_LESSONS.md §8.2). Pace comes from a few
        # sustained content graphics (e.g. one milestone gauge that updates as
        # a climb of numbers is spoken), NOT a change every ~3s — long stretches
        # of presenter + captions are intentional. Pace ≠ treatment: a
        # talking-head short is still "produced" (has graphics), just slow.
        # Sniper design parameters. Selected by ``target.pace``.
        "pacing_talking_head": {
            "min_changes_per_min": 4.0,    # a few cuts/min + sustained graphics
            "max_still_gap_s": 16.0,       # long presenter stretches are on-style
            "hook_front_load": 1.3,        # still front-load, but relaxed
        },
        # PUNCH tempo (scripts/producer/docs/findings/PUNCH_STYLE.md): one
        # locked camera, hard cuts between wide and tight framings on key
        # words (§2), and two text layers carrying the emphasis (§4). The
        # pacing lint counts cuts plus graphic entrances and staged lands, so
        # the floor is met by cuts and word-locked text together; caption
        # changes are not counted, which is why the still ceiling sits above
        # the generic 8s (§2 C8). The hook is carried by a graphic from frame
        # zero rather than by a burst of cuts (§1 H2). Selected by
        # ``target.pace == "punch"``.
        "pacing_punch": {
            "min_changes_per_min": 14.0,   # design floor, ~one change per
                                           # 4.3s (PUNCH_STYLE.md §2 C1)
            "max_still_gap_s": 12.0,       # admits one held closing line
                                           # (§2 C8)
            "hook_front_load": 1.3,        # front-load lives in the graphics/
                                           # text layer (PUNCH_STYLE.md §1 H2)
            # Advisory doctrine (the brain/skill reads these; the pacing lint
            # only reads the three keys above): the text layers keep the
            # on-screen state changing between cuts, and a music bed is
            # recommended but stays the operator's opt-in (PUNCH_STYLE.md §6
            # M1-M3: standard duck, never cut to the beat — speech is the
            # timing authority).
            "state_changes_per_min": 70.0, # advisory design target (§9.1)
            "music": True,                 # bed recommended (§6 M1)
            # Style-aware punch ceiling (G17): static punch-in steps may reach
            # x1.45 so a tight framing reads as a new shot (PUNCH_STYLE.md
            # §2 C5, §10 G17). Read by plan_lint_motion when target.pace ==
            # "punch"; other paces keep MOTION["punch_in"]["zoom_max"] = 1.25.
            # Stays inside the punch_in.py primitive's hard ceiling
            # (ZOOM_MAX_HARD 1.55).
            "punch_zoom_max": 1.45,
        },
        # RESTRAINED tempo (docs/studies/RESTRAINED_STYLE.md): one steady
        # frame, a frame-one thesis card, and plain verbatim captions that
        # carry the pace. Cuts only remove flubs, retakes and dead air (§2 C2);
        # a single uncut take is on-style, so the rate floor is zero and the
        # still ceiling is long (§2 C1, C4). No zoom (§3 Z1). The pacing lint
        # does not count the caption layer, which is why these floors are
        # effectively off; the t=0 thesis card still satisfies the hook ratio.
        # Selected by ``target.pace == "restrained"``.
        "pacing_restrained": {
            "min_changes_per_min": 0.0,    # cuts are optional
                                           # (RESTRAINED_STYLE.md §2 C1)
            "max_still_gap_s": 40.0,       # longest legal hold (§2 C4)
            "hook_front_load": 1.0,        # flat cadence: the hook need not
                                           # be denser than the body (§1 H3);
                                           # the t=0 thesis card satisfies it
            # Advisory doctrine (the brain/skill reads these; the pacing lint
            # only reads the three keys above): the tempo authority is the
            # plain whisper caption layer, and there is no music bed
            # (RESTRAINED_STYLE.md §4 CAP1, §6 M1).
            "state_changes_per_min": 80.0, # advisory caption-cue target (§4 CAP1)
            "music": False,                # no bed (§6 M1)
        },
        # SLIDEWARE tempo (docs/studies/SLIDEWARE_STYLE.md): full-frame slide
        # sections alternate with the talking head; cuts happen only at
        # section boundaries (§3 AC1) and the camera never moves (§4). The
        # pacing lint counts page turns, staged lands and graphic entrances,
        # so the rate floor is met by the graphics layer, not by cuts. The
        # hook is carried by graphics, with frame zero fully dressed
        # (§2 AH1-AH3). Selected by ``target.pace == "slideware"``.
        "pacing_slideware": {
            "min_changes_per_min": 16.0,   # design floor, ~one change per
                                           # 3.75s from the graphics layer
                                           # (SLIDEWARE_STYLE.md §9)
            "max_still_gap_s": 8.0,        # the slides never rest longer
                                           # than a generic short (§9)
            "hook_front_load": 1.3,        # hook density lives in graphics,
                                           # not cuts (SLIDEWARE_STYLE.md §2 AH3)
            # Advisory doctrine (the brain/skill reads these; the pacing lint
            # only reads the three keys above): one graphic economy (slide
            # deck OR persistent ledger, §3 AC3), two caption skins (§5 ACAP2),
            # one accent (§1 B1) and real evidence only (§6 E3) — the
            # SLIDEWARE_STYLE.md §9 checklist.
            "state_changes_per_min": 65.0, # advisory design target (§9)
            "music": True,                 # bed recommended, operator
                                           # opt-in (§7 AM1)
            "punch_ins": False,            # no punch-ins (§4 AZ1) — the
                                           # punchIns track stays EMPTY
            "transitions": False,          # hard cuts only (§4 AZ2) — the
                                           # transitions track stays EMPTY
        },
        # CLIENT-REEL tempo (docs/studies/SHORTFORM_LESSONS.md §8): the THIRD
        # PACE POLE — a promotional reel about a service or result. Hook = ONE
        # continuous shot with ZERO cuts under staged text (§1.3, §1.5); body
        # momentum lives in a word-locked proof MONTAGE + a quiet verbatim
        # caption layer. Motion budget for the WHOLE ~30s: 2 zoom-outs + 1
        # punch-in + 1 overlay burst — a budget that CONFLICTS with punch
        # (zero transitions) and restrained (zero zooms), so it lives in its
        # own profile and never bleeds into desk talking-head presets (§8.1
        # scope guard). Every key is a Sniper design parameter justified in
        # §8. Selected by ``target.pace == "client-reel"``.
        "pacing_client_reel": {
            "min_changes_per_min": 8.0,    # floor below the montage-driven
                                           # change rate — a quieter body
                                           # WARNs, it is not a wall
            "max_still_gap_s": 10.0,       # the hook may hold one shot under
                                           # text; the body never rests
                                           # longer than the montage spacing
            "hook_front_load": 1.3,        # hook density lives in the staged
                                           # text stack, not cuts (§1.5)
            # Advisory doctrine (the brain/skill reads these; the pacing lint
            # only reads the three keys above): the per-30s motion/emphasis
            # BUDGET of the pole — spend it exactly, never per-cut.
            "state_changes_per_min": 90.0, # quiet caption layer churning
                                           # about every 0.7s
            "music": False,                # the bed is chosen at posting
                                           # time on the platform, not baked
                                           # into the master (§6)
            "target_duration_s": 30.0,     # a ~30s reel, usually shorter
            "hook_cuts": 0,                # hook = one continuous shot
            "energy_peaks_max": 1,         # ONE overlay burst + riser on the
                                           # hook's promise resolution, never
                                           # per-cut (§5)
            "zoom_outs_per_30s": 2,        # hook reveal + closing move
            "punch_ins_per_30s": 1,        # the proof/testimonial beat only
            "overlay_bursts_per_30s": 1,   # the single energy peak above
            "accent_words_per_30s": 3,     # accent = payload only: place,
                                           # outcome, CTA verb (§2.4)
        },
        # HOOK STACK (docs/studies/SHORTFORM_LESSONS.md §1). Advisory doctrine
        # the brain/skill reads when authoring a produced short's hook zone.
        # The two-tier TEXT LOCKUP is the cross-style INVARIANT (§1.2; the
        # style documents' hook rules agree on it); the zoom-out + riser tier
        # is a PROMO-POLE addition — only under a produced client-reel
        # treatment (§1.4, §1.6).
        "hook_stack": {
            "zone_s": 3.0,                  # hook zone 0..~2.5-3s (= the
                                            # hook_window_s proposition beat)
            "captions_in_hook": False,      # DELETE auto-caption cues under
                                            # the hook — the designed lockup
                                            # shows INSTEAD; captions start at
                                            # the first body word (~3s)
            "lockup": "two-tier",           # plain white bold line + payload
                                            # word in accent style — accent
                                            # color is a SKIN choice, the
                                            # two-tier structure the invariant
            "lockup_line_h_frac": (0.05, 0.07),  # ~5-7%H per line, chest
                                            # band, never covering the face
            # Promo-pole tier (SHORTFORM_LESSONS §1.4): zoom-OUT reveal at
            # t=0 on a layer above footage and text. HARD RULE: frame zero
            # must not be visibly over-zoomed — start at 1.34x, never above
            # 1.5x (Sniper design parameters).
            "zoom_out": {"scale_from": 1.34, "scale_from_max": 1.5,
                         "dur_frames": 60, "ease": "out-cubic"},
            # ~1.2s riser under the hook resolving EXACTLY at body start,
            # level pulled well down (SHORTFORM_LESSONS §1.6;
            # AUDIO["riser_bridge_s"]).
            "riser_s": 1.2,
        },
    },
    "longform": {
        # Long-form must breathe: trim only stalls, preserve intentional beats.
        "silence_gap_s": 1.0,
        "silence_gap_aggressive_s": 0.7,
        "cut_pad_s": 0.25,
        "filler_removal": "clarity",    # remove only clarity-hurting filler
        "speech_speed": 1.0,            # cut time out, don't accelerate
        "speed_cap": 1.0,
        "speed_cap_filler": 1.0,
        "duration_target_s": (900, 1200),   # 15-20 min sweet spot
        "duration_floor_s": 300,
        "duration_hard_max_s": 3600,
        "duration_discovery_max_s": 3600,
        "aspect": "16:9",
        "reframe_default": "none",
        "captions_burn": False,         # sidecar SRT / uploaded CC preferred
        "captions_style": "line",
        "hook_window_s": 30.0,          # first-30s retention signal
        "broll_min_spacing_s": 10.0,    # lone-insert cadence; the BODY carries
                                        # b-roll too (envelope corrected
                                        # 2026-07-07; EDITCRAFT_LESSONS §10.3)
                                        # — bursts ride BROLL["burst"]
        "broll_insert_s": (1.5, 4.0),
        "broll_insert_max_s": 8.0,
        "ending_loop": False,
        # --- Edit doctrine (EDIT_DECISION_STUDY.md, C0666 raw↔edited, 2026-07-05) --
        # The pro editor of the reference video kept 94.7% of raw words: the edit
        # was RETAKE REMOVAL + PAUSE TIGHTENING, not trimming. These encode that.
        #
        # Big cuts (failed takes) land at SENTENCE BOUNDARIES only — never
        # half-splice two takes together. Word surgery inside an otherwise-kept
        # sentence is capped tiny (dedup / false-start restarts only).
        "keep_clean_takes": True,
        "micro_cut_max_words": 3,       # in-sentence surgery: dedup/false-start ≤3 words
        # Retake policy: when a line is delivered twice, keep the LATER take
        # (study: later take won 3/3). retake_scan.py defaults to this and only
        # FLAGS (never flips) a later take that scores clearly worse.
        "retake_default": "later",
        "retake_lookback_utts": 10,     # search this many later utts for a re-delivery
        # A whole failed segment can be re-delivered after an interruption,
        # far beyond the utt window (REFERENCE_STYLE_STUDY.md R21, from the
        # owner's own footage). retake_scan additionally searches this many
        # SECONDS ahead under stricter guards (long anchors, higher ratio, joined-window
        # match) and always flags long-range finds needsOperator.
        "retake_lookback_s": 120.0,
        # Pause-tightening is the PRIMARY length lever (62% of the reference
        # reduction was silence: 18.6s head + 61.4s inter-sentence pause; only 31%
        # was words). Tighten inter-sentence gaps ≥ threshold down to a kept breath
        # BEFORE cutting any content. Emphasis pauses (after questions / short
        # theses) are protected — flag KEEP, per the car3 protected-pause precedent.
        "pause_gap_threshold_s": 1.2,   # propose a trim on any gap ≥ this
        "pause_keep_residual_s": 0.35,  # leave this much breath after tightening
        "pause_recover_floor_s": 0.5,   # count silence ≥ this toward total recoverable
        # Kept talking-head runs are LONG (study: mean 47.7s, max 174.1s between
        # audio cuts) — pacing comes from graphics/zooms OVER continuous speech,
        # never from chopping a good take. Advisory doctrine numbers for the brain.
        "mean_kept_run_s": 47.7,
        "max_kept_run_s": 174.0,
        # Hook front-load: the opening ~60s runs 2.2–2.5x the device density of the
        # body (LONGFORM_VISUAL_STUDY.md: cuts 2.2x, visual-state changes 2.3x,
        # zoom events 2.5x in the first 60s vs the cruise). Cuts/zooms/graphics are
        # stacked in the hook, then eased to a repeatable cruise.
        "hook_density_multiplier": 2.35,
        # Visual-rhythm floors the upstream pacing coordinator lints against
        # (docs/studies/PACING_RHYTHM_STUDY.md: long-form median 7 changes/min, ~4.6s
        # shots, hook ×1.7). Floors sit deliberately BELOW the medians — a WARN,
        # not a wall (P1: no talking-head shot past ~20s without a change).
        # REGION-AWARE (docs/studies/PRODUCTION_ENVELOPE_STUDY.md): production is
        # front-loaded — the hook changes every ~1.5-2s (punch-ins + stacked
        # graphics), the body breathes on 10-30s holds. So the still-gap ceiling is
        # TIGHT in the hook window and LOOSE in the body: a 30s hold is a defect in
        # the intro, correct in the body.
        "pacing": {
            "min_changes_per_min": 5.0,    # below the 7/min median (style range 5-15)
            "hook_still_gap_s": 4.0,       # hook: change every ≤4s (front-load)
            "max_still_gap_s": 20.0,       # body: no visual change gap past ~20s
            "hook_front_load": 1.5,        # below the measured ×1.7 hook front-load
            # --- INTRO ENVELOPE (docs/findings/PRO_INTRO_ENVELOPE.md, measured
            # frame-by-frame on the pro reference intro, 2026-07-10). The first
            # ~3 minutes are the DENSEST region of a pro longform: ~25 perceived
            # cuts/min, 32% of intro seconds carry a non-head visual (~50% inside
            # the first 60s), the hook opens with an on-head overlay within ~1s,
            # and receipts run as ~1s-per-shot MONTAGES, never lone inserts.
            # Floors sit deliberately below the measured pro values.
            "intro_window_s": 180.0,           # envelope region = min(dur, this)
            "intro_min_nonhead_share": 0.28,   # pro 0.32 — share of intro seconds
            "hook60_min_nonhead_share": 0.40,  # pro ~0.50 in the first 60s
            "hook_overlay_by_s": 4.0,          # first graphic/overlay opens by here
            "receipt_montage_state_s": (0.8, 1.5),  # per-receipt hold in a montage
            # STATE-CHURN INVARIANT (docs/studies/EDITCRAFT_LESSONS.md §1.2):
            # produced content churns SOME visual layer (captions, card
            # builds, lands, pills, cuts, inserts) at ~45-90 events/min while
            # hard cuts may stay far lower. Advisory band the brain reads —
            # never force CUT density to hit an energy number; pick WHICH
            # layer churns per style. Sniper design parameter.
            # SCOPE: the (45, 90) band describes PRESENTER/PRODUCED zones —
            # screen-share-heavy videos legitimately run below it (retention
            # rides cursor/PIP/demo audio, §1.1 lane split). Never flag a
            # screen-share-heavy longform against this floor; a future lint
            # must scope the band by visual-state zone.
            "state_churn_per_min": (45.0, 90.0),
        },
        # LANE SPLIT (docs/studies/EDITCRAFT_LESSONS.md §1.1): presenter
        # footage and screen-share footage are DIFFERENT GRAMMARS — the
        # presenter lane changes shot/state about 15.6 times per minute (a
        # change every ~4s), only ~5.8/min of them hard cuts, ~39% of them
        # cutaways; the screen-share lane runs ~0.6 cuts/min with retention
        # carried by cursor motion + persistent PIP + demo audio + pills.
        # Sniper design parameters (advisory; the decimals are kept because
        # consumers read them, not because they were measured). Never apply
        # one lane's pacing lint to the other. Advisory doctrine today (the
        # brain reads it; LESSON-014); roadmap = a lane-aware pacing pass
        # that switches ceilings by the plan's visual-state zones.
        "pacing_lanes": {
            "presenter": {"state_changes_per_min": 15.6,
                          "hard_cuts_per_min": 5.8,   # detector cuts only
                          "cutaway_share": 0.39},
            "screen-share": {
                "cuts_per_min": 0.6,
                # CAMERA-HOLD LEGALITY (EDITCRAFT_LESSONS §1.1): a zero-cut
                # hold up to 157s is legal ONLY while another layer churns —
                # a bare hold that long is NEVER legal on presenter footage.
                "retention_layers": ("cursor", "pip", "demo-audio", "pills"),
                "churned_hold_max_s": 157.0,
            },
        },
        # KEYWORD PILLS, NOT CAPTIONS (EDITCRAFT_LESSONS.md §5): the longform
        # emphasis layer is sparse caption pills echoing the key phrase —
        # about one every four minutes, <=3 words TYPICAL (not a hard cap —
        # a longer phrase is legal when the exact wording is the point),
        # center-screen, only where the exact words matter. Never a verbatim
        # caption stream (the SRT sidecar remains the CC track).
        "emphasis_pills": {"per_min": 0.25, "words_typical": 3},
        # PERSISTENT WALKTHROUGH PIP (EDITCRAFT_LESSONS.md §4.1 — extends
        # pending pip_takeover #39; the key keeps its historical name): during
        # an in-depth screen walkthrough, composite a circular presenter PIP
        # ~11% frame width bottom-right over the least important region
        # (never over the content being discussed); introduce it when depth
        # increases, omit during quick fly-throughs.
        # LONGFORM ONLY — the shorts PIP ban (2026-07-10) stands.
        "tutorial_pip": {"width_frac": 0.11, "corner": "bottom-right",
                         "avoid": "content-zone",
                         "introduce_on": "depth-increase"},
        # MUSIC AS SEGMENT ARCHITECTURE (EDITCRAFT_LESSONS.md §6.2): split
        # the longform by subject change, one music mood per segment, NEW
        # track per chapter with a riser+hit at the section card; a
        # music-STOP is a deliberate jolt reserved for a major pivot, a slow
        # fade-out is the segment-closing signal; drop/duck the bed under the
        # offer/CTA so the ask is heard. LONGFORM ONLY — punch shorts keep a
        # constant bed, restrained has none (their style documents). Advisory
        # doctrine (the brain plans segments; audio_mix executes the bed).
        "music_segments": {"mood_per_segment": True,
                           "new_track_per_chapter": True,
                           "stop_is_jolt": True, "fade_out_closes": True,
                           "duck_under_cta": True,
                           "bed_under_voice_db": 20.0},  # ~20 dB under
                                           # voice (§6.2) — inside the
                                           # AUDIO["music_duck_db"] band
    },
}

# ---------------------------------------------------------------------------
# Treatment levels — how much ENGAGEMENT stack rides on top of the clean cut
# ---------------------------------------------------------------------------
# The plan's ``target.treatment`` picks one (default "produced"). These flags
# gate the ENGAGING lanes ONLY. Basic captions + the per-mode format reframe
# (9:16 for shorts, none for long-form) are NOT gated here — they are part of the
# base render EVERY treatment gets. The skill branches on ``target.treatment``:
#   clean-cut = editorial ONLY (take/retake selection + silence/pause tightening
#     + outtake/false-start removal), then the mode's base reframe + basic
#     captions (karaoke burn for shorts, SRT sidecar for long-form). It SKIPS the
#     graphics proposer, the zoom/motion proposal, seam transitions, and every
#     hyperframes render — fast + cheap ("just remove the silences / pick the
#     right takes / drop the outtakes").
#   produced  = the clean cut PLUS the full engaging stack: motion v2 (eased
#     pushes + aliveness creeps + face-recompose), graphics (whiteboards /
#     kinetic / receipts per graphics_style), seam transitions, kinetic
#     burns/captions. The default when the operator wants it engaging.
# A MIDDLE ground (clean cut + subtle aliveness motion, no graphics) is authored
# as motion=True with the graphics/transitions/kinetic tracks left empty — not a
# named level. NO render-code branch reads these flags: render.py already skips
# empty tracks, so clean-cut is simply a plan whose engaging tracks are empty.
# This catalog is the single source of truth the skill + docs cite.
TREATMENTS = {
    "clean-cut": {"graphics": False, "motion": False,
                  "transitions": False, "kinetic": False},
    "produced":  {"graphics": True,  "motion": True,
                  "transitions": True,  "kinetic": True},
}
TREATMENT_DEFAULT = "produced"

# ---------------------------------------------------------------------------
# B-roll lane doctrine (docs/studies/EDITCRAFT_LESSONS.md §2 +
# docs/studies/SHORTFORM_LESSONS.md §4). DATA CATALOG — exempt from the logic
# line limit.
#
# The consolidated b-roll knobs: the planner lanes
# (planner/graphics_planner_receipts.py + _illustration.py) read their hold/
# gap constants from here (same values they shipped with — relocated, not
# retuned); the trigger/hold/burst/credit/polish bands are Sniper design
# parameters whose rationale lives in EDITCRAFT_LESSONS §2.1-§2.9 (long-form)
# and SHORTFORM_LESSONS §4 (Shorts). The per-mode footage ceilings
# (MODES[*]["broll_insert_s"/"broll_insert_max_s"]) are UNCHANGED — these
# bands are the per-KIND doctrine the brain picks holds from.
# ---------------------------------------------------------------------------
BROLL = {
    # -- planner-lane constants (read by the lanes; values unchanged) -------
    "receipt_hold_s": 2.5,          # R17: receipts run 1-4s
    "receipt_dedup_s": 30.0,        # same artifact re-named inside this → 1 row
    "concept_hold_s": 2.5,          # R24: concept stock runs 1.5-3.5s
    "concept_every_s": 60.0,        # tier-below-receipts cap: 1 per 60s
    "illustration_hold_s": 2.5,     # matches the receipts / concept-stock hold
    "illustration_min_gap_s": 30.0, # at most one slot per 30s of body
    # -- TRIGGER→INSERT LATENCY (EDITCRAFT_LESSONS §2.1): land every
    #    b-roll/graphic within this window of its trigger — before the
    #    phrase the image is a riddle, much later the viewer has moved on.
    #    Timing citations are read from word timings, never recalled
    #    (LL-013, LESSON-027). The ANCHOR is the REFERENCE-PHRASE
    #    START (the first word of the naming phrase), so an insert may lead
    #    the phrase's head noun by up to ~1.5s while trailing the trigger.
    #    The receipts lane lands outStart ON the word (latency 0 — inside
    #    the band).
    "trigger_latency_s": (0.0, 1.5),
    # -- HOLD BANDS by insert kind (EDITCRAFT_LESSONS.md §2.4 — recognise
    #    vs read time per kind; "referenced-creator" = footage of a person
    #    the speaker names, the key keeps its historical name).
    #    The brain picks the band by kind; card kinds also respect
    #    MOTION["hold_max_s"] — see EDITCRAFT_LESSONS.md §10.4 for the
    #    12s-list-card vs 11s-ceiling adjudication (ceiling stands).
    "hold_bands_s": {
        "referenced-creator": (1.5, 2.5),
        "literal-object": (2.0, 4.0),
        "montage-burst": (0.6, 0.7),
        "comparison-card": (9.0, 10.5),   # long enough to see/hear it TWICE
        "list-card": (8.0, 12.0),
        "step-card": (2.0, 3.0),
        "diagram-card": (2.5, 8.5),
    },
    # -- LITERAL-FIRST MATCHING (EDITCRAFT_LESSONS §2.2; LESSON-012): named
    #    person/tool/product/site → show THAT thing. Conceptual b-roll only
    #    for emotional beats (regret/boredom/effort), staged as graded
    #    footage of the speaker's own world.
    "literal_first": True,
    "conceptual_only_for": ("emotional",),
    # -- B-ROLL PRIORITY LADDER (EDITCRAFT_LESSONS §2.3): choose by
    #    explanatory density — Sniper motion graphics first, a purpose-shot
    #    insert of the real thing next, stock last. Demonstrating the
    #    explained thing on a real on-screen artifact outranks any metaphor
    #    illustration.
    "priority": ("motion-graphics", "purpose-shot", "stock"),
    # -- VO CONTINUITY LAW (EDITCRAFT_LESSONS §2.5; LESSON-013): A-roll
    #    speech never stops under an insert; all b-roll is VIDEO-ONLY,
    #    embedded clip audio muted (broll_insert already composites
    #    video-only). Demo/native audio only when the demo IS the point.
    "vo_continuity": True,
    "demo_audio_exception": "playthrough",
    # -- CREDIT LABEL LAW (EDITCRAFT_LESSONS §2.6): footage the operator did
    #    not shoot (and has the right to use) carries a lower-left credit
    #    label for the insert's FULL duration. Chip comp + brollTrack
    #    `credit` field = roadmap; LESSON-013 binds the brain now.
    "credit_label": {"corner": "lower-left", "template": "CREDIT: {name}",
                     "full_duration": True},
    # -- INSERT POLISH LAW (EDITCRAFT_LESSONS §2.8): every insert gets the
    #    A-roll LUT/grade + stabilization when handheld, and reuses the one
    #    motion vocabulary — indistinguishable in polish from A-cam.
    "insert_polish": {"grade_matches_aroll": True,
                      "stabilize_handheld": True},
    # -- STILLS vs CARDS SPLIT (EDITCRAFT_LESSONS §7.3; LESSON-017):
    #    photos/screenshots get slow scale/position drift in this band
    #    (%/s) or an image-focus
    #    operator (MOTION["image_focus_ops"]); DESIGNED cards stay
    #    pixel-frozen — aliveness comes from build cadence, never drift.
    "still_drift_pct_per_s": (0.5, 1.0),
    # -- BURSTS ATTACH TO MONTAGE BEATS, NOT POSITIONS (EDITCRAFT_LESSONS
    #    §2.9; SHORTFORM_LESSONS §4). Example/proof/offer beats carry the
    #    cut bursts; each offer-montage shot gets a benefit label. The
    #    MODES[*]["broll_min_spacing_s"] cadence stays the rule for LONE
    #    inserts — a burst is the beat-attached exception (SHORTFORM_LESSONS
    #    §9.2; the intro envelope's receipt_montage_state_s (0.8-1.5) is a
    #    DIFFERENT device and unchanged — EDITCRAFT_LESSONS §10.2).
    #    BURST MAGNITUDES ARE VISUAL-STATE/SHOT-CHANGE COUNTS, NOT DETECTOR
    #    HARD CUTS: the detector-cut ceilings below are a separate, lower
    #    bound. Any future burst lint must count STATE EVENTS (cuts +
    #    graphics + b-roll + panel churn), never detector cuts alone. All
    #    burst numbers are Sniper design parameters (EDITCRAFT_LESSONS §2.9).
    "burst": {
        "short": {"max_inserts": 3, "window_s": 4.0, "hold_s": (0.6, 1.3)},
        "longform": {"intro_states_per_10s": 16,   # intro montage ceiling
                     "pitch_states_per_30s": 42,   # offer/CTA montage ceiling
                     "detector_cut_peaks": {"per_10s": 11, "per_30s": 19},
                     "hold_s": (0.6, 0.7)},
    },
}

# ---------------------------------------------------------------------------
# Hook cards (operator brand, 2026-07-04): white container, black text.
# ---------------------------------------------------------------------------
HOOK_CARD = {
    "max_lines": 2,
    "max_words": 8,                 # hard lint rule (reads in ~1-1.6s @5-10wps)
    "max_chars_per_line": 26,       # 72px+ bold fits the 870px-wide safe box
    "hold_s": 3.0,                  # present ON frame 1; 2.5-3.0s convention
    "hold_min_s": 1.0,
    "hold_max_s": 6.0,
    "from_frame_one": True,         # frame 1 doubles as cover + loop start
    # Placement: upper third of the safe box, centered on VISUAL_CENTER_X.
    "y_range": (250, 560),
    "style": {
        "container": "white",       # rounded white card
        "container_alpha": 0.96,
        "corner_radius": 28,
        "text_color": "black",
        "font": "Inter",            # bold sans; operator may override
        "font_size_range": (72, 120),
        "padding": 36,
    },
}

# ---------------------------------------------------------------------------
# Captions (burned; derived from kept words — never brain-authored)
# ---------------------------------------------------------------------------
CAPTIONS = {
    "font": "Inter",
    "font_size": 56,                # 54-72px comfortable band
    "font_size_range": (48, 72),    # 48 = readability floor
    "max_lines": 2,
    # Chars must fit the 870px safe width at font_size: bold sans avg advance
    # ~0.55em → 56px × 0.55 × 28 ≈ 862px ≤ 870. (E2E 2026-07-04 caught 42 @
    # 64px overflowing the canvas — keep this pair consistent if either moves.)
    "max_chars_per_line": 28,
    "words_per_sec_max": 10,        # TikTok official pacing 5-10 wps
    "block_s": (1.2, 2.5),          # per-block on-screen persistence
    "block_min_s": 1.0,
    "block_max_s": 6.0,
    "gap_split_s": 0.8,             # phrase break: a silence longer starts a new block
    "hang_s": 0.25,                 # hold after the last word, clamped to next block
    # Lower band inside the safe box; baseline never below y=1340.
    "baseline_max_y": 1340,
    "y_band": (1150, 1340),
    "style": {
        "fill": "white",
        "outline": "black",
        "outline_px": 5,
        "karaoke_highlight": "#FFD400",  # active-word color in karaoke mode
    },
    # Minimal word-at-a-time style (docs/studies/REFERENCE_STYLE_STUDY.md
    # R1/R2). ONE word (or a <=3-word phrase
    # when adjacent words nearly touch) per Dialogue event, chest-anchored, soft
    # drop shadow, no heavy outline box; emphasis words render gold in a
    # serif-italic accent face. Additive sub-dict — karaoke/line ignore it.
    "MINIMAL": {
        "font": "Inter",
        "font_size": 80,                # R1: ~4-5% of frame height (80px @1080w)
        "font_size_range": (64, 96),
        # Phrase grouping: fold adjacent words into one event only while the gap
        # between them stays under phrase_gap_s (near-continuous speech), capped
        # at phrase_max_words. Emphasis words are always solo (own accent style).
        "phrase_gap_s": 0.12,           # <120ms between words -> same event
        "phrase_max_words": 3,
        # Timing: each event runs word-start -> next word-start; a word never
        # lingers more than hang_s past when it stopped being spoken (caps
        # dead-air at phrase ends), and shows >= min_hold_s (bounded by the next
        # onset — rapid speech can't be held longer without stacking two words).
        "min_hold_s": 0.18,
        "hang_s": 0.4,                  # <=0.4s hang at phrase ends (R1)
        # Chest band: the event's vertical CENTER sits at the middle of this
        # y-range (px on the 1920 canvas) — neck/chest, under the chin (R1).
        # Overridden per-plan by faceBBoxNorm (face-relative) when the plan
        # carries it (render.py wiring); the C12 bandYOffsetPx up-shift also
        # carries here via the shifted baseline_max_y.
        "chest_band_y": (1050, 1150),
        # Face-relative anchor: center = (bbox_bottom + face_gap_frac) of frame
        # height, clamped inside the safe box (8% of frame height below the chin).
        "face_gap_frac": 0.08,
        # Type treatment: thin outline + soft drop shadow — NOT a heavy box (R1).
        "outline_px": 2,
        "shadow_px": 2,
        "fill": "white",
        # Two-tone accent (R2): emphasis words render gold in a serif-italic
        # face. Georgia Italic is a system serif (see templates/motion/tokens.css
        # --font-serif-accent note); libass resolves it via fontconfig on macOS.
        "accent": "#FFD400",
        "accent_font": "Georgia",
    },
    # WHISPER — the Punch base caption layer (G2; scripts/producer/docs/
    # findings/PUNCH_STYLE.md §4 CAP1-CAP3, §9.2). Small white sentence-case
    # sans cues of 1-3 words, hard replace-per-cue (no fade, no karaoke
    # sweep — CAP1), soft shadow with NO box and NO outline stroke, centred
    # in the y0.60-0.64 band below the face. Emphasis is inline: listed
    # words take the accent from the cue's FIRST frame (CAP3 — never swept
    # in); keyword promotions live in the lockup layer (punch-shout-lockup
    # comp, §5.4 E1), not here. Also the plain caption layer of the
    # Restrained style, with no emphasis words (RESTRAINED_STYLE.md §4
    # CAP2). Rendered by captions_whisper.py.
    "WHISPER": {
        "font": "Inter",
        "font_size": 42,                # 2.2%H of 1920 (PUNCH_STYLE.md §9.2)
        "font_size_range": (40, 44),    # design band (§9.2)
        # Cue grouping: verbatim 1-3 word chunks; a gap >= phrase_gap_s or a
        # sentence end starts a new cue (CAP2).
        "phrase_gap_s": 0.35,
        "phrase_max_words": 3,
        "min_hold_s": 0.25,             # CAP2 replace-cadence floor
        "hang_s": 0.35,                 # never linger through dead air
        # Cue center band as a fraction of frame height (§5.2 placement
        # grid: headroom lockups above the face, captions below it).
        "band_y_frac": (0.60, 0.64),
        "center_x": 540,                # horizontal centre of 1080 (§5.2) —
                                        # NOT the icon-rail-corrected 495
        "outline_px": 0,                # NO stroke, NO box (CAP2 treatment)
        "shadow_px": 2,                 # soft shadow only
        "fill": "white",
        # Inline emphasis accent (CAP3, §5.1). The value is a design-system
        # choice; the style specification fixes only its role.
        "accent": "#F2D24B",
        "sentence_case": True,          # white sentence-case (CAP2)
    },
}

# ---------------------------------------------------------------------------
# Encode (final masters) — YouTube row is the officially-published anchor
# ---------------------------------------------------------------------------
ENCODE = {
    "vcodec": "libx264",
    "profile": "high",
    "pix_fmt": "yuv420p",
    "gop_closed": True,
    "bframes": 2,
    "coder": "cabac",
    "movflags": "+faststart",
    "bitrate_by_fps": {30: "12M", 60: "18M"},   # above YT minimums 8/12M
    "acodec": "aac",
    "audio_bitrate": "256k",
    "audio_rate": 48000,
    "audio_channels": 2,
    "mezzanine_crf": 12,            # intermediate stages: near-lossless x264
    "mezzanine_preset": "fast",
    # Cut-stage PARTS only (cut_speed.encode_segment / concat_parts). No
    # B-frames, so the concat can rebuild every copied packet's timestamp from
    # its index (packet order == presentation order); float PCM audio, so the
    # join carries no per-part AAC priming and the mezzanine's AAC is encoded
    # exactly once, at the concat. Measured 2026-09-06 (82-part 311.7s NTSC
    # long-form): the concat demuxer offsets each file by its MILLISECOND
    # container duration, so stream-copied NTSC parts (never a whole ms)
    # accumulated ±1-tick seam gaps → avg_frame_rate 280380000/9354877 ≠
    # 30000/1001, failing the exact CFR profile the cut-preview/opening
    # authorities require. Other mezzanine stages keep the encoder defaults.
    "cut_part_bframes": 0,
    "cut_part_acodec": "pcm_f32le",
    # Graphics COMPOSITE pass only (graphics_stage._composite_pass): veryfast
    # measured 16.9s→9.4s on the 108s e2e composite with CRF 12 still governing
    # quality (output was even smaller). VideoToolbox was explicitly rejected —
    # slower on this box AND loses CRF rate control. Other mezzanine stages
    # (cut/punch/transitions) keep mezzanine_preset.
    "composite_preset": "veryfast",
    "max_file_mb": 287,             # TikTok in-app cap = tightest
}

# Preview proxy (preview_proxy.py) — written next to final.mp4 after a
# successful assemble for instant editor scrubbing. Short side 480 (even dims),
# dense keyframes (-g 24) so a scrub bar can seek anywhere cheaply.
PROXY = {
    "short_side": 480,
    "crf": 28,
    "preset": "veryfast",
    "gop": 24,                      # keyframe every 24 frames = scrub-dense
    "audio_bitrate": "96k",
}

# Draft mode (draft_render.py) — pre-review-wall watchable candidate. The
# DRAFT watermark must be UNMISTAKABLE on every frame (big translucent center
# mark + solid corner badge); the burn is one fast x264 pass with the mastered
# audio stream-copied. Geometry is height-relative so shorts and longform get
# proportionate marks. A draft is never a deliverable — see draft_render.py.
DRAFT = {
    "center_frac": 0.16,            # center "DRAFT" glyph height / frame height
    "center_alpha": 0.30,           # translucent: watchable but unmissable
    "corner_frac": 0.036,           # corner badge text height / frame height
    "corner_margin_frac": 0.018,    # badge inset from the top-right corner
    "corner_box_alpha": 0.65,
    "crf": 20,                      # watchability, not delivery, quality
    "preset": "veryfast",           # speed is the point of a draft
    "fontfile": "Inter-Bold.ttf",   # resolved against repo assets/fonts/
}

# ---------------------------------------------------------------------------
# Audio mastering
# ---------------------------------------------------------------------------
# Byte-changing mastering policy, shared without importing the DSP runtime.
MASTERING_POLICY_VERSION = 3  # v3 compensates/flushes static limiter lookahead
AUDIO_MIX_POLICY_VERSION = 2  # v2 exact bed trim/duck clock, including the final partial block

AUDIO = {
    "lufs_target": -14.0,           # satisfies YT normalization; safe IG/FB
    "true_peak_dbtp": -1.5,         # DELIVERY ceiling (audit pass line)
    # loudnorm's linear-mode limiter systematically overshoots its TP param by
    # ~0.1-0.2 dB (edge C13: -1.5 param measured -1.3/-1.4). Target lower so
    # masters land clean under the -1.5 delivery ceiling.
    "loudnorm_tp_param": -2.0,
    "lra": 11.0,
    "lufs_tolerance": 1.0,          # audit: measured LUFS within ±1
    "tiktok_loud_lufs": -11.0,      # optional TikTok-only loud master
    # Music bed (Phase 2): duck under dialogue while speaking; rise in gaps.
    # Long-form music segments sit ~20 dB under the voice, inside this band
    # (docs/studies/EDITCRAFT_LESSONS.md §6.2).
    "music_duck_db": (18.0, 20.0),
    "music_gap_db": (10.0, 12.0),
    # Word-boundary cut joins: short equal-power crossfade kills clicks.
    "join_crossfade_ms": 15,
    # J-CUT LEADS (docs/studies/EDITCRAFT_LESSONS.md §6.3, continuity
    # mechanism CM-2): the DEFAULT seam is late-in-pause (picture shortly
    # before the incoming word onset — that lives in the cut boundaries the
    # edit brain picks, not here). About 1-in-5 seams may carry a TRUE
    # J-LEAD: incoming audio onset BEFORE picture, preferred band 65-95ms
    # (near the ITU-R BT.1359 audio-before-video acceptability limit, so a
    # lead reads as momentum, not a sync error). Sniper design parameters.
    # ``cutTrack[i].audioLeadMs`` = the incoming segment's audio PRE-ROLL
    # (source audio from before its in-point) starts this many ms before the
    # picture cut — baked into the OUTGOING part's tail by cut_speed, so
    # every part keeps audio == video length and A/V sync is untouched.
    # Never exceed ~300ms (beyond it the lead is heard as two sentences
    # overlapping — the hard edge).
    "jcut": {
        "lead_default_ms": 80,          # inside the preferred 65-95ms band
        "lead_band_ms": (65, 95),       # preferred J-lead band (lint WARNs
                                        # outside it; the hard max ERRORs)
        "lead_max_ms": 300,
        "prev_min_residual_s": 0.1,     # the outgoing part must keep at
                                        # least this much of its own audio
    },
    # SFX class vocabulary (docs/studies/EDITCRAFT_LESSONS.md §6.1).
    # whoosh/click/pop = the MECHANICAL layer
    # (whoosh-on-motion, highlight-sound-on-highlight — audio/sfx_library
    # ships these); riser/hit/drone = the EMOTIONAL layer mapped to beat
    # types at plan time: riser = pre-payoff tension (HONESTY GATE: only
    # when a real payoff follows; riser→hit chain legal), hit = payoff/
    # emphasis (every new section = riser+hit), drone = dark/suspense mood.
    # riser/hit/drone synthesis into sfx_library is the named roadmap;
    # LESSON-018 binds the brain's mapping.
    "sfx_classes": ("whoosh", "click", "pop", "riser", "hit", "drone"),
    # Trim every SFX to the animation's ENTRANCE duration only, and give it
    # a fade-in handle to soften the attack (EDITCRAFT_LESSONS §6.1).
    "sfx_trim_to_entrance": True,
    "sfx_fade_in_handle": True,
    # RISER-BRIDGE (docs/studies/SHORTFORM_LESSONS.md §1.6): ~1.2s riser
    # under a short's hook, ENDING exactly where the body starts, level
    # pulled well down; subject to the riser honesty gate. Optional
    # produced-treatment slot — not a default of any style pace.
    "riser_bridge_s": 1.2,
}

# Dialogue cleanup presets (plan.audioEnhance.preset → ffmpeg filter chain).
# Runs pre-master so loudnorm re-levels the cleaned signal. "voice" zones in on
# speech: kill rumble below the voice band, track-and-subtract the STEADY
# background (room tone / hum / AC — afftdn is weak on non-steady noise like
# traffic or chatter; that needs a source-separation pass, not a filter), add
# presence for intelligibility, then even the micro-dynamics gently.
AUDIO_ENHANCE = {
    "voice": ("highpass=f=80,"
              "afftdn=nr=12:nf=-45:tn=1,"
              "equalizer=f=3200:width_type=q:width=1:gain=2,"
              "acompressor=threshold=-20dB:ratio=2.5:attack=15:release=200"),
    # stronger denoise for noticeably noisy rooms; slight voice coloration
    "voice-strong": ("highpass=f=100,"
                     "afftdn=nr=20:nf=-38:tn=1,"
                     "equalizer=f=3200:width_type=q:width=1:gain=2.5,"
                     "acompressor=threshold=-20dB:ratio=3:attack=10:release=180"),
    # RNNoise (ffmpeg arnndn) — a trained speech/noise separator, far better on
    # messy non-steady noise than afftdn's spectral subtraction. Model vendored
    # in audio/models/ (see PROVENANCE.md); the literal `{models}` token is
    # substituted with that directory's absolute path by
    # audio_enhance.build_filter — never hardcode the path here.
    "voice-rnn": ("highpass=f=80,"
                  "arnndn=m={models}/bd.rnnn,"
                  "equalizer=f=3200:width_type=q:width=1:gain=2,"
                  "acompressor=threshold=-20dB:ratio=2:attack=15:release=200"),
    # Source separation (Demucs two-stem): the heavy tool for NON-steady noise
    # (music bleed, chatter, traffic). NOT an ffmpeg chain — the `@` sentinel
    # routes audio_enhance.run_audio_enhance to audio/audio_separate.py, which
    # runs Demucs in its own venv and remixes vocals over a muted residual.
    "separate": "@demucs:two-stems=vocals",
}

# ---------------------------------------------------------------------------
# Reframe / face tracking (stage 2 — 9:16 vertical crop windows)
# ---------------------------------------------------------------------------
# Detection is per SHOT (one static window per timeline segment), never
# per-frame — a static crop reads as an intentional camera choice; per-frame
# tracking jitters. Numbers are practitioner heuristics → tunable.
FACE_TRACK = {
    "samples_per_segment": 5,       # frames sampled evenly across each shot
    "min_face_samples": 3,          # need a face in >= this many samples to trust "face"
    "haar_scale_factor": 1.1,       # CascadeClassifier pyramid step (smaller = slower/finer)
    "haar_min_neighbors": 5,        # higher = fewer false positives
    "haar_min_size_frac": 0.06,     # ignore faces smaller than 6% of frame height
    # If the primary face's center-x wanders more than this fraction of the
    # frame width across the samples, the shot has no stable subject to anchor
    # a static crop on → fall back to a center crop and flag it.
    "max_centerx_spread_frac": 0.25,
    "crop_aspect_w": 9,             # target vertical crop aspect (9:16)
    "crop_aspect_h": 16,
    # Optional YuNet model path (env PRODUCER_YUNET_MODEL overrides). The
    # FaceDetectorYN class ships with opencv>=4.7 but the .onnx weights do NOT;
    # when this is unset the shipped Haar cascade (bundled) is used instead.
    "yunet_model_path": os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "models",
        "face_detection_yunet_2023mar.onnx"),  # vendored 2026-07-05 (sibling
    # video-editor drop); YuNet >> Haar on profiles/turned heads. Env
    # PRODUCER_YUNET_MODEL still overrides; delete the file to fall back.
    "yunet_score_threshold": 0.7,
}

# ---------------------------------------------------------------------------
# Plan lint bounds
# ---------------------------------------------------------------------------
LINT = {
    "speed_min": 0.5,
    "speed_max": 2.0,
    "max_cut_ranges": 400,          # sanity ceiling for one output
    "max_title_cards": 6,
    "max_broll_inserts": 24,
}

PLATFORMS = ("tiktok", "reels", "shorts", "youtube")
REFRAME_STRATEGIES = ("face", "center", "blurpad", "none")
# plan.reframe.layout — "fill" (default; today's strategy path or the manual
# crop override) | "split" (Opus-Clip "Layout: Split": two crops of the SAME
# source vstacked to the 9:16 canvas — StreamYard-style screen-share frames
# where webcam inset + shared screen are baked into one 16:9 recording).
REFRAME_LAYOUTS = ("fill", "split")
REFRAME_SPLIT = {
    "frac_range": (0.3, 0.7),   # top cell's share of output height
    "frac_default": 0.5,
    "crop_min_frac": 0.05,      # a crop thinner than 5% of the frame is a mistake
}
CAPTION_STYLES = ("karaoke", "line", "minimal", "whisper")
FILLER_MODES = ("all", "clarity", "none")

# ---------------------------------------------------------------------------
# Motion graphics / layouts (MG track — see PRODUCER_MOTION_GRAPHICS_PLAN.md)
# ---------------------------------------------------------------------------
MOTION = {
    "treatments": ("kinetic", "broll", "templated", "clean"),
    "visual_states": ("talking-head", "screen-share", "mixed"),
    # Anchor legality is visual-state-dependent (operator doctrine 2026-07-05):
    # screen-share zones allow ONLY own-screen cutaways OR focus-shift (the base
    # blurs back, so the screen is never covered) — the screen stays the star.
    #   free-band   = a card in the free band (default alpha overlay)
    #   own-screen  = opaque full-frame cutaway takeover (captions suppressed)
    #   focus-shift = alpha graphic over a BLURRED base (R5) — screen-share-legal
    #   headroom / chest / beside-face = alpha overlay TRANSLATED face-relative
    #     (R3/R4); legal only where there's a face (talking-head / mixed) and each
    #     REQUIRES a measured faceBBoxNorm the compositor reads per-entry.
    "anchors": ("free-band", "own-screen", "focus-shift",
                "headroom", "chest", "beside-face"),
    # Face-relative anchors need a face to anchor to (R3/R4).
    "face_anchors": ("headroom", "chest", "beside-face"),
    "hold_min_s": {"short": 1.0, "longform": 1.5},
    # Hold/takeover ceilings are MODE-KEYED: a short's own-screen takeover is a
    # 2.5s texture beat, but the pro longform's full-frame cutaways run 2.6-9.8s
    # (whiteboard build 8.5s, takeover cards 7.7s, pyramid 6.2s — INTRO_MACHINE_
    # VS_PRO_AUDIT §2, measured 2026-07-06). A graphic world that BUILDS (nodes
    # landing per spoken item) needs the full enumeration span.
    "hold_max_s": {"short": 6.0, "longform": 11.0},
    "takeover_max_s": {"short": 2.5, "longform": 10.5},
    "takeover_max_count": {"short": 2, "longform": 3},
    # Graphics allowed per 10s of a zone, by its budget level.
    "zone_budget_per_10s": {"high": 4, "medium": 2, "low": 1},
    # audioGain dB band is owned by audio/audio_gain.py (DB_MIN/DB_MAX ±12)
    # and linted via plan_lint_audio → parse_windows; no config knob here.
    # Punch-in zoom (MG-3): a subtle static scale-up paired with a jump cut.
    # Research (long-form editing report, 2026-07-04): jump cuts read as
    # intentional when the reframe also changes — the "punch-in". These are the
    # DOCTRINE bounds the plan lint enforces; the ffmpeg primitive (punch_in.py)
    # keeps a wider hard-safety range for its own sanity checks.
    "punch_in": {
        "zoom_min": 1.05,       # below this the reframe is imperceptible
        "zoom_max": 1.25,       # above this it reads as a push/zoom, not a punch
    },
    # Seam-cover transitions (R15 / INTRO_MACHINE_VS_PRO_AUDIT §3): white flash
    # (~3 frames @ native fps) + light-leak wash (~375ms orange→pink), whoosh
    # SFX riding each seam. DOCTRINE bounds for the plan lint; the primitive
    # (transitions.py) keeps its own hard sanity checks (sorted, 1.0s spacing,
    # 0.5s edge margin).
    "transitions": {
        "kinds": ("white-flash", "light-leak", "zoom-pull"),
        "max_per_min": 2.0,          # flashes cover world-changes, not every cut
        "min_spacing_s": 1.0,        # hard floor between seams
        "sfx_peak_dbfs": -15.0,      # audit §3/§5: whoosh peaks −11..−15 dB
                                     # against a −40 dB speech-gap floor
        "flash_frames": 3,           # wash → full white → new shot
        "leak_dur_s": 0.375,         # 9 frames @24fps, in the 150-400ms band
        # XFADE FAMILY — REMOVED (operator rejection, 2026-07-11, FAILURE_
        # LEDGER LL-014). The curated ffmpeg-xfade sampler (fades/wipes/
        # slides/dissolves) was rejected on sight: no rule in Sniper's
        # doctrine gives a stock transition an editorial job. Longform seams
        # are joined ONLY with Sniper's seam grammar: panel sweeps (rail
        # push, MODULE_STUDY T-B), face-bridged recomposition, under-panel
        # cuts, blur-recede (T-D), and seam-role zoom-pulls; flash/leak only
        # at their seam role (below). plan_lint_motion hard-ERRORs any
        # "xfade:*" kind, all modes.
        # SEAM ROLES (docs/studies/EDITCRAFT_LESSONS.md §2.7): most inserts
        # enter and leave on a plain hard cut; each cover kind is legal ONLY
        # at its seam type — zoom pull-in/pull-out at a-roll<->b-roll seams,
        # glare/flash/whip-blur at graphic<->a-roll seams. Transitions are
        # SEAM MARKERS (about one every three minutes), never intra-lane
        # decoration. Advisory doctrine; max_per_min above stays the ceiling.
        "seam_roles": {"zoom-pull": "aroll<->broll",
                       "flash-leak": "graphic<->aroll"},
        "longform_events_per_min": 0.34,   # ~1 seam marker per 3 min
        # ZOOM-PULL SEAMS (EDITCRAFT_LESSONS.md §2.7, continuity mechanism
        # CM-1): three variants with defaults and allowed bands — Sniper
        # design parameters, deliberately configurable. Executed by
        # motion/zoom_pull.py through transitions.py kind "zoom-pull";
        # LONGFORM-ONLY at the lint gate (seam-role grammar), and the events
        # count against max_per_min like every other seam cover.
        # FALSE-POSITIVE GUARD baked upstream: only feature-tracked (ORB/ECC)
        # scale evidence may propose a zoom-pull during study — never
        # faceW-only events (a face-width change can be a physical lean).
        "zoom_pull": {
            "variants": ("punch-cut", "whip", "settle"),
            "seam_roles": ("aroll->broll", "broll->aroll"),
            # (A) PUNCH-THEN-CUT: a ~+20% digital punch-IN on the a-roll
            # over 0.25-0.42s, bell velocity (ease-in-out), COMPLETES
            # 0.6-1.3s BEFORE the cut; the cut itself is covered by a
            # light-leak/flash — zoom and cover are SEQUENTIAL, never
            # simultaneous, so the seam reads as one event (cover defaults on).
            "punch_cut": {
                "scale": 1.205, "scale_band": (1.10, 1.25),
                "attack_s": 0.33, "attack_band_s": (0.25, 0.42),
                "complete_before_s": 0.9, "complete_band_s": (0.6, 1.3),
                "cover_default": "light-leak",   # or "white-flash" / false
            },
            # (B) WHIP-THROUGH: an accelerating zoom SPANS the cut — an
            # ease-in ramp of ~1s into a blur-masked peak AT the cut (the
            # blur hides the frames where the upscale is largest); the
            # incoming side settles ease-out, landing ~0.6s after the cut.
            "whip": {
                "peak_scale": 1.9, "peak_band": (1.5, 2.0),
                "ramp_s": 1.0, "ramp_band_s": (0.7, 1.4),
                "settle_scale": 1.195, "settle_band": (1.10, 1.25),
                "settle_s": 0.6, "settle_band_s": (0.4, 0.8),
                "blur_sigma": 12.0,          # radial/motion blur proxy at peak
                "blur_span_s": 0.12,         # blur gate ± this around the seam
            },
            # (C) POST-CUT SETTLE: the incoming shot eases OUT from a slight
            # zoom (under 12%) over 0.3-0.55s, starting within ~0.55s of the
            # cut — a soft landing, not an emphasis.
            "settle": {
                "from_scale": 1.08, "from_band": (1.05, 1.12),
                "dur_s": 0.4, "dur_band_s": (0.3, 0.55),
                "delay_s": 0.1, "delay_max_s": 0.55,
            },
        },
    },
    # EYE-TRACE CONTINUITY (docs/studies/EDITCRAFT_LESSONS.md §7.1,
    # continuity mechanism CM-4): at a hard cut or full-frame graphic
    # insertion, the incoming frame's focal point (face / key text /
    # highlighted element) should land near the outgoing frame's gaze point
    # when legibility and fit leave a choice; violations only as deliberate
    # FLAGGED jolts. WIRED (2026-07-11): previous-shot focal xy (entry
    # ``gazeXY`` when the planner knows a cursor/focal point, else the
    # faceBBoxNorm center) is an ADDITIVE placement bias in
    # planner/graphics_anchors.resolve_offset_v2 + an Audit B advisory WARN
    # (audit/audit_motion.check_eye_trace over the graphics_placements.json
    # sidecar). Designed anchors, emptiness and fit legality win first, so
    # the bias is a NEAR-TIE BREAKER only and the audit stays advisory.
    # Sniper design parameters:
    #   bias_weight     — additive term on the free-space region score
    #                     (scores run ~0.1-0.5; 0.05 = tie-breaker scale).
    #   warn_dist_frac  — Audit B WARN when a graphic's landed center sits
    #                     further than this from the gaze point (normalized
    #                     2D screen units; 0.45 flags only clear jumps
    #                     across the frame, not ordinary anchor offsets).
    #   audit           — "warn" (advisory) | "off" (skip the check).
    #   jolt_flag_key   — entry flag naming a DELIBERATE violation:
    #                     flagged entries never WARN.
    "eye_trace": {"audit": "warn", "jolt_flag_key": "deliberateJolt",
                  "bias_weight": 0.05, "warn_dist_frac": 0.45},
    # ENTRANCE CAUSALITY (docs/studies/EDITCRAFT_LESSONS.md §7.2 —
    # reconciles long-form move-ins, punch instant-pops and restrained
    # frame-0 pins): every graphic entrance needs a cause the viewer
    # can perceive. A silent unexplained mid-video pop is the ONLY illegal
    # state. Lint spec (longform produced lane, roadmap in
    # plan_lint_motion): entries with inDur=0 must carry an sfx slot or
    # start at t=0. LESSON-016 binds the brain now.
    "entrance_causality": {"legal": ("move-in", "pop+sfx", "frame0")},
    # IMAGE-FOCUS OPERATORS (docs/studies/EDITCRAFT_LESSONS.md §7.4,
    # continuity mechanism CM-3): the six-name still-image b-roll operator
    # vocabulary (four are executable today — ``focus_ops`` below). Use on
    # screenshots/photos, NOT on designed cards (those stay pixel-frozen —
    # BROLL["still_drift_pct_per_s"] / LESSON-017 own the split).
    "image_focus_ops": ("animate-key-text", "highlight-scribble",
                        "darken-surround", "hue-shift-signed",
                        "circle-arrow-underline", "subject-glow"),
    # SIGNED color semantics for hue-shift: red = negative connotation,
    # green/yellow = positive (EDITCRAFT_LESSONS §7.4 — the colour lands the
    # evaluation before the viewer parses the numbers).
    "hue_shift_semantics": {"negative": "red", "positive": "green-yellow"},
    # EXECUTABLE image-focus operators (EDITCRAFT_LESSONS §7.4, CM-3):
    # Sniper design parameters, part of the produced graphics stack (gated
    # by treatment at the lint gate). Rendered by broll/focus_ops.py on
    # brollTrack inserts (plan field ``focusOps``); still images only —
    # designed cards stay pixel-frozen (LESSON-017).
    "focus_ops": {
        "ops": ("highlight", "darken-surround", "blur-surround",
                "hue-shift-signed"),
        # (a) HIGHLIGHT: translucent marker-colour left-to-right wipe —
        # 0.4s by default (a short key-number pass), up to 0.7s for a
        # larger region.
        "highlight": {"color": "0xFFD84D", "alpha": 0.4,
                      "wipe_s": 0.4, "wipe_band_s": (0.3, 0.7)},
        # (b) DARKEN-SURROUND: flat ~−25% luma outside the focus tile,
        # applied within one frame (no ramp), hold ~1-2s.
        "darken": {"luma_gain": 0.75, "hold_band_s": (0.8, 2.5)},
        # sibling BLUR-SURROUND: blur outside the sharp region, no dim.
        "blur": {"sigma": 8.0},
        # (c) HUE-SHIFT-SIGNED: full-frame fill ramped over ~233ms (7
        # frames @30fps); hold 0.8-4.5s. BT.601 chroma targets: red
        # (negative), yellow → green (positive; yellow holds ~1.0s first so
        # a positive wash never reads as a warning).
        "hue_shift": {"mix": 0.65, "ramp_s": 0.233,
                      "hold_band_s": (0.8, 4.5),
                      "positive_yellow_s": 1.0,
                      "uv": {"red": (103.0, 217.0),
                             "yellow": (35.0, 157.0),
                             "green": (92.0, 68.0)}},
    },
    # Narration-paced module builds (MODULE_STUDY.md §3 rank 1 / §5 item 4):
    # a card lands 3-6 modules timed to SPOKEN WORDS, not a fixed stagger —
    # the guidance band is about one short spoken phrase between lands, and
    # 0.25s is the shortest gap at which two arrivals still read as two
    # events (Sniper design parameters). The brain picks WHICH words; code
    # converts them to comp-relative times (graphics_copy.fill_module_lands);
    # the lint floor keeps two modules from stacking on one instant.
    "module_lands": {
        "min_spacing_s": 0.25,       # HARD lint floor between consecutive lands
        "band_s": (0.6, 1.4),        # narration-beat band (guidance
                                     # for the brain's word picks, not a wall)
    },
    # PROGRESSIVE POINT REVEAL (operator doctrine 2026-07-10, FAILURE_LEDGER
    # LL-011): a multi-point LIST comp on longform must land each point
    # word-locked to when the speaker reaches it — never all-at-once. The
    # brain picks the words, graphics_copy.fill_row_lands converts them to
    # comp-relative spec.rowLands (glass-rail) — whiteboard-list already
    # carries per-item atN from fill_list_spec. plan_lint_visual.
    # check_row_lands ERRORs a >=2-item list comp on longform without
    # per-item lands. Data catalog: kind -> {item_prefix, lands_key,
    # max_items}; lands_key "at" = per-item atN scalars, anything else = a
    # list under that spec key.
    "row_lands": {
        "min_spacing_s": 0.25,       # same stacking floor as module_lands
        "kinds": {
            "glass-rail": {"item_prefix": "title", "lands_key": "rowLands",
                           "max_items": 6},
            "whiteboard-list": {"item_prefix": "item", "lands_key": "at",
                                "max_items": 6},
        },
    },
    # EMPTY-CHROME STAGING (showpiece QC 2026-07-10, FAILURE_LEDGER LL-002):
    # the c0679 whiteboard entered on 3 dead frames + 2.08s of frozen canvas
    # before item 1 (at1 2.29s); the rail sat textless 0.9s; the takeover panel
    # black 1.0s. Sniper's build envelope (MODULE_CARDS §1.3) never holds a
    # near-empty shell longer than a moment — blank chrome reads as a stall. The
    # FIRST DECLARED content land (spec.moduleLands[0] / earliest atN) must sit
    # this close to the comp's outStart — else enter the card later (still
    # word-locked) or land a module on the cut. plan_lint_visual.check_first_land.
    "first_land": {
        "own_screen_s": 0.6,         # full-frame cutaway: dead canvas = ERROR
        "panel_s": 0.9,              # panel/overlay: the face carries it = WARN
    },
    # ON-CARD TEXT CONTRAST (showpiece QC 2026-07-10, LL-004): the statement
    # card's accent-blue keywords measured ~2:1 against the navy panel. For
    # comps whose accent paints LARGE (>40px) text, lint computes the WCAG
    # relative-luminance ratio of spec accent colors vs the comp's known bg
    # token and ERRORs under the large-text floor. plan_lint_visual.check_contrast.
    "contrast": {
        "min_ratio": 3.0,            # WCAG large-text floor
        # Reviewed local text/backing declarations, not a guessed footage color.
        # Any template edit invalidates this narrow qualification until reviewed.
        "text_plate_sources": {
            "section-marker": "64b1e7733ff6b975edbb288fce74c712fd127ba86d488b939dc1b285497962ee",
        },
        # kind -> {spec.bg value -> bg hex}. "" = the comp's default variant.
        # Only VERIFIED tokens (sampled from the comp css) — an unknown
        # kind/variant is skipped, never guessed. Data catalog.
        "kind_bg": {
            "statement-card": {"": "#0a1123", "dark": "#0a1123",
                               "cream": "#F1F4F6"},
            "module-takeover": {"": "#121721"},
            "whiteboard-list": {"": "#F1F4F6", "cream": "#F3EFE6"},
        },
    },
    # LEFT-COLUMN OWN-SCREEN BALANCE (showpiece QC 2026-07-10, LL-005): the
    # whiteboard-list fills only the left ~40% of the canvas; a >5s full-frame
    # hold leaves the right side empty grid for its whole life. WARN (taste,
    # operator may hold it deliberately). plan_lint_visual.check_left_balance.
    "left_column": {
        "kinds": ("whiteboard-list",),
        "max_hold_s": 5.0,
    },
    # CARD FORM SELECTION (docs/studies/MODULE_CARDS.md §1.4 mapping table,
    # FAILURE_LEDGER LL-015 / LESSON-029): the card form follows the beat's
    # INFORMATION SHAPE. Planner-facing DATA: info-shape -> the form family
    # (comp kinds) that renders it. The brain classifies the beat's shape;
    # the form follows — a mismatched form (numbers on a plain statement
    # card) is a defect. Every kind here must exist as a comp under
    # templates/motion/compositions/ (tested). Roadmap forms join their
    # families when built (dated-timeline -> chronology, ui-diff -> evidence,
    # scanner-lanes -> qa — MODULE_CARDS §4). Data catalog — exempt from
    # the line budget.
    "card_form_map": {
        # numbers vs a baseline / hero-vs-comparison hierarchy (module #9/#11)
        "comparison": ("module-bullet-bars", "module-scoreboard",
                       "module-takeover", "versus-split", "chart-story"),
        # change over time — the trend hole ledger/scoreboard cannot draw
        # (catalog wave B; decline-chart / mk-line-graph join when ported)
        "trend": ("chart-story",),
        # ordered or parallel steps — pipeline tiles / steps rail (#8/#17/#18)
        "process": ("module-pipeline", "module-rail", "glass-rail",
                    "agenda-slide", "whiteboard-map", "list-build"),
        # receipts / KV ledgers / tool-identity + authorization (#3/#5/#13)
        "evidence": ("slideware-receipt-cell", "module-ledger-dark",
                     "whiteboard-connector", "logo-card", "icon-badge",
                     "icon-badge-wide"),
        # speaker authority / biography / earned identity proof
        "credibility": ("avatar-bio-card", "module-ledger-dark",
                        "whiteboard-connector", "logo-card"),
        # a new chapter or promised roadmap, not a generic thesis card
        "chapter": ("section-takeover", "agenda-slide", "whiteboard-map",
                    "module-pipeline"),
        # measurements vs a LIMIT — threshold tick + amber footer (#11/#12)
        "limit": ("module-bullet-bars", "module-scoreboard"),
        # a single hero metric / gauge (#9 boxed callout, #11 hero number)
        "scale": ("module-scoreboard", "stat-card", "widget-gauge",
                  "count-up"),
        # multi-point lists / checklists (#8/#10; LL-011 row lands apply)
        "list": ("glass-rail", "module-rail", "whiteboard-list",
                 "canvas-pip-list", "agenda-slide", "list-build"),
        # pure thesis — no data, just the sentence (#19); line-swap is the
        # setup-then-subvert masked replacement beat (catalog wave B)
        "thesis": ("statement-card", "fragment-payoff", "kinetic-quote",
                   "kinetic-quote-wide", "line-swap"),
    },
    # Deterministic SUPPORT for the form contract (strict-scope lint ERROR,
    # plan_lint_visual.check_form_shape): a card whose spec carries >=
    # numeric_min numeric tokens (claims_contract.claim_tokens — arithmetic
    # parse) while a declared comparative marker is SPOKEN in its window
    # (cleaned-token SET MEMBERSHIP against this catalog — the same
    # declared-token pattern as motion_triggers.CONTRAST_WORDS and the
    # LL-012 chrome gate; no regex, no semantic inference) but whose kind
    # sits outside card_form_map["comparison"]. Deliberately NARROW: lighter
    # scopes WARN; produced/full longform fails closed.
    "form_shape": {
        "numeric_min": 2,
        "near_s": 3.0,               # claims_contract.CLAIM_NEAR_S band
        "comparative_words": ("versus", "vs", "than", "compared"),
        "strict_scopes": ("produced", "full"),
    },
    # VARIETY (docs/studies/MODULE_CARDS.md §2, LL-016 / LESSON-030): variety
    # lives in STRUCTURE, not palette — tokens repeat, layouts don't (a
    # repeated anatomy reads as something already read; the catalog offers a
    # distinct form per information shape, §1.4). plan_lint_visual.check_variety:
    # consecutive same-kind windows ERROR for produced/full longform (WARN in
    # lighter scopes; caption layers + deliberate statements[] swap chains
    # exempt). At >=40s the first minute needs >=4 windows / >=4 forms; below
    # 40s, any plan that already carries four windows still owes four forms.
    # Beyond
    # 60s the first min(output,180s) grows from >=5 windows / >=4 forms to
    # >=8 / >=6 at 180s, while retaining proportional diversity. The whole plan
    # keeps its >=6 / ceil(.5*N) floor. Sniper design parameters, all
    # deliberately permissive: a well-planned video clears them without trying.
    "variety": {
        "min_windows": 6,
        "min_distinct_ratio": 0.5,
        "scopes": ("produced", "full"),
        "local_floors": (
            {"label": "first minute", "window_s": 60.0,
             "min_output_s": 40.0, "min_windows_floor": 4,
             "min_distinct_floor": 4, "min_distinct_ratio": 0.75},
            {"label": "first three minutes", "window_s": 180.0,
             "min_output_s": 60.0, "min_windows_floor": 5,
             "min_windows_floor_every_s": 25.0,
             "min_distinct_floor": 4,
             "min_distinct_floor_every_s": 30.0,
             "min_distinct_ratio": 0.67},
        ),
        # Caption/whisper LAYER kinds: a caption layer is furniture riding
        # under the cards, not an information-bearing layout — exempt from
        # the consecutive-repeat WARN and the diversity denominator.
        "layer_kinds": ("slideware-caption-dual-mode",),
    },
    # Word-locked seams (MODULE_STUDY.md T-G / §5 item 5): a seam between
    # words reads as the speaker's own punctuation; one inside a word clips a
    # sound. Seams further than this (shorter than a typical stressed
    # syllable — a Sniper design parameter) from the nearest KEPT-word
    # boundary draw a lint WARN; the planner snaps them at plan time
    # (planner/word_lock.snap_to_word_boundary).
    "word_lock": {
        "warn_off_boundary_s": 0.15,
    },
    # FACE-ANCHORED RECOMPOSE (operator defect report 2026-07-10, defect 1):
    # when a rail/panel is on screen the SUBJECT RE-CENTERS in the remaining
    # space — footage scales+pans (eased, one overlapping move WITH the rail
    # growth) so the face lands at the midpoint of the non-panel region
    # (MODULE_STUDY.md T-B): the glide starts ~3 frames BEFORE the rail is
    # visible and runs eased over ~0.40s, OVERLAPPING the 0.33s rail growth,
    # so the rail reads as the cause of the move (Sniper design parameters).
    # Rendered as role:"recompose" punchIns windows (motion/recompose.py) —
    # eased attack in, hold through the panel, eased release out.
    "recompose": {
        "lead_s": 0.12,          # glide starts ~3 frames before the rail lands
        "move_s": 0.40,          # eased glide duration (12 frames @30fps)
        "zoom_margin": 1.02,     # headroom over the minimal pan-enabling zoom
        "zoom_floor": 1.05,      # below MOTION["punch_in"]["zoom_min"] the
                                 # move is imperceptible — floor it there
        "zoom_cap": 1.34,        # recompose band ceiling (was 1.25 =
                                 # punch_in.zoom_max). Measured on c0679 v2
                                 # (2026-07-10): our delivered baseline face is
                                 # dead-centered (fx 0.5154) and small (Haar
                                 # fw 0.125), so landing the remaining-space
                                 # center 0.6651 needs z=1.32 — and the zoomed
                                 # in-rail face width (0.165) is still a
                                 # modest chest-up framing, not a lunge. punch_in's
                                 # hard ceiling (1.55) still governs safety;
                                 # ordinary punches keep the 1.25 band
                                 # (plan_lint_motion routes recompose windows
                                 # to THIS cap).
        "max_landing_error_frac": 0.04,  # after a jump cut, exact remaining-
                                 # space centering may exceed the tasteful zoom
                                 # cap. Land at the closest crop-feasible point
                                 # only when the miss is <=4% of frame width;
                                 # larger misses still force a layout change.
        # Source-derived settled occlusion geometry for every free-band rail.
        # ``side: spec`` means the comp exposes spec.side; fixed-side module
        # chassis are measured from their shipped 1920px composition CSS.
        "geometry": {
            "glass-rail": {"width_frac": 0.3302, "side": "spec",
                           "default_side": "left"},  # 634 / 1920
            "module-rail": {"width_frac": 0.3302, "side": "left"},
            "module-bullet-bars": {"width_frac": 0.375,
                                     "side": "left"},  # 720 / 1920
        },
    },
    # SMOOTH LONGFORM ENFORCEMENT (defect report 2-4, 8): longform grammar is
    # eased ramps and glides — 0-frame footage pops are SHORTS grammar. Any
    # discontinuous footage-scale step must land ON a cut seam; while a panel
    # is up, footage moves must be eased (never punch-cuts). plan_lint_smooth.
    "longform_smooth": {
        "min_ease_s": 0.25,      # eased footage moves must run at least this
        "graphic_guard_s": 0.5,  # discontinuity closer than this to a graphic
                                 # entrance/exit (even on-seam) draws a WARN
        "seam_tol_s": 0.15,      # "on a seam" tolerance
        "scale_jump_tol": 0.01,  # boundary scale step above this = a pop
        "max_layout_families": 3,  # defect 7: TWO module chassis + one
                                   # lower-band card (MODULE_CARDS §1.1);
                                   # more reads as N one-off graphics (WARN)
        # GAP-FILLER ZOOM PAIRS (operator review v2 showpiece 2026-07-10,
        # FAILURE_LEDGER LL-007): the 14-17s zoom-in+out pair existed only to
        # fill the 12.47→19.60 graphics gap. A punch that releases back to
        # wide within this window, overlapping NO graphic and carrying NO
        # emphasis trigger/evidence annotation, is a gap-filler — WARN
        # (plan_lint_smooth._warn_gap_filler_zooms; prefer a graphic / panel
        # extension, LESSON-007).
        "gap_pair_max_s": 4.0,
    },
    # Placement-zone discipline (defect 7): kind → canonical layout FAMILY.
    # Sniper's system (MODULE_CARDS §1.1): a light rail on the anchored side
    # (~1/3 of the width, the face re-centred in the rest), a dark takeover
    # with an optional right-hand presenter card (MODULE_STUDY rank 11), and
    # one lower-band panel.
    # Data catalog (O(1) lookup) — exempt from the logic line limit.
    "layout_families": {
        "glass-rail": "rail",
        "module-takeover": "takeover",
        "glass-takeover-bg": "takeover",
        "section-takeover": "takeover",
        "slideware-takeover-deck": "takeover",
        "glass-lower-third": "lower-third",
        "statement-card": "statement",
        "kinetic-quote-wide": "statement",
        "fragment-payoff": "statement",
        "whiteboard-list": "whiteboard",
        "whiteboard-map": "whiteboard",
        "canvas-pip-list": "whiteboard",
        "agenda-slide": "whiteboard",
    },
    # Zoom engine doctrine — the two formats INVERT the zoom's role (REFERENCE_
    # STYLE_STUDY.md R13; long-form numbers also in LONGFORM_VISUAL_STUDY.md §2):
    #   LONG-FORM = SEMANTIC. Zoom is a second, sparse track under the cuts (2.15
    #     events/min) that lands on MEANING: punch-IN on a stressed claim (Rule 1),
    #     punch-OUT on a section reset (Rule 2), in→out BRACKET reserved for the
    #     biggest lines (Rule 3), slow RAMP under a story (Rule 4), every zoom a
    #     departure from a preserved-wide baseline that resolves back (Rule 5).
    #   SHORTS = RHYTHMIC. Zoom IS the cut: most cuts land tighter or wider than
    #     the last. Up to 10 events/min (well above long-form) but a similar
    #     ~18% magnitude (frequency scales, size does not); direction BALANCED
    #     (in:out ≈ 1.0), alternating push-pull, not a lean-in; ramps rare;
    #     brackets are occasional texture. Sniper design parameters.
    # The lint + the MG-4 zoom proposer branch on grammar via ["by_mode"].
    "zoom": {
        # Shared LINEAR-scale bounds. step_max is the ceiling a BRACKET's in-punch
        # may reach (long-form §2 max ~51%; ordinary punches stay in the tighter
        # MOTION["punch_in"] band). Ramps creep at 0.3-1.8%/s (long-form only).
        "magnitude": {"step_max": 1.51, "ramp_rate_range": (0.3, 1.8),
                      "ramp_rate_default": 0.8},
        # In→out brackets are capped HARD per video (R13 Rule 3: the biggest
        # lines only; a short uses them only as occasional texture).
        "bracket_max_per_video": 3,
        # Baseline doctrine (Rule 5): the wide framing is "home" (scale 1.0). Every
        # zoom resolves back to it, never below (the framed clip can't reveal more).
        "baseline_scale": 1.0,
        # MODE-KEYED grammar (R13). Each mode carries its own median push magnitude
        # + cadence budget shape; the proposer reads ["grammar"] to choose its pass.
        "by_mode": {
            "longform": {
                "grammar": "semantic",       # zoom carries meaning; sparse
                "step_median": 1.21,         # study §2: median push ~21%
                # Front-loaded cadence CEILING (plan_lint_motion._check_hook_body_
                # cadence). Two motion TRACKS share this budget: (1) sparse SEMANTIC
                # punches/brackets that land on meaning (R13 — still trigger-gated,
                # naturally sparse) and (2) the continuous ALIVENESS CREEP (eased
                # stretch ramps under talking stretches). MOTION_GRAMMAR_STUDY.md
                # (2026-07-06) measured the pro body alive ~50% of the time with a
                # subtle push always running, vs the machine frozen 67% (one 39s dead
                # hold) — the body cap of 2/min was FORBIDDING track (2). Raised to
                # admit the aliveness layer; the hook still front-loads ~2.35× (R20).
                "cadence": {"hook_per_min": 6, "body_per_min": 5, "hook_s": 60},
            },
            "short": {
                "grammar": "rhythmic",       # zoom IS the cut; every cut reframes
                "step_median": 1.18,         # R13: shorts median reframe ~18%
                # Uniform, cut-driven cadence — one reframe every ~6-10s (a few
                # per minute reads calm, 10/min high-energy); no hook/body split.
                "cadence": {"per_min": 10, "reframe_every_s": (6, 10)},
            },
        },
        # MG-4 zoom PROPOSER defaults (graphics_planner_zoom). Practitioner
        # heuristics → tunable; nothing here auto-injects (the operator vetoes).
        "proposer": {
            "punch_hold_s": 1.6,        # a long-form punch-in holds the beat this long
            "bracket_release_s": 0.8,   # the wide-settle tail after a bracket's hold
            "punch_out_s": 0.8,         # a topic-boundary reset (a brief out-ramp to wide)
            "ramp_min_stretch_s": 10.0, # an uncovered stretch longer than this earns a slow
                                        # eased ALIVENESS creep so the frame never freezes.
                                        # Lowered 30→10 (MOTION_GRAMMAR_STUDY §2/§8): the pro
                                        # creeps under short stretches AND continuously; 30s
                                        # let the machine sit dead-still for 39s. Now applied
                                        # to a segment's FROZEN TAIL (after its last punch),
                                        # not just punch-free segments (carpet-the-creep).
            # An eased-ATTACK push (mid-shot thesis punch, grammar G6): smoothstep in
            # over this many seconds to the target zoom, then hold. ~0.9s per the
            # frame-accurate ORB zoom trace (docs/studies/MEASURED_EDIT_GRAMMAR.md §1: the
            # pro's INTENTIONAL pushes run 8-15%/s over ~0.7-1.1s — a VISIBLE
            # deliberate push, NOT the 0.5s/42%/s flick this used to emit). Capped at
            # half the punch window so a hold remains.
            "push_attack_s": 0.9,
            # Push magnitude scales with the beat's IMPORTANCE (MEASURED_EDIT_GRAMMAR
            # §1: +7-16% by how much the word matters — the fastest/biggest push in
            # the intro, +14.5%, landed on the PRODUCT name). Keyed on confidence as
            # the importance proxy; with the ~0.9s attack this yields ~9/12/17 %/s.
            "push_zoom_by_conf": {"high": 1.15, "medium": 1.11, "low": 1.08},
            # A thesis beat within this of a cut boundary is a punch-ON-CUT and stays a
            # hard step (a step reads as intentional AT a cut, G6); farther in-shot, it
            # becomes an eased push so it does not snap in a continuous shot.
            "punch_on_cut_eps_s": 0.35,
        },
    },
    # Long-form per-zone density doctrine (MG-3), encoded as data the brain
    # reads when it has NO editor notes. Sources: PRODUCER_MOTION_GRAPHICS_PLAN
    # §1.5 (mode default: "kinetic intro 60s → templated body → stingers at
    # chapters") and §2.2 long-form column (cadence / hold / takeover / concurrency).
    "longform_zone_defaults": {
        # §2.2 "front-load the first 30-60s dense"; §1.5 "kinetic intro 60s".
        "intro_kinetic_s": 60,          # first 60s runs the dense kinetic zone
        "intro_budget": "high",         # intro carries the high density budget
        "intro_treatment": "kinetic",
        # §1.5 "templated body" — everything after the intro leans templated/low.
        "body_treatment": "templated",
        "body_budget": "low",
        # §2.2 "one per 10-15s early" — the early-body pattern-interrupt cadence
        # (oscillating bursts, not metronomic); a guideline, not a hard gate.
        "interrupt_every_s": (10, 15),
        # §2.2 "no static stretch > 60-90s" — force a visual change before the
        # ceiling; the conservative end of the band so the body never flatlines.
        "max_static_stretch_s": 90,
        # §1.5 + §2.2 "full-frame takeovers: chapter transitions + intro thesis
        # only" — stingers fire AT chapter boundaries (topic-boundary trigger).
        "stinger_at_chapters": True,
        "takeover_zones": ("intro", "chapter"),
        # §2.2 long-form: hold floor 1.5s (calmer pace), concurrency <= 2 layers.
        "hold_min_s": 1.5,
        "concurrency_max": 2,
    },
    # MG-4 auto-graphics planner (graphics_planner.py) — proposal-time doctrine.
    # The planner PROPOSES candidates from triggers; the brain reviews + the
    # operator vetoes. Nothing here auto-injects into a plan. Numbers are
    # practitioner heuristics → tunable.
    "planner": {
        # Minimum OUTPUT-time gap between two accepted graphics (breathing room —
        # graphics stacked tighter than this read as clutter, not emphasis).
        "min_gap_s": 2.0,
        # One-mark-once (R12): the SAME resolved icon may not reappear inside this
        # window — two OpenAI knots for one sentence is exactly what R12 forbids.
        "one_mark_window_s": 8.0,
        # Default hold for an entity badge/chip (it lands on the word + holds).
        "entity_hold_s": {"short": 1.6, "longform": 2.0},
        # Default hold for a non-entity graphic (stat/list/contrast/thesis).
        "default_hold_s": {"short": 2.2, "longform": 2.8},
        # Adjacent specific entities within this window fold into ONE multi-slot
        # badge/chip-row ("Codex and Gemini" → one icon-badge), up to max_slots.
        "entity_group_window_s": 3.5,
        "max_slots": 4,
        # Short mode is one zone; this is its suggested density budget.
        "short_zone_budget": "medium",
        "short_zone_treatment": "kinetic",
        # Confidence tiers the planner emits + their rank order (high wins ties).
        "confidence_rank": {"high": 3, "medium": 2, "low": 1},
        # A topic-boundary is only worth a graphic when its detector confidence is
        # at least this — a bare pause (low) in a short is dead air, not a chapter.
        "topic_boundary_min_conf": {"short": "high", "longform": "medium"},
    },
    # R12 generic-entity blocklist — words that name a whole CATEGORY, not a
    # SPECIFIC product, so they earn no entity graphic: an "AI" mark while the
    # speaker says "AI" adds zero information (worse when it borrows a brand's
    # mark). Lowercased, matched against the cleaned entity text. Data catalog
    # (O(1) membership) — grow it freely; exempt from the logic line limit.
    "generic_entity_blocklist": (
        "ai", "a.i.", "ml", "llm", "llms", "gpt", "agi",
        "internet", "computer", "computers", "software", "hardware",
        "phone", "phones", "video", "videos", "content", "app", "apps",
        "application", "applications", "tech", "technology", "cloud", "web",
        "website", "online", "digital", "data", "code", "coding",
        "platform", "platforms", "tool", "tools", "model", "models",
        "algorithm", "algorithms", "startup", "startups", "business",
        "marketing", "brand", "brands", "product", "products", "system",
        "systems", "workflow", "workflows", "channel", "channels",
        "saas", "b2b", "b2c", "crm", "cms", "api", "apis", "ui", "ux",
        # Calendar words read as Title-case entities but earn no brand graphic.
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ),
}

# ---------------------------------------------------------------------------
# Free-space placement (Placement v2 — graphics_anchors + free_space)
# ---------------------------------------------------------------------------
# Placement v1 nudged a full-canvas comp by the face's DEVIATION from a nominal
# head, so a comp that authored its content at mid-frame (e.g. chip-row's
# ``top:855px``, right at the chin) barely moved and landed ON the face. v2
# instead MEASURES the frame's occupied space (face+hair, body silhouette, busy
# background) and places the graphic's rendered content bbox ABSOLUTELY into the
# emptiest legal region (R3 "the headroom IS the graphics canvas"). Numbers are
# practitioner heuristics → tunable; calibrated 2026-07-05 on the car3 framing
# (face high+large, empty car-headliner above the hair).
FREE_SPACE = {
    "samples_per_window": 12,       # frames sampled evenly across a graphic's window
    # Occupancy grid over the 1080x1920 canvas (finer than visual_state's 8x6).
    "grid_cols": 12,
    "grid_rows": 16,
    # Face -> "face+hair" exclusion. Haar boxes the face (brow->chin) only, so the
    # hair sits ABOVE the box. The TRUE hair top is MEASURED per window via
    # median-background subtraction (see measure_hair_top — the head moves, the
    # room doesn't, so |frame - median plate| isolates the person even for dark
    # hair on a dark background; technique from the sibling video-editor project).
    # The 40%-of-face-height up-expansion below is the FALLBACK used only when the
    # hair can't be measured (hat/hood, too little head motion, detection gaps);
    # sides always use the 25% guess (ears/side-hair — no cheap measurement).
    "face_expand_up": 0.40,
    "face_expand_side": 0.25,
    # Hair-top measurement (median-bg subtraction) search window + thresholds.
    "hair_search_half_w": 300,      # search band half-width around the face center
    "hair_search_up": 350,          # search this many px above the face top
    "hair_diff_thresh": 14,         # |frame-plate| mean-channel diff -> "person"
    "hair_row_min_px": 25,          # a row needs this many person-px to count as hair
    # Placement re-verification (verify_placement / CLI --verify): the composite is
    # re-measured and the graphic must clear the (measured) face by >= this gap.
    "verify_min_gap_px": 0,
    # Body silhouette below the chin: a column face_width * this wide, chin ->
    # frame bottom (shoulders/torso/gesturing hands). Marks the lower-mid frame
    # occupied so a graphic isn't placed onto the body.
    "body_width_mult": 2.2,
    # Headliner top margin — the top of the headroom band. DELIBERATELY smaller
    # than SAFE_BOX["top"] (250): that 250 is the LOWER content/caption stack's
    # margin; the top edge of a short is mostly clear (only a small centered
    # platform tab), and R3 + the operator want persistent graphics UP in the
    # headliner. Left/right/bottom placement still clamp to SAFE_BOX.
    "headroom_top_inset": 60,
    # A candidate region shorter/narrower than this can't hold a graphic -> dropped.
    "min_band_px": 90,
    # The anchor's PREFERRED region is taken only if it is at least this empty;
    # otherwise placement falls back to the best-scored feasible region (logged).
    "prefer_emptiness": 0.55,
    # Edge-density (busy-background) detection — reuse visual_state's Canny params;
    # a finer grid means smaller cells, so the busy-cell threshold is a touch higher.
    "edge_downscale_w": 720,
    "canny_lo": 80,
    "canny_hi": 180,
    "cell_edge_frac": 0.06,
    # Anchor NAME -> preferred free-space region. The anchor expresses PREFERENCE,
    # not a hard slot: headroom prefers the top band, chest the below-face band,
    # beside-face the emptier side — each falls back by score if its region is
    # occupied or can't hold the graphic.
    "anchor_region": {
        "headroom": "headroom",
        "chest": "lower-third",
        "beside-face": "beside-face",   # resolves to left-of-face / right-of-face
    },
    # Caption band awareness (suggest_caption_band): when the mid-frame is
    # body-occupied (face sits high, torso/hands fill the middle), captions read
    # better DROPPED to the lower band near the baseline ceiling instead of the
    # default chest band. Fractions of canvas height; render.py wires the result.
    "caption_low_band": (0.62, 0.70),   # ~1190..1344 px on 1920
}


# ---------------------------------------------------------------------------
# Slip-cover window scoring (edit/cover_select.py — FAILURE_LEDGER LL-008)
# ---------------------------------------------------------------------------
# The v2 showpiece's 45.3-47.8s wide slip-cover read as an OUTTAKE: silent,
# mouth-closed, motionless footage. A slip-cover must show the subject
# actively DOING something (gesturing / working / moving) — these are the
# deterministic knobs the cover lane scores candidate source windows with.
# Numbers are practitioner heuristics → tunable.
COVER_SELECT = {
    "sample_w": 160,           # gray downscale width for the frame-diff probe
    "sample_h": 90,            # fixed probe height (aspect distortion is
                               # irrelevant to motion measurement; fixed dims
                               # keep the pure-python diff simple)
    "sample_fps": 5.0,         # frame-diff sampling rate
    "motion_ref": 6.0,         # mean |Δluma|/px/frame that counts as FULL
                               # motion (energetic gesturing on our footage);
                               # normalizes the 0..1 motion score
    "gesture_ref": 5.0,        # same reference, LOWER HALF only (the hands
                               # band — the deterministic gesture proxy)
    "motion_weight": 0.6,      # score = 0.6 * motion + 0.4 * gesture
    "gesture_weight": 0.4,
    "retake_pad_s": 2.0,       # hard-exclude windows overlapping a
                               # retake_scan cut span ± this (that footage is
                               # an outtake BY CONSTRUCTION)
    "speech_min_share": 0.30,  # transcript empty for >70% of the window ...
    "silent_motion_floor": 0.60,  # ... excludes it UNLESS motion clears this
                                  # (silent + static = outtake-looking;
                                  # silent + visibly working is legal)
    "score_floor": 0.35,       # below this NO window is used — cover the
                               # seam with a graphic takeover (LESSON-008)
    "search_s": 20.0,          # candidate search radius around the seam span
    "hop_s": 0.5,              # candidate window hop
    # LIP-FLAP guard (operator review 2026-07-10, FAILURE_LEDGER LL-010): a
    # slip-cover shows the SAME speaker, so any visible on-camera speech in
    # the window mouths words that are NOT the underlying audio — it reads
    # as an AV-sync error (the c0679 v3 cover carried 0.49s of it: the
    # abandoned line's tail + the restart's onset). Windows whose spoken-word
    # overlap exceeds this many SECONDS are hard-excluded ("lip-flap").
    "lip_flap_max_s": 0.25,
}


# ---------------------------------------------------------------------------
# Global caption corrections (sibling video-editor concept, 2026-07-05)
# ---------------------------------------------------------------------------
# Whole-word, case-insensitive fixes applied to EVERY captions run, merged
# UNDER plan-level captions.corrections (plan wins on key collision). Casing
# fixes ASR reliably gets wrong + this operator's recurring brand mishears.
CAPTION_AUTO_CORRECTIONS = {
    "youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram",
    "linkedin": "LinkedIn", "iphone": "iPhone", "ios": "iOS", "ai": "AI",
    "api": "API", "apis": "APIs", "ui": "UI", "saas": "SaaS", "ceo": "CEO",
    "Hagen": "HeyGen", "Hits Hitsfield": "Higgsfield", "Higgs field": "Higgsfield",
    "cable five": "Fable 5", "Fable five": "Fable 5",
}
