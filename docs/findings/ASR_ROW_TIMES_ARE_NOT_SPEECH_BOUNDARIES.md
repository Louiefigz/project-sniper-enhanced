# ASR row times are not speech boundaries

## The real-footage failure

On 2026-09-07, fresh local small.en transcription of C0679 (834.335 seconds)
finished in **165.06 seconds command wall time**, including **160.155 seconds**
in the per-source stage. Its 2235 words passed the structural timing gate:
no collapsed runs, invalid durations, backward starts or overlaps.

Yet the first “If” covered **0.370–8.640 seconds**, and the restart “if” covered
**11.540–13.620 seconds**. Of 2234 adjacent word pairs, 2204 touched exactly.
The largest positive gap was only 0.37 seconds. Consequently, the 1.2-second
pause proposer returned zero trims. This did **not** prove that the recording
contained no pauses.

Two different problems must not be conflated:

1. The parser used wrapped row envelopes, including padding to the next row,
   and divided multiword rows uniformly. This adds timing that was not supplied
   as an individual word/token interval.
2. Whisper's own ordinary token intervals can stretch across silence. Simply
   using those intervals cannot establish accurate acoustic endpoints.

## A bounded comparison, not a guessed fix

Private evidence:
`/private/tmp/sniper-c0679-current-20260907.9p06WA/word-timing-diagnostic-1/`.

We extracted source 0–35 seconds once as the existing mono16k PCM conversion.
Both arms used the installed identical small.en model, CPU, eight threads,
English, full JSON, `-ml 1 -sow -nfa`. The second arm alone added `-dtw small.en`.
No model download, paid API, source mutation or accepted-transcript rewrite.
The original 60-second aggregate work clock also covered full source hashes
before and after, model/runtime hashes and result verification.

| Observed stage | Seconds |
|---|---:|
| PCM extraction | 0.367404 |
| Ordinary token arm | 4.441921 |
| DTW arm | 4.756802 |
| Complete diagnostic work | 19.591410 |
| Complete command wall | 19.69 |

This single short comparison is not a full-video DTW performance forecast.
Both arms had identical text, ordinary intervals and probabilities: 75 rows,
73 words and 99 tokens (77 lexical, 13 punctuation, 9 controls).

Using real text-token envelopes instead of row envelopes narrowed 23/73 words,
removing 1.730 seconds of row-only span. Touching pairs dropped from 71/72 to
48/72 without overlaps. Examples: “for” 9.600–9.840 became 9.600–9.640;
“every” 19.080–19.450 became 19.080–19.300. Those are provider intervals,
**not independently verified speech boundaries**. Both problematic opening
words remained stretched.

Confidence also needs lexical scope. A timestamp-control token reduced
“single” from its lexical probability .997280 to a row average .557941.
Excluding control probabilities preserves what the provider reported; it does
not calibrate confidence or prove that the word was recognized correctly.

## Why DTW points cannot become made-up intervals

Installed whisper.cpp1.9.1 requires `-nfa` for DTW: default flash attention
disables it. We retained initialization logs showing `dtw=1`, `flash attn=0`.
The same installed model supports its compiled small.en head preset.
[Official implementation](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/src/whisper.cpp#L3404)

Full JSON ordinary token offsets are milliseconds. `t_dtw` is a rough event
point emitted in 10ms units (seconds = value/100), not a start/end pair.
[Assignment](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/src/whisper.cpp#L8191),
[JSON writer](https://github.com/ggml-org/whisper.cpp/blob/v1.9.1/examples/cli/cli.cpp#L698).
In this sample 42/90 text-token DTW points lay outside their ordinary token
intervals, up to 720ms away; three adjacent points were equal. Converting a
point to `end = next_point` would assign pauses to words again. Neither timing
estimate wins merely because it looks more convenient for a cut.

## Production consequences and remaining qualification

The pause proposer now reports `timingDiagnostics` with explicit
`acousticSilenceQualified: false` and `absenceOfPausesEstablished: false`.
For at least20 pairs, a touching fraction of at least.95 adds an informational
warning. It changes no cuts, never invents a pause and does not reject genuine
rapid speech. Empty/sparse input cannot establish absent pauses either.

A strict, versioned token-envelope parser was tested against the full source,
not just the successful short fixture. The normal provider failed in158.33s:
the full model output contains three standalone zero-duration lexical words.
A separate same-settings raw diagnostic retained2266rows/2235words in149.06s;
the three failures are “of” at122.820s, “a” at231.230s and “I” at801.790s.
These are whole words, not harmless zero-length subpieces of positive words.
Their emitted row intervals are50ms,20ms and60ms, respectively; those row
spans are not evidence of positive ordinary-token or acoustic durations.

**Release decision: the strict parser stays experimental.**
`scripts/local_whisper_token_parser.py` preserves exact token text and bounds,
rejects ambiguous intervals, excludes recognized controls and preserves order.
It permits a zero lexical subpiece only inside an otherwise positive lexical
envelope; punctuation cannot rescue a wholly zero lexical word. It still
rejects all three retained full-source counterexamples.

Production `scripts/local_whisper_parser.py` explicitly retains the existing
row/uniform compatibility contract, including its known floor, normalization
and confidence limitations. Its provenance policy is
`sniper-whisper-row-uniform-compatibility-v1`. There is no hidden
try-strict-then-fallback branch or runtime selection knob. The aggregate
deadline, owned cleanup, local-only policy and strict NDJSON improvements stay.
The full raw output reproduces the previously admitted162utterances/2235words
exactly under the restored production parser. Root's combined cohort passed
157tests in4.815s (7.75s command wall); this is not acoustic qualification.

Why not label the three row exceptions provisional and continue? The current
`transcript_cut_evidence._load_words` consumer strips unknown per-word fields,
and the current timing-review gate detects opening/prefix anomalies, not these
internal tiny-word uncertainties. Such a label would not reliably survive to
cut/caption decisions. A separately versioned, preserved uncertainty contract
and applicable downstream gates must exist before replacing the default.
Do not make otherwise usable source transcription fail wholesale, and do not
hide uncertain endpoints to make it pass. The original admitted transcript
remains unchanged and must not be retroactively relabeled as token output.

Source-audio review remains necessary for uncertain boundaries. On the
unapproved produced C0679 proposal, the gate identified both the kept restart
and excluded opening “If”; prepare retained two exact source review windows
without recording listening or acceptance. The same candidate also retains
four repeated-word errors. Do not delete extra words, change its intended
treatment to bypass the stricter opening checks, or manufacture attestations
to make this candidate green.

This method is not a speech VAD, forced alignment of an exact transcript,
subjective listening evaluation, or a quality/latency qualification for a
completed ten-minute production video.
