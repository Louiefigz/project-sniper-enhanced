# Dirty-fragment proof is not program-clock proof

## The assertion

A locally correct repair fragment does not prove that the complete repaired
program has the authoritative frame or pre-AAC PCM duration. Before a cut
repair can be called a proved candidate, rebuild and fully decode the whole
candidate against the absolute project clock.

## The incident

P2 could render a dirty repair unit and prove that the unit contained the
expected delivery frames and samples. The controller then returned
`candidate-proved`, but it had not composed that unit back into the parent.
Therefore it had no terminal proof for:

- total delivery frames `F`;
- total pre-AAC samples `B(F)`;
- a gap or duplicate at either splice;
- decoded picture/PCM preservation outside the dirty closure.

The fragment receipt was valid evidence for the fragment. It was not evidence
for the complete program.

## Evidence with real numbers

The terminal fixture uses `F = 150` and `S = 48,000`. The compositor now fully
decodes the parent and candidate and requires:

| FPS | Required `B(150)` samples/channel |
|---|---:|
| `24000/1001` | 300,300 |
| `24/1` | 300,000 |
| `25/1` | 288,000 |
| `30000/1001` | 240,240 |
| `30/1` | 240,000 |
| `50/1` | 144,000 |
| `60000/1001` | 120,120 |
| `60/1` | 120,000 |

`tests/test_p2_terminal_composite.py` passes this matrix, plus repairs at the
first, middle, and terminal dirty windows. Audio-only repairs hash every
decoded picture frame; picture-changing repairs hash decoded picture outside
the dirty window. Both hash pre-AAC PCM outside the audio closure.

The adjacent 44.1→48 kHz fixture additionally proves that two source ranges
share the same normalized `P(sourceSample)` boundary, and that each complete
candidate still terminates at `B(F)`.

The compositor re-hashes the actual parent, fragment, FFmpeg, and FFprobe
bytes. It also requires the controller-held expected operation hash. A supplied
receipt hash cannot substitute for observing those bytes.

## The principle

Use one absolute clock:

```text
B(frame) = floor(frame × sampleRate × fpsDenominator / fpsNumerator)
```

Partition and splice with absolute half-open ranges. Then prove the final
program, not the sum of locally rounded durations. Codec/container duration and
AAC decoder padding remain observations, never editorial authority.

## When not to use the full-program proof

Do not pay for a full media decode during plan-only target resolution or
candidate enumeration; those stages make no media-completion claim. A dirty
fragment proof is also sufficient for a private cache entry that is explicitly
marked fragment-only and cannot be promoted.

Do require the full proof before `candidate-proved`, preview promotion, revision
CAS, final export, or any claim that unrelated media stayed unchanged.

This proof does not replace alignment, VAD, re-transcription, click/room-tone
checks, operator audition, caption refit, or Palmier readback. Those remain
separate release gates.
