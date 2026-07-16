# Checked lanes need region-bound render evidence

A GUI checkbox is an operator contract, not permission for the editor to make an unrelated gesture somewhere in the timeline.

The weak implementation checked only whether a lane-shaped field existed. That let an empty long-form caption object count as captions, a transition at 80 seconds satisfy a first-minute intro, a `treatmentMap` row satisfy the promised punch-in lane, and a legacy `treatment: clean-cut` label disable pacing even when stored scope remained `produced`.

The correct test binds each promise to what the renderer will actually produce in the governed region:

- transitions: at least one real transition must land on an eligible internal intro seam; evidence receipts may explain the remaining hard cuts;
- motion: a checked zoom/motion lane needs an actual `punchIns` row, not merely a treatment label;
- long-form captions: the stored caption lane controls whether the renderer writes `captions.srt`;
- credibility: a detected early credibility beat must bind to a credibility graphic while that lane is automatic;
- pacing: explicit `target.scope` owns the engagement contract; a legacy treatment label cannot downgrade it.

Use this rule whenever product UI says an effect is “required.” Presence checks are acceptable only when the field itself is the exact render instruction and is constrained to the promised time region. Otherwise check the downstream behavior, not the JSON shape.

