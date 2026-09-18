# ASR word spans can hide dead air

## Finding

A word-safe cut can still begin on silence when the ASR assigns a long pause to
one word token. In C0679, the kept opening token `if` occupied
11.271–13.661s: 2.390 seconds. Independent waveform inspection measured about
2.36 seconds of silence in the same interval.

The boundary contract correctly reported that 11.271s was a word boundary. It
could not tell that most of the word's span was silence. One critic caught the
stall and another passed the identical cut, proving this signal cannot remain a
probabilistic review choice.

## Deterministic rule

`transcript_cut_quality.py` now rejects the first kept function word of a
produced/full long-form cut when its ASR span is at least 1.5 seconds and at
least four times the median duration of the next three-to-eight words. The
receipt records the token, source interval, duration, cut index, local median,
and pace ratio. A revision must remove the pause using legal word boundaries;
it may not cut inside the anomalous token merely to make the timer shorter.

This rule is deliberately narrow. It catches a stalled hook on function words
such as `if`, `a`, or `you` without rejecting names, acronyms, later
sentence-final pauses, globally slow delivery, or lighter edit scopes.
Editorial critics still own subtler cadence decisions.

## Why review is still required

The hard gate catches a measurable timing anomaly. It does not decide which
alternate take is strongest or whether a repaired splice sounds natural. After
the deterministic repair, two independent clean reviews of the same cut hash
remain mandatory.
