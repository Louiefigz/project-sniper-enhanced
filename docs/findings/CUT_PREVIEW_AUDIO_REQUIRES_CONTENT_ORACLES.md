# A correct duration is not proof of correct cut audio

2026-09-06. Scope: deterministic synthetic 160×90 H.264/yuv420p footage,
30000/1001 fps, stereo 48 kHz AAC, FFmpeg 8.0_1. These are engineering
fixtures, not creative-quality or deployed ingest-admission qualification.

The private guided-cut preview initially reused the current cut renderer's
AAC-concatenated mezzanine. A three-part, 105-frame fixture produced:

- Video clock: 168,168 audio samples (3.5035 seconds).
- MP4 presented audio: 169,192 samples.
- Fully decoded PCM: 172,032 samples.

Counting AAC packets or tolerating the extra samples would mislabel interior
priming/presentation effects as harmless trailing padding. An experimental
`aresample=48000:async=1:first_pts=0,apad,atrim=end_sample=...` audio-only remux
passed duration, padding and full/proxy equality, but an independent source
impulse still moved by **8.830742 ms**. That path was rejected and removed.

## The second defect: tempo processing at identity speed

The next test retained source-derived float samples until one final AAC
encode. It reused the canonical first-part audio filter, including:

```text
[0:a]aformat=channel_layouts=stereo,
atrim=start=0:end=0.9,asetpts=PTS-STARTPTS,
atempo=1.0,aresample=48000,
aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,
afade=... [own]
```

The first source energy centroid was 0.209962663817 seconds
(sample coordinate 10078.207863); the preview centroid was
0.197427326610 seconds (9476.511677): **601.696186 samples / 12.535337 ms early**.
Removing only the mathematically identity `atempo=1.0` from private preview
own/lead filters makes the independent interior/J-cut/end-content test pass.
This is not a license to remove tempo filters at nonidentity speeds.

## Implemented private-preview policy

`cut_preview_audio.py` reuses admitted-source channel authority and canonical
trim/J-cut filters, skips unity tempo processing, writes float32 stereo parts,
and derives each sample window from accumulated executed video frame counts.
It concatenates float bytes losslessly and encodes AAC once, while copying
the exact encoded picture stream. The preview receipt binds the audio-clock
artifact, media bytes, strict full decode, presentation samples and AAC padding.
Raw cut concat and work parts remain private for diagnosis.

A further packet-level check found the copied concat picture began at PTS
630 in a 1/30000 timebase (**21 ms**), while source-derived audio began at zero.
The private remux now admits an origin adjustment only within one declared
video frame. It verifies actual output start PTS is exactly zero and hashes
every ordered packet's relative PTS, DTS, duration, size and compressed payload
before/after. Any decimal timestamp rounding, missing frame or changed payload
fails. Both file hashes and the packet-clock proof are bound by `audioClockHash`.
This is timestamp-only private normalization; it does not repair the ordinary
final renderer. The failed pre-correction sample is retained under
`/private/tmp/sniper-preview-pts-vexqh8ua/` for diagnosis.

Tests use five source impulses: an interior first-cut event, incoming J-cut
preroll, two second-cut events, and retained ending audio after silent footage.
The oracle compares actual decoded source locations against declared source
selection and executed frame-grid starts, not merely one renderer against itself.

## Qualification still required

The ordinary final/master renderer still uses the canonical AAC/tempo path.
**Preview-to-final audio equivalence is an open blocking qualification defect.**
Do not claim that a good private preview proves the final preserves identical
cut audio until the ordinary path receives a separately reviewed correction
and the same source-content oracle. Nonunity tempo needs an explicitly stated
algorithm-appropriate tolerance; arbitrary compressed-audio impulses are not
necessarily sample-perfect under legitimate time stretching.

Initial private-preview admission is therefore explicitly **source speed 1**.
It rejects nonunity plans before hashing media/rendering, without rewriting an
approved cut. A 1.25× NTSC diagnostic retained 96 frames but reported
`r_frame_rate=30000/1001` versus `avg_frame_rate=160000/5339`; this fails the
strict CFR gate. The audio test separately compares to an independently invoked
legitimate `atempo=1.25` source reference with 3 ms energy-centroid tolerance,
but that is not permission to seal the defective picture candidate. Its failed
attempt is retained at `/private/tmp/sniper-preview-speed-yaznmxm6/`.

## 2026-09-06 addendum: the join clock and the presentation clock are container facts

Two later long-form failures (LL-038, LL-039 in `scripts/producer/docs/findings/FAILURE_LEDGER.md`)
sharpened this finding. Both were MP4 container arithmetic, not audio content:

- **Join clock.** The concat demuxer offsets every file by its container
  duration, which MP4 stores in milliseconds. NTSC parts are never a whole
  millisecond, so 82 stream-copied parts drifted to `avg_frame_rate
  280380000/9354877` and failed the strict CFR gate, although each part was
  CFR and the compiler drift was inside tolerance. The 21 ms PTS-630 origin
  noted above was the same family (B-frame reorder plus edit list).
  `cut_speed.concat_parts` now rebuilds the copied video clock from the packet
  index over B-frame-free parts; the picture origin is zero without any
  `-itsoffset` and the packet-clock proof above still binds it. The retimed
  (1.25×) diagnostic that "failed the strict CFR gate" therefore no longer
  fails there: that failure was the join defect, not a property of retiming.
  Nonunity speed is still refused by admission only.
- **Presentation clock.** The receipt reader requires the AAC presented
  sample count to equal the sealed float total exactly. The priming edit list
  is written in the MOVIE timescale; at the MP4 default (1000) the presented
  duration is millisecond-rounded, so equality held for the 3 s fixtures only
  because 90 NTSC frames (144144 samples) are a whole millisecond, and the
  long-form's 14968554 samples presented as 14968560. The private mux now sets
  the movie timescale to the sample rate; the verifier was not loosened.

The ordinary cut mezzanine moved closer to the private policy (float PCM
parts on the cumulative sample clock, one AAC generation) but its own/lead
filters still apply `atempo=1.0` at identity speed (`CutAudioFilter.preserve_unity`
defaults to false there), so preview-to-final audio equivalence remains the
open qualification defect stated above.

Later the same day the ordinary mezzanine was measured against the same
source-content oracle (`tests/test_render_source_audio_media.py`): with float
PCM parts on the cumulative sample clock, one AAC generation and the
exact-window declick, the 0.2 s source impulse lands within **0.85 ms**
(the test that pinned a >3 ms misalignment now guards alignment instead). Its
own/lead filters still apply `atempo=1.0`, so this is one fixture's evidence,
not the formal preview-to-final equivalence gate, which remains owed.
