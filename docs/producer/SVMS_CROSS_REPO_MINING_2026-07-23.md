# Cross-repo mine: super-video-maker-skill → PROJECT_SNIPER — 2026-07-23

> Source: `https://github.com/Bomx/super-video-maker-skill` ("SVMS"), analyzed
> read-only as untrusted content (cloned to scratchpad, never into this repo,
> nothing executed). 51-agent workflow (`wf_5b5fc8e1-5c0`): 7 comparative
> lenses, every candidate adversarially verified against Sniper's actual code
> and doctrine. **38 candidates confirmed, 5 refuted — collapsing after
> dedup to ~12 real builds.** Companion to
> `QUALITY_MINING_REPORT_2026-07-23.md` (the in-repo 57-gap report); GOLD
> below = closes a gap that report already proved.

## The one-sentence takeaway

**Sniper's QC wall audits the plan; SVMS audits the delivered file.** ~80% of
what survived verification is render-side QC — checks pointed at `final.mp4`
itself. Importing that habit closes several defect classes that have already
shipped past Sniper's wall (LL-002, LL-010, LL-017, LL-028 ×2, stale SRT).
Everywhere else — determinism boundary, independent critics, failure ledger,
hash-bound resume, word-level cuts, face-aware reframe, reference studies —
Sniper is far ahead and nothing in SVMS displaces any of it. SVMS's own core
production lanes (HeyGen/Seedance/Replicate paid generation) violate Sniper's
$0/no-egress doctrine and its own ROI doc rules that lane a NO-GO.

## Top 5 by quality-per-effort (critic-ranked, post-dedup)

1. **"Audit B sees what ships" stills upgrade (S)** — one
   `plan_frames`/`audit_frames` extension merging THREE 4-5-way duplicate
   clusters: dense entrance-window sampling (frame-0 formed-arrival proof,
   LL-002 class), brollTrack windows into review stills (the only composited
   visual lane with zero stills today — LL-010/LL-017 were operator-caught),
   and zone-guide overlays (safe box / caption band / hook zone / PiP hole
   drawn onto copies of the stills) so both paid critic rounds read evidence
   instead of guessing geometry.
2. **Burned-caption presence/band check in Audit B (S)** — keyed to actual
   ASS cue windows (parse the persisted final ASS, sample in-cue,
   white-fraction/differential metric — the naive edge-density version is
   miscalibrated over live footage and would be dead code). Audit B has zero
   checks on the most-watched layer of the deliverable; `render.py:519-528`
   already declares a caption-less short a doctrine violation.
3. **Final-render re-ASR conformance gate (M)** — ONE local-whisper pass over
   the shipped master with THREE consumers: stale-SRT/cut-drift detection
   (proven shipped: cue at 108.6s in an 81.4s video), abandoned-sentence
   catch (LL-028 shipped twice past the wall), and named-term ASR-survival →
   `caption_corrections` proposals. Generalizes to clipper/segmenter's
   zero-QC hole. The first gate that ever *listens to* what shipped. Do NOT
   build three whisper passes.
4. **Hook-zone caption suppression (S)** — `captions_in_hook=False` exists in
   config with zero readers; `suppress_captions` mechanism exists for
   own-screen graphics. Wire it for hook lockups/titleCards: affects the
   first 3 seconds of every produced short (LESSON-022, currently violated by
   every short).
5. **Windowed duck-depth + with-music LUFS re-measure on the final mux (S)** —
   pure measurement of the already-rendered file; closes the "duck depth is
   warning-only at mix time and never re-measured" gap (LL-018 class).

Near-misses (both S, both doc/config-only): SFX event-class doctrine (unlocks
the six already-built seam packs + gives `entrance_causality` config its first
reader), and catalog-vs-gate coherence validation in selftest (the
`canvas-pip-list` contradiction class, generalized).

## Remaining confirmed builds (merged)

- **Golden-render regression for the 46-comp catalog (M)** — probe-still +
  pHash fingerprints; a tokens.css edit can currently restyle all 46 silently.
- **Declared capability requirements + plan-time preflight (S)** — the demucs
  trap killer, generalized: presets/lanes declare deps; lint fails early.
- **Verbatim-redundant card WARN (S)** — LL-009's mute/blind test as
  arithmetic token-overlap (route through the gate-policy layer).
- **Three-band music grammar for LESSON-019 (M/L — adjudicate effort)** —
  plan vocabulary + multi-bed `music_stage`.
- **Bed conditioning at prep (S)** — dynamics flatten + speech-band EQ carve +
  hum preflight; adjudicate against simply replacing `default-bed.mp3` (ship
  one fix, not both halves).
- **Still-image b-roll insert branch (S)** — GOLD, closes PACING G1: still →
  timed video window with colored-card/blur-pad fit.
- **Interaction-events sidecar + local scripted browser receipt recorder
  (M+M)** — click/scroll events JSON → screenshare gazeXY/eased zoom targets;
  feeds the Tier-1 screenshare-PIP program. Local, $0, no egress.
- **Fifth caption identity: boxed/pill active-word highlight (M)** — fold into
  the existing Tier-4 caption-identity port as one program, one source list.
- **Doctrine ports (S, docs only)** — hook micro-lints (one-number-per-line,
  time-to-first-spoken-word), b-roll repetition budget (same asset must show a
  different detail), sourced-receipt honesty rules from REVIEW_VIDEO_PLAYBOOK
  → receipts-lane critic doctrine, anti-AI image-prompt SOP for pool stills.

## Hard rules from the conflict analysis

1. **Every new detector lands inside the gate-policy layer** (the 57-gap
   report's #1 structural fix) with declared blocking semantics + allow
   vocabulary. Born-WARN standalone detectors recreate the root disease the
   report diagnosed — four SVMS candidates were framed that way; do not ship
   them that way.
2. **Blank-screen detector needs the flash/montage allow-vocabulary** —
   white-heavy comps (`color-wash`, `whiteboard-*`) will false-positive;
   adjudicate together with the `detect_flash` escalation, not separately.
3. **Speech-rate/pacing gates sequence AFTER the lane-aware pacing false-WARN
   fix** — otherwise more alarm fatigue on screenshare holds.
4. **One re-ASR pass, one caption-identity program, one bed fix** — the
   duplicate clusters are merged above; don't double-track them against the
   57-gap report rows they close.

## Refuted / correctly skipped

Refuted (5): render-vs-reference change-parity audit; WARN-adjudication
tri-state promotion (×2 — conflicts with existing promotion contract); velocity
blur on seam moves; SFX riser/hit kit extension (LESSON-018 honesty gate must
land first). Skipped with reason: the entire paid-generation lane
(HeyGen/Seedance/Replicate/ugc, ~2,300 LOC) — $0/no-egress doctrine, and
SVMS's own ROI doc calls it NO-GO; Remotion as a render substrate (assemble.py
chain is a doctrine invariant); `SPOKEN_VO_HUMANIZER.md` (belongs to the
rag-system scriptwriting domain, not Sniper — flagged as a lead there).
Genuine small misses caught by the critic and folded in above: the
laptop-bezel/gradient-canvas presentation anatomy from
`demo_video_composer.py`, and the sourced-receipt montage guardrails.

## Provenance

Workflow `wf_5b5fc8e1-5c0`, 2026-07-23: lens counts (confirmed/refuted)
qc-tools 8/2, captions 4/0, motion-graphics 6/1, craft-playbooks 8/0,
audio-music 4/1, orchestration 4/1, generative-broll 4/0. Per-candidate
file:line evidence (both repos) in the workflow journal. SVMS clone lives in
session scratchpad only.
