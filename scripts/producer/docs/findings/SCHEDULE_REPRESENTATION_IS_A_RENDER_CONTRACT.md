# A valid timing list must survive the renderer boundary

The long-form candidate could not render its thirteenth graphic. Its pipeline
composition declared `moduleLands` as a string, with pipe/comma-separated times.
The native JavaScript also understood arrays. The plan validator required an
array, but the strict rendering CLI rejected that array before JavaScript ran.
Changing the plan from one representation to the other merely moved the error.

The repair uses one strict parser for explicit module times. It rejects partial
numbers, nonfinite values, negatives, duplicates and descending schedules. The
validator still enforces the existing spacing and hold limits. The first-content
check, visible-completion calculation and pacing model now read the same schedule.
Malformed schedules cannot supply visual activity to the pacing score.

At the renderer boundary, an array is serialized only when the actual template
metadata declares that timing field as a string. For example, `[0, 2.44]` becomes
`"0.0|2.44"`. The authored plan is unchanged. Other fields receive no coercion.
Both the native and sealed render paths receive the same explicit variables.

The real blocked pipeline graphic was rendered through the pinned Mac runtime in
both forms. Each produced 296 frames at 1920×1080/30 fps, 9.866667 seconds, with an
identical SHA-256 of
`5993c2ae1036dece57edde0710198228cab5852afebbc88eb2c22e389157ae5f`.
Full decoding and content-occupancy checks passed; an actual frame showed the
complete three-part diagram. These facts qualify the representation repair, not
the whole video's editorial decisions or narration timing.

Use this approach when an authored data shape and an external runtime transport
have different representations of the same validated values. Do not turn it into
a general string-coercion fallback: unknown fields, wrong types, missing modules
and unreadably short holds must still fail. Preserve authored inputs and prove
that both supported forms reach the actual renderer with equivalent meaning.

The same boundary issue appeared in the next long-form revision. A statement
swap authored as `statementLands: "2.58"` was treated as a claim that the speaker
had to say. The template's existing content classifier already marked that
field as a timing control. The claims gate now uses that shared classification
only for top-level controls declared by the selected template. Unknown fields,
nested content and actual visible numbers remain checked. Malformed timing
still fails the template gate; excluding it from speech claims is not admission.

An adversarial test also exposed the opposite error: `"Review 92|Catch it"`
paints a numeric claim, but splitting only on whitespace hid `92` inside the
token `92|Catch`. Numeric matching now splits the same painted units as phrase
matching before checking the numbers. Both `"92%|450M"` claims remain visible to
the gate. This is why a metadata fix needs a test that false visible claims
still fail, not just a test that legitimate control strings pass.
