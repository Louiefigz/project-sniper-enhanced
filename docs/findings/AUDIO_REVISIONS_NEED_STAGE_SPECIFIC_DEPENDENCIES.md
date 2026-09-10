# Audio revisions need stage-specific dependencies

## The problem

A render graph can report unnecessary work even when the underlying renderer
already knows how to reuse picture. Sniper's source-float-v2 path applies
dialogue cleanup, gain and authored seam SFX at full-program audio mastering,
but the graph still included those settings in its timeline/base identity.
Changing gain therefore made unchanged picture inputs look stale.

Removing all audio fields from every hash would be wrong: the final must change,
and legacy renderers really do bake some of those settings into their base.

## Reuse the existing renderer projection

The September8 follow-up uses the existing `finishing_free_plan` and
`base_plan_lineage_digest` for source-float-v2 timeline/base dependencies only.
The pending-base writer and reader use the same projection. Scene, composite
and final projections retain their existing meaning. Legacy callers keep the
old default and identical digest domains.

```python
roots = stage_input_roots(plan, manifest, inputs.audio_clock_policy)
lineage = base_plan_lineage_digest(plan, inputs.audio_clock_policy)
```

Do not infer execution from a graph node's dirty label alone. In the exercised
non-caption fixture, composite and final both reference the same `final.mp4`.
Changing its AAC changes both artifact hashes, even though the video packets
are identical and no graphics/composite stage ran. The correct assertion is:
source, timeline, base and raw dialogue are reused; final audio changes; actual
video packets remain identical; graphics/composite execution is absent.

## Actual evidence, not a speed promise

The integrated follow-up passed12 actual synthetic graph scenarios in
134.351seconds suite /135.37seconds wall. The four-second program includes cuts,
right-only audio, silence, a retained tail event, music and an existing visual
seam. Actual command times were:

| Command | Seconds |
| --- | ---: |
| Base generation | 13.407 |
| First assembly | 17.107 |
| No-op graph recheck | 5.593 |
| Music revision | 16.098 |
| Cleanup plus gain revision | 15.025 |
| Held finished-master reassembly | 10.878 |
| Gain-only revision | 13.901 |
| Cleanup preset change | 14.039 |
| Music/SFX change on an existing seam | 14.732 |

These are not matched before/after benchmarks. A previous owner measurement
of15.11seconds before versus15.03after did not establish a meaningful speedup.
Correct invalidation is the demonstrated result.20 final live digest, registry,
graph and store tests passed in9.64seconds wall; changed picture roots and
foreign/resealed authority still reject. Native artifacts and command logs:
`/private/tmp/sniper-v2-graph-cli-s02o0pc2`.

## When not to reuse

Do not apply this projection to legacy baked-audio bases, changed cuts/speed,
new visual seams, changed framing, stale source/implementation bytes or a
mutable pointer without the independently held graph/master identity. An
existing seam gaining SFX is audio-only; adding the seam itself is not. Tiny
synthetic packet equality does not supply creator listening, full-video quality
approval, guided/source-color eligibility or the two-hour generation target.
