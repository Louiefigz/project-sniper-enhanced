# Quality-mining sweep — 2026-07-23

> Full-repo survey: what already exists in this repo (dormant modules, warn-only
> gates, unencoded ledger lessons, unharvested studies, operator run artifacts,
> frozen-program salvage, deferred items) that would improve OUTPUT QUALITY of
> the shipping PRODUCER product. 74-agent workflow (7 mining lenses, every
> candidate adversarially verified against code — refute-by-default), plus a
> completeness critic. **57 candidates confirmed, 9 refuted.** Every confirmed
> item cites file:line evidence in the workflow journal
> (`wf_0fa61ce6-870`); this doc is the curated ranking.

## The structural insight (the critic's #1)

Roughly 10 of the 57 confirmed items are one root defect: **a deterministic
detector exists, but promotion ignores it.** Flash, freeze, safe-zone, seam
drift, gap-filler zooms, safe-margin text, brollTrack frames — all detected,
all WARN-only, all shippable. The highest-leverage single move is a
**declarative gate-policy layer**: every detector declares blocking semantics
per lane/format plus an allow-vocabulary for declared intent (authored
transitions, montage bursts, screenshare holds, declared freezes). That closes
the class, resolves the conflicts below by construction, and makes future
detectors block-by-default instead of being born WARN-only.

## Tier 1 — the three programs to do first

1. **Unified gate-policy escalation bundle** (M) — the policy layer above,
   covering: Audit B WARN-escalation beyond `motion_pacing`, `detect_flash`
   off-transition FAIL, `detect_freeze` allow-list (its `allow` param is dead
   code today), YDIF stutter gate on the monolithic path, brollTrack frames
   into Audit B review stills, safe-margin ERROR at plan time, word-lock seam
   snapping (tested `snap_plan_seams` has zero production callers), LL-007
   gap-filler zooms. **Sequencing:** fix the lane-aware pacing false-WARNs
   (screenshare holds) BEFORE escalation, and make the flash gate burst-aware
   (see Conflicts) or it outlaws the measured montage grammar.
2. **The shrink-to-PIP program** (L; merges 3 candidates that hid its
   priority) — `pip_takeover.py` is a complete, operator-approved-for-longform
   renderer with zero call sites; the planner literally stamps *"gate-legal
   fallback while canvas-pip-list's PiP renderer is unwired"* into plans as it
   downgrades beats. Wiring it unlocks the face-bridge entrance ("the footage
   IS the transition") and the longform screenshare presenter-PIP chapter
   format MODULE_CARDS rates as governing ~42% of reference runtime.
   Interim S fix shipped separately: stop advertising `canvas-pip-list` in
   `card_form_map`/`intro_semantic_contract` (catalog/gate contradiction).
3. **Ship-integrity S-cluster** (all S) — properties every deliverable must
   have, none checked today: full-stream decode `-xerror` in Audit B (three
   full decodes already run; the error signal is discarded), audio streamhash
   proof across composite/mux (a silent lossy re-encode passes today),
   stale-SRT detection (proven in a shipped run: last cue at 108.6s in an
   81.4s video), and a burned-caption presence/band check (Audit B has ZERO
   caption checks).

## Tier 2 — S-effort quick wins (do alongside anything)

| Item | Why it stings |
|---|---|
| Demucs preflight | GUI "Isolate voice" + brain-authorable preset passes EVERY gate, then kills the render at stage 4.4 after the expensive stages ran (`demucs` not installed, not in requirements, not probed by `/setup`) |
| `brand_lint.py` never executes | The only brand-color enforcement in the pipeline has no caller; the 2026-07-18 audit proved an off-token hex ships end-to-end |
| `default-bed.mp3` fails the system's own hum gate | The bundled bed measures a 111 Hz line at 39.1 dB prominence, 100% stable — the delivery-hum detector's FAIL threshold is 14 dB. The only deterministic music choice ships a defect |
| SFX palette unreachable | Six lead-timed seam packs fully wired in `transitions.py`; no doctrine names the slot, so no plan ever uses them |
| QC_CHECKLIST staleness | `sync-checklist` was never run for LL-033; the stale list is pinned byte-for-byte into every run's critic evidence; no freshness test |
| Accent-contrast auditor silent-skip | When the rendered accent color doesn't match the request, the ONLY pixel-level gate for the LL-033 family emits no verdict at all |
| Punchlist #10 timeout split | Quality angle: visual authoring legitimately needs >45 min on longform; the shared bound forces a choice between starving visual quality and a 90-min wedged-cut leash |

## Tier 3 — encode the operator's own pain (from ~/ProjectSniper artifacts)

- **Alarm fatigue is live:** Audit B's accent-contrast check is mathematically
  incapable of passing the house stroked-lemon type, so every punch short
  exits FAIL and the operator has learned to ship over red. Merge with the
  silent-skip + scene-derived-measurement candidates into ONE accent overhaul
  (see Conflicts) — do not just relax it.
- **LL-028 is not actually closed:** two shipped social-polished finals kept
  an audible abandoned "And number six is..." after the gate, the cut wall,
  and two reviews. Needs a stronger abandoned-sentence detector.
- **Denoiser choice is guessed:** the operator hand-A/B'd voice vs voice-rnn
  (+5.63 dB SNR delta); encode a measured per-source chooser.
- **Frame-0 formed-arrival proof** for own-screen graphics entering on a cut
  (LL-002's lint ceiling sits above the measured blank window).
- **LL-009 verbatim-redundant cards:** a repo test PINS the gate passing the
  exact card the operator flagged — add the arithmetic overlap WARN + critic
  line.
- **LESSON-022 hook-zone captions:** every produced short burns caption cues
  under the hook lockup in the first ~3s — suppression covers own-screen
  graphics only. (Merged duplicate of the study-lens finding.)

## Tier 4 — larger capability programs (sequenced later)

- Face tracking for shorts reframe (`reframe.track` reserved; face can drift
  25% of frame width before any guard fires; merged with tracker-v2)
- Caption identity port (2–3 of the 36 vendored DNA identities as burned
  styles; shipping system has four hardcoded looks)
- LESSON-019 longform music-as-segment-architecture (plan vocabulary +
  multi-bed `music_stage`)
- Typed mechanical patches (RepairIntentV1 primitive only — port from the
  frozen dossier, not the program)
- Seeded-defect + blinded critic calibration pack (three ledger defects
  passed the full critic wall; calibrate the wall)
- Per-pixel silhouette safe zones for placement (gesturing hands)
- Screenshare readability gate at ingest (<~18px glyph FAIL — the one class
  nothing downstream can repair, per doctrine "never ken-burns")
- Still-image b-roll on colored card (PACING G1; insert-stage image branch
  missing), body flash/montage burst grammar, final-third card taper,
  loudness-coupled entrance intensity, tool-identity receipts for the
  ffmpeg bus (LL-017 class), Palmier stored-media byte readback (LL-018
  class), LESSON-013 credit labels, LESSON-023 emphasis budget, LESSON-025
  b-roll latency band, LESSON-016 entrance causality (config has zero
  readers), LESSON-018 SFX beat-class honesty, LL-033 bare-accent lint.

## Areas the lenses missed (completeness critic — verified gaps)

1. **Clipper + segmenter have ZERO QC** — no loudness re-measure, decode
   check, or drift audit on clipper's master/FCPXML; none of producer's cut
   machinery (retake_scan, LL-028, transcript contracts) runs there.
2. **ASR word confidence is captured then discarded** — no low-confidence
   caption-word proposer before burn (cheap, deterministic).
3. **Two critic briefs drift independently** — `sync-checklist` regenerates
   QC_CHECKLIST only; SKILL step-7.5 reviewer checklist + TS review prompts
   encode no ledger IDs and have no single source of truth.
4. **FRAME.IO findings dead-end** — no consumer turns `results.json` into a
   revision set or ledger rows (also: paid-API vision vs $0 doctrine).
5. **No golden-render regression for the 46-comp catalog** — a tokens.css
   edit can silently restyle all 46.
6. **Duck depth / with-music LUFS are warning-only at mix time** and never
   re-measured by Audit B across the body.

## Conflicts requiring one adjudication each (do not ship halves)

- Flash FAIL vs body-montage grammar → one burst-and-transition-aware gate.
- WARN escalation vs lane-aware pacing → fix false WARNs first.
- Accent-contrast relax vs tighten vs re-measure → one merged overhaul.

## Refuted (already covered — do not re-mine)

On-screen-text QC already in the approval chains; transcripts_dir already
wired in GUI/Palmier lint routes; dated-timeline form + form-shape semantic
extensions landed 2026-07-15; emphasis-scarcity already guarded;
pause-threshold tightening (no visible delta on the operator's actual edits);
Palmier reclaim ceremony + inspect_timeline image blocks (structural,
adjudicated elsewhere); exact hold-duration cataloging (diminishing returns).

## Provenance

Workflow `wf_0fa61ce6-870` (74 agents, 7 lenses, adversarial verify pass,
completeness critic), 2026-07-23. Full per-candidate evidence with file:line
in the workflow journal. Lens counts (confirmed/refuted): dormant 7/1,
warn-only 10/0, lessons 10/0, studies 9/3, operator 6/1, salvage 8/1,
deferred 7/3.
