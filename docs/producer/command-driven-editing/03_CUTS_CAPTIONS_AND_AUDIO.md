# Cut repair, captions, and audio

> **Status:** Proposed target architecture.
>
> [Previous: authority and commands](02_AUTHORITY_COMMANDS_AND_TIMING.md) ·
> [Back to the plan index](../COMMAND_DRIVEN_EDITING_EXECUTION_PLAN.md) ·
> [Next: motion, assets, and references](04_MOTION_ASSETS_AND_REFERENCES.md)

## Word-safe local repair

`cut.restoreSpeech` uses deterministic resolution and validation, not a general
model rewrite. Code enumerates mechanically valid candidates; a different take
requires operator or governed-reviewer selection.

Procedure:

1. Resolve the quoted phrase using stable word IDs, approximate time,
   occurrence, speaker, and surrounding words.
2. Stop on unresolved ambiguity.
3. Inspect source handles, waveform, pinned alignment evidence, seam, adjacent
   words, room tone, and current cut segment.
4. Try the least disruptive valid repair:
   - move the seam while preserving duration;
   - use an L/J cut while picture stays locked;
   - extend the local clip and reclaim equal silence inside a bounded window;
   - use the same utterance from an equivalent local handle.
5. If only a different take works, present duration-neutral candidates and
   source/semantic provenance for explicit selection.
6. Never synthesize, voice-clone, or substitute semantically different speech.
7. If no valid local solution exists, return `NON_RIPPLE_IMPOSSIBLE` and an
   exact ripple-impact proposal.
8. Render a padded local preview.
9. Run a pinned aligner, waveform/VAD, and re-transcription. These provide
   bounded evidence, not sole proof of human audibility.
10. Check duplicates, gaps, clicks, plosives, room-tone discontinuity, lip
    sync, frame cadence, and captions.
11. Promote only after preservation checks pass.

Before picture lock, an approved ripple reopens cut review. After picture lock,
non-ripple is the default and ripple is never silent.

Non-ripple requirements:

- identical total output frames;
- identical output mapping outside the dirty window;
- unchanged scene/media timing and hashes outside the dependency closure;
- unchanged music/caption state outside overlapping dependents;
- unchanged Palmier inventory outside bound affected elements.

Picture-seam repair is duration-neutral in whole delivery frames. Exact speech
handles remain integer source samples and may cross a picture boundary as an
audio-only L/J overlap. Quantization residuals may use only receipt-bound
crossfade/room-tone samples; they cannot consume adjacent speech or an onset.
If complete-word preservation is impossible under those constraints, stop with
`NON_RIPPLE_IMPOSSIBLE`.

### Implemented private rendered-plan boundary

The controller now separates three structured modes:

- `analyze` resolves the phrase and enumerates candidates without mutation;
- `prepare` builds diagnostic splice evidence, renders the exact proposed plan
  through the current full renderer, and durably stores the private candidate
  without advancing selected authority;
- `execute` can promote only a separately staged and fully evidenced
  `CUT_REVIEW`; it cannot create that review.

The first-class route keeps analysis, preparation, review, approval, and
execution separate. The released preparation vocabulary is bounded; an
operation must carry exact source/project sample ranges and a canonical speed
rational, preserve picture mapping outside its dirty closure, and recompile
explicit caption/dialogue authority. Existing same-target or overlapping
leads fail closed, while a later disjoint repair inherits the prior
DialogueTrack/DialogueMap as its exact parent and appends only its own handle.

Preparation renders and decodes the dirty diagnostic fragment/composite, then
renders the exact proposed plan into a separate private artifact directory.
The durable package binds the exact plan-object hash and semantic plan digest
to the staged render graph, execution receipt, candidate pointer, and final
candidate bytes. It also publishes a strict rendered-plan candidate descriptor
that the existing cross-runtime promotion-evidence gate can consume; QC
receipts therefore bind the full-plan `.mp4`, not the diagnostic splice.
Deleted private media is restored by hash before those bindings are
revalidated. The result is
`status:"rendered-plan-candidate-prepared"`, not approval: the head remains
`PICTURE_LOCKED`, `CUT_REVIEW` is not staged, the prior graph remains active,
and project `final.mp4` is not replaced. A separate review transition stages
that exact candidate; approval then seals operator selection and automated QC,
and execution accepts only the resulting package. Plan/media equivalence is
therefore closed for the candidate the operator actually reviews. Caption and
chapter timing outside the new dialogue handle remains exact. A legacy J-cut
that predates dialogue-caption authority is not upgraded by inference.

The first four now have a candidate-bound automated-QC controller, but that
does not remove the package blockers by assertion. The controller reopens the
preparation package plus full-plan descriptor, hashes the candidate again,
extracts only the dirty frames plus one-second handles (hard maximum 30
seconds), and pins every FFmpeg/Whisper/model byte in a sealed tool manifest.
It runs CPU-only Whisper for re-transcription, deterministic program-waveform
gap/click/duplicate/room-tone checks, and a separately pinned repository
source-waveform adapter. The tool manifest binds the Python runtime, adapter,
closed policy, and their exact hashes. A passing audio-only run publishes four
immutable lane items in the shape consumed by the promotion-evidence
validator, content-addresses one `CutRepairAutomatedQcBundleV1`, and binds that
bundle once to the preparation hash. TypeScript can run or reopen that exact
bundle. It never manufactures operator approval.

The independent adapter reports transcript-bound source-waveform presence and
explicitly labels that result **not audibility proof**. It is separate from
Whisper, rejects ambiguous matches, and normalizes admitted 44.1 kHz source
spans onto the 48 kHz project clock. The VAD lane remains a bounded
**program-waveform envelope**, not isolated-dialogue semantic VAD.
Picture-changing repairs return `LIP_SYNC_ORACLE_UNAVAILABLE`, and the present
waveform seam lane does not claim an independent plosive classifier. Eligible
audio-only repairs can close all four automated lanes; operator audition,
review staging, package sealing, and activation still require their distinct
authorities before promotion.

An explicit first-class caption track no longer blocks this narrow preparation
route when its exact dialogue authority can be derived from the current
caption/source projection. The deterministic `DialogueMapV1`-aware compiler
owns J pre-roll, primary, and L-tail word placement plus correction-token
partitions. Sequential disjoint J-cuts retain the prior child authority as
their exact parent. Cut-repair review, program-audio promotion, and final
activation remain separate blocked gates. An existing J-cut with no prior
dialogue-caption authority fails with
`CAPTION_DIALOGUE_EXISTING_JCUT_AUTHORITY_REQUIRED`.

Restoring already-known words can stay local. Changing transcript content or
word identity also recomputes claims, chapters, beats, scene/b-roll triggers,
on-screen copy, captions, and reference-style events. Equal duration does not
make a semantic change local.

## General L/J-cut support

The exact media-independent substrate now exists as closed
`DialogueTrackV1`/`DialogueMapV1` contracts in TypeScript and Python. It owns
integer source/output sample ranges, rational requested/effective speed,
primary plus J/L handle topology, exact terminal `B(F)` samples, and shared
44.1→48 kHz `P(sourceSample)` boundaries. A retained cross-language golden
proves J-cut, primary, and L-cut seams with a `5/4` retime. A private exact
dialogue-stem renderer now source-proofs, normalizes once, applies
pitch-preserving rational retime, mixes exact J/L sample ranges, reconciles
only bounded tails, and publishes an immutable self-hashed receipt. The
dialogue-aware caption mapper is also implemented.

An explicit opt-in program-audio controller now consumes that exact dialogue
stem. Its closed request binds the track/map file bytes and content hashes,
the complete dialogue source snapshot set, exact expected counts for
room-tone/music/SFX stems, and pinned FFmpeg/ffprobe bytes. Auxiliary inputs
must already be full-program mono/stereo PCM `s32` at the project sample rate
and exactly `B(F)` samples. The controller duplicates the mono dialogue into
stereo, linearly sums every declared auxiliary without normalization, proves
the exact stereo output clock, and publishes a create-once read-only
generation with a self-hashed receipt and strict render graph. Missing,
extra, stale, short, incorrectly formatted, or reordered authority fails
before program publication.

This is private infrastructure, not a release flip. The only production
boundary is `audio/dialogue_program_cli.py` with
`kind:"exact-dialogue-program-render"`; its receipt is explicitly
`admissionStatus:"private-unpromoted"`. Incremental mode may reuse a sealed
dialogue-stem generation while rebuilding the program mix. Forced-full mode
requires a fresh dialogue generation. A retained real-media test changes only
the music authority, proves the program bytes change, then proves the
incremental and forced-full dialogue/program hashes are byte-identical for the
same inputs while room tone, music, and SFX remain graph dependencies and
receipt proofs.

Legacy `audioLeadMs` remains intentionally rejected by first-class dialogue
authority. The legacy/default renderer, cut-repair preparation and promotion,
final video mux, selected authority, and Palmier are not activated by this
controller. It also does not yet cache or splice a bounded dirty region of an
existing program stem; incremental reuse is currently at the dialogue-stem
boundary. The retained equivalence fixture is six seconds, not a 10–14-minute
runtime or performance qualification.

The target needs:

- exact source-frame/sample handles;
- schema and lint support;
- released plan adapter plus governed final-video/promotion integration;
- source-handle proof;
- Palmier adapter projection;
- parity fixtures at every released rational FPS, including normalized VFR.

An audio-only handle is bounded to a visually covered interval. If it creates
visible lip-sync drift, use a picture repair or stop.

## Alignment evidence

Pin the aligner runtime, model, cache format, and provenance. A repair preview
uses:

- forced alignment;
- waveform/VAD;
- re-transcription;
- deterministic duplicate/gap checks;
- operator audition when evidence is uncertain.

The system reports acoustic/transcript evidence. It does not claim that forced
alignment independently proves audibility.

## First-class caption track

Replace the current global/ghost split with one transcript-derived track:

```ts
interface CaptionTrackV1 {
  schemaVersion: 1;
  source: "kept-transcript";
  defaultPolicy: "off" | "line" | "karaoke";
  groups: Array<{
    groupId: string;
    anchor: TimingAnchorV1;
    styleId: string;
    mode: "line" | "karaoke-word" | "karaoke-phrase";
    placement: string;
    language?: string;
    suppressUnderSceneIds?: string[];
  }>;
  transcriptCorrectionHash?: string;
}
```

Rules:

- Caption words come from stable transcript IDs plus a display-correction
  ledger, never model-written replacement prose.
- Display correction preserves audio identity/timing.
- Caption correction reasons, chapter titles, and display-token limits count
  Unicode code points in both runtimes, not TypeScript UTF-16 code units.
  Five hundred emoji therefore pass a 500-character field and 501 fail.
  Blank/edge trimming uses one explicit shared whitespace set, including
  U+0085 and U+FEFF, so TypeScript and Python cannot accept different caption
  authority bytes.
- Karaoke/style changes may target arbitrary groups or ranges.
- Suppression and cue splitting happen at word boundaries.
- Caption shards remain separate alpha assets until finalization.
- Shard boundaries use stable groups and bounded durations.
- The global correction hash remains authority, but content and placement use
  separate fingerprints:
  - `captionContentDigest` binds word IDs, relevant display-correction rows,
    style/font/text-shaping inputs, language, and compiler/toolchain;
  - `captionCueFingerprint` binds the content digest, resolved cue frame/sample
    ranges, relevant full or sliced `timelineMapHash`, exact project FPS,
    word-timing digest, segment speed/version, destination/safe-zone placement,
    and caption compiler/toolchain.
- A placement-only change may reuse a proved content texture when shaping is
  unchanged, but it must regenerate/revalidate the cue/placement node.
- A cut, ripple, or speed change invalidates every caption cue/placement node
  whose resolved frame/sample range or relevant map-slice digest changes,
  including downstream cues shifted by a duration-changing speed edit, even
  when word IDs and displayed text are unchanged.
- SRT, burned captions, and Palmier assets use one compiler.
- Use native Palmier captions only when word timing, style, and readback fidelity
  are proved; otherwise use regenerable alpha clips.
- Scene suppression invalidates only overlapping shards.

Required migration:

- remove captions from every reusable picture-base path;
- migrate current master/assemble and short-form gates;
- update fingerprints, authority hashes, and Audit B;
- adapt legacy global `captions` plans;
- wire word-boundary scene suppression;
- keep SRT, burned, and Palmier outputs on one cue compiler.

The explicit `CaptionTrackV1` path now passes those gates. It materializes
bounded RGBA alpha clips, consumes them after the caption-free picture
composite, binds the same cue generation into SRT and regenerable Palmier
assets, and retains short/long dirty-versus-forced-full traces. Plans without
`captionsTrack` continue through the legacy adapter; they cannot satisfy a
first-class range-caption claim.

## Caption edge policies

- Tiny scene overlap suppresses only overlapping words, not a whole long cue.
- One-to-many spelling changes bind source word IDs to display tokens through a
  deterministic timing policy.
- Repeated names/homophones use stable IDs, never global replacement.
- Punctuation-only correction preserves word timing.
- Cut/ripple/speed changes recompile every caption group whose resolved
  frame/sample range or relevant map-slice digest changes, including shifted
  downstream groups.
- Very fast speech groups phrases or discloses unreadability.
- Multiple speakers use speaker-aware grouping and collision rules.
- RTL/CJK/emoji/URLs require local glyph closure and actual rendered
  shaped-bounds measurement; an unavailable glyph fails closed instead of
  silently using a LastResort box.
- Profanity display and audio masking are separate policies.
- First/last visible frames are tested at the actual project timebase.

## Audio and music architecture

Keep immutable dialogue, room-tone, transition/SFX, and music stems separate
during iteration.

Audio topology is ordered:

```text
source dialogue probe
  → channel inspection/dead-channel repair/declared normalization
  → normalized dialogue/room-tone stems ┐
independent music/SFX asset nodes ───────┴→ ducking/program mix
                                          → program mastering
```

Every program node that reads or mixes source dialogue/audio depends on the
normalized stem. Independent music/SFX decode or generation need not wait for
it, but raw pre-normalized dialogue can never enter a transition mix, ducking
stage, program mix, or mastering path.

Audio cue anchors may be:

- output-frame/sample locked;
- transcript/content locked;
- section locked;
- music-beat locked;
- source-time locked.

Music is section-based rather than one global bed: asset, in/out, loop policy,
fades, automation, duck policy, and beat anchor.

Fade operations carry `overflowPolicy: "reject" | "clamp"`. Rejection is the
default. An explicit clamp stores its resolved frame/sample duration in the
receipt for idempotent replay.

Local audio previews rebuild only the affected mix closure. Final LUFS and
true-peak mastering are program-wide. Picture-neutral audio edits use video
stream copy.

Verify:

- no click, dropout, clipped onset, duplicated syllable, phase error, or
  room-tone jump;
- dialogue/music separation and duck depth;
- transition/SFX sync;
- final integrated loudness and true peak;
- no picture rebuild for eligible music-only changes.

Duration authority is never the media container's or AAC decoder's reported
duration:

- video authority is the compiled delivery-frame range at exact rational FPS;
- audio authority is the compiled/pre-AAC PCM sample range at project sample
  rate;
- decoded final frames/samples and container duration are QC observations only;
- multi-segment AAC assembly must prove encoder padding does not accumulate at
  every seam;
- the final mux/clamp uses the declared authoritative frame/sample clocks and
  records any permitted terminal reconciliation.

Exact rational FPS numerator/denominator travels unchanged through compilation,
fingerprints, ffmpeg arguments, receipts, and QC.

Preservation is exact at immutable pre-master stem/segment nodes. A declared
program-wide mastering change may alter final PCM elsewhere; compare that final
under frozen mastering tolerances, not an impossible byte-identical promise.
