---
name: reference-editor
description: Study a finished reference video or raw+edited pair meticulously, frame by frame; classify its cuts, graphics, transitions, animation, layout, typography, captions, color, audio, and editorial intent; save evidence-bound templates and reference-inspired profile guidance for the producer skill. Use when the operator shares a YouTube, Instagram, TikTok, or local video and asks to study its edit style or build templates from it. Verified mimic/replication is not a released capability.
---

# Reference Editor

Turn reference evidence into a reusable editing grammar, then use that grammar
to produce new content. Copy structure and mechanics only—never copy creator
identity, words, claims, logos, footage, screenshots, music, or branding.

**Qualification boundary:** this workflow produces a study/profile and planning
guidance. Verified mimic is not released (P6 is 0/7). The safe output is an
audited exact MP4 or its approved flat mirror; editable Palmier application is
an isolated, production-shaped experiment whose connected hybrid path remains
P5-blocked. Palmier Pro is not configured in the packaged release, so its steps
below do not apply there. Fetching a reference link downloads it with `yt-dlp`;
Chrome cookies are read only with the operator's explicit per-fetch permission.

## Choose the workflow

When applying a particular shot/style explicitly requested by the operator,
persist its shot-to-catalog decisions through the shared
[reference-shot reuse map](../../../docs/producer/REFERENCE_SHOT_REUSE.md).
Research-only library enrichment and ordinary inspiration do not require a
project-bound map. The map preserves inspected choices for Short and Long native
planning; it does not replace the detailed visual study or qualify a style match.

- **Research for a close functional match:** study complete narrative coverage,
  align spoken/caption cues with the visuals, inspect important motion windows,
  and map the storytelling jobs to inspected HyperFrames catalog sources. Prefer
  reuse, configuration and composition before bounded custom work. State which
  frames/audio were actually reviewed, timing confidence and unverified candidate
  behavior. This delivers research/planning guidance, not a compiled style pack;
  it does not invoke the replica builds or compilation steps below. If exact
  motion or word-lock claims are needed, obtain the corresponding frame/audio
  evidence before making them. Do not turn a small sample into global cadence
  constants. Use this mode when the operator prioritizes close catalog matches.
  Save selected actual creator frames with timestamped context sequences and
  paired story/layout/type/timing notes. Follow the existing
  [Shorts reference library](../../../resources/references/README.md):
  retain source URL/time/hash, a stable reference ID, what was visually reviewed,
  the exact inspected candidate source and any adaptation gap. Keep observed
  behavior separate from proposed improvements. The Producer must open selected
  images during planning and compare the same targets during native preview QA;
  a prose description is not a substitute for looking at the reference.
  Use [Format foundations](../../../resources/references/shorts/FORMAT_FOUNDATIONS.md)
  to extract the message, viewing need, format choice, actual framing, meaningful
  development and exit condition. Compare a complete case with a plausible
  alternative, including within one creator's work. Transfer the function and
  hierarchy to the new source; keep observed behavior, inferred purpose and
  proposed improvements distinct. A split needs readable content and deliberate
  presenter framing as well as two pane jobs. Include counterexamples and
  limitations rather than treating every reference decision as a quality target.
- **Learn only:** reference → meticulous study → evidence-bound templates →
  study pack.
- **Apply existing:** study pack + new source → reference-inspired Producer
  plan → exact MP4.
- **Learn and apply:** complete Learn first; never plan the new edit while the
  reference review is incomplete.
- **Raw + edited pair:** run the same visual study on the edited video and also
  use `scripts/producer/edit/study_edit_diff.py`; the pair is stronger evidence
  for keep/remove decisions than a finished reference alone.

Before writing review JSON, read
`references/STYLE_PACK_SCHEMA.md`. When a new template is required, also read
`.claude/skills/producer-study/SKILL.md` in full and follow its build/verification
bar.

## 1. Intake and provenance

For a URL, choose a dedicated directory under `_references/` in the operator's video workspace
(`${SNIPER_WORKSPACE_ROOT:-$HOME/ProjectSniper}/_references/`)
and run:

```bash
.venv/bin/python3 scripts/producer/study/fetch_reference.py \
  --url <URL> --out-dir <REFERENCE_DIR>
```

Use `--allow-cookies` only after explicit operator permission. Preserve the
downloaded VTT. For a local file, do not move or rewrite it. Record the exact
video path printed by intake.

## 2. Meticulous frame study

Run the deep extractor at source cadence, not the ordinary 30 fps cap:

```bash
.venv/bin/python3 scripts/producer/study/study_deep.py \
  <VIDEO> <STUDY_DIR> --meticulous --transcript <TIMED_TRANSCRIPT>
.venv/bin/python3 scripts/producer/study/reference_style_cli.py prepare \
  <VIDEO> <STUDY_DIR>/deep_study.json <STUDY_DIR>/reference-review
```

If no timed transcript exists, use the cached local-Whisper path before study.
Never use untimed prose as word-lock evidence.

The extractor scans every source-cadence frame deterministically. The review
worklist merges overlapping edit events so interacting animation is inspected
together. Every event window includes every source frame plus three frames
before and six after. Non-event spans are covered by start/mid/end frames.
`unclassifiedRuns > 0`, missing frames, or uncovered source frames blocks the
style pack.

## 3. Two independent visual looks

Initialize the two bound receipts:

```bash
.venv/bin/python3 scripts/producer/study/reference_style_cli.py init-review \
  <WORKLIST> mechanics <STUDY_DIR>/mechanics-review.json
.venv/bin/python3 scripts/producer/study/reference_style_cli.py init-review \
  <WORKLIST> editorial <STUDY_DIR>/editorial-review.json
```

### Look A — mechanics, chronological

View every contact-sheet page in chronological order. For every event, inspect
the full frame sequence—not only entrance/settled/exit. Record geometry,
presenter placement, transition boundary, build order, attack/hold/release,
easing, typography, palette, contrast, occlusion, and animation modules. Open
the original-resolution frames whenever a sheet is ambiguous.

### Look B — editorial, reverse chronological

Use a fresh review context and do not expose the mechanics receipt. View every
sheet again in reverse order. Classify what the graphic communicates, why it
appears on those words, whether it progresses, what structure is reusable, and
whether an existing template actually matches. Reversing order reduces
anchoring to the first pass.

Both passes must classify every worklist item with the same five shared fields.
Confidence below 0.80 requires an original-frame drill-down. Never pass an item
with a material issue.

If the shared classifications disagree, initialize an `adjudication` receipt,
inspect the disputed frame sequences a third time, and resolve only from pixels
and transcript evidence. The compiler refuses unresolved disagreement.

## 4. Bind or build templates

Read the existing catalog first:

```bash
.venv/bin/python3 scripts/producer/graphics/template_contract_cli.py --catalog
```

After both reviews agree, initialize the bound registry instead of hand-copying
item ids or hashes:

```bash
.venv/bin/python3 scripts/producer/study/reference_style_cli.py init-templates \
  <WORKLIST> <MECHANICS_REVIEW> <EDITORIAL_REVIEW> \
  <STUDY_DIR>/template-registry.json [--adjudication <ADJUDICATION_REVIEW>]
```

For each reviewed graphic window:

1. Reuse a catalog template only when information anatomy, layout chassis, and
   animation grammar genuinely match.
2. Otherwise build a new composition under
   `templates/motion/compositions/` using house tokens and reference structure.
3. Render realistic data, inspect every animation phase beside the reference,
   run template validation and pixel/alpha proof, and save the proof frame.
4. Write a template-registry binding with `structureOnly:true`. A reference
   graphic without a verified `matched|built` binding blocks compilation.

Do not create cosmetic aliases to fake variety. One renderer earns one name.

## 5. Compile the immutable study pack

Fill every generated registry row with its verified binding, then run:

```bash
.venv/bin/python3 scripts/producer/study/reference_style_cli.py compile \
  <WORKLIST> <MECHANICS_REVIEW> <EDITORIAL_REVIEW> <TEMPLATE_REGISTRY> \
  <DEEP_STUDY> <STUDY_DIR>/reference_style_pack.json \
  [--adjudication <ADJUDICATION_REVIEW>]
```

Compilation requires complete source-frame coverage, two passing reviews,
classification agreement, zero unclassified motion runs, source/worklist hash
binding, and proof for every reusable graphic template. Never hand-author or
edit a compiled pack.

## 6. Use the grammar as guidance for new content

Invoke the `producer` skill and default to its exact rendered-file branch. Read
the complete study pack before visual planning. Map new transcript beats to the
reference's **information forms**, then use compatible bound templates; never
paste reference copy or force a reference device onto an incompatible beat.

Every planned reference-derived row must retain its evidence binding:

- `graphicsTrack[]`: `referenceGrammarId`, `informationForm`, bound `kind`.
- `transitions[]`: `referenceGrammarId`, bound transition `kind`.
- `punchIns[]`: `referenceGrammarId`, `referenceAnimationFamily`.

Run both reference gates before unlocking Palmier:

```bash
.venv/bin/python3 scripts/producer/reference_profile_lint.py <PLAN> <PROFILE> \
  --reference-id <ID> --mode <short|longform> --strategy mimic
.venv/bin/python3 scripts/producer/reference_style_pack_lint.py \
  <PLAN> <STYLE_PACK> --reference-id <ID>
```

Render and audit the exact MP4 through the producer contract. If the operator
explicitly requests the editable Palmier experiment, use only an isolated
candidate and still finish with exact-candidate export, deterministic Audit B,
and both rendered reviews. That experiment is not connected P5 qualification.

## Completion standard

Report separately:

- What was measured from every frame.
- What was judged twice and adjudicated.
- Which templates were reused versus newly built.
- What mechanics transferred and what could not transfer to the new content.
- Exact MP4 export/QC evidence; if separately exercised, label Palmier evidence
  experimental.

One reference may produce a reference-bound study pack, not a verified mimic.
Promote a durable house style only after multiple references, variance analysis,
operator approval, and the currently missing P6 qualification.
