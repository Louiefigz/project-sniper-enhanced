# EDIT DECISION STUDY — RAW vs EDITED long-form

**What this is.** A word-for-word diff of the operator's RAW camera take (C0666,
18:24, 4K — *contains retakes*) against the professionally EDITED YouTube video
("Replaced 5 Content Tools With 1 Production Workflow", 16:15, 1080p). It answers
the operator's exact question — *"what was taken out from long form and why —
there were retakes essentially"* — from the two Deepgram word-level transcripts,
and distills the editor's decisions into rules for **PRODUCE LONGFORM**.

**Reproduce it:**
```bash
.venv/bin/python scripts/producer/edit/study_edit_diff.py \
    raw.transcript.json edited.transcript.json \
    --out report.json --dump-utts utts.tsv
```
Analysis engine: `scripts/producer/edit/study_edit_diff.py` (reusable, 295 logic
lines). Source transcripts: `study-pair/{raw,edited}.transcript.json`.

---

## TL;DR (the headline)

**This was a *light* edit of an unusually clean take.** The editor kept **94.7 %
of the raw words**. The published audio is reconstructable from the retained raw
words at **99.4 % similarity** — i.e. the edited soundtrack is C0666 end to end,
with **no b-roll voiceover and no second audio source**.

The entire word-level edit reduces to **removing three failed takes**. Everything
else that makes the video 2:09 shorter is **silence**: an 18.6 s head pre-roll
plus ~61 s of pause-tightening between sentences. Put bluntly:

> The editor's job here was **retake removal + pause tightening**, not trimming.
> When the delivery is good, you keep it — you don't chop a clean take into
> pieces.

**Retake-selection policy (the gold):** when a line was delivered twice, the
**later take won — 3 out of 3 times (100 %)**. In every case the *earlier* take
had a legible defect (a false start, a hedge, or an unfinished thought) and the
later take was clean and complete.

---

## 1. Alignment (raw ↔ edited) and its quality

**Method.** Two complementary passes (both in `study_edit_diff.py`):

1. **Word-level backbone** — `difflib.SequenceMatcher(autojunk=False)` over the
   normalised token streams. Because the editor preserves order, EDITED is an
   ordered subsequence of RAW: `equal` blocks = KEPT words, `delete` blocks =
   CUT words, `insert` blocks = words whose source is *not* in C0666.
2. **Utterance-level verdicts** — each raw utterance is labelled from the
   fraction of its words kept: **KEPT** (≥ 85 %), **KEPT-TRIMMED** (15–85 %),
   **CUT** (< 15 %).

**Verdict counts (277 raw utterances):**

| Verdict | Utterances |
|---|---|
| KEPT (verbatim) | 256 |
| KEPT-TRIMMED (partial) | 4 |
| CUT | 17 |

### Alignment-quality confession (read this before trusting the numbers)

I verified honestly and the backbone is **high confidence**, but there are real
caveats:

- **Backbone match = 99.4 %.** Re-joining every KEPT raw word and comparing to
  the full edited transcript gives `fuzz.ratio = 99.4`. The retained raw words
  *are* the edited script.
- **Verbatim spot-checks pass.** Reading both transcripts around 5 alignments:
  raw u30 *"that doesn't eat up your entire life."* → edited u19 (verbatim);
  u100 *"and now I had that board."* → edited u82 (verbatim); u9 (intro take-2)
  → edited u0 (verbatim); u227 *"pull in your raw footage"* → edited u185
  (verbatim, with the *"raw,"* stumble trimmed). All confirmed.
- **Retake predictions confirmed by phrase search.** Every defective take is
  *absent* from the edited fulltext and every winning take is *present*:
  `"the past basically two years"` → **OUT**, `"the last two years was thinking"`
  → **IN**; `"so here's what i do number"` → **OUT**,
  `"here's what i have you literally do this week"` → **IN**;
  `"let me try that again"` → **OUT**.
- **⚠️ Two INDEPENDENT Deepgram passes.** raw and edited were transcribed
  separately, so the *same* audio word is sometimes tokenised differently:
  `xernio`/`xerneo`, `clogcode`/`clog code`, `frameio`/`frame.io`,
  `nonnegotiables`/`non negotiables`. This manufactures ~6 phantom single-word
  "cuts" and **all 26 of the "edited-only" words**. I discount them: the real
  net edits are the 3 retakes plus a handful of true micro-cuts. Do not read the
  single-word-cut list as gospel. **Fix for future pairs:** transcribe BOTH files
  in one session with the same Deepgram keyword/brand-term set, so identical audio
  tokenises identically and this whole noise class disappears.
- **N = 1.** One video, one editor session. The retake policy below is a strong
  signal but a small sample — treat it as a prior, re-confirm on future pairs.
- **No audio was inspected.** Dead-air is inferred from word-gap timings only;
  breaths and sub-word pauses aren't measured. "Boundary vs mid-sentence" cut
  placement uses punctuation/capitalisation, then cross-checked by reading each
  span.

**Verdict:** HIGH confidence on KEPT/CUT word accounting and on the 3 retakes;
MEDIUM confidence on the single-word micro-cut taxonomy (transcription noise
contaminates it).

### Edited content NOT in C0666

Effectively **none.** The 26 "edited-only" words are transcription-tokenisation
noise on brand names (see above) plus a few one-word pickups. There are **zero
contiguous edited-only spans ≥ 4 words**. Conclusion: the finished video's
**audio is 100 % C0666**. Any b-roll in the finished video is visual-only, laid
*over* the retained narration — it never replaces or supplements the voice track.

---

## 2. Retake detection — which take won, and why

A retake is detected structurally: a **CUT** raw line whose near-duplicate twin
**survives** elsewhere (the *nearest* kept twin, so an immediate re-take isn't
confused with a later callback). Three events found; **the later take won every
time.**

### Retake #0 — the entire intro (take-1 @ 18.6 s → take-2 @ 58.6 s)

- **Take 1 (CUT):** u0–u6, 18.6–47 s — *"If you run content for yourself or a
  small agency, write this sentence down… There it is. The line that will fix
  half of your content problems this year…"*
- **Retake marker (CUT):** u7 *"Yeah. K."* (47.5 s) + u8 *"Let me try that
  again."* (52.3 s), then a **5.0 s reset pause**.
- **Take 2 (KEPT → edited u0):** u9 @ 58.6 s — *"If you run content for yourself
  or a small agency, write this sentence down."*
- **Why take-2 won:** take-1 was aborted by the operator himself ("Let me try
  that again"); take-2 is the clean delivery. Also note take-2 tightened the
  wording: *"The line that will fix half…"* → *"That line alone will fix half…"*
  (u12). **The published video opens on the second take of the first line.**

### Retake #1 — "the common mistake" (@ 341.8 s → 349.4 s)

- **Take 1 (CUT):** u83 — *"The common mistake that I made for**, like, the past
  basically** two years was thinking that I needed more tactics."*
- **Take 2 (KEPT):** u84 — *"So the common mistake that I made **for the last two
  years** was thinking…"*
- **Why take-2 won:** take-1 hedges the timeframe (*"for, like, the past
  basically two years"*); take-2 states it cleanly (*"for the last two years"*).
  **Hedge removed → keep the confident take.**

### Retake #2 — "here's what I do" (@ 550.8 s → 564.4 s)

- **Take 1 (CUT):** u135 *"So here's what I do."* (trails off) → u136 *"Oh,"* →
  u137 *"so here's what I have you literally do this week."* → u138 *"I would
  say"* (all CUT, interleaved with false starts).
- **Take 2 (KEPT):** u141 @ 564.4 s — *"So here's what I have you literally do
  this week. **Number one is pick your target for the next ninety days…**"*
- **Why take-2 won:** take-1 is incomplete — it sets up "here's what I do" but
  never lands the payload. Take-2 is complete: it names the action and rolls
  straight into step one. **Keep the take that finishes the thought.**

**Retake win-rate by position: LAST/later take = 3/3 (100 %).**

---

## 3. Cut taxonomy — what was removed, by bucket

17 CUT utterances + 4 KEPT-TRIMMED. Note the retake take-1 lines dominate by
time; the rest is small.

| Bucket | Utts | Seconds | What it is |
|---|---:|---:|---|
| retake-loser | 8 | 27.3 | The take-1 lines from the 3 retakes above |
| tangent / weak-alt | 3 | 11.7 | u3/u5/u6 — *also part of the intro take-1* (re-split by take-2, so not auto-matched; hand-classify as intro retake) |
| filler-hedge | 4 | 4.6 | *"Yeah. K."*, *"Let me try that again."*, *"okay."*, and trimmed *"I think it's called Xerneo now"* |
| false-start | 3 | 2.1 | *"Oh,"* (553 s), *"you already have"* (560 s), *"scheduled,"* (839 s) |
| trim (in kept lines) | 3 | 6.8 | Word-level surgery inside otherwise-kept sentences |

**The word-level cuts fall into exactly two populations:**

**(a) Three BIG cuts, all at sentence boundaries** — the whole failed take lifted
cleanly, never half-spliced:
- 81 words / 35.0 s @ 19 s — intro take-1 + reset
- 20 words / 5.9 s @ 342 s — "common mistake" take-1
- 23 words / 12.8 s @ 551 s — "here's what I do" take-1 + stumbles

These three account for **124 of the 149 cut words** — essentially the entire
word-level edit.

**(b) ~18 tiny mid-sentence cuts (1–3 words each)** — word surgery inside kept
sentences:
- **Duplicated-word dedup:** *"…everything that **that** everyone else does"*
  (387 s) → one "that".
- **False starts on names/URLs:** *"from just say, like, **frame dot** into the
  system"* (876 s); *"The editors pull in **raw, pull in** your raw footage"*
  (898 s) → restart removed.
- **Single filler connectives at seams:** *"But"* (171 s), *"It"* (406 s),
  *"a"* (447 s), *"your"* (837 s).
- **(Discounted)** *"Lait"*, *"Xerneo"*, *"Cloud Code"*, *"Clog"*, *"non
  negotiables"* — these are transcription-tokenisation differences of the same
  spoken word, **not real edits** (see §1 confession).

### Dead air (silence removed)

14 inter-word gaps ≥ 1.2 s totalling **27.3 s** of the ≥1.2 s class. The two
biggest sit *inside* the intro reset (3.5 s after *"K."* @ 49 s; 5.0 s after
*"again."* @ 54 s). The rest are 1.2–2.1 s beat-pauses at sentence transitions
(*"…tactics. | So…"* 348 s; *"…faster. | The…"* 513 s) that the editor tightened.
Counting sub-1.2 s micro-pauses too: the raw spoken region held **142.6 s** of
pause, edited holds **81.2 s** → **61.4 s of pause removed by tightening.**

---

## 4. Stats

| Metric | RAW | EDITED |
|---|---:|---:|
| Total duration | 1103.6 s (18:24) | 974.7 s (16:15) |
| First spoken word | 18.6 s | 0.0 s |
| Utterances | 277 | 215 |
| Words | 2829 | 2705 |
| Voiced (word) time | 933.7 s | 893.3 s |
| Pause time (spoken region) | 142.6 s | 81.2 s |

- **Reduction:** 128.9 s (~2:09), **12 % shorter**.
- **Words kept:** 2679 / 2829 = **94.7 %**. Backbone reconstruction 99.4 %.
- **Words removed (net):** ~124 (the 3 retakes); micro-cut words (~25) are nearly
  offset by 26 re-transcription "inserts".
- **Time budget of the 128.9 s reduction:** ~80 s (**62 %**) silence removed
  (18.6 s head pre-roll + 61.4 s pause-tightening) + ~40 s (**31 %**) words
  removed (the 3 retakes) + a few seconds of micro-cuts.
- **Kept runs are LONG:** 21 continuous kept-speech runs, **mean 47.7 s, max
  174.1 s** uninterrupted. The talking head is not chopped into rapid segments.
- **Cut placement:** boundary-vs-mid-sentence correlates with **cut size** — the
  3 big cuts (retakes) are sentence-boundary-aligned; the ~18 tiny cuts are
  mid-sentence.
- **Retake win-rate:** later take 3/3 (100 %).
- **Head:** entire 0–58.6 s of raw removed (pre-roll + intro take-1). Edited
  opens on the clean take.
- **Tail:** outro/CTA preserved **verbatim** — raw u272–276 *"So click that next,
  and we'll rip apart your current system together."* = edited u212–214. Not
  trimmed.

---

## 5. Edit-decision rules (for PRODUCE LONGFORM)

Every rule is cited to this pair. Confidence noted; N = 1, so treat as priors.

1. **When a line is re-delivered, keep the LATER take.** 3/3 = 100 % here (intro
   58.6 s, "common mistake" 349 s, "here's what I do" 564 s). *[HIGH]*

2. **Keep the take that is COMPLETE and defect-free; the earlier take's defect
   tells you why it lost.** Observed take-1 defects: an aborted false start
   (*"Yeah. K. Let me try that again"* @ 47–53 s), a hedge (*"for, like, the past
   basically two years"* → clean *"for the last two years"*), and an unfinished
   thought (*"So here's what I do."* → *"…do this week. Number one is…"*). *[HIGH]*

3. **Remove a failed take whole, at sentence boundaries — never half-splice
   two takes.** All three retake cuts (81 w, 20 w, 23 w) are boundary-aligned;
   the editor never stitched take-1's opening to take-2's ending. *[HIGH]*

4. **Retake markers are always cut.** *"Let me try that again"*, *"Oh,"*, and the
   reset pauses are the operator's own restart cues and never survive. Detect and
   drop them. *[HIGH]*

5. **Don't over-cut a clean take.** 94.7 % of words were kept. If the delivery is
   good, the edit is retake-removal + pause-tightening, *not* aggressive
   trimming. Resist the "cut everything" reflex. *[HIGH]*

6. **Pause-tightening is the primary length lever, ahead of word-cutting.** 62 %
   of the 2:09 reduction was silence (18.6 s head + 61.4 s inter-sentence pause);
   only 31 % was words. Tighten gaps ≥ ~1.2 s at sentence transitions before you
   consider cutting content. *[HIGH]*

7. **Cut the head pre-roll and the first (failed) take; open on the best take of
   the first line.** Edited 0.0 s = raw's *second* hook take @ 58.6 s; the first
   58.6 s of raw is gone. *[HIGH]*

8. **Preserve the outro/CTA verbatim.** The end-screen call-to-action (*"click
   that next…"*) is kept intact — do not trim the close. *[HIGH]*

9. **Mid-sentence micro-surgery targets three things:** duplicated words
   (*"that that"* → *"that"*), false starts on names/URLs (*"frame dot…"*,
   *"raw, pull in…"*), and single filler connectives at seams (*"But"*, *"It"*,
   *"a"*). Keep these cuts tiny (1–3 words) and inside otherwise-kept sentences.
   *[MEDIUM — some overlap with transcription noise]*

10. **Trim hedges that weaken a claim, keep the claim.** *"for, like, the past
    basically two years"* → *"for the last two years"*; *"from just say, like,
    frame dot"* trimmed to the substance. *[MEDIUM]*

11. **The spine is ONE continuous cleaned narration — audio is never replaced.**
    The edited soundtrack is 100 % C0666 (no b-roll VO, no second source).
    B-roll and graphics ride *on top* of the retained voice track. Build the
    long-form as: clean the single narration first, then layer visuals. *[HIGH]*

12. **Leave long uninterrupted talking-head runs.** Mean kept run 47.7 s, max
    174 s with no audio cut. Pacing/energy comes from *graphics and zooms over
    continuous speech* (see the zoom + graphics audit), not from chopping the
    audio. Do not fragment a good take to "add pace". *[HIGH]*

13. **Don't infer word-cuts from transcription disagreement.** Single-word deltas
    that coincide with brand/compound names (Xernio, Clogcode, frame.io) are
    tokenisation artifacts, not edits. Only cut on genuinely duplicated or
    false-start tokens you can see in the words. *[HIGH — methodological]*

---

## Appendix — artifacts

- Engine: `scripts/producer/edit/study_edit_diff.py`
- Machine report: `study-pair/edit_diff_report.json` (JSON: totals, verdicts,
  cut buckets, retake events, dead-air samples, kept-runs, insert spans)
- Per-utterance verdict table: `study-pair/edit_diff_utts.tsv`
- Sources: `study-pair/{raw,edited}.transcript.json` (Deepgram nova-3, word-level)
