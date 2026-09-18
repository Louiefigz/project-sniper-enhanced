# Director library (`resources/director`)

The Shorts Director reads this library to choose and audit a Short's opening: the
written hook on screen, checked against the recording's first spoken words and
first picture. It ships with Project Sniper and is read only from this folder, or
from an absolute `SNIPER_DIRECTOR_LIBRARY` folder with the same six files.

## Provenance

Authored for Project Sniper on 2026-09-18 from first principles, using the
published research listed under [Sources](#sources) as background for the
taxonomy and the opening criteria. It replaces an earlier library that was
withdrawn. Its categories, identifiers, templates, formulas, formats, examples,
training pairs and criteria were written for this library.

Every recording, speaker and number in the examples is an illustration written for
this library. None is a real person's words or result. Sniper has not measured how
these patterns or criteria perform on published Shorts; they are design rules
with stated reasons, not measured findings.

## Files

The loader (`src/lib/server/native-director-library.ts`) requires exactly these
six UTF-8 files, each at most 256 KiB. Their byte hashes are recorded in every
Director decision and request, and the whole parsed catalog is frozen into each
native Short project as `DIRECTOR-LIBRARY.json`, so an edit here never changes a
saved project's record.

| File | Contents | Grammar the loader reads |
|---|---|---|
| `formats.md` | 10 explanation shapes | `## <format_id> — <title>` sections |
| `hook-anchors.md` | 40 opening patterns in 10 categories | `### <n>. <CATEGORY> — ` headings and `` | `<anchor-id>` | "<template>" | <notes> | `` rows |
| `hook-formulas.md` | 29 slot formulas | `### <R or T id> · <name>` with `- formula: ` and `- disqualify-if: ` lines |
| `hook-references.md` | 25 reference openings, R501–R525 | one `- **R5nn · <name>** — …` line each |
| `hook-training-problem-aware.md` | 6 training pairs, T701–T706 | `### T7nn` sections |
| `hook-training-solution-aware.md` | 6 training pairs, T707–T712 | `### T7nn` sections |

Every formula ID has a matching reference or training entry. All 25 references and
T701, T704, T707 and T710 have formulas; the other training pairs use their named
anchor's slots. Identifiers: format IDs are lower-case words joined by `_`; anchor
IDs begin with a short category word (`situation-`, `gap-`, `steps-`,
`number-`, `mistake-`, `assumption-`, `compare-`, `moment-`, `define-`,
`result-`); references are numbered from R501 and training pairs from T701.

## How the Director uses the library

1. Quote the payoff: the retained words that tell the viewer what they came for.
2. Name the viewer, their problem and their starting point (below).
3. Choose a format the recording supports, and reject one or two others with a
   reason from the recording.
4. Find the source material that powers a category, then choose one anchor and one
   example; reject one or two other anchor/example pairs with source reasons.
5. Bind every slot (the example's formula slots, or else the anchor's) to exact
   contiguous retained words.
6. Write two or three fills of the same pattern and audit each against the six
   opening criteria.
7. Choose a passing fill and plan the first picture, placement, contrast, reading
   time and exit. A separate critic invocation reviews the whole decision.

The local title tool (`src/lib/server/native-hook-template.ts`) can also fill a
quoted template literally. Its one optional clause belongs to `steps-toward-goal`:
` (in [timeframe])` is dropped when no timeframe is supplied.

## Why the categories are named for source material

A Short is cut from a real recording, and Sniper never invents what the speaker
said. The useful first question is therefore not "which hook style is strongest"
but "what does this recording contain that can hold attention?" Each category
names that material, so choosing a category is a search the Director can perform
and the critic can check in the transcript:

| Category | Material the recording must contain | Why it can hold attention |
|---|---|---|
| NAMED SITUATION | a situation the viewer is in, with its consequence | people attend to and remember information that refers to themselves (Rogers, Kuiper & Kirker, 1977) |
| GAP THE SPEAKER CLOSES | a precise question the speaker answers | a specific, recognised gap in knowledge produces curiosity (Loewenstein, 1994) |
| COUNTED STEPS | an explicit sequence the speaker walks through | a stated count tells the viewer the gap is bounded and closable |
| REAL NUMBER | a number with its unit and meaning | a concrete figure is easier to picture and hold than a general claim (Sadoski, Goetz & Fritz, 1993) |
| COSTLY MISTAKE | a mistake, its cost and its fix | people weigh potential losses more heavily than equivalent gains (Kahneman & Tversky, 1979) |
| ASSUMPTION CHECK | a common belief the speaker tests | input that departs from what a viewer expects draws attention (Itti & Baldi, 2009) |
| SIDE BY SIDE | two options compared on stated points | a decision the viewer already faces is personally relevant (Petty & Cacioppo, 1986) |
| MOMENT FROM THE STORY | a specific event the speaker lived | narratives draw listeners into the events they describe (Green & Brock, 2000) |
| PLAIN DEFINITION | a term the speaker explains | a term the viewer keeps hearing without understanding is a recognised gap |
| VISIBLE RESULT | an operation or result visible in the footage | the picture carries the proof, so the words can stay short |

The formats are ordered by the kind of understanding the viewer leaves with (one
change, a procedure, a choice, a number, a correction, a revised belief, an
analogy, a demonstration, a story, a meaning); each names the material it needs
and when to reject it.

## Opening criteria (Director plan schema v2)

Every fill is audited on six criteria, in this order. Each verdict cites literal
text from the written hook, the spoken opening or the first-picture description,
and code rejects a citation that is not present on that surface. The chosen fill
must pass all six; a fill that fails one is recorded as failing, never rescued by
the others.

1. **`supportedClaim` — nothing on screen claims more than the recording.** Every
   number, result, timeframe, frequency, ease or certainty in the written hook
   appears in the retained words with the same strength: hedges such as "about",
   "usually" or "can" are kept, no figure is computed or rounded by the Director,
   and a goal is never shown as an achieved result. *Why first:* Sniper edits a
   real person's recording, so an overstated hook misleads the audience and puts
   words in the speaker's mouth; no other strength can offset that. Public
   advertising guidance applies the same standard to any objective claim: it must
   be truthful and substantiated (U.S. Federal Trade Commission, *Advertising
   FAQ's: A Guide for Small Business*).
2. **`answerablePromise` — the opening asks one question the payoff answers.** The
   written hook poses one specific question or promise, and the quoted payoff
   answers it inside the retained cut. *Why:* curiosity comes from a specific gap
   the viewer notices (Loewenstein, 1994), and it is strongest when the viewer
   already knows part of the answer and expects to learn the rest (Kang et al.,
   2009). An opening whose gap the Short never closes spends the viewer's trust.
3. **`viewerStake` — the viewer can see what is in it for them.** The hook names
   something the target viewer has, does, wants or is deciding, in their terms:
   the viewer's goal, not only the speaker's method or topic. *Why:*
   self-referential information is processed more deeply (Rogers, Kuiper & Kirker,
   1977), and personal relevance increases how closely people attend to a message
   (Petty & Cacioppo, 1986).
4. **`concreteDetail` — at least one specific detail from the recording.** A number
   with its unit, a named object, place, time or symptom; "this trick" or "a simple
   fix" does not count, and neither does a bare number whose meaning is withheld.
   *Why:* concrete text is judged more interesting, is understood faster and is
   remembered better than abstract text (Sadoski, Goetz & Fritz, 1993), and in a
   second or two a concrete detail is what a viewer can picture.
5. **`channelAgreement` — words, voice and picture point at the same thing.** The
   written hook, the recording's first spoken words and the first picture present
   the same subject at the same moment; none contradicts or competes with the
   others. *Why:* people learn better when corresponding words and pictures are
   presented together and extraneous material is left out (Mayer, 2009: coherence,
   signalling and temporal-contiguity principles). Competing channels split
   attention exactly when the viewer decides whether to stay.
6. **`glanceReadable` — readable in full at phone size while it is on screen.** One
   idea, plain words, line breaks at phrase boundaries, and enough time on screen.
   *Why:* adults read connected non-fiction silently at roughly 240 words per
   minute on average (Brysbaert, 2019), under better conditions than a phone
   screen over moving footage. **Sniper design parameters:** code enforces at most
   12 words and two lines (`MAX_DIRECTOR_HOOK_WORDS`); as a planning rule the
   Director budgets at least 0.3 seconds per written word plus half a second to
   find the text, which stays below that average reading rate. Neither number was
   measured on Shorts.

The order runs from truth, through the promise the Short must keep, to attention,
to execution. It is also the order the critic should challenge.

## Viewer starting point

Plan v2 records one of three levels in `awareness.level`, with a reason from the
recording:

- `problem_unseen` — the viewer does not yet recognise the problem. The opening
  must show the situation or symptom first (NAMED SITUATION, MOMENT FROM THE STORY,
  REAL NUMBER); ASSUMPTION CHECK and SIDE BY SIDE usually assume too much.
- `problem_aware` — the viewer feels the problem but does not know the fix. Open on
  the symptom, the mistake or the question (see `hook-training-problem-aware.md`).
- `solution_aware` — the viewer knows fixes exist and is comparing them or doubting
  one. Open on the options, the belief about a fix, or the fix working (see
  `hook-training-solution-aware.md`).

Three levels are enough because a Short cut from an operator's own explanation has
one question to settle at the start: how much of the problem the opening must
establish before its promise makes sense.

## Plan versions

New Director decisions use plan schema v2 (`src/lib/producer/contracts/native-director-v2.ts`,
`schemas/producer/native-director-v2.schema.json`). Plans saved before 2026-09-18
used schema v1 with a different audit key set. The parser still reads a v1 plan
and re-validates it against its own frozen library with the same binding and
audit rules, but the full cold check of a saved Director record
(`readNativeDirector`) refuses one: its frozen prompts were built from wording
that is no longer in the product and cannot be reproduced. New decisions are
always v2.

## Sources

- Brysbaert, M. (2019). How many words do we read per minute? A review and
  meta-analysis of reading rate. *Journal of Memory and Language, 109*, 104047.
- Green, M. C., & Brock, T. C. (2000). The role of transportation in the
  persuasiveness of public narratives. *Journal of Personality and Social
  Psychology, 79*(5), 701–721.
- Itti, L., & Baldi, P. (2009). Bayesian surprise attracts human attention.
  *Vision Research, 49*(10), 1295–1306.
- Kahneman, D., & Tversky, A. (1979). Prospect theory: An analysis of decision
  under risk. *Econometrica, 47*(2), 263–291.
- Kang, M. J., Hsu, M., Krajbich, I. M., Loewenstein, G., McClure, S. M., Wang,
  J. T., & Camerer, C. F. (2009). The wick in the candle of learning: Epistemic
  curiosity activates reward circuitry and enhances memory. *Psychological
  Science, 20*(8), 963–973.
- Loewenstein, G. (1994). The psychology of curiosity: A review and
  reinterpretation. *Psychological Bulletin, 116*(1), 75–98.
- Mayer, R. E. (2009). *Multimedia Learning* (2nd ed.). Cambridge University Press.
- Petty, R. E., & Cacioppo, J. T. (1986). The elaboration likelihood model of
  persuasion. *Advances in Experimental Social Psychology, 19*, 123–205.
- Rogers, T. B., Kuiper, N. A., & Kirker, W. S. (1977). Self-reference and the
  encoding of personal information. *Journal of Personality and Social
  Psychology, 35*(9), 677–688.
- Sadoski, M., Goetz, E. T., & Fritz, J. B. (1993). Impact of concreteness on
  comprehensibility, interest, and memory for text: Implications for dual coding
  theory and text design. *Journal of Educational Psychology, 85*(2), 291–304.
- U.S. Federal Trade Commission. *Advertising FAQ's: A Guide for Small Business*
  (business guidance publication).

These works are cited as background for design choices. They were cited from the
published literature, not re-read or re-measured for this library, and none of
them studies Shorts openings directly.
