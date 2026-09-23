# Retained silence needs the kept clock

The cut gate used two incompatible sources of evidence at the same boundary.
It admitted a cut inside a nominal word when the removed audio measured quiet,
then estimated retained silence from the previous fully ended ASR word. A
displaced word could therefore turn a safe edge into an invented long pause.

On the ten-minute qualification recording, five edges failed that estimate.
At source 79.43, for example, the previous complete word implied 0.85 seconds
of silence. The shared acoustic measurement showed only 0.35 seconds of
continuous qualified quiet retained at that edge. No word time was rewritten.

## Three different quantities

1. An ASR gap is the distance between token boundaries. It is an estimate.
2. A hysteresis silence run is useful for locating pauses. It can contain frames
   too loud to establish that nothing was spoken there.
3. Qualified quiet intersects that run with the shared frame-level headroom
   rule. It is the same conservative evidence used to admit a silence removal.

The broad 26.12–28.30 pause initially appeared to leave 1.20 seconds across
two kept clips. The frame-level evidence contained louder frames around
26.96–27.24, so that was not 1.20 seconds of continuous qualified quiet.
Using the broad span alone would simply replace one false alarm with another.

## Correct accounting

`transcript_cut_silence.py` intersects the existing hysteresis spans with
`Measurement.quiet_spans()`. At an edge it counts only the continuous qualified
quiet inside the selected clip, divided by the clip's playback speed.

```python
retained_end = end - max(clip_start, quiet_start)
output_quiet = retained_end / speed
```

Adjacent quiet portions are then joined on the output clock. An entirely quiet
clip carries the preceding quiet forward; speech resets it. Otherwise a series
of individually short clips could hide one long pause. Both the individual
edge and the joined seam retain the existing 0.75-second ceiling.

This exposed an actual issue that the old ASR heuristic missed: one join kept
0.35 seconds before its cut and 0.93 seconds after it, totaling 1.28 seconds.
Extending the removal by 0.58 seconds, wholly inside audio that passed the
existing unspoken check, left 0.35 + 0.35 = 0.70 seconds. The candidate plan
then passed without changing its transcript or relaxing a threshold.

## Evidence and limits

Twelve focused regression cases cover displaced word bounds, real long quiet,
leading/trailing edges, short quiet clips, joined pauses, playback speed,
invalid speed, audible word refusal, and transcript-only fallback. The wider
90-test cut/timing/correction set also passes. The actual qualification plan
changed from five misleading failures to one correctly identified long join,
then cleared after the quiet-only adjustment.

Receipts now identify `silenceEvidence` and `retainedSilenceS`. A trusted
measurement is required for the acoustic route; unavailable or refused audio
measurement keeps the conservative transcript-based fallback. Word-cut and
removed-speech checks are unchanged.

This does not prove that a sound is a word, that ASR text is correct, or that a
join sounds good. Music, noise and very quiet speech can complicate acoustic
interpretation. Do not use these measurements as a substitute for actual
listening, as permission to repair source-word timing, or as approval of a
complete produced edit.
