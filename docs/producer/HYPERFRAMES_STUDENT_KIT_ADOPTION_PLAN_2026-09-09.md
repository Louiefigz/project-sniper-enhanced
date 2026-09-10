# HyperFrames student kit: selective adoption plan

Date: September 9, 2026. Status: editorial guidance adopted in the canonical
Producer prompt; asset integration remains planned. No kit runtime or card
installed or admitted by this adoption.

The second, full audit is complete: see [findings, all-skill dispositions, helper tests and catalog evidence](/Users/aaronfigueroa/development/demos/YT-Automation/PROJECT_SNIPER/docs/producer/HYPERFRAMES_STUDENT_KIT_FULL_AUDIT_2026-09-09.md). Its pinned source is `b1afdb1dcbcad39dd27638ea699f132fe44ce6df`. This plan incorporates that audit; implementation and current-runtime asset qualification remain separate work.

## Decision and scope

Use the kit as an optional extension for **both shorts and longs**, wherever an individual asset or editorial technique earns its place. **Prioritize the storytelling and short-form editorial guidance before card imports.** The user clarified that better editing decisions are the principal opportunity. Start asset adoption with a small long-form graphics pilot because the source cards are landscape; qualify selected vertical adaptations separately.

The user's requirements are authoritative: preserve our motion graphic cards, current editing system and native HyperFrames Studio delivery. The project's pinned HyperFrames runtime is currently **0.8.31**; the kit pins **0.7.109**. Our runtime and subsequent project-approved upgrades win. Do not downgrade, install a second older runtime, patch the SDK, or build a compatibility layer to accommodate a kit item. Drop incompatible items.

Preserve saved C0679 Attempts A/B and their footage, creative choices,
dependencies and benchmark evidence. B is now sealed. Aaron's subsequent review
authorizes a separate creative revision using more visual variety and a
full-frame opening. This plan neither claims kit assets are compatible nor
promises a reduction in editing hours.

The shared `.claude/skills/producer/SKILL.md` now contains the distilled visual
storytelling instructions for produced/full shorts and longs. The Codex adapter
and Claude `/produce` command route to it. Existing headless authoring already
reads and snapshots this canonical skill; no second prompt or planner was added.
Aaron's full-frame opening and Chrome handoff preferences are explicitly scoped
to his jobs. Older pinned runs retain their original doctrine. The separate
production revision and subsequent viewing must establish whether these prompt
changes improve actual output; guidance adoption is not visual qualification.

## What belongs where

| Material | Destination | Proposed use | Selection boundary |
| --- | --- | --- | --- |
| Card registry, semantic categories and named content slots | Both | Discover a graphic by the idea it explains; preserve source identity and slot limits | Metadata is reference evidence, not permission to put a card in a plan |
| Transparent supporting graphics | Longs first; selected shorts | Definitions, concise evidence and process reveals alongside footage | Must add useful expression beyond an existing card and keep the face, presentation and captions clear |
| Diagrams and comparisons | Longs first; vertical versions only where readable | Explain relationships, changing states or a before/after | Compare against our existing whiteboard, pipeline, comparison and chart families before selecting |
| Opaque statement/section cards | Either, sparingly | A deliberate hook, chapter break or payoff | No return to a mostly full-screen-card treatment; skip duplicates of existing takeovers and markers |
| Storytelling and transcript-anchored reveal guidance | Both | Match each visual to a spoken idea; reveal supporting parts at the right words; use callbacks when useful | Adapt to our brief; do not import fixed pacing, mandatory visual styles or extra opening renders |
| Short-form source mapping, footage reuse and caption timing checks | Shorts; source timing principles also help longs | Use the audit's counterexamples to evaluate a demonstrated gap in our existing controls | Do not copy the upstream helpers: six invalid inputs passed targeted probes; preserve our schema and timing authority |
| Sound choreography, authentic demonstration footage and shot-variety review | Both | Connect audible impacts, visible actions and results; flag repeated visual mechanisms and semantic footage reuse | Extend current cue notes, asset admission and editorial review; no extra mixer, provider or review pipeline |
| Website/product asset selection and brief-to-storyboard guidance | Both where relevant; optional promos | Source useful product evidence and plan shots against real available assets | Current HyperFrames already provides capture and workflow routing; do not duplicate them |
| Upstream editor, transcription, silence-cut and render orchestration | No adoption in this phase | Existing system continues to own these functions | Do not add another EDL, transcript authority, audio path, paid service or staged full-video render pipeline |
| Package files, bundled HyperFrames skills, setup scripts and old runtime workarounds | Exclude | None | Keep our package lock, installed tools, local instructions and runtime behavior |

The pinned source has 406 **draft** cards: all declare 1920×1080, all reference an external script or stylesheet, and none has its registry-named preview in the Git tree. The audit structurally scanned every card and inspected selected implementations; it did not render them. “406 available references” must never become “406 production-ready additions.”

## How it extends the current system

Use one existing selection flow: spoken idea and edit intent → catalog candidates → compatible asset and layout → native Studio composition → existing export and review gates. The kit supplies additional candidates and design references, not another editing system.

The current `scripts/producer/graphics/catalog_discovery*.py` modules already distinguish reference items from integrated, measured items. Their source loader currently knows the official mirror and local registry; it is not a generic plug-in loader. If the pilot justifies a persistent kit inventory, extend that seam with explicit source identity and tests. Do not put kit rows in the official HyperFrames mirror or inherit approval from a similar local name.

Preserve the existing planner, scope, timing and placement rules. `graphics_planner.py` remains the proposer where that route is used; kit availability does not activate graphics on a trim-only request or change the chosen visual profile. An editor may choose an existing card, an official catalog transition, a qualified kit graphic, or no graphic according to the content. There is no kit quota or preference bonus.

For reusable registered templates, retain the existing typed-variable contract, capability measurements and scene adapter. Never hand-author a passing row in `comp_capabilities.json`. For the current native authoring route, use its existing scene/package contracts and actual Studio/export evidence. Registration measurements alone do not establish native delivery compatibility.

The Studio transformation modules already address unique composition identities, scoped styles, local dependencies and mounted duration. Inspect and reuse those mechanisms where applicable; do not paste standalone HTML directly into a timeline. The older `studio/project_writer.py` describes a review-only view, so success in that view alone is not proof of a finished native project. Keep native graphics editable during review; do not bake every card revision into a full-footage MP4 to make the import work.

## Execution sequence

### 0. Strengthen editorial decisions before adding designs

Compare the kit's `video-storytelling`, `short-form-edit` and `hyperframes-video-beats` guidance against our canonical Producer skill. Existing Producer guidance already covers standalone hook/payoff, multiple hook-copy candidates, protected pauses, semantic graphic selection, attention and pacing. Do not describe these as newly acquired abilities.

The promising extensions are more explicit sequence-level review:

- **Shorts:** assess the opening as footage, words and sound together; name the specific viewer question, identify the source moment that answers it, and ensure that answer arrives before the CTA. Judge each subsequent shot by the new evidence or consequence it provides. Avoid having narration, captions and a graphic all repeat the same sentence.
- **Longs:** maintain recognizable visual context through an explanation, guide attention to one active idea, and visibly advance a promised result toward completion. A persistent diagram can help a process explanation; it is an optional technique, not a requirement to turn every video into one large animated canvas.
- **Both:** use narration anchors to choose reveals and transitions, preserve natural pauses and presenter expressions, and review transitions in motion. Apply these decisions through the existing edit plan and review packet, without a second timing authority or a duplicate validation system.
- **Shot variety:** examine adjacent shots by their visual action, not their headings or colors. Repair repetitive card entrances that do not develop the idea; retain deliberate pauses and useful quiet cuts.
- **Sound and evidence:** name a cue's intended audible impact, select footage that demonstrates the spoken point, and inspect both the action and its result through the actual crop. Reuse existing source admission, audio controls and the user's framing requirement.
- **Reference review:** add missing viewer-question, sequence-development and payoff questions to the existing reference-editor review. Its source-frame study already exists; do not introduce a second extractor.

Distill only the useful differences into the existing skill's appropriate scoped reference during implementation. Use `short-form-edit` for new recorded shorts; `short-form-video` is explicitly a legacy example scaffold. Preserve the current native runtime, presenter-led brief and first-minute activity goal. Do not import mandatory three-opening renders, fixed brightness/presence percentages, perpetual-motion requirements, old renderer flags or the entire upstream skill directory. Storytelling QA commands absent from the kit are ideas, not shipped dependencies.

Evaluate on a small short and a long-form section after the independent benchmark: compare source-faithful hook/payoff, ease of following the explanation, unnecessary visual repetition, creative revision count and authoring time. These are editorial judgments until supported by audience data. Retain improvements that help without adding disproportionate review work; qualify any executable helper separately on our runtime. A useful guidance-only adoption does not depend on any kit card passing.

### 1. Pin and select before adding integration code

- Reuse the completed pinned inventory and source hashes in `docs/producer/evidence/student-kit-audit-2026-09-09/`. Re-audit changed material only if adopting a different source revision. Current-runtime playback/export qualification is still outstanding.
- Use the audited registry and source as references. Do not execute setup or import upstream agent instructions. Retain notices for copied material; use our branding and verified episode copy, not teaching placeholders or showcase media.
- Compare candidates with our existing library, especially `stat-card`, `chart-story`, `versus-split`, `whiteboard-map`, `nateherk-pipeline`, `glass-lower-third` and `section-marker`. Record “already covered” rather than porting another skin without a use case.
- Shortlist **at most three families** against actual episode needs. A Venn relationship or two-axis classification is a reasonable first candidate. Funnel widths in the source are fixed independently of displayed percentages: admit only an explicitly schematic treatment or correctly adapted quantitative geometry. Cycle, tree, hierarchy and spectrum remain optional references where existing maps do not suffice. Fewer than three, including zero, is an acceptable result.

Deliverable: a small selection/rejection table with upstream identity, local alternative, useful difference, target aspect, dependencies and reason to proceed or drop. Do not build a new searchable 406-item provider until a selected asset passes the pilot.

### 2. Adapt only the selected assets

- Map upstream `data-slot` content to our existing typed variables and constraints. Preserve useful slot length limits, deterministic timing and one registered paused timeline per composition.
- Use the current project's local GSAP, fonts and assets. Scope CSS, DOM IDs, timeline IDs and script state per instance; repeated copies must not affect one another or the footage.
- Apply our brand tokens and presenter-led layouts. For longs, favor graphics beside the presenter or presentation, with inset rounded panels where appropriate. Whenever the presenter is shown, preserve the face and necessary gestures through entry, layout changes and exit. Continuous head tracking is not an added requirement.
- Treat 16:9 and 9:16 as separate capabilities. Reflow a selected short-form layout for readable phone text, captions and presenter space; do not crop a landscape card and label it vertical-ready. A card may remain long-only.
- Allow straightforward asset, slot and layout adaptation. If compatibility requires a different engine, another dependency stack, SDK changes or a new renderer, reject it. Use a 45-minute initial compatibility investigation cap per family; this is a work limit, not a promised implementation time.

### 3. Qualify the addition alongside existing cards

Run one small landscape fixture and, only for vertical candidates, one small portrait fixture under the current pinned toolchain. Include existing cards, live footage/audio, captions, two instances of the candidate and a presenter/presentation layout change. Keep fixtures outside the active C0679 attempts.

| Gate | Required evidence |
| --- | --- |
| Current-runtime compatibility | No dependency downgrade or runtime patch; current lint/validation and the applicable template/scene contracts pass |
| Local and deterministic | Required assets resolve locally; no unexpected network requests, uncontrolled timers or stale source/dependency evidence |
| Studio behavior | Start playback before the graphic, cross both boundaries, seek forward/backward, restart, and reload; footage remains visible and graphics appear and disappear at the intended times |
| Reuse and editing | Two instances have independent copy and timing; changing text and duration updates the intended instance, survives save/reload, and remains editable without a full-video render |
| Layout and clarity | Short/long text cases, actual delivery aspect, clear captions, readable graphic, presenter safely in frame and no CSS or stacking interference with existing cards |
| Audio and picture | Preserve the fixture's existing audio behavior and source mapping; no added duplicated/choppy audio, blank/stuck frame or lingering takeover; native preview and exported output agree at entry, readable hold and exit |
| Regression and resources | Existing relevant tests pass; playback and export retain their established gates; compare elapsed time and peak temporary storage with the same fixture before the addition |

Use current managed preview and native-work resource controls, one heavy media/browser job at a time. Apply the existing cache policy and verified cleanup rather than retaining extra full-length intermediates. Do not regenerate the entire catalog without a source/dependency change that requires it under current tooling.

Add targeted tests for the actual extension: unknown or duplicate identity, invalid slots, missing local assets, wrong aspect and stale capability evidence. Reuse existing validators rather than copying the kit's validation scripts wholesale. Document any reproducible integration lesson in the project's findings documentation.

### 4. Connect qualified assets to the editorial workflow

Only after the fixtures pass, connect accepted assets to discovery and the existing planning/authoring route. Keep exact provenance and aspect-specific evidence available; unqualified items stay references and are ineligible for automatic selection. Mark rejected items with a reason so another agent does not repeatedly try to port them.

Use the editorial guidance qualified in step 0 when selecting and timing the new assets: spoken anchor, visual purpose, reveal timing, readable hold and clean exit. Preserve the user's first-minute goal of purposeful visual activity roughly every 2–4 seconds. That activity can be a reveal, highlight, layout change or transition within a coherent scene; it need not be a new full-screen card every few seconds. Later long-form sections receive graphics where they explain the subject. Short-form pacing follows the hook, explanation and payoff. Do not import the kit's slower default beat intervals or force its visual style.

The helper audit is complete. Use its tested counterexamples only if a concrete missing validation remains in our current route. Keep our source and edited transcript timelines authoritative; adapt a check to our existing schema instead of maintaining two plan formats. Animation-map and contrast-report scripts depend on internal producer APIs and offer heuristic checks; reuse useful diagnostic concepts through our existing scene/contrast controls rather than installing those scripts.

### 5. Keep only what proves useful

Compare the same two or three spoken ideas using the existing library and the qualified additions. Record card selection, authoring/revision time, Studio readiness, export/QA time, peak temporary storage and visual assessment separately. A reuse candidate must provide a useful visual capability or reduce authoring effort, while preserving quality and avoiding material playback/export/resource regression. Report measured numbers; do not infer saved hours from card counts.

Enable only passing assets as optional candidates. Disabling their discovery/admission entries must remove them from new plans without breaking existing cards or already saved self-contained projects. Preserve imported dependencies needed by saved projects. Expand only when a real episode needs something beyond the accepted set; importing all 406 is not a completion criterion.

## Completion criteria

This adoption is complete when the selected useful additions work in the current native Studio and exported output, each declared aspect is separately verified, relevant existing behavior passes regression checks, provenance is recorded, and a small real authoring comparison demonstrates value. The result may be both-format assets, long-only assets, guidance without imported code, or rejection of the kit. Every outcome is preferable to adding maintenance work with no editing benefit.

Implementation order: finish the independent video trial; qualify the useful storytelling/short-form guidance in our existing workflow; pin/deduplicate the asset candidates; prove one candidate end to end; complete the bounded shortlist only if it helps; then expose passing assets to the existing workflows. The adoption must not become another open-ended prerequisite for editing shorts and longs.

## Sources and local authority

- [Student kit overview](https://github.com/nateherkai/hyperframes-student-kit) and [package/runtime versions](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/package.json).
- [Library contract](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/style-library/GUIDE.md) and [library use guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/style-library/SKILL.md).
- [Verification scope](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/docs/VERIFICATION.md), [storytelling guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/video-storytelling/SKILL.md), [beat guidance](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/hyperframes-video-beats/SKILL.md) and [short-form workflow](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/.agents/skills/short-form-edit/SKILL.md).
- [License](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/LICENSE), [pipeline permission](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/licenses/PIPELINE-USE-PERMISSION.txt) and [third-party notices](https://github.com/nateherkai/hyperframes-student-kit/blob/b1afdb1dcbcad39dd27638ea699f132fe44ce6df/THIRD_PARTY_NOTICES.md).
- Local authority: `templates/motion/package.json`, `templates/motion/AGENTS.md`, `scripts/producer/CLAUDE.md`, current discovery/template/scene/Studio contracts, and `docs/producer/C0679_NATIVE_HYPERFRAMES_DIRECTION_2026-09-09.md`. The user's accepted native and presenter-led direction takes precedence over older compatibility-route descriptions.
