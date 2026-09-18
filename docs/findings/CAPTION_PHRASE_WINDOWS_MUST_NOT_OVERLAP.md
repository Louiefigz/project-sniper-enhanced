# Source word bounds and visible phrase bounds have different jobs

The WildFireVlog3 Nate-style test exposed a one-frame caption collision. At 25 fps,
flooring the next word's start and ceiling the preceding word's end can make both
word records cover one frame even when the original speech is continuous.

In the retained “This is our current game plan” passage, the first displayed
phrase inherited frames 124–143 from its words. The next phrase began at 142.
Both phrases consequently appeared at frame 142. The HyperFrames layout check
reported overlapping text; the source words themselves were not the error.

`native-short-composition.ts` now derives each phrase's visual end as the minimum
of its final word's end, its caption view's end, and the next phrase's start.
The first phrase therefore clears at 142. The exact source word tuples remain
unchanged, including their floor/ceil timing and karaoke evidence. Clip duration
and explicit GSAP exit use the same helper, so backward seeks follow the same rule.

The focused regression uses a preceding word ending at 21 and the next phrase
starting at 20. It verifies a 0.8-second visible first phrase and a frame 20 exit,
while asserting that source word evidence was not mutated. The actual Nate render
was inspected at 142 and 143, including reverse seeks, and both encoded frames
passed comparison with independent native captures.

Use this policy for sequential phrase captions that share one reading lane.
Do not apply it to intentionally simultaneous speakers, translations or independent
caption lanes without grouping by lane first. Do not move the audio, rewrite
the source timestamps or remove spoken words merely to make a layout test pass.
