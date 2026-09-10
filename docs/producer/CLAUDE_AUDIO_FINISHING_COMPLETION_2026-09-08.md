# Source-float-v2 audio finishing: completion note (Claude Code, 2026-09-08)

Scope: the parallel audio-finishing assignment in
`CLAUDE_AUDIO_PARALLEL_HANDOFF_2026-09-08.md`. This note is scoped to audio. It does not mark
Project Sniper complete, does not infer the two-hour editor target from short fixtures, and its
synthetic/TTS measurements are not creator listening approval. Coordination report with
manifests and patch paths: `/private/tmp/sniper-claude-audio-handoff.md`.

## What now works on the source-float-v2 path

A plan may carry `audioEnhance` (catalog ffmpeg presets `voice`, `voice-strong`, `voice-rnn`),
`audioGain` windows and `transitions[].sfx` (engine whoosh or a built pack item). They are applied
at program-master time on the retained float dialogue bus, in this order, all pcm_f32le at the exact
bus clock: cleanup -> measured-latency removal -> gain windows -> SFX sum -> music bed ducked by the
finished dialogue (without SFX) -> the single whole-program master -> one AAC delivery. Opening and
body audio remain bit-exact excerpts of that finished program.

## Ownership map

- Pure contract: `scripts/producer/audio/program_finish_contract.py` (validation, `finishing_free_plan`,
  canonical settings). Execution: `scripts/producer/audio/program_finish_bus.py`. Reuse:
  `scripts/producer/audio/program_master_reuse.py`.
- Connected existing owners: `program_mix_bus` (finishing before the bed; detector keyed on the
  finished dialogue), `program_master_bus` (receipt `finishing`, input hash, verification),
  `program_master_cache` (strict read), `render_audio_authority` (v2 validates, v1 still refuses),
  `assemble_source_audio` (v2 lineage seal, master reuse), `assemble_picture_reuse`
  (finishing-invariant picture key).
- Integration hunks (Codex reconciles): `render.py` (skip legacy enhance/gain stages and strip stage
  SFX once source-float audio is admitted; pass the policy to the render seal), `assemble.py`
  (`_finishing_invariant_current`), `cut_delivery_authority.py` (`base_plan_lineage_digest`,
  policy-aware seals, verify accepts a v2 finishing-free lineage), `guided_opening_frames.py` and
  `guided_presenter_profile.py` (audioEnhance/audioGain no longer "unqualified lanes"; the presenter
  profile validates them explicitly with `finishing_reason` so malformed values still reject),
  `scripts/producer/CLAUDE.md` (module map), the mix-registry contract data
  (`program-audio-mix-registry-v1.json`, one new owned program consumer + dependency).

## Behaviour guarantees and their tests

| guarantee | test |
|---|---|
| invalid / unavailable / unsupported finishing is refused before any media work | `test_program_finish_contract.py`, `test_program_finish_media.py::test_08`, `test_assemble_finishing_media.py::test_05` |
| cleanup delay measured per installed chain; clicks stay on exact samples; the program tail is the processed source, not padding (Codex-confirmed defect, fixed) | `test_program_finish_media.py::test_01`, `::test_01b`, `::test_01c` |
| +6 dB window lands on the edited-time interval after a middle source passage was cut, ramped edges, audio outside untouched | `test_program_finish_media.py::test_02` |
| SFX summed after cleanup at exact start samples; dialogue stem carries none | `test_program_finish_media.py::test_03` |
| finished + music premaster is the exact float sum; whole-program master qualified against the unchanged -14 LUFS / -1.5 dBTP thresholds; duck detector keyed on finished dialogue | `test_program_finish_media.py::test_04` |
| no finishing requested: pristine bus, null `finishing` (disabled treatments stay off) | `test_program_finish_media.py::test_05` |
| changed settings / assets / relabelled receipts reject | `test_program_finish_media.py::test_06`, `::test_09` |
| opening excerpt is a bit-exact slice of the finished master | `test_program_finish_media.py::test_07`, `test_assemble_finishing_media.py::test_06` |
| real callers: render.py base admits finishing and skips legacy stages; assemble delivers the finished program on identical picture packets | `test_assemble_finishing_media.py::test_01`, `::test_02` |
| finishing revision keeps base and raw bus, preserves picture packets, rebuilds only the master | `test_assemble_finishing_media.py::test_03` |
| held-graph master reuse: forced-full reassembly reuses the finished master; foreign or resealed pointers are declined and rebuilt; cancellation propagates before any rebuild | `test_current_render_graph_audio_media.py::test_03c`, `::test_03d`, `test_program_master_reuse.py` |
| graph-backed finishing revision: picture and raw dialogue reused, master rebuilt | `test_current_render_graph_audio_media.py::test_03b` |
| without a held graph the pointer is never authority (declined, rebuilt) | `test_assemble_finishing_media.py::test_04` |
| standalone render never silently omits finishing (v2 monolithic refused, v1 refused, legacy applies, base reports deferred) | `test_assemble_finishing_media.py::test_07` |
| failed master / delivery / audit keep the last accepted final | existing `test_program_master_bus_media.py`, `test_assemble_source_audio_media.py` (unchanged, green) |

## Supported / unsupported

- Supported: `voice`, `voice-strong`, `voice-rnn` (vendored RNNoise model, bytes bound in the receipt);
  gain windows within +-12 dB, non-overlapping, inside the program; `sfx: true` and the six built
  pack items; music with ducking as before.
- Refused explicitly: `separate` (Demucs runtime and downloaded weights); unknown presets; unbuilt
  or unknown SFX names; malformed windows; `music.duck=false` with dialogue (unchanged rule).
- Unchanged by design: source-float-v1 and legacy-v1 behaviour; loudness/peak thresholds;
  MASTERING_POLICY_VERSION 3 and AUDIO_MIX_POLICY_VERSION 2; the legacy `audio_enhance.py` stage
  (its own uncompensated 25 ms delay is reported separately, not fixed here).

## Measured facts worth keeping

- FFmpeg 8.0 cleanup delay: afftdn chains 1200 samples, arnndn 480. Neither flushes its delayed tail
  at end of input; the chain input must be padded by the delay (plus a guard) or the final samples
  become silence. See `docs/findings` candidate below.
- Real-speech evidence (macOS TTS + pink noise + hum, cut with a removed middle passage): pause noise
  floor about 3.5 dB lower with `voice`; +6 dB window realised as +4 dB after whole-program
  re-mastering; measured duck depth 12 to 14.5 dB; every variant lands at -14.0 to -14.2 LUFS and
  -2.0 dBTP. Retained: `/private/tmp/claude-501/-Users-aaronfigueroa-development-demos-YT-Automation/64e4085b-2c1b-4250-80e2-e5195e41b946/scratchpad/evidence/listenable/` (README.md, evidence.json, WAV + MP4).

## Remaining integration steps (Codex)

1. Reconcile the owned patch and the integration patch against the live tree; the live refusal for
   v2 finishing stays until this evidence is accepted.
2. Decide whether `transitions` (visual seam covers) become qualified in the guided opening/body
   profiles; SFX finishing is ready whenever they are.
3. Optional follow-up outside this package: the render graph's `base.plan` / `timeline.plan`
   digests (`current_render_graph_nodes.py`) still use the full graphics-free plan digest, so in the
   graph flow a finishing-only edit marks node-base dirty (a wasteful but correct base rebuild); using
   `base_plan_lineage_digest(plan, policy)` there would keep node-base clean on v2.
4. Creator listening on real footage; nothing here is perceptual approval.
