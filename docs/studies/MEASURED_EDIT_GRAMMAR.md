# Measured Edit Grammar — the pro edit, frame-accurate + word-correlated

Every number here is **measured** from `angle generator.mp4` (the pro edit of C0679),
0–92s intro, via a feature-tracked digital-zoom trace (ORB similarity transform,
12 fps), face-height trace (8 fps), Canny caption-band analysis, brightness/green
transition detection, and Deepgram word timing on the edited timeline. This
replaces the vague heuristics ("punch on thesis, 1.2×, ease 0.8%/s") the system
shipped with — those were config defaults, never measured. See
`PRODUCTION_ENVELOPE_STUDY.md` for the front-loading envelope; this doc owns the
**per-event grammar**: magnitudes, rates, and the WORD that triggers each.

## 1. Zoom is BIMODAL, and speed scales with importance

The pro does NOT have one zoom behavior. Measured, there are three:

| Behavior | Rate | Magnitude | When |
|---|---|---|---|
| **Fast push-in** | **8–15 %/s** over ~0.7–1.1s | +7 to +16% | naming/introducing the key noun |
| **Hold** (aliveness) | 0.5–1.0 %/s | tiny drift | everything between |
| **Pull-out** | −3 to −4 %/s over ~1.3s | −5% | transition to a new point |

**The system shipped with 0.8 %/s for EVERYTHING** — i.e. only the *hold*. It never
does the fast push, which is the entire source of intentional energy.

**Push speed ∝ importance** (measured, word-correlated):
- 16.7s **~11 %/s** → "your **AI content system** is" (names the subject's problem)
- 18.0s ~10 %/s → "…is probably **at** [this stage]"
- 39.2s **~14.5 %/s** ← the FASTEST push in the minute → "this **angle generator
  workbook**" (the product — the single thing he most wants remembered)
- 77.2s ~8 %/s → "**tools every creator should use in 2026**" (a list item)

Rule: **fast push-in on the named payload noun; the more it matters, the faster the
push.** Pull-OUT on "So most people are stuck…" (topic transition). Hold otherwise.

## 2. Cuts — ~4.6/min, on thought boundaries

7 hard cuts in 92s = **4.6/min** (consistent across 3 methods). Every one lands on a
sentence start / pivot:
- 15.2s "**Because right now**,…"  · 35.2s "In fact, **I'm building the platform**"
- 45.2s (pull-out+cut) "So **most people are stuck**"  · 47.2s "**So let me** [show you]"

Rule: **cut on the first word of a new thought / pivot**, not mid-clause. The felt
density is NOT from cuts (only ~4.6/min) — it is from pushes + graphics + cut-covers
(long-form; no captions).

## 3. Transitions — cut-covers, ~5–8/min

White-flash / **green light-leak** washes fire ON the hard cuts (measured at
15.2 / 35 / 54 / 61.8 / 87s = the cut times) to mask them, plus a **rapid-flash
burst ~62s** over a fast example montage. Rule: **a flash covers a hard cut on an
energy beat; a rapid burst marks a montage.** Not every cut gets one.

## 4. Graphics — word-locked, and ABSENT on filler

- **Tool chips** (`icon-badge`, top-left over headroom): appear **word-locked to each
  tool name** — ChatGPT chip @8.0s, Claude @9.0s, Gemini @10.0s → **~1.0s stagger**,
  all gone by ~10.5s (~2.5s total). Colored glow per brand.
- **Credibility PIP takeover** (~26.9–35.1s, **~8.2s**): full-frame dark takeover,
  subject shrunk to a **circular PIP** joined by a curved white line to text; **two
  claims revealed in sequence** ("spent a decade as a software engineer" magenta →
  "obsessed with using AI to build content systems" white); the **PIP repositions**
  (center→left→center) as each block writes on. Word-locked to "So I've spent a
  decade." (No system lane exists — `pip_takeover` is unwired.)
- **Full-frame statement cards**: sparse (~0.7/min), on the *claim* beat.
- **Why NOT**: filler/connective sentences get NOTHING. Graphics ride only a named
  entity, a claim, or a list — never "B, Ali, lower it."

## 5. Captions — SHORTS ONLY (this section was measured wrong)

⚠️ **CORRECTION.** The earlier claim here ("~68%+ of the intro, a near-constant
colored caption layer") was a **FALSE POSITIVE**. It came from a Canny edge-density
metric over the lower third, which on these LONG-FORM pairs picked up the desk edge,
the hands, the mug, and the full-frame statement CARDS — not captions. Verified by
looking: the pro long-form talking head runs **clean, no words on screen**.

The truth: **on-screen captions (words to follow the speech) are a SHORTS format
element only.** Long-form has none. The on-screen text you see on long-form is
full-frame **cards** (editorial), which §4 already covers. The pro's SHORTS caption
style is NOT verified from these files (both measured pairs are long-form) — treat
any karaoke/color-emphasis claim as unconfirmed until a real short is measured.

## 6. Per-minute budget (first minute, measured — LONG-FORM)

~4.6 cuts + ~5–8 flash-transitions (on cuts) + chips (word-locked burst) + 1
credibility CARD + ~3–4 fast pushes. **No captions** (long-form). The first minute
is the DENSEST — every second carries a word-locked decision. The prior system put a
generic pass on it: 3 detector-flagged cards, one 0.8%/s creep. That gap is the problem.

## 7. Encoding targets (→ system rules, with tests)

1. Zoom rate bands in `producer_config.MOTION`: `push 8–15 %/s`, `hold 0.5–1 %/s`,
   `pull −3 %/s` — replace the single 0.8%/s.
2. **Importance-scaled push**: push magnitude+speed from the payload noun's weight
   (entity/product/number > generic), word-locked to that noun — not "on a thesis".
3. Chip stagger 1.0s, word-locked to each named entity.
4. Credibility-PIP lane (wire `pip_takeover`) on the credibility beat.
5. Transitions as cut-covers on energy beats; burst on a montage run.
6. Captions: SHORTS ONLY (long-form has none). Style unverified from these files.
