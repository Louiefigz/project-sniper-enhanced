# Reference style vocabulary and purposeful variation

Project Sniper can turn one explicitly selected reference study into planning
research that keeps a recognizable visual language while allowing different
cards, transitions, graphics, layouts, and information reveals. The existing
strategy agent remains the creative director. The operator does not choose an
effect from a menu, and the engine does not rotate effects randomly.

This feature does not qualify verified mimicry, visual quality, playback, or a
render. Exact reference-shot reuse maps and release-ready style packs retain
their existing meanings and gates.

## 1. Author and check the vocabulary

Create an agent-authored draft after inspecting the current profile, deep study,
full frames or motion sequences, and actual catalog sources. The draft records:

- stable traits that should make related work feel coherent;
- flexible traits that can change for the new information;
- signature devices that may repeat intentionally;
- purpose-based families, such as comparison or evidence;
- one to eight inspected contenders per family, with fit, difference,
  configuration, variation options, evidence, confidence, and availability;
- a policy for coherence, variation, repetition, and uncertainty.

Do not pad a family to reach three or four options. One strong contender is
valid. A contender with unresolved prerequisites must be `prerequisite` or
`research-only`; it cannot be selected as ready.

`ready` here means the frozen contender has a current source and measured,
selection-eligible integration for planning. It does not waive a current job's
guarded probe or catalog receipt. `VISUAL-PLAN.json` must still carry that exact
execution evidence before the allocator may select the contender.

```bash
./sniper python3 scripts/producer/graphics/reference_style_vocabulary_cli.py \
  prepare /absolute/vocabulary-draft.json \
  /absolute/study/reference_style_vocabulary.json

./sniper python3 scripts/producer/graphics/reference_style_vocabulary_cli.py \
  check /absolute/study/reference_style_vocabulary.json
```

The machine contract is
`schemas/producer/reference-style-vocabulary-v1.schema.json`. The CLI freezes
the exact evidence and inspected catalog records. Any changed evidence or
selected catalog source requires a new vocabulary preparation and review.

## 2. Select treatments for a project

When the selected reference has a current vocabulary, Short, Long, and ordinary
Producer strategy inputs expose it. For each scene or graphic that claims
vocabulary use, the agent follows this order:

1. State the viewer's information need.
2. Choose the family that serves that need.
3. Compare the inspected contenders in that family.
4. Select the best supported contender.
5. Adapt its configuration and information development to the new content.
6. Record the executable visual or graphic identity, alternatives, rationale,
   and repeat mode.

The selection is content-driven. Novelty is a tie-breaker after legibility,
content fit, and evidence. Repetition is allowed for a signature, callback, or
necessary repeat when the application says why.

If another valid catalog treatment serves the viewer need better, ordinary
planning may use it without claiming that it belongs to the vocabulary. The
supplemental record must explain how it stays coherent with the project-level
style or why the content justifies an exception.

Native Shorts save `strategy.styleApplication` and a generated
`STYLE-APPLICATION.json`. Each selected treatment has a stable `choiceId` and
binds a scene index, a ready catalog adaptation, and the scene-visible element
where that adaptation is mounted. One scene may carry several choices when it
combines separate cards, transitions, or text mechanisms; a mounted vocabulary
treatment cannot be omitted. Native Long projects save top-level
`styleApplication`; its catalog bindings pin each project-owned implementation
and source hash, and its choices name executable HTML IDs. Ordinary
`edit_plan.json` saves top-level `styleApplication`. Its `choices` contain only
graphics that claim membership in an inspected vocabulary family. A valid
measured catalog treatment outside those families uses `supplementalChoices`
with its exact `catalogId`/graphic kind and either a concrete coherent
relationship to the selected style or evidence for a justified exception.
Every reconciled `graphicsTrack[].id` appears exactly once across the two lists.
Normal catalog admission and visual-source policy still decide what can execute;
the vocabulary never becomes a closed catalog allowlist.

Changing an application changes the project/plan hash and requires a new current
review. A prepared request with a vocabulary cannot omit its application. A
project without a vocabulary cannot claim one.

## 3. Coordinate related Shorts

Related outputs use a bounded immutable context file with scope
`related-native-short-style-context`. An unrelated project is never included
implicitly. The context binds the selected `referenceId` and exact
`vocabularySha256`; sibling records from another vocabulary are rejected.

Use `planningMode: "shared-allocation"` when several Shorts will be planned in
parallel. Include the current output and every sibling as `planned`, with the
family, contender, configuration, and development allocated for each scene.
Freeze that file before preparing any individual request.

Use `planningMode: "serialized"` when each later Short can depend on completed
predecessors. Include only prior `authored` outputs, and bind each exact
`STYLE-APPLICATION.json` path and hash. The current output must not appear as a
sibling.

Prepare the Short with:

```bash
./sniper node --import tsx scripts/producer/native-short.ts \
  prepare-related /absolute/project/producer \
  /absolute/related-style-context.json
```

The authored application must compare every same-family sibling `choiceId`. It
records both composition and information-development differences. Swapping a
component ID while keeping the same formula is not meaningful variation.
Identical treatment is accepted only as an explicit matching signature,
callback, or necessary repeat.

The context source, copied request document, predecessor applications,
vocabulary, and vocabulary evidence remain pinned through build, cold read,
export, and picture reuse. Changing a sibling or allocation creates a new
request; it never changes an earlier reviewed request in place.

## 4. Uncertainty and failure behavior

- Missing vocabulary: use normal catalog-first direction and make no
  vocabulary-grounding claim.
- Present malformed or stale vocabulary: stop and prepare it again.
- Limited frame coverage: retain `coverage.status: "limited"` and state what
  motion or chronology was not reviewed.
- No family for the viewer need: inspect a new family or record the gap. Do not
  claim that an unrelated effect belongs to the vocabulary. A valid general
  catalog choice may instead use the ordinary supplemental record with explicit
  relationship or exception evidence.
- Every contender blocked: leave the choice unresolved and report the
  prerequisites.
- One clearly superior contender: use it even if another would increase raw
  variety.
- Same component with materially different development: allowed when recorded
  and reviewed.
- Different IDs with the same composition/development: does not establish
  variation.
- Missing sibling application in serialized mode: stop. Use a shared allocation
  for concurrent planning instead.
- Long callbacks across sections: allowed with an intentional repeat mode and
  explanation.
- Old projects and studies without this artifact remain readable and gain no
  new style-variation qualification.

The independent plan review judges whether the declared options actually share
the reference language and whether their variation improves the explanation.
Structural checks alone do not prove that visual quality.

## 5. Ordinary visual-plan compilation

`VISUAL-PLAN.json` is the separate route-neutral planning authority. Its public
Python boundary is `planner.visual_plan_contract.validate_visual_plan`, and
`invalidation_inputs` returns the contract-owned `visualPlanSha256`,
`pictureInputSha256`, catalog pin hash, and reusable upstream-authority hash.
Ordinary planning does not invent a second schema or copy candidate payloads
into `edit_plan.json`.

For a new produced/full ordinary edit, the authoring controller creates the
pending plan, validates it, allocates it, and freezes the canonical result beside
`edit_plan.json`. The edit plan records only `visualPlanApplication`: one ordered
execution row for every allocated opportunity, tied to the selected candidate,
exact output window, and actual graphic, transition, or restraint decision.
The planning gate resolves the saved plan again and rejects a missing, stale,
partial, substituted, or timing-inconsistent application before rendering.

The independent critic receives the same bounded plan content and immutable
binding. A gate-driven repair runs against a staged read-only copy of those exact
bytes, so a revision cannot silently replace its planning authority. Legacy work
and scopes for which visual planning is inapplicable keep their established path.
See [VISUAL_PLAN.md](VISUAL_PLAN.md) for the shared route and recovery contract.
