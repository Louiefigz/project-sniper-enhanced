# PRODUCER — Edge Case Catalog (living document)

Seeded 2026-07-04 from PRODUCER_PLAN.md §8. This is NOT a completeness claim —
it grows every time real footage surprises us (precedent: PIPELINE_EDGE_CASES.md
reached 131 cases the same way). Add a row the moment a case is discovered,
even before it's handled.

Status: `planned` (design exists) · `handled` (code + verified) · `open`
(known, no mitigation yet) · `wontfix` (accepted with rationale).

## Ingest

| # | Case | Handling | Status |
|---|------|----------|--------|
| I1 | VFR footage (phones) — timestamp math drifts | Detect r_frame_rate≠avg_frame_rate at probe; normalize to CFR at mezzanine | planned |
| I2 | HEVC / 10-bit iPhone source | Decode via ffmpeg, mezzanine is 8-bit x264 | planned |
| I3 | Mixed resolutions/fps across sources | Normalize to common profile at stage 1 | planned |
| I4 | Portrait-shot source (already 9:16) | Reframe becomes passthrough / crop-for-16:9 | planned |
| I5 | Rotation metadata (phone sidecar rotate) | Respect display matrix at probe + render | planned |
| I6 | No/corrupt audio track on "raw footage" | Reclassify as b-roll, warn | planned |
| I7 | Multi-hour 4K files | Transcribe from extracted audio; render only kept ranges | planned |
| I8 | Same file added twice (or copies) | Content-hash dedup in manifest, warn | planned |
| I9 | Unsupported/garbage file in folder | Skip with per-file error, don't abort the batch | planned |

## Transcription

| # | Case | Handling | Status |
|---|------|----------|--------|
| T1 | Deepgram fails mid-chunk | Retry chunk; on repeated failure mark gap + surface (never silent-skip) | planned |
| T2 | Heavy crosstalk / wrong diarization | CLIPPER mic-bleed doctrine + operator speaker-map override | planned |
| T3 | Non-English source | Pass detected language through | planned |
| T4 | Music-only / silent b-roll | Vision-description path, hasSpeech:false | planned |
| T5 | Empty transcript on speechful video | Error loudly — do not proceed to an empty plan | planned |

## Brain / plan

| # | Case | Handling | Status |
|---|------|----------|--------|
| B1 | Hallucinated timestamps / asset ids | plan_lint rejects with specific errors; bounded retries | **handled** (plan_lint.py, verified 2026-07-04) |
| B2 | No strong hook found | Present best candidates + scores; never fabricate a promise | planned |
| B3 | Content can't fill target duration | Shorter output beats padded output; flag it | planned (lint floor errors) |
| B4 | Operator feedback contradicts platform doctrine | Comply + warn once with the research basis | planned |
| B5 | Combined transcripts exceed context | Hierarchical: per-source candidates → global assembly | planned |
| B6 | Same content in multiple takes | Take-selection (keep the better copy) | planned |

## Longform→clips→shorts conversion

| # | Case | Handling | Status |
|---|------|----------|--------|
| C1 | Moment spans a segment boundary | Candidate selection runs on source transcript, not segment silos | planned |
| C2 | Hook sentence starts mid-utterance | Word-level cut; first spoken word must stand cold | planned |
| C3 | Self-containedness: payoff needs setup minutes earlier / "like I said earlier" | Reject candidate or splice the setup in; never assume prior context | planned |
| C4 | Caller speaks with no intro (attribution) | Hook card / caption establishes speaker when it matters | planned |
| C5 | Clip under duration floor after cuts | Merge with adjacent beat or drop; never pad | planned (lint floor) |
| C6 | Overlapping candidate moments | Dedup at ranking | planned |
| C7 | Source has burned-in graphics/lower-thirds | Vision flags at ingest; caption band must not stack | planned |
| C8 | Loop point lands mid-word | Nudge out-point to word boundary via timeline map | planned |
| C9 | Unflattering first frame | Hook card covers frame 1; cover prefers settled frame | planned |
| C10 | Profanity near the hook (demonetization) | Audit A flag; optional caption masking, operator decides | planned |
| C11 | Numerals/currency in captions | Caption formatter normalizes; Deepgram smart_format does most | planned |
| C12 | Source's own burned-in lower-third sits INSIDE the caption band, under our karaoke captions (real case: a website label at ~y1200 on c1) | `captions.bandYOffsetPx` (0-400, lint-bounded, up-only) shifts the band; verified in ASS MarginV; ingest vision-flagging still planned for auto-detection | **handled** (manual offset, 2026-07-05) / planned (auto-detect) |
| C13 | ffmpeg loudnorm linear mode systematically overshoots the TP target | AUDIO.loudnorm_tp_param=-2.0 (separate from the -1.5 delivery ceiling) across master+audio_mix; re-mastered c1 measures -1.9 dBFS clean | **handled** (2026-07-04, empirically verified) |
| G21 | glass-rail DEFAULT SAMPLE DATA leaks: unset rows 4-6 render the template's fallback demo text ("Captions/Music/Export") and unset subN show sample subs — defaults must be EMPTY (sample data belongs only in renders/samples) | Comp defaults emptied (unset rows render NOTHING; demo content is a preview-only SAMPLE block active when every var is unset); glass-lower-third had the same pattern — fixed identically. schedule-stack + list-build still carry it (flagged) | **handled** (2026-07-06) |
| G22 | glass-rail renders full-width over a CENTERED talking head — face fully covered (violates R3). Built/tested against screen-share where no face conflict existed | side var added (left|right, schedule-stack convention, mirrored slide-in, same 96px safe margin); note the v2 intro DROPPED the rail entirely per R14 (pro shows nothing at the agenda) | **handled** (2026-07-06) |
| C16 | Quiet high-crest CAMERA-MIC sources (Sony C0666) land ~-15.6 LUFS vs -14 target — loudnorm can't close the gap; acompressor and speechnorm pre-stages both failed to move it | ROOT CAUSE (2 parts): (1) camera records mic to ONE channel — the dead channel costs ~3 LU and ships one-eared speech; (2) ffmpeg loudnorm linear=true SILENTLY degrades to dynamic when measured_TP + (target−measured_I) > TP param (here +7.7 > −2.0) — dynamic undershoots I and crushes LRA. Fix: master.dead_channel_prefix dual-monos the live channel; _linear_eligible pre-checks the fallback condition; ineligible sources get STATIC gain + true-peak limiter (LRA preserved). v2 intro: −14.1 LUFS / LRA 4.3 / TP −1.9 | **handled** (2026-07-06; see also X21 ordering) |
| C15 | Word-snap grabs one word past the phrase → range ends on a dangling conjunction ("...more creative. And" / "...a camera. So" — operator-caught on car1, transcript-verified) | Brain doctrine: check every range's FINAL word against {and,so,but,or,because,then,which,that} → pull the edge back one word; future: transcript-aware lint rule (lint reads transcriptPath) | **handled** (doctrine + car1 v3) / planned (lint) |
| C14 | (Evidence) blurpad vs center on screen content, measured | Danger-zone (y>1400) edge density: blurpad ≈0.000 vs center 0.016–0.031 on real frames — empirically confirms the focal-subject treatment doctrine + C7 | reference |

## Face crop

| # | Case | Handling | Status |
|---|------|----------|--------|
| F1 | No face (screen share / slides) | Center crop or blurpad by content type | **handled** (real-cv2 fallback verified 2026-07-04) |
| F2 | Two faces (host + guest) | Active-speaker crop via diarization windows; Phase 1: highest-confidence + multiFace flag | handled (flag) / planned (active-speaker) |
| F3 | Face near frame edge | Clamp crop window, never off-canvas | **handled** (25 crop-math unit tests) |
| F4 | Low detection confidence | Center fallback + lowConfidence flag for Audit B | **handled** |
| F5 | Speaker walks across frame mid-shot | Static per-shot window Phase 1; re-split shot if audit flags | planned |
| F6 | OpenCV 5.0 dropped Haar (CascadeClassifier + XML) | Pin `opencv-python-headless>=4.8,<5` — load-bearing; YuNet used only when model path configured | **handled** (requirements pin) |
| F7 | Face-path reframe accumulates up to ~1 frame per interior boundary of drift. Root cause: the per-range extract expressed each cut in SECONDS (`-ss outStart -t dur`), so every part rounded to the frame grid independently and a frame straddling a boundary fell into NEITHER part (part i's `-t` truncated before it; part i+1's accurate `-ss` seek started after it). Data-dependent: car2 dropped 1 frame at each of 5 interior boundaries (1629→**1624**, −5f/6seg, exceeding the reframe assertion's 1.0+0.5×6=4.0 tol → render raised); car1's boundaries happened to round cleanly (1119→1119, 0 drift — the "+4.95f/4seg" once noted for car1 was the X19 master container-duration artifact, not the reframe frame count) | reframe's face path now cuts on SHARED, endpoint-pinned FRAME INDEXES: `_frame_boundaries` builds `[0, round(outStart×fps)…, total_frames]` (each interior boundary computed once + reused by both adjacent parts → no gap/overlap; endpoints pinned → telescopes to exactly the input length), `_extract_part` selects via `trim=start_frame:end_frame` + `setpts=N/FRAME_RATE/TB` (video-only), then `_concat_mux` concats the parts and copy-muxes the mezzanine's audio ONCE (timing is video-side, so audio passes through untouched). Frame-exact by construction — no rounding luck | **handled** (2026-07-05: car2 face 1624→1629 exact; full render chain that formerly raised at the reframe assertion now passes end-to-end for car1 1119→1119 & car2 1629→1629 incl. audit 20/0/0; center byte-stable md5-identical; testsrc2 2-seg & single-window exact) |

## B-roll

| # | Case | Handling | Status |
|---|------|----------|--------|
| R1 | Empty folder / no match for a named noun | Skip or generate; never decorative, never fuzzy-match | planned |
| R2 | B-roll shorter than slot | Don't stretch >1.25x; pick another or shorten slot | planned |
| R3 | Orientation mismatch (16:9 asset on 9:16 canvas) | Center-crop if safe else blurpad | planned |
| R4 | Burned text/watermark near safe zones | Vision flags at catalog time | planned |
| R5 | Higgsfield generation fails / NSFW-flagged / slow | Without-b-roll fallback for that slot + note; per-run credit cap | planned |
| R6 | Generated text-in-image garbling | HARD RULE: no text-bearing generations | planned |
| R7 | B-roll placed over hook card or payoff | Lint rejects card overlap; payoff protection at plan time | **handled** (card overlap in plan_lint) / planned (payoff) |

## Music

| # | Case | Handling | Status |
|---|------|----------|--------|
| M1 | Track shorter than video | Self-seamless period + stream_loop tiling (O(1) graph); seam step 1.23x interior (no click) | **handled** (audio_mix, 2026-07-04) |
| M2 | Track longer than video | Trim + 2s qsin fade ending at video end (bar-boundary trim = Phase 2+ refinement) | **handled** (audio_mix) |
| M3 | Library track at wild loudness | Measured single-gain pre-norm to dialogue-relative reference (preserves music dynamics; float PCM, no clip) | **handled** (audio_mix) |
| M4 | Unlicensed track | `licensed` field warning in Audit A; operator responsibility | planned |
| M5 | No library match + generation unavailable | Ship without-music variant + say so | planned |

## Render

| # | Case | Handling | Status |
|---|------|----------|--------|
| X1 | Speed change AV drift | atempo/setpts from same factor; duration asserted vs compiler ±1 frame | planned |
| X2 | Caption/overlay drift after cuts+speed | ALL overlay math via timeline_map.json; Audit B re-transcription backstop | **handled** (compile_timeline verified) / audit planned |
| X3 | Audio clicks at word-boundary joins | 0.1–0.3s cut padding + ~15ms crossfades | planned |
| X4 | Filter graph complexity blowup | Staged rendering, per-range extract + concat | planned |
| X5 | Disk space / very long renders | Preflight check; stage-resumable work dir | planned |
| X6 | ffmpeg version differences | Extend existing check_ffmpeg_version pattern | planned |
| X7 | Output exceeds TikTok 287MB cap | Warn + optional re-encode at lower bitrate | planned |
| X8 | MP4 container duration inflated ~1 frame by AAC encoder padding | Assert durations on the VIDEO TIMELINE (frame_count/fps), never container duration; tolerance 1.0 + 0.5×n_segments frames | **handled** (cut_speed, 2026-07-04) |
| X9 | Final master +1 duplicated tail frame (CFR fills AAC-padded mezzanine tail) | Harmless <40ms; not asserted; revisit if loop-point matching (C8) needs exact tail | open |
| X10 | Caption char budget vs font metrics mismatch → line overflows canvas | max_chars_per_line and font_size are a COUPLED pair (0.55em avg advance × chars ≤ 870px safe width); 42@64px overflowed, fixed to 28@56px | **handled** (e2e-caught 2026-07-04, config comment locks the pair) |
| X11 | master() failure reported as dict, not raised → render claimed success with no output | render.master_stage raises on status != done (was the one non-propagating stage) | **handled** (review-caught P0, 2026-07-04) |
| X12 | Systematic sub-frame bias could accumulate between timeline_map time and CFR frame grid → caption/crop drift, hidden by per-segment tolerance | Symmetric frame-count assertion after reframe (render._assert_reframe_frames); Audit B transcript re-check (X2) remains the Phase-2 backstop | **handled** (assertion) / planned (audit backstop) |
| X13 | Single caption token > max_chars (URL, long numeral) can't wrap → overflows safe width | captions._split_oversized pre-pass: hyphenated pieces, proportional karaoke timing | **handled** (review-caught, 2026-07-04) |
| X14 | Replayed same-source range (intentional repeat) gets captions only on first copy (remap_words maps to earliest containing segment) | Lint rejects overlapping same-source cut ranges in Phase 1; revisit if replay becomes a wanted editorial pattern | planned (queued behind lint refactor) |
| X15 | Short mode + reframe strategy "none" → 16:9 output with 1080x1920-authored captions rescaled wrong | Lint couples strategy to mode aspect | planned (queued behind lint refactor) |
| X16 | Hook-card char limits count code points, not visual width (emoji/ZWJ mis-measure) | Accepted-nominal: copy is RAG-grounded plain text; revisit only if emoji cards become a style choice | wontfix (documented 2026-07-04) |
| X17 | Zero transcribed words with captions.burn on → caption-less short shipped as success | render.captions_stage raises; explicit captions.burn=false is the only override | **handled** (review-caught, 2026-07-04) |
| X18 | 287MB TikTok cap warning fires on long-form outputs (642MB longform is fine for YouTube) | render.master_stage filters the size warning in longform mode | **handled** (2026-07-04) |
| X19 | Per-part AAC tail padding accumulates through concat (~1 frame/cut part); master's CFR pass pads video to the audio tail → duration drift scales with part count (audit-caught on 4-part car cuts: +4.95f) | MasterSpec.duration clamp: master encodes with -t predicted+half-frame — exact by construction; tail junk trimmed | **handled** (2026-07-05, both cars re-audited 20/0/0) |
| X20 | Master rounded fractional NTSC fps to integer (`-r 24` on a 23.976 source) → CFR duplicates ~1 frame/42s and every frame-indexed event downstream slides off its seam (v2 intro: seam flashes "vanished" — found +7/+8 frames late; v1 shipped 30fps from a 23.976 source the same way) | MasterSpec.fps_exact carries the rational rate verbatim to -r (render.master_stage sets it whenever the rate isn't integer); int fps stays for GOP/bitrate lookups only. v2 verified 7352→7352 frames, flashes frame-exact | **handled** (2026-07-06, retest-caught) |
| X21 | ORDERING LAW: any stage that MIXES audio (transitions' whooshes land on both channels) must run AFTER dead-channel repair — the mixed SFX makes a dead source channel look alive to master's detector, silently shipping one-eared speech (v2 intro first render: speech ch2-only at −68 dB in ch1 windows) | render.channels_stage (dual-mono via master.dead_channel_prefix) runs immediately after cut_stage, before every audio-touching stage; video stream-copied, audio-only re-encode | **handled** (2026-07-06, retest-caught) |
| X22 | punch_in ramp crops were NEVER centered: ffmpeg `crop` freezes in_w/in_h at the pre-zoom link config and doesn't track per-frame `scale=eval=frame` growth — the bare `crop=W:H` "centered default" resolved to constant (0,0), silently anchoring every animated ramp TOP-LEFT since MG-3 | Crop x/y expressions recompute scaled dims from t with the same closed form as the scale branch (lockstep by construction); ramps also gained centerX/centerY recompose targets + smooth ease (R16). Marker-verified ±1.1px | **handled** (2026-07-06, build-caught during pan-aware extension) |
| X23 | Dark takeover comps (kinetic-quote worlds) tripped Audit B's blackdetect (pix_th 0.10): near-black build-in reads as "unexpected mid-video black" — AND genuinely reads as dead air (the pro's dark takeovers keep a lit surface from frame 1) | Two-sided: comps keep their base+vignette ABOVE the 10% luma floor (kinetic-quote-wide lifted #0a0a0b→#101014/#2a2a33 core); audit_glitch.detect_black takes plan-declared own-screen windows and demotes fully-contained runs to WARN (audit_render passes graphicsTrack own-screen spans) | **handled** (2026-07-06, v3 retest-caught; comp fix alone turned the check PASS) |

## Motion graphics / layouts (MG track, 2026-07-05)

| # | Case | Handling | Status |
|---|------|----------|--------|
| G1 | Graphic copy contains a number/claim NOT in the transcript (brain invention) | Lint cross-checks spec values appear in transcript text; verbatim-grounding rule | planned |
| G2 | **H.264/MP4 cannot carry alpha** — "transparent MP4" is not a thing | Overlay renders must be ProRes 4444 (.mov), VP9 (.webm) alpha, or PNG sequence; compositor recipe per format; MG-1 agent verifying hyperframes' exact emission | planned (verification in flight) |
| G3 | Template slot text overflow (long values/names) | Auto-size like hook cards + per-slot char limits in template schema, lint-checked | planned |
| G4 | Graphic collides with active LAYOUT regions (stat card over split seam / captions) | Graphics zones come FROM the active layout; lint per-layout collision check | planned |
| G5 | Takeover during payoff or hook card | Lint exclusion windows (payoff protection + card window) | planned |
| G6 | Zone density budget exceeded | Lint per-treatment-zone budget enforcement | planned |
| G7 | Headless-Chrome render crash mid-batch | Per-comp isolation, one retry, then fail loudly naming the comp — never ship partial graphics silently | planned |
| G8 | Render cache staleness (template or tokens.css edited, spec unchanged) | Cache key = hash(spec + template content + tokens.css) — asset content, not just parameters | planned |
| G9 | Caption block straddles a layout boundary (band jumps mid-sentence) | Split the block at the boundary; captions never move mid-block | planned |
| G10 | split-critique asset shorter than its zone | Freeze last frame + warn; never stretch >1.25x, never loop silently | planned |
| G11 | PiP bubble / graphic occludes the exact screen region being discussed | Anchor override in plan + Audit B vision checklist item | planned |
| G12 | Livestream source already HAS a baked-in corner cam; PiP layout would double it | When source carries a corner cam, PiP = crop/promote the EXISTING cam region, never overlay a second copy | planned |
| G13 | List-item pop lands off its spoken word after speed change | Timing derives from triggerWords through the timeline map (never hand-set); audit spot-checks item-vs-word alignment | planned |
| G14 | Font not ready at headless capture start (blank/fallback text in render) | tokens.css embeds Inter as base64 (no network/disk race); audit frame check is the backstop | **handled** (MG-1 tokens design) |
| G15 | Cartoon/illustrated faces on screen content read as real faces (Haar) | faceBBoxNorm is ADVISORY on screen-share/mixed zones; zone STATE stays robust (fused with screen signal); operator override available | **handled** (documented, visual_state 2026-07-05) |
| G16 | Ambiguous footage (no face, low screen detail) has no honest visual state | Conservative talking-head default at LOW confidence = explicit operator-override signal, never a fake verdict | **handled** (visual_state) |
| G17 | ASR mis-transcriptions become entity triggers ("United Percent" = "100 percent") | High-recall by design; brain filters; corrections map fixes the caption side | reference |
| G18 | ffmpeg overlay of 12-bit yuva444p12le ProRes DIRECTLY over a lavfi `color=` source SILENTLY drops the foreground (blank bg, looks fully transparent) | Alpha VERIFICATION must extract RGBA PNG first, then composite PNG-over-color; production compositing over real video is unaffected (byte-identical proof) | **handled** (documented 2026-07-05 — would cost hours undebugged) |
| I9 | Portrait content baked inside a 16:9 container with REAL black pillars (operator's car .movs: 3840×2160 canvas, ~9:16 content) — geometry probes say landscape, the pixels say portrait; naive 4:5 card crops include the baked bars | Detect via column-luma probe (pillar columns ≈ 0); treat content rect, not container rect, as the source geometry (blurpad wings for 16:9 uses); glass-takeover demo hit this 2026-07-06 | **handled** (root cause FIXED 2026-07-06: cut_speed.decide_profile was rotation-blind — display_dims() now swaps canvas on ±90 display-matrix rotation; ingest_probe was already rotation-aware; shorts were unaffected only because portrait-4K content is exactly 9:16 so the center crop recovered it pixel-for-pixel) |
| G20 | RAW EMOJI in hyperframes markup DEADLOCKS the headless render — font-load hang, no error, no timeout (documented by the sibling video-editor project; we haven't hit it because no template uses emoji YET) | Never put emoji codepoints in comp markup; bake glyphs to trimmed PNGs via scripts/producer/captions/bake_emoji.py (vendored) and overlay as <img> | **handled preemptively** (2026-07-05) |
| G19 | Comp missing root data-duration attr renders at wrong length (JS fallback ≠ render length) | graphics_render seds the attr — should ERROR clearly when absent; add comp-lint rule | open (template-author-caught) |
| G21 | A hard zoom STEP (instant scale snap) that lands MID-SHOT — not on a cut — reads as a glitch/mechanical (the machine snapped ~84% of pushes, many into dead frames; MOTION_GRAMMAR_STUDY G6). A step is only legible when a cut hides it | `graphics_planner_zoom._apply_motion` emits a hard step only when a thesis beat falls within `punch_on_cut_eps_s` (0.35s) of a cut; farther in-shot it becomes an eased-attack PUSH (`attackS`: smoothstep 1.0→zoom then hold). Brackets keep their snap-in/hold/release; aliveness/boundary ramps always ease. `plan_lint_motion` validates `attackS` (0 < attackS ≤ window) | **handled** (2026-07-06, motion-grammar v2) |

## Loops / modes

| # | Case | Handling | Status |
|---|------|----------|--------|
| L1 | Feedback ping-pong | 2 auto-revision rounds, then human | planned |
| L2 | MCP unavailable (headless) | Degrade to library-only, say so | planned |
| L3 | Missing API keys (live mode) / HF credits exhausted | Feature-gated, clear errors, no silent degradation | planned |
| L4 | Skill vs live doctrine drift | Both read same config/prompts; golden-plan parity fixture | planned (Phase 4) |
