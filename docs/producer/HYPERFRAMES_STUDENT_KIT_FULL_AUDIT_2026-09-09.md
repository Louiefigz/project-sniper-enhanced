# HyperFrames student kit: full adoption audit

**September 9, 2026 · Research and planning only**

## Decision

The kit is worth using selectively. Its greatest contribution to Project Sniper is **more explicit editorial judgment**, especially for recorded shorts and the opening of a long video. The first assessment gave the card library too much prominence and did not adequately examine the storytelling and short-form resources.

The recommended order is:

1. Improve how the editor plans and reviews the opening, promised payoff, visual explanations, shot variety and sound.
2. Reuse specific reference-analysis and asset-selection practices through the existing workflow.
3. Qualify a few diagrams that explain something the existing cards do not express well.
4. Leave the current HyperFrames runtime, editing timeline, audio system and delivery controls in charge.

This is an extension to the editor. It does not establish a new rendering engine, automatically make all catalog items usable, solve Studio playback, or demonstrate a two-hour turnaround. Benefits to creative quality are plausible and testable; saved hours and audience retention remain unmeasured.

## 1. What was audited

The source was pinned to **`b1afdb1dcbcad39dd27638ea699f132fe44ce6df`**, committed September 8, 2026. The kit package pins HyperFrames **0.7.109**; the project's installed and declared runtime is **0.8.31**. Current project-approved versions remain authoritative. [Pinned source](https://github.com/nateherkai/hyperframes-student-kit/tree/b1afdb1dcbcad39dd27638ea699f132fe44ce6df), [kit package](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/package.json), [project package](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/templates/motion/package.json).

The audit inventoried the complete 1,023-file Git tree and examined every major subsystem, including all 14 canonical skill entry points, their supporting-resource inventory, all 14 root helper scripts, skill-level executable helpers, both scene templates, the full card registry and all 406 card HTML sources, the 12 teaching-project structures, examples, setup, tests and provenance. The isolated checkout contained 828 text/source/provenance files. Of 94 mirrored skill resources, 91 had identical Git blobs and three differed only in skill-directory paths; these were not counted as extra capabilities.

Depth varied deliberately: the editorial resources and reusable helpers received detailed source review; all card sources received a structural scan, with selected implementations examined closely; teaching projects received source and dependency screening. This was **not a visual approval of every card or every example**. Media was not downloaded or played, no browser/render jobs were started, and no packages or skills were installed. The separate fresh video benchmark was not changed.

Evidence is preserved in the [audit inventory](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/audit-inventory.json), [complete Git-tree inventory](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/source-tree-inventory.json), [406-row card inventory](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/card-source-inventory.csv), and [local comparison source hashes](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/local-comparison-sources.json). Findings below distinguish source inspection, executed tests and proposed adoption.

## 2. Where the kit can actually improve editing

### A. Plan the opening as a complete audiovisual sequence

**Priority: first · Shorts and long-form openings · Editorial refinement**

`short-form-edit` asks for an opening that connects a specific viewer question, visible evidence and a source-supported answer. Its curiosity worksheet makes the editor identify what the viewer expects to learn and where the video actually delivers it. That is more useful than choosing attractive hook text alone. [Short-form workflow](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/SKILL.md), [curiosity and entertainment](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/curiosity-and-entertainment.md).

Sniper already asks for standalone hook/payoff, examines all source transcripts, and proposes hook variations. The useful addition is to join those decisions into one reviewable sequence: **what is promised, what appears immediately, which retained source moment proves it, and when the loop closes**. This is a refinement of the existing editor, not evidence that it previously had no storytelling ability. [Current Producer](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/.claude/skills/producer/SKILL.md:358), [existing hook contract](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/scripts/producer/hook_contract.py).

For the user's opening, activity every 2–4 seconds can be a reveal, demonstration, contrast, highlight or layout change within the same explanation. It need not be a succession of unrelated title cards. The viewer should gain something from each change.

**Adaptation:** add concise promise/evidence/payoff notes to the existing edit plan and review packet. Generate alternative opening concepts cheaply when uncertain. Do not make three rendered openings and a full animatic mandatory for every edit.

### B. Make graphics explain a cause and a result

**Priority: first · Both formats · Editorial refinement**

The short-form motion guidance separates meaningful visual action from decoration. A button press can create a task; a connected node can enable the next step; an accumulating result can demonstrate the payoff. It also calls out the redundancy of narration, captions and a headline all saying the same thing. [Motion and footage guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/premium-motion-and-footage.md).

Our semantic card selection already maps content to graphic families. The useful extension is to require an explanation of **what changes in the graphic and why the viewer needs to see that change**. An existing pipeline, comparison or chart can gain more from better choreography than from a new visual skin.

**Example of application, not a claim about the user's transcript:** for a verified explanation of a one-person operation, show one person performing several named functions, then show which functions a demonstrated tool takes over. Preserve the actual source's meaning and evidence; do not invent efficiencies, capabilities or numbers.

### C. Preserve visual context through a longer explanation

**Priority: first · Longs; selected shorts · Optional technique**

`video-storytelling` develops recognizable spatial context, persistent objects, deliberate focus changes and a return to the opening image for the payoff. The workbook demonstrates a small sequence whose parts accumulate into an understandable whole. [Storytelling skill](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/video-storytelling/SKILL.md), [neutral workbook](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/docs/STORYTELLING-WORKBOOK.md).

This can improve a multi-step lesson: show an overview, explain one part, return with that part completed, then progress. `hyperframes-video-beats` adds a complementary idea: keep a relevant supporting graphic available through the spoken explanation and reveal its parts at the appropriate words. [Beat guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/hyperframes-video-beats/SKILL.md).

**Adaptation:** reuse existing map, process and timed-reveal capabilities. Track the promised answer as well as the visible state. A recurring object alone is not proof of a meaningful open loop.

**Exclude:** forcing every video onto one permanent canvas, fixed presenter percentages, rigid color symbolism, or the kit's slower default beat intervals. Its fixed five-slot Python example is a design reference, not a general storyboard engine.

### D. Detect repetitive editing even when the cards have different names

**Priority: first · Especially shorts · Strong review refinement**

The short-form references recommend examining adjacent shots with the headings effectively removed. If the underlying action is always “a box arrives and text appears,” changing the title or color has not created much variety. They also examine anticipation, release and deliberate pauses instead of requiring constant uniform motion. [Reference-analysis worksheet](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/reference-analysis.md), [quality gates](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/quality-gates.md).

**Adaptation:** during the existing editorial review, flag consecutive shots that repeat the same visual mechanism without developing the idea. Record timestamped problems and a specific repair. Preserve good presenter expressions and useful pauses. Do not turn this into a new visual-event quota or a claimed retention score.

### E. Design sound around the visual action

**Priority: early · Both formats · Guidance, not another mixer**

The short-form resources distinguish a sound file's start from its audible impact, and map cues to anticipation, contact and release. They also call for a distinct listening pass in which speech remains intelligible against music and effects. [Short-form workflow](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/SKILL.md), [motion and footage guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/premium-motion-and-footage.md).

This is useful for the user's card/transition example: the graphic's reveal and sound should feel like one intentional event. The current audio pipeline still owns placement, gain, fades, source mapping and output QC. Imported loudness targets, universal splice lengths and mandatory whooshes must not override it.

**Adaptation:** add the intended audible impact to existing cue notes; use established audio controls to implement it. This can reduce creative revisions, but it cannot repair a decoder, sample-clock or Studio playback defect by itself.

### F. Choose real evidence and preserve the action when reframing it

**Priority: early · Both formats · Asset-planning refinement**

The kit asks the editor to inspect available footage before fixing the concept, distinguish actual moving footage from animated stills, and choose a shot that demonstrates the spoken point. Its footage ledger distinguishes source scenes from filenames: a crop, reversal or re-encode may still be the same shot. [Reference analysis](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/reference-analysis.md), [footage guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/premium-motion-and-footage.md).

Sniper already has admitted-source and hash checks; reuse them. Semantic repetition across different encodings remains a useful editorial review question, not something the kit's hash validator automatically recognizes. [Existing pool admission](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/scripts/producer/broll/pool_admission.py).

For portrait versions, inspect the action and its result at multiple moments. Keeping the presenter's face visible is necessary, but a demonstration also fails if the important button, hand or resulting screen is cropped away. This directly complements the user's requirement: whenever the presenter is shown, preserve framing through full-size, presentation and smaller-view transitions. No continuous head-following effect is required.

### G. Use reference videos to study sequence decisions

**Priority: early when a reference exists · Both formats · Mostly reinforcement**

The kit's reference worksheet asks what an entire sequence sets up and resolves, how the action changes, and how sound supports it. That is useful beyond extracting colors or a transition preset. However, our reference-editor already requires extensive source-frame coverage and separate mechanical/editorial review. [Kit worksheet](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/references/reference-analysis.md), [current reference-editor](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/.claude/skills/reference-editor/SKILL.md:63).

**Adaptation:** incorporate any missing sequence-level questions into that existing review. Do not add a second reference extraction pipeline. Finished showcase videos can be studied later as examples of hooks, pacing and sound, but they do not include editable source projects and were not watched during this audit. [Showcase scope](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/examples/showcase/README.md).

### H. Translate a brief into an appropriate asset and storyboard

**Priority: selective · Both formats and adjacent promos · Considerable overlap**

`make-a-video` contains a plain-language intent-to-catalog map, a shot-and-sound storyboard format, and structured style intake. `website-to-hyperframes` adds a useful asset-first habit: inspect authentic website assets and product screens before designing the scenes. [Catalog intent map](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/make-a-video/references/catalog-intent-map.md), [storyboard template](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/make-a-video/references/storyboard-template.md), [website workflow](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/website-to-hyperframes/SKILL.md).

These can support genuine product demonstrations in a long lesson, a short explanation, or a standalone promo. They do not add website capture to HyperFrames: **0.8.31 already documents `capture` and routes URL-led videos to a product-launch workflow**. [Installed capture documentation](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/templates/motion/node_modules/hyperframes/dist/skills/hyperframes-cli/references/init-and-scaffold.md:33), [current workflow routing](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/templates/motion/node_modules/hyperframes/dist/skills/hyperframes/SKILL.md:46).

**Adaptation:** improve the editor's questions and asset choices through its current brief. Reuse known user preferences. Do not import eight approval gates, additional paid-provider requirements, forced branded outros, fixed act percentages or dense decorative layers on every scene. Treat the old catalog map as examples; query our current catalog before choosing an asset.

## 3. All 14 skills: disposition

| Skill | Useful contribution | Adoption decision |
| --- | --- | --- |
| `short-form-edit` | Whole-shot hooks, explicit payoff, reference study, footage and sound discipline | Highest-priority guidance; adapt into Producer. Helpers require separate scrutiny. |
| `video-storytelling` | Spatial continuity, callbacks, focus and visible progress | High-priority optional techniques. Exclude rigid style rules and unshipped tooling. |
| `hyperframes-video-beats` | Spoken anchors and persistent explanatory graphics | Distill into existing beat planning; user pacing wins. |
| `make-a-video` | Brief, storyboard and intent-to-asset examples | Reuse selected prompts; current runtime workflow remains owner. |
| `website-to-hyperframes` | Asset-first product storytelling and brand reference | Conditional website/demo sourcing guidance; capture already exists. |
| `style-library` | Purpose/slot-based graphic discovery | Reference source for a small diagram pilot, not bulk import. |
| `short-form-video` | Existing May Shorts example maintenance | **Legacy scaffold. Do not use as the new short-form workflow.** |
| `edit-video` | Beginner sequence of transcript, silence and mistake editing | Mostly duplicate orchestration; do not add another pipeline. |
| `cut-silences` | Transcript-driven pause proposals and review | Existing source-aware pause tools stay; do not universally shorten pauses. |
| `cut-mistakes` | Candidate repeats plus reviewed removal | Existing retake/cut tools stay; do not assume the later take is better. |
| `hyperframes` | Older core/style/caption guidance and reference tools | Installed 0.8.31 documentation wins. Select design ideas only. |
| `hyperframes-cli` | Older CLI workflow | Do not install over current instructions. |
| `hyperframes-registry` | Catalog lookup and composition wiring | Already available; current registry contract wins. |
| `gsap` | Animation recipes and audio-data extraction | Reference-only; choose seek-safe patterns supported by the current runtime. |

The distinction between `short-form-edit` and `short-form-video` is explicit in the source, not inferred from their names. [Current short workflow](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/SKILL.md), [legacy short workflow](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-video/SKILL.md). The complete resource list is preserved with the source inventory.

## 4. The entire card library, and what is genuinely worth considering

The registry contains **106 Vox-style and 300 Kallaway-style cards**, all marked draft. Its five purposes are 78 section cards, 101 stat cards, 81 overviews, 73 lower thirds and 73 labels. There are 260 tier-one and 146 tier-two items. These are catalog entries, not 406 distinct editorial capabilities. [Pinned registry](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-library/registry.json).

The structural audit found:

- All 406 roots declare **1920×1080**. Portrait capability must be designed and verified separately.
- All 406 reference an external script or stylesheet; local dependency preparation is needed for a self-contained project.
- None declares duration on the card root. This is not automatically a runtime defect—mounted duration can be supplied by a host—but it prevents treating the standalone source as an already-qualified project asset.
- The registry names preview paths, but **none of those preview files exists in the pinned Git tree**.
- Four cards have slots absent from literal parsed HTML. Three use JavaScript-generated markup; the number-callout implementation has a declared term lookup with a default fallback. Source slot names alone therefore do not prove editable copy reaches the visible result.

These are source findings, not claims that every card fails. The upstream verification itself says the 406 drafts were not individually rendered and approved. [Upstream verification](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/docs/VERIFICATION.md), [audited card rows](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/card-source-inventory.csv).

| Candidate or family | Why it may help | Existing overlap and limit |
| --- | --- | --- |
| **Venn relationship** | Explain overlapping responsibilities, tools or concepts | More specific visual vocabulary than another list. Source uses fixed circles/positions; qualify actual copy and aspect. |
| **Two-axis matrix** | Locate choices along two meaningful dimensions | Useful classification view; distinguish it from the existing two-way comparison. It is not a data-driven scatterplot. |
| **Funnel / narrowing stages** | Explain a process that loses options or narrows candidates | Existing pipeline covers generic steps. Source widths are fixed independently of displayed percentages: use only as a schematic or adapt real quantitative geometry. |
| Cycle, tree, hierarchy, nested layers, spectrum | Explain feedback loops, dependencies or ordered tradeoffs | Compare against existing mindmap/flow/whiteboard tools first. Reserve until a real episode needs a distinct relationship. |
| Source footnote, definition, annotation, formula and evidence labels | Put a short supporting explanation beside footage | Existing callouts, markers and lower thirds cover much of this; meaningful content roles matter more than a different skin. |
| Gauges, rings, counters, dashboards, quotes, social and section cards | More styling choices | High overlap with local and official catalog items. Low priority; no bulk port. |

Selected source implementations: [Venn](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-library/02-kallaway/cards/tier1/t1-overview-venn.html), [matrix](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-library/02-kallaway/cards/tier1/t1-overview-matrix.html), [funnel](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-library/02-kallaway/cards/tier1/t1-overview-funnel.html), [number callout](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-library/02-kallaway/cards/tier2/t2-lb-numbercallout.html).

The existing discovery system already distinguishes reference material from integrated/measured capabilities. Reuse that separation. Keep existing motion cards and the official catalog available, with no preference bonus for imported assets. **Start with one useful diagram; three families is a ceiling for the first pilot, not an obligation.** [Current discovery](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/scripts/producer/graphics/catalog_discovery.py).

## 5. Executable helpers: actual findings, not documentation promises

### Tests executed

The kit's **11 included behavior tests passed** on Node v23.10.0. They exercise basic cut retiming, cut bounds, beat timing, caption drift, scene coverage and footage-ledger behavior. These were text-only tests; no FFmpeg render or paid transcription was invoked. [Saved test output](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/upstream-tests.txt), [upstream tests](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/tests/short-form.test.mjs).

Nine additional probes tested the two short-form validators. A valid control passed; missing and shifted captions were correctly rejected. **Six inputs that would be unacceptable for Sniper were accepted:**

| Probe | Result and implication |
| --- | --- |
| Missing program duration | Accepted; downstream arithmetic can become non-finite without an error. |
| Missing scene end | Accepted; coverage comparison alone does not establish a valid interval. |
| Anchor phrase absent from the transcript | Accepted; the helper checks presence and nearby time, not that the words were spoken. |
| Scene/program end at 1.01 seconds with 30 fps | Accepted; scene starts are checked for frame alignment, ends are not. |
| Changed source end for a retained word | Accepted; source-start mapping is checked, mapped word end is not. |
| Infinite footage end | Accepted by the pure validator; interval comparisons lack a finite-number requirement. The probe obtains infinity from JSON `1e400`. |

This is a small targeted counterexample set, not a statistical reliability score. It demonstrates why copying the helper scripts would not be an upgrade to our timing authority. [Reproducer](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/reproduce-validator-probes.mjs), [results](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/evidence/student-kit-audit-2026-09-09/validator-probe-results.json), [plan validator](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/scripts/validate-plan.mjs), [footage validator](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/scripts/validate-footage.mjs).

### Every root helper script

| Script | Finding / recommendation |
| --- | --- |
| `build-edl-review.mjs` | Useful kept/cut visualization and direct jumps to removed material. Players are not a source-to-output synchronized comparison. Consider the interaction in our current review UI; do not add another render requirement. |
| `check-kit.mjs` | Distribution/structure checks, not visual or current-runtime approval. Remote references and historical video projects are not end-to-end qualified. |
| `new-video.mjs` | Starter scaffolding; redundant with current project tooling. |
| `preflight.mjs` | Regex-based assumptions about root attributes and timeline variable names can reject valid current constructions or miss invalid ones. Keep current CLI and project contracts. |
| `preflight-all.mjs` | Runs the older preflight across projects; does not establish playback correctness. |
| `setup.mjs` | Installs/copies the kit environment and skill configuration. Excluded from adoption. |
| `smoke-media.mjs` | Eight-second synthetic picture/tone exercise. Useful example of a narrow smoke test; no proof of natural speech joins or a full real edit. Not run here. |
| `style-library/build-registry.mjs` | Rebuilds metadata; warnings and declared files are not admission evidence. Do not create a second catalog authority. |
| `style-library/gen-kallaway-style.mjs` | Derives manifest entries from filenames and source slots. Packaging utility, not new editing capability. |
| `style-library/new-style.mjs` | Copies the style blueprint. Low priority alongside existing template contracts. |
| `sync-codex-skills.mjs` | Mirrors instructions for agent environments. Do not sync them into our active skill trees. |
| `transcribe-elevenlabs.mjs` | Adds an unnecessary provider path. Its temporary MP3 uses a predictable source-adjacent filename with overwrite and cleanup: it can clobber an existing sibling MP3. Do not reuse wholesale. |
| `validate-beat-sync.mjs` | Narrow anchor check; allows up to 1.8 seconds of lead, unlike the stricter short-form guidance. Does not replace word/frame/sample validation. |
| `video-use-to-hyperframes-transcript.mjs` | Simplified range conversion, partial-word clipping and missing-transcript continuation; inadequate as our multi-source/speed-aware timing authority. |

Primary implementations: [root scripts](https://github.com/nateherkai/hyperframes-student-kit/tree/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/scripts), [beat validator](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/scripts/validate-beat-sync.mjs), [transcript converter](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/scripts/video-use-to-hyperframes-transcript.mjs), [transcription helper](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/scripts/transcribe-elevenlabs.mjs), [EDL review](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/scripts/build-edl-review.mjs).

### Helpers inside skills and references

The silence and mistake scripts provide a beginner cut pipeline, but their staged full-video outputs would add encoding and intermediate storage if adopted literally. Candidate-repeat detection uses a text-similarity heuristic; a later similar segment is not automatically a better take. Keep our existing canonical cut plan and reviewed pause/retake tools. [Cut candidates](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/cut-mistakes/scripts/find-cut-candidates.mjs), [cut application](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/cut-mistakes/scripts/apply-cuts.mjs), [silence helper](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/cut-silences/scripts/cut-silences.mjs).

Two less obvious tools deserve mention:

- **Animation-map inspector:** enumerates GSAP tweens and samples element bounds to describe motion, collisions and inactive intervals. The reporting idea can assist diagnosis. The script imports internal `@hyperframes/producer` APIs, samples a representative target, and uses heuristic temporal/geometry checks. Nested traversal can revisit descendants. It is not proof that actual footage or all moving elements remain visible. Sniper already has an animation-map contract and filmstrip checkpoints. [Kit inspector](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/hyperframes/scripts/animation-map.mjs), [local animation map](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/scripts/producer/graphics/animation_map.py).
- **Contrast report:** proposes time-sampled text readability over rendered backgrounds. However, it estimates background from a ring outside the text bounds, which can differ from the pixels behind the glyphs, and also imports internal producer APIs. Treat it as a diagnostic idea, not an automatic pass for translucent text over moving footage. Sniper already has source-bound text-plate and contrast checks. [Kit report](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/hyperframes/scripts/contrast-report.mjs), [local text contrast](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/scripts/producer/graphics/template_text_contrast.py).

The GSAP audio extractor offers RMS/frequency data for optional music-responsive graphics. Current HyperFrames already has beat analysis and a music-led workflow. The kit helper decodes the whole track into memory and uses integer samples-per-frame; non-divisor frame rates can drift. Its references also disagree on per-frame callbacks versus build-time tweens. Do not import it as a synchronization primitive or make reactive captions mandatory. [Extractor](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/gsap/scripts/extract-audio-data.py), [audio-reactive reference](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/hyperframes/references/audio-reactive.md), [caption techniques](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/hyperframes/references/dynamic-techniques.md).

Finally, the storytelling docs refer to `qa-tokens`, `qa-no-crossfade`, `qa-legibility`, `qa-seamjump`, `qa-deadframe`, `qa-presence`, `qa-exposure` and a flicker script that are **not shipped in this tree**. Those are lessons/check ideas, not ready-to-run additions. The wall-of-slots geometry has fixed example-specific positions and an acknowledged recap inconsistency. [Design-system references](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/video-storytelling/reference/design-system.md), [wall reference and known gap](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/video-storytelling/reference/patterns/wall-of-slots/README.md).

## 6. Templates, teaching projects and other overlooked resources

### Two scene templates

**Left glass popout** illustrates a panel entering while the camera image changes scale. This is relevant to the user's presenter/presentation transitions as a choreography reference. It is not automatic safe framing: the source uses a fixed left-anchored **1.30× zoom**, a fixed 52.67-second source duration and fixed card timing. It does not detect or verify the face, create a general bubble layout, or prove safe entry/exit for different footage. It also applies a fixed color filter. Adapt the idea through current framing/layout controls, not by replacing them. [Actual template](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-templates/left-glass-popout/index.html).

**Dark graph paper** is an optional background texture. It adds no editing capability and should not replace the current brand or consume a mandatory full-video layer. Both templates use a public GSAP CDN in source. [Template scope](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-templates/README.md).

### All 12 teaching projects

| Project | Potential lesson | Boundary |
| --- | --- | --- |
| `aisoc-app-release` | Tease, reveal, product showcase and outro sequencing | Branded promo example, not a generic long-form editor. |
| `aisoc-hype` | Problem/proof/benefit pacing | Reference composition only. |
| `aisoc-lesson-5-1` | Teacher beside explanatory materials; topic-aligned reveals | Fixed PiP/crop; storyboard intentionally ends mid-lesson. Not evidence of a complete standalone payoff. |
| `claude-edit-intro` | Caption, chart and PiP demonstrations | Older fixed source/layout and debug assumptions. |
| `clickup-demo` | Authentic product-action footage and still selection | Includes account-specific browser/API scripts; some create external tasks/lists. Do not run or port that orchestration. |
| `first-agent-promo` | Bespoke promo transitions and visual sequence | React/Babel prototype with a custom frame-capture route; exclude that separate renderer. |
| `golden-ratio-demo` | An explanatory visual motif that returns at the ending | Keep the callback lesson; do not import fixed palette, constant whip transitions or audio-reactive presenter motion. |
| `hyperframes-sizzle` | Examples of charts, UI, shaders and transitions | Many examples overlap the official catalog. No new shader/render stack. |
| `linear-promo-30s` | Product screenshot sequencing and shape continuity | Brand-specific and includes old Studio diagnostic scripts. |
| `may-shorts-18` | Source/caption/reveal timing reference | Legacy fixed short scaffold. |
| `may-shorts-19` | Another edited short with seam treatments | Legacy fixed short scaffold; archived scene versions are not extra production features. |
| `may-shorts-6` | Talking-head/card sequence | Landscape example despite “shorts” name; not proof of portrait readiness. |

These projects were source-screened, not visually re-rendered. Their metadata and text-path inventory are retained in the audit evidence. Useful primary examples: [lesson storyboard](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/video-projects/aisoc-lesson-5-1/STORYBOARD.md), [callback storyboard](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/video-projects/golden-ratio-demo/STORYBOARD.md), [ClickUp population script](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/video-projects/clickup-demo/scripts/populate.mjs), [separate capture script](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/video-projects/first-agent-promo/scripts/capture.mjs).

The starter and synthetic editing examples are teaching fixtures. The prompt/workbook documents are useful training references, not additional engines. The three finished showcase videos have no editable project sources in the kit. Design palettes, typography and motion recipe files can expand creative vocabulary, but their fixed style preferences must not become universal editing rules.

The source includes reuse permissions for teaching material and separate third-party notices. Preserve applicable notices for copied source; replace placeholder statistics, source labels and branding with verified episode content. Included third-party assets and showcase footage do not carry blanket reuse rights. [Permission](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/licenses/PIPELINE-USE-PERMISSION.txt), [provenance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/THIRD_PARTY_NOTICES.md).

## 7. Compatibility and scope decisions

Do **not** merge the kit's agent instructions wholesale. They contain conflicting defaults: mandatory continuous movement versus intentional holds, hard-cut bans versus deliberate clean cuts, old duration-padding conventions, and different audio-reactive patterns. Several reference paths use older skill names. Apply narrowly selected ideas under the current project contract.

Version age alone does not prove a card incompatible. Straightforward adaptation of copy slots, local assets, scope and layout may be worthwhile. However, if an item needs an older runtime, SDK patch, alternate renderer or special compatibility layer, **drop it**. Do not interpret a successful static scan as native Studio compatibility.

The installed 0.8.31 entry point already separates plain captions, overlays on unchanged footage, custom footage edits, music-led videos and URL-led promos. Retiming, reordering, reframing and mixing footage belong to its custom-edit route; a similarly named talking-head overlay route is not automatically appropriate for our full edit. This routing is documentation evidence, not a declaration that every route has been independently proven in our project. [Current routing and edit cross-references](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/templates/motion/node_modules/hyperframes/dist/skills/hyperframes/SKILL.md:46).

No kit material examined supplies a demonstrated solution to our full-video playback, temporary-storage, render-cache, final cleanup or end-to-end benchmark requirements. Those remain owned by current development and its actual output tests. Adopting the staged cut MP4s, full-frame PNG capture, or mandatory multiple drafts could increase time and storage.

## 8. Bounded adoption and how to judge the benefit

The revised [adoption plan](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/HYPERFRAMES_STUDENT_KIT_ADOPTION_PLAN_2026-09-09.md) remains the execution document. This audit changes priorities and resolves inspection unknowns; it does not install or enable anything.

**First increment: guidance only.** Add the useful differences to an appropriate Producer reference and the existing review packet: promise/evidence/payoff, what changes in each explanatory graphic, continuity, adjacent-shot repetition, source-backed action, and intended sound impact. Reuse current settings and approval decisions. No new mandatory render pass or document bundle.

**Second increment: compare on actual editing work.** After the independent benchmark, use one short and one long-form section. Measure authoring time, creative revisions, time to an editable Studio preview, and any additional preview/export/storage cost separately. Review source-faithful payoff, explanatory clarity, visual repetition, intelligibility and presenter/action framing. Quality judgments should name exact moments; audience retention requires audience data.

**Third increment: one diagram where it earns its place.** Start from a content need the existing catalog serves poorly. Venn or a two-axis classification is a reasonable first candidate. Keep funnel treatment conditional on truthful geometry. Qualify two instances, actual copy, mounted duration, local assets, seek/restart/reload, entry/exit and saved editability, then compare native preview and export. Qualify 9:16 separately.

**Stop rule:** skip a candidate already served well by the current library; reject one that requires a runtime compromise; do not expand a pilot that adds disproportionate work. The plan's 45-minute initial compatibility-investigation cap per asset family is a work limit, not an estimate of implementation time.

This can help the editor make better choices and may reduce creative rework. It has **not yet demonstrated substantial end-to-end time savings**. A successful first adoption can consist entirely of better editorial guidance; importing a large library is not a prerequisite for finishing or testing a full video.
