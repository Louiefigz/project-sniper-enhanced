# Measure delivery and the complete reveal before choosing shot lengths

In the September 12 native Shorts cases, the follow-up example had 49 words in
13.04 seconds (225.46 words/minute), the offer story 65 in 24.52 seconds
(159.05), and the member calculation 19 in 8.24 seconds (138.35). These numbers
describe word timing; they do not establish emotional energy or comprehension.

Looking at smaller windows exposed two actionable timing issues. A standalone
"what?" caption occupied four frames at 25 fps: 0.16 seconds. Keeping the same
word timings but grouping it with "saying, you know" gives the rhetorical phrase
16 frames (0.64 seconds). A fast highlight can follow speech while the containing
phrase provides a stable reading window. This is an editorial regrouping of
existing occurrences, not new ASR or invented caption copy.

The offer formula occupied 3.16 seconds, but its last term settled at 18.04
seconds and the scene ended at 18.52. The complete relationship therefore had
only 0.48 seconds. A 25-frame viewing budget failed against that actual window.
Moving the next visual handoff within the spoken bridge gave the completed
formula 29 frames / 1.16 seconds without lengthening the 24.52-second Short.

```text
complete-result hold = next visual handoff - final useful action settling
19.20 s - 18.04 s = 1.16 s
```

Use a whole-program rhythm and local speech cues to coordinate captions, cuts,
titles, inserts and motion. Count useful developments inside a shot separately
from scene cuts. Bind the decisions to the actual word and visual clocks so a
revision cannot retain stale budgets.

Encoded-frame inspection then exposed a dependent-label error: at frame 480,
the outgoing old offer was labeled PROPOSED WORDING. Moving the text entrance
without moving the label had made the intermediate state misleading. Revision 2
keeps CURRENT WORDING until the outgoing words clear, switches both labels at
19.55 seconds, and checks the actual label states at frames 480 and 489. This
is why timing changes need state-level checks as well as duration arithmetic.

Adding explicit state checkpoints also shifted the sparse reverse-seek sample
set and exposed an end-of-video issue at frame 583: the injected dog frame could
survive a mask applied only to the original video. Use an untimed parent for the
exit and remove the original video-only mask: keeping both can copy stale
clipping into the injected image on reverse seek. Reuse `nativeVisualExit` for
that parent. Explicit editorial checkpoints now always run in both
directions; their coverage must not depend on their index in a sparse sample.

Do not use this as a universal one-second reading rule, as proof that four-word
captions always fit, or as permission to accelerate dialogue. Dense unfamiliar
information can need longer; a simple recognition shot can need less. A static
timing report cannot see a custom animation hiding the result, and a numerical
pass cannot replace listening and phone-size playback review.
