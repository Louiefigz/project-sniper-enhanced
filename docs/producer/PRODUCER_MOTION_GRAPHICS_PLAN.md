# PRODUCER Motion Graphics — Plan (MG track)

> **STATUS: HISTORICAL DESIGN RECORD.** The MG system this doc designs has since
> **shipped** — the live module map is `scripts/producer/CLAUDE.md` (Graphics
> section) and `docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md` is kept for design
> rationale only. The "DRAFT" line below is the original 2026-07-05 header.
>
> Status: DRAFT — operator review. 2026-07-05.
> Extends PRODUCER_PLAN.md. Reference styles: (a) dense kinetic
> talking-head (long-form YouTube, operator-supplied script excerpt);
> (b) INSTAGRAM SHORT-FORM layout study (operator-supplied screenshots — lost
> to macOS thumbnail-drag purge ×3; re-save to Desktop/folder to restore).
> When the IG references land: (1) calibrate placement/proportionality against
> real pixels, (2) MINE THE GRAPHICS for reusable patterns → new template
> candidates (operator: "take note of the cool graphics to see if we can
> reuse any of them").

Turn talking-head cuts into a **motion-graphic experience**: transitions,
infographics, stat cards, list builds, kinetic typography — appearing exactly
when they support what's being said, for shorts AND long-form.

---

## 1. The core question: WHEN do graphics help?

**Doctrine: a graphic must restate the speech in a second modality — never
decorate it.** (Same law as b-roll: purposeful, reason required, no filler.)
A graphic earns its slot only when the words contain STRUCTURE the ear alone
holds poorly:

- numbers ("a million followers", "billions of views", "$12k/mo")
- enumerations ("the six biggest shifts", "three things you need")
- named entities (apps, brands, people, products)
- contrasts ("before AI vs after", "X not Y")
- sequences/processes ("first… then… finally")
- definitions & theses (the sentence the clip exists for)
- topic boundaries (chapter/section changes → transition stingers)

If a sentence has none of these, the speaker's face IS the graphic. Silence of
graphics is a design choice, not a failure — over-decorating is the #1 way this
goes wrong (research: visual variety helps retention; noise fatigues it).

### The kinetic grammar (from the supplied intro script, annotated)

| Script beat | Graphic that carries it |
|---|---|
| "Social media is going to look completely different **in the age of AI**" | Full-frame kinetic title takeover (~2s) |
| "for **brands**, for **creators**, for **anyone**…" | 3-chip sequential pop, one per spoken item |
| "the rules are being **completely rewritten**" | Kinetic text effect (strike-through / rewrite animation) |
| "**a million followers** … **billions of views**" | Stat cards with animated counters |
| "the **six biggest** social media shifts" | Numbered 6-slot grid tease (empty slots = open loop) |
| "**strategy** and the exact **tactics**" | Two-column framework card |

That's the grammar to encode: every graphic maps 1:1 to a spoken structural
element, appears ON the word (word-level timestamps make this exact), and
holds just long enough to read.

## 1.5 The treatment map + editor notes (operator input channel, 2026-07-05)

A video is not uniformly decorated — it has **treatment zones** (operator
observation from the kinetic reference: the dense kinetic treatment is mostly
the FIRST MINUTE; later sections lean on b-roll; others on templated graphics;
some stay clean). Every produce run therefore builds a **treatment map**:

```jsonc
"treatmentMap": [
  { "outStart": 0,   "outEnd": 55,  "treatment": "kinetic",   // dense MG intro
    "budget": "high" },
  { "outStart": 55,  "outEnd": 340, "treatment": "broll",     // folder b-roll carries
    "budget": "medium" },
  { "outStart": 340, "outEnd": 520, "treatment": "templated", // stat/list cards only
    "budget": "low" },
  { "outStart": 520, "outEnd": 859, "treatment": "clean" }    // face + captions
]
```

**Where the map comes from — EDITOR NOTES, a first-class input.** The operator
gives freeform direction, exactly like briefing a human editor:

> "Make the first 45 seconds pop hard — full kinetic. The coaching-bot section
> should use b-roll from the folder. Keep the last third clean, just captions.
> Stat cards whenever I say numbers."

The brain parses notes → treatment map + per-zone graphic budgets + standing
rules ("stat cards whenever I say numbers" becomes a trigger-level always-on
for this video). Notes are optional: with none, the mode default applies
(shorts: kinetic throughout within density caps; long-form: kinetic intro
60s → templated body → stingers at chapters). Notes are also the calibration
memory: recurring instructions graduate into the operator's standing style
defaults (config), so the system converges on their taste video by video.

Editor notes also interact with the feedback loop: post-render notes ("too
busy in the middle, drop the chips at 2:10") revise the treatment map/plan
exactly like cut feedback — versioned, diffable, re-rendered.

## 1.7 The LAYOUT system (operator-specified 2026-07-05)

A **layout** is a named composition that OWNS the canvas geometry: which
region holds what, where captions live, where text/graphics may land. Layouts
are assigned per treatment-map zone (`"layout": "split-critique"`), so one
short can open full-face, switch to a critique split, and end on blurpad.
Captions become **layout-driven** — the fixed lower-band assumption breaks
(the split layout wants captions in the middle seam), so `captions.py` takes
its band from the active layout, not global config.

Operator's core four (v1):

| Layout | Geometry (1080×1920) | Captions | Text/graphics zone | Suits |
|---|---|---|---|---|
| `full-face` | Talking head fills frame | Lower band (y≈1150–1340) | Upper third (hook-card band) | Simple talking-head cuts — "this may suffice" for most |
| `text-overhead` | Speaker lower ⅔; kinetic text block above head | Lower band | Above-head block (y≈250–700); can TRANSITION into `versus-split` | Short-form emphasis moments (sparing use) |
| `split-critique` | **Top half: the asset under discussion (moving, from operator b-roll); bottom half: speaker** | **Middle seam** (y≈880–1040) | Top-asset annotations (arrows/circles) | Critique/reaction/commentary on a thing |
| `blurpad-screen` | 16:9 screen centered, blurred pad fills | Lower band | **Title/context text IN the top blurred pad** (y≈100–620 — dead space becomes signal) | Screen-share content (the proven livestream treatment, upgraded) |

More archetypes are being researched from the wild (greenscreen-cutout over
asset, corner PiP, meme top-bar, doc-style full b-roll, podcast frame…) —
research report lands in this doc's appendix; the top candidates join the
config after operator review. Each layout entry in `producer_config.LAYOUTS`
declares: region map, caption band, text zones, required assets
(e.g. split-critique REQUIRES a b-roll asset — lint enforces), and automation
cost (pure-ffmpeg vs needs person-segmentation).

**Audio/music is layout- and zone-aware** (extends §7 of the core plan +
audio_mix machinery): `split-critique` runs the top asset's own audio ducked
UNDER the speaker (same sidechain, different source); documentary/b-roll
zones want the music bed up; kinetic intro zones can take a music accent;
clean zones keep the bed low or absent. The treatment map carries an
`audio` hint per zone; audio_mix consumes it. Trending-audio (platform-side)
remains a posting decision, not baked in.
**Music default (operator doctrine, 2026-07-05): NONE unless explicitly
requested.** When a zone's convention wants a bed (documentary/b-roll zones),
the brain RECOMMENDS and asks — it never adds music on its own. Source when
approved: operator track, or Higgsfield under the opt-in prompt-review
protocol above.

## 2.1 Visual-state placement doctrine (operator calibration from MG-1, 2026-07-05)

MG-1 verdict on real footage: graphics QUALITY and TIMING approved — but
placement was wrong for the content. The missing dimension: **the footage's
visual state decides where graphics may go, or whether they go at all.**
Triggers say "a graphic could help HERE"; the visual state says "THIS way."

| Visual state | Graphics placement law |
|---|---|
| **Screen-share** (screen is the star) | **NO overlay graphics on the screen** — it is already the visual; stacking text on it is double load. Graphics appear only as **their own screen**: cut away to the graphic full-frame (b-roll style), then back. Captions + hook card remain OK (approved on real footage). |
| **Talking head** | Graphics live AROUND the face — side panel / above-head headroom / the side the face isn't on. **The face is NEVER covered**: face bbox + margin = hard exclusion zone (face_track already finds it). Text PROPORTIONATE to framing — subject far from camera → placement and scale adapt; never too large, never too small. |
| **Mixed / PiP** | Graphics in the region that is neither screen-content nor face. |

Implementation (MG-2): every treatment zone carries a `visualState`
(talking-head | screen-share | mixed) — detected per zone from face detection
(exists) + screen-content heuristics (edge density / UI chrome), operator
notes can override. Lint: graphic anchors must be legal for the zone's visual
state; face-exclusion enforced from face_track windows. The own-screen
graphic (cutaway) is a first-class graphic kind: `"anchor": "own-screen"` —
it behaves like the kinetic-quote takeover (which worked in MG-1 precisely
because it TOOK OVER instead of stacking).

## 2.2 The visual-tactics catalog (operator, 2026-07-05 — "tactics we can save and use")

Named, reusable cutaway tactics — the visual analog of the hook swipe files
swipe file (`hooks_catalog.py`): the brain picks BY NAME from proven tactics,
never improvises unnamed moves. Grows as references land; eventually a
`tactics_catalog` data module. Seed entries from the operator's IG study
(top block) + the edited long-form graphics study (batch 2, bottom block —
`whiteboard-note` … `schedule-stack`, see LONGFORM_VISUAL_STUDY §3 +
REFERENCE_STYLE_STUDY R9):

| Tactic | What it is | When |
|---|---|---|
| `broll-cutaway` | Cut to real b-roll as its own screen, return to speaker | Concrete noun / shown thing (talking-head zones) |
| `infographic-cutaway` | Cut to a templated graphic full-frame (own-screen), return | Structural speech (numbers/lists/contrasts) where visual state forbids overlays |
| `blur-tease` | Show the asset DELIBERATELY BLURRED — the illusion of curiosity; reveal later (or never — comment bait) | Withholding a reveal: "wait till you see this", product/result teases |
| `quote-takeover` | Full-frame kinetic text carrying the spoken line (captions suppressed) | Thesis lines — proven in MG-1 on c1 |
| `chip-row` | Sequential pop of named-entity pills (up to 4; wraps 2×2), one per spoken name (template: `chip-row`) | Named entities — apps/brands/products (talking-head or own-screen) |
| `versus-split` | Two-column before/after comparison card; contrast rows land per beat (template: `versus-split`) | Contrasts — "X not Y", "before AI vs after" |
| `topic-stinger` | Full-frame brand-blue wipe carrying a chapter title; hides the hard cut (template: `stinger-wipe`, opaque MP4) | Topic/chapter boundaries — long-form chapters, hard subject switch |
| `screen-annotation` | Hand-drawn marker underline or circle, stroke-drawn over a screen region (template: `underline-circle`) | Emphasis on ON-SCREEN content — own-screen / approved contexts only (PLAN §2.1) |
| `whiteboard-note` | Miro-style white grid board: an accent label chip joined by a hand-drawn connector line (draws in) to a dark caption box (template: `whiteboard-connector`, alpha) | A "labelled node → its outcome" beat — "in that time → I built X" (talking-head zones) |
| `logo-takeover` | Clean white full-frame with a single centered brand mark that pops (template: `logo-card`, opaque MP4) | Naming a SPECIFIC tool/brand (R12) — the "tools being replaced" beat |
| `statement-takeover` | Full-frame dark (or warm) gradient carrying one bold statement, keyword in accent, staged text build (template: `statement-card`, opaque MP4) | Thesis / definition lines — the frame hands off to the words |
| `agenda-takeover` | Dark "N Steps" title with an accent glow underline over numbered rows that stamp in (template: `agenda-slide`, opaque MP4) | Enumerated plan / chapter agenda — "3 steps", roadmap beats |
| `color-wash` | Brief accent-family gradient wash that sweeps across the frame to bridge a cut (template: `color-wash`, alpha ~0.8s) | Beat / topic transitions — a soft colored bridge between shots |
| `section-marker` | Eyebrow + serif-accent title + qualifier, anchored on the empty side, eyebrow-first build (R9/R10; template: `section-marker`, alpha) | Numbered section markers over the live head — "System No.2 / Familiarity / Rule" |
| `schedule-stack` | Color-semantic rounded cards (title + time) stacked on the empty side, staggered wipe-in (template: `schedule-stack`, alpha) | Routine / schedule / phased-plan beats — time-blocked days or workflows |

Each tactic entry declares: template(s) it uses, visual states it's legal in,
duration bounds, and its trigger affinity. IG reference screenshots (pending
operator re-save to Desktop — thumbnail-drag purged ×4) will be mined for
additional tactics + exact styling.

| Parameter | SHORTS | LONG-FORM |
|---|---|---|
| Graphic cadence | Near-continuous is allowed (kinetic intro style); every trigger is a candidate | Front-load the first 30–60s dense; body follows pattern-interrupt doctrine (one per 10–15s early, oscillating bursts, no static stretch > 60–90s) |
| Hold time | ≥ 1.0s per readable element; word-chips can be faster in a build | ≥ 1.5s; longer holds fit calmer pace |
| Full-frame takeovers | ≤ 2.5s, never during the hook card, max ~2 per short | Chapter transitions + intro thesis only |
| Concurrency | ≤ 2 graphic layers + captions | ≤ 2 |
| Placement | Inside SAFE_BOX free band: y≈560–1150 (between hook-card band and caption band); anchor opposite the focal subject | 16:9 thirds; lower-third zone + side panels |
| Exclusions | Never over hook card; never over the payoff face moment; never under captions | Never over chapter title moment |

All numbers land in `producer_config.MOTION` as tunable defaults (same
research-honesty rule as everything else).

## 3. Architecture — how it renders

```
transcript (word-timed) ──► TRIGGER DETECTOR (logic, deterministic)
                                   │ candidates: {word-span, trigger type, payload}
                                   ▼
                        BRAIN (skill, judgment)
             selects which candidates EARN a graphic, fills template slots
                                   │ graphicsTrack in edit_plan.json
                                   ▼
                     plan_lint (windows, holds, collisions, reasons)
                                   ▼
            HYPERFRAMES render (HTML template → transparent-alpha MP4)
                                   │ + Higgsfield raster assets inside comps
                                   ▼
        composite stage (extends overlays.py: alpha-video overlay at out-time)
                                   ▼
                    captions → master → AUTO-AUDIT (+ new MG checks)
```

### 3.1 `graphicsTrack` (new plan section — same contracts as everything else)

```jsonc
"graphicsTrack": [
  { "outStart": 3.2, "outEnd": 5.4,
    "kind": "stat-card",                  // template id from the library
    "spec": { "value": "1,000,000", "label": "followers", "count_up": true },
    "anchor": "right-panel",              // placement slot, not raw pixels
    "reason": "restates 'a million followers' — number trigger",
    "triggerWords": [412, 413] }          // word indices — timing derived, not invented
]
```

- Timing derives from `triggerWords` via the timeline map (brain can nudge ±,
  lint bounds it) — the LLM never freehands timestamps.
- `kind` must exist in the template library; `spec` is validated against that
  template's slot schema; `reason` required (b-roll rule). Lint enforces
  density caps, hold minimums, band collisions (captions/hook card), takeover
  limits.

### 3.2 The template library — brand-locked, brain-filled

`templates/motion/` — versioned HTML comps with `data-*` timing (hyperframes
format), all sharing one brand token sheet (`tokens.css`: Inter, white card /
black text — same DNA as the hook cards — plus operator accent color TBD).

Starter set (v1):
| Template | Trigger it serves |
|---|---|
| `stat-card` (counter animation) | numbers/metrics |
| `list-build` (N slots, pop per item) | enumerations |
| `chip-row` (entity/logo chips) | named entities |
| `kinetic-quote` (full-frame takeover) | thesis/definition lines |
| `versus-split` | contrasts |
| `step-flow` (arrows) | sequences |
| `underline-circle` (annotate a region) | emphasis on screen content |
| `stinger-wipe` (chapter transition) | topic boundaries |

The brain FILLS templates (copy, values, item lists); it does not design
freeform HTML per graphic — that's how visual consistency and lint-ability
survive automation. New templates are authored deliberately (operator + skill
session), then join the library.

**Hyperframes renders** each comp to a transparent-alpha clip at 1080×1920 or
1920×1080; deterministic output means comps are cacheable by content-hash
(same spec → reuse the rendered overlay, $0/0s).

**Engine defaults (operator doctrine, 2026-07-05): hyperframes is the DEFAULT
visual engine; Higgsfield is OPT-IN only.** Rationale: hyperframes output is
deterministic, brand-tokened HTML — safe to automate; AI-generated imagery
varies wildly and needs human eyes. **Higgsfield protocol when opted in:**
(1) the brain proposes prompts best suited to the short (or the operator
supplies/discusses them), (2) prompts are agreed BEFORE any API call, (3)
generations are reviewed together before they enter the composition. Never
fire-and-forget. Hard rules carry over: no AI text-in-image (text is HTML's
job), no faces by default. Generated assets still cache into broll/generated/
with their prompt as description.

### 3.3 Compositing

Extend the existing overlay stage: today it overlays timed PNGs (hook cards);
MG adds timed **alpha-video** inputs — same ffmpeg overlay graph with
`enable=between(t,s,e)`, mezzanine quality, captions still burn on top last.
Transitions (stingers) are the one full-frame case: crossfade the base video
under the stinger's alpha at cut points.

## 4. Skills vs logic (the operator's question, answered explicitly)

| Concern | LOGIC (deterministic code) | SKILL (judgment) |
|---|---|---|
| Find candidate moments | ✅ `motion_triggers.py`: regex/pattern pass over word-timed transcript → numbers, enumerations ("N things/shifts/ways"), entities, contrast markers, sequence markers. High recall, zero cost | — |
| Decide which candidates EARN a graphic | — | ✅ producer skill + new `references/motion-doctrine.md`: the earn-its-slot test, density budget vs mode, style restraint |
| Write the graphic's content (copy, values, list items) | — | ✅ brain, from the transcript verbatim (numbers never invented — lint cross-checks `spec` values appear in transcript text) |
| Template choice + slot fill | — | ✅ brain (hyperframes' own 21 skills assist authoring new templates) |
| Timing | ✅ derived from triggerWords via timeline map | brain may request nudges within lint bounds |
| Density/hold/collision enforcement | ✅ plan_lint | — |
| Render + composite + cache | ✅ hyperframes + overlays stage | — |
| QC | ✅ audit: frame per graphic midpoint, hold-time check, band collisions | ✅ vision review of extracted frames |

## 5. Phasing

**MG-1 — Proof on a real short (no pipeline changes).**
Install hyperframes (`npx skills add heygen-com/hyperframes`; Node 22+ check).
Author `tokens.css` + 3 templates (stat-card, list-build, kinetic-quote).
Hand-compose graphics for ONE existing short — c1 has a natural triple-list
("post more, save time, make more money") and a stat ("ten years in software")
— composite manually, deliver for review. **Exit: operator watches a
kinetic version of an approved short and calibrates taste.**

**MG-2 — Pipeline integration.**
`graphicsTrack` + `treatmentMap` schema + lint rules (incl. zone-budget
enforcement) + selftests; `motion_triggers.py` candidate detector;
editor-notes → treatment-map parsing in the producer skill; overlays stage
alpha-video support; render-graph caching; audit MG checks. **Exit: a plan
with graphicsTrack renders + audits clean end-to-end, driven by a real
editor-notes brief.**

**MG-3 — Vocabulary + long-form.**
(Implementation pointer from MG-2B: topic-boundary detection for chapter
stingers is the natural extension of `motion_triggers.py` — add a
`topic-boundary` trigger kind rather than a separate detector.)
Full template set (8+), chapter stingers, long-form density profile, punch-in
zooms between beats (pairs with jump cuts — pure ffmpeg, no HTML needed).
**Exit: long-form chapter transitions + intro sequence on the livestream cut.**

**MG-4 — Full auto + generation.**
Trigger detector feeds the brain by default in PRODUCE SHORT/LONG; Higgsfield
imagery inside comps; style variants per platform. **Exit: "produce a short"
yields motion graphics with zero extra operator input.**

## 5.5 Optimizations (2026-07-05 pass)

1. **Content-addressed render cache** — key = hash(spec + template content +
   tokens.css). Same graphic across plan revisions = $0/0s reuse. The single
   biggest lever for the feedback loop.
2. **Draft-quality preview path** — operator iteration renders at 540×960 /
   CRF 30 / no loudnorm verify (~4-6× faster); full quality only on approval.
   Pairs with partial re-render (§4.5 core plan) for near-interactive loops.
3. **Single-pass overlay batching** — composite all graphics + cards in ONE
   ffmpeg pass (chunked ≤8 overlay inputs per pass to keep filter graphs
   robust) instead of a pass per element.
4. **Parallel template renders** — comps are independent; render N at once
   (headless Chrome instances are cheap at these durations).
5. **Layout compositor primitives** — per Appendix A: center-crop,
   scale-to-band, blurred-pad, overlay-with-drawtext built ONCE as shared
   functions; layouts A–H are declarative compositions of them. No per-layout
   ffmpeg code.
6. **Idle-variant pre-renders** — each template ships with a pre-rendered
   sample (built at template-authoring time) so plan review can show the
   operator what a graphic will look like without a render round-trip.
7. **Already shipped, reused here**: mezzanine reuse across variants,
   stage-resume, transcript/vision caches, smartcut master patching (§4.5).

## 6. Open questions (parked, non-blocking)

1. ~~Brand tokens~~ SETTLED 2026-07-05 (rec adopted): accent = the Project Sniper
   badge blue, pixel-sampled from real footage into tokens.css. Fonts Inter.
2. **kinetic reference screenshots** — two drop attempts expired (macOS deletes
   thumbnail-drag temp files the instant the drag ends). Reliable path: save
   to Desktop/a folder, tell the session where; it sweeps them into permanent
   reference storage. They calibrate exact card styling/spacing/animation feel.
3. ~~Pilot pick~~ SETTLED (rec adopted): c1 is the MG-1 pilot (in progress).
4. How loud should the style be? Kinetic is maximalist; a dialed-back variant
   (fewer takeovers, more lower-thirds) may fit Project Sniper's visual system better. MG-1
   review answers this empirically.

---

## Appendix A — Layout archetype catalog (web research, 2026-07-05)

Eleven archetypes cataloged (operator's four + seven researched). Full report
with geometry percentages, caption/text zones, and sources in the session
research; condensed here. Automation: FF = pure ffmpeg · SEG = needs person
matting.

| # | Archetype | Tier | Auto | Note |
|---|---|---|---|---|
| A | Full-frame talking head + mid-frame captions | ubiquitous | FF | our `full-face`; captions y≈58-70% = our band ✓ |
| B | Kinetic text over lower-⅔ head → split | niche | FF | our `text-overhead`; reuses A+C compositors |
| C | Horizontal split: asset top / speaker bottom / captions in seam | ubiquitous | FF | our `split-critique`; = OpusClip Screenshare family |
| D | 16:9 centered + blurred pad + title in top blur | common | FF | our `blurpad-screen` ✓ |
| E | Greenscreen-cutout speaker over full asset | common | **SEG** | highest ceiling for critique; ONLY layout needing matting; flag-gated, build last |
| F | **Corner PiP webcam bubble over screen recording** | common | FF | "THE livestream money layout" for this creator; needs separate webcam track (or crop the baked-in corner cam) |
| G | Top-bar meme frame (solid bar + setup line) | common | FF | cheapest hook-delivery layout |
| H | Faceless b-roll + VO + captions | ubiquitous | FF | for no-speaker zones; NEEDS a music bed |
| I | Podcast stacked two-cam / audiogram | common | FF+diarization | deferred (needs two-cam source) |
| J | Chat/Reddit-story scroll over bg | niche | FF+templating | different genre; deferred |
| K | Duet / versus side-by-side | niche | FF | situational |

**Build order (research recommendation, adopted):** A, F, C, D, G, H, B, then E.
**Shared primitives:** center-crop · scale-to-band · blurred-pad · overlay-with-drawtext — archetypes A–H are compositions of these four.

**Music-per-layout mapping** (feeds the treatment map's audio hints):
talking-head/PiP → original voice IS the track, bed optional −18..−24dB;
critique/greenscreen → asset's own audio ducked under VO (convention);
documentary/story → bed REQUIRED (music does the emotional work);
asset-forward/meme-frame → clip's own audio, else trending sound (posting-side).
Trending audio = reach lever; original audio = identity lever (accounts <50K
measurably lift with original voice). Sources: OpusClip layout docs, House of
Marketers + Zeely safe zones, jeffbullas/Orphiq on audio strategy.
