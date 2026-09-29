"""Governing instruction sections and required checks for native-Short role packets.

Data catalog (exempt from logic-file limits). A selector names either an exact
Markdown heading, which spans to the next heading of the same or higher level
outside code fences, or a unique line prefix running to the first later line
with an end prefix. Resolution fails closed when a selector stops matching, so
a renamed or deleted section can never silently disappear from a packet.
Sections judged not applicable to a role are omitted here deliberately; the
clip owner, as author, reads the Producer skill and native workflow in full
because the Codex adapter requires the canonical skill to be read completely
before authoring.

Critic rows may subtract sub-ranges (`except_` + `drop`) or assign a section only when
the subject uses a feature (`when`, `drop(..., unless=...)`). This catalog is the
maintained authority for what a role need not read: every exclusion carries its reason
into the packet, is still resolved (so it fails closed when renamed), and a feature whose
use is unknown never excludes anything. Features are listed in FEATURES.
"""
from __future__ import annotations

CATALOG_VERSION = "native-short-role-packets-v3"
ROLES = ("clip-owner", "plan-critic", "motion-critic", "final-critic")
ROUTE = "native-short"
WHOLE = "whole"

# Record families written by the typed submission helper (scripts/producer/native-review.ts).
RECORD_PREFIX = {"clip-owner": "CLIP-OWNER", "plan-critic": "PREBUILD-REVIEW",
                 "motion-critic": "MOTION-REVIEW", "final-critic": "FINAL-REVIEW"}
SUBMIT_OPERATION = {"plan-critic": "submit-prebuild", "motion-critic": "submit-motion",
                    "final-critic": "submit-final"}
OBSERVATION_KIND = {"plan-critic": "native-plan-review-observations",
                    "motion-critic": "native-motion-review-observations",
                    "final-critic": "native-final-review-observations"}

SKILL = ".claude/skills/producer/SKILL.md"
NATIVE = "docs/producer/NATIVE_SHORTS_WORKFLOW.md"
STORY = "src/lib/producer/visual-storytelling.ts"


def heading(title: str) -> tuple[str, str]:
    """Select one exact Markdown heading and its body."""
    return ("heading", title)


def span(start: str, end: str) -> tuple[str, str, str]:
    """Select a unique starting line prefix up to the first later end prefix."""
    return ("range", start, end)


def whole() -> tuple[str]:
    """Select the whole document (to subtract from with `except_`)."""
    return ("whole",)


def paragraph(start: str) -> tuple[str, str]:
    """Select one paragraph: a unique starting line prefix through the line before the next blank line."""
    return ("paragraph", start)


def drop(selector: tuple, reason: str, unless: str | None = None, *, pin: str) -> tuple:
    """Exclude a sub-range always, or only when the subject is known not to use `unless`.

    `pin` is the first 16 hex of the SHA-256 of the excluded lines: any edit inside the range fails
    packet resolution until the catalog is reviewed (role_packet_sections.pinned).
    """
    return ("drop", selector, reason, unless, pin)


def except_(base: tuple, *drops: tuple) -> tuple:
    """A section minus the listed sub-ranges; each exclusion must lie inside it."""
    return ("except", base, drops)


def when(feature: str, selector: tuple, reason: str, *, pin: str) -> tuple:
    """Assign a section only when the subject uses the feature (unknown use still assigns it); pinned like drop."""
    return ("when", feature, selector, reason, pin)


# Subject features that decide conditional sections; computed from the plan and its request packet
# (role_packet_native.plan_features). None means unknown and always keeps the section.
FEATURES = {
    "catalog-staging": "The plan stages catalog compositions (catalogFiles/catalogTitle) or a built-in canvas.titleCard.",
    "reference-route": "The request selects a reference (selectedReference/selectedReferences) or a visualSources "
                       "decision uses the reference route.",
    "related-group": "The request was prepared with RELATED-STYLE-CONTEXT (relatedStyleContext).",
    "source-burned-captions": "canvas.captionMode is source-burned.",
    "supporting-media": "The plan binds supporting-video or image assets (inserts, captures, logos).",
    "caption-suppressions": "canvas.captionSuppressions declares caption-free windows (e.g. under the opening title).",
}
REFERENCE_ONLY = "Applies only with this job's selected reference (request selectedReference(s) or a visualSources reference route)."


STORY_SHARED = (span("const SHARED_DIRECTION", "const FORMAT_DIRECTION"), span("  short: [", "  longform: ["))
SKILL_CRITIC = (heading("## Current visual source rule"),
                heading("## Executable readiness before ordinary rendering"),
                heading("## Visual storytelling — produced/full plans and creative revisions"),
                heading("## House rules (non-negotiable)"))
SKILL_VERIFY = span("7. **Verify before presenting.**", "8. **Feedback**")
PIPELINE_CRITIC = (heading("## Current visual source rule"),
                   heading("## Latest operator direction — September 19, 2026: no UI, the buyer's own agent"),
                   except_(heading("## Operator direction — September 9, 2026"),
                           drop(span("**September 16 long export reliability:**", "**September 15 review handoff correction:**"),
                                "Native Long exporter reliability and exporter-route enforcement: engine behavior, not a "
                                "native Short review decision.", pin="28553082919a2237"),
                           drop(span("The explicit performance goal is a completely edited 10-minute", "Agent-selected transition effects"),
                                "The 10-minute Long delivery target; a Short batch clock is governed by NATIVE_SHORTS_DEADLINE_BATCH.md.",
                                pin="9727480ee0094251"),
                           drop(span("When the operator explicitly targets a particular reference shot/style", "For the active C0679 work"),
                                REFERENCE_ONLY, unless="reference-route", pin="16118bfccddcb85d"),
                           drop(span("For the active C0679 work", "## Stage 1"),
                                "C0679-specific direction, the September 9 audit and the Palmier/controller doctrine sentence and "
                                "diagram, which the September 19 agent route above supersedes (retired web app, Palmier not "
                                "configured per AGENTS.md).", pin="fa05100f0f30db51")))

BASE = (
    ("docs/producer/NATIVE_SHORTS_DEADLINE_BATCH.md", WHOLE,
     "Approved-content handover, counted clock, task dispatch and review/handoff commands."),
    ("AGENTS.md", WHOLE, "Operator contract: apply instructions before presenting work, ./sniper launcher, "
     "privacy boundary, independent fresh-subagent reviews, handoff rules."),
    ("CLAUDE.md", (span("# CLAUDE.md — Project Sniper", "## Engineering reference"),),
     "Claude Code entry: imports AGENTS.md and names the canonical skills and Codex adapters. "
     "The Engineering reference applies to application changes, not production roles."),
    (".agents/skills/producer/SKILL.md", WHOLE, "Codex adapter for the same canonical Producer doctrine."),
    ("docs/producer/VISUAL_SOURCE_POLICY.md",
     (except_(whole(), drop(heading("## Staging catalog components in a native Short"),
                            "Catalog staging and built-in title-card rules apply only when the plan stages catalog "
                            "compositions or a canvas.titleCard.", unless="catalog-staging",
                            pin="8cc75ae5d94f1fb9")),),
     "Catalog-first source decisions; independent review needs explicit visualSourceSelection coverage and honest "
     "reuse/gap judgment."),
)

OWNER = BASE + (
    (SKILL, WHOLE, "Canonical Producer doctrine; the adapter requires reading it completely before authoring."),
    ("docs/PIPELINE.md", WHOLE, "Canonical route; wins every contradiction."),
    (NATIVE, WHOLE, "Native Short request, strategy v3, build, preview review, export, audio and handoff."),
    ("docs/producer/NATIVE_PREFLIGHT.md", WHOLE, "Early static preflight on the exact staged project, "
     "before any preview or export work."),
    ("docs/producer/RENDER_READINESS.md", WHOLE, "Review bundle shape, preview reuse and full-render admission."),
    ("docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md", WHOLE, "Directing plan, feasibility and the "
     "independent critique that precede assembly."),
    ("docs/producer/STUDIO_REVIEW_LANE.md", (heading("## Required review handoff: local playback and Studio"),),
     "Default handoff: checked local MP4 playback plus the matching live editable Studio project."),
    ("docs/producer/NATIVE_REVIEW_BUNDLES.md", WHOLE, "Shared local playback and Studio review preparation."),
    ("docs/producer/COLLABORATION_MODES.md", WHOLE, "Collaboration preset checkpoints and batch execution defaults."),
    ("docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md", WHOLE, "Edit scope, story assembly and review."),
    ("docs/producer/WEB_BROLL_WORKFLOW.md", WHOLE, "Real subject decision; applies to website/repository inserts."),
    ("docs/producer/REFERENCE_SHOT_REUSE.md", WHOLE, "Applies only when the operator explicitly targets "
     "a reference shot/style (then --reference-map is required)."),
    ("docs/producer/NATIVE_TITLE_CARD_TEMPLATE_2026-09-10.md", WHOLE, "Title copy, exact user titles and layout."),
    ("docs/producer/VISUAL_PLAN.md", WHOLE, "Shared visual plan for new produced/full edits."),
    ("docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md", WHOLE,
     "Current route behaviour and explicit blockers."),
    ("resources/references/shorts/FORMAT_FOUNDATIONS.md", WHOLE, "Packaged Short reference foundations."),
    ("resources/references/shorts/sequences/DIRECTING_GUIDE.md", WHOLE, "Sequence directing guide."),
    ("resources/director/README.md", WHOLE, "Director hook/format library and opening criteria."),
    ("docs/studies/MEASURED_EDIT_GRAMMAR.md", WHOLE, "Measured edit grammar handed to plan critics."),
    ("scripts/producer/docs/findings/FAILURE_LEDGER.md", (heading("## Brain lessons"),),
     "Every LESSON is a hard authoring contract, re-checked each audit round."),
    ("scripts/producer/docs/findings/QC_CHECKLIST.md", WHOLE, "Standing render QC panel brief."),
    (STORY, STORY_SHARED + (span("  author: [", '  "plan-review": ['),),
     "Shared short-form author standard composed by visualStorytellingInstructions('short', 'author')."),
)

SKILL_STEP4 = except_(span("4. **Visual-plan convergence", "5. **Show the operator the plan"),
                      drop(span("   The cut-only previsual", "   **MANDATORY, before round 1:**"),
                           "Ordinary edit_plan.json convergence loop, GUI round policy and review_packet.py: a native "
                           "Short critic starts from this role packet, whose typed submission refuses stale inputs.",
                           pin="3bc432014d4d0ddc"),
                      drop(span("   - **a. Deterministic audit", "   - **b. Independent strategy critic"),
                           "Ordinary-route edit_plan.json gates (cut, lint, hook, claims, comp-size, geometry, operator "
                           "intent); a native plan is gated by the native-short.ts writer/cold reader and the static "
                           "preflight. The critic's own claims duty is step b below.", pin="330e54125407e3c1"))
NATIVE_PLAN = (
    except_(span("# Requesting and producing native Shorts", "### Prepare a stored guided proposal"),
            drop(span("The optional app offers", "## Before assembly"),
                 "Retired web-app controls (AGENTS.md: not in this release); the inspection duty for supplied media is "
                 "carried by 'One asset decision across images and video'.", pin="bf34869bb7b37086"),
            drop(heading("### Prepare related Shorts as one group"),
                 "Applies only to a request prepared with RELATED-STYLE-CONTEXT.", unless="related-group",
                 pin="1c1c29e373ebe897"),
            drop(span("Studio can still need a browser-compatible preview",
                      "When the user explicitly targets a particular reference shot/style"),
                 "Studio preview-codec and native long-form adapter notes; no plan decision.", pin="869b73c8f578e64a"),
            drop(span("When the user explicitly targets a particular reference shot/style", "First establish whether the user wants"),
                 REFERENCE_ONLY, unless="reference-route", pin="fb564cddbf1c70ed")),
    except_(heading("### Build and export"),
            drop(paragraph("For an inspected source with existing burned-in captions"),
                 "Applies only to canvas.captionMode source-burned.", unless="source-burned-captions",
                 pin="a197e25932188472")),

    heading("### Avoid wasted work without lowering quality"),
)
PREBUILD_PLAN = (except_(whole(),
                         drop(heading("## What the long-form paths actually provide"),
                              "C0679 history and the retired automated route's modules; the requirement they motivated "
                              "is the 'Shared planning sequence' below.", pin="cc920600d3b24a04"),
                         drop(span("New native long exports require a complete-project review", "## This example's recovery"),
                              "Native Long export review (studio/native_long_prebuild.py); not a Short plan.",
                              pin="0ade697d94ececd0"),
                         drop(heading("## This example's recovery"), "Recovery narrative of one historical example; not a rule.",
                              pin="3b55b72febb4d83b")),)

PLAN_CRITIC = BASE + (
    (SKILL, SKILL_CRITIC + (
        heading("## Collaboration preset before dependent work"),
        heading("## Establish editorial scope before selecting or reshaping footage"),
        heading("## Existing-project revisions — scope before the new-edit workflow"),
        heading("### Long-form source to finished shorts"),
        SKILL_STEP4),
     "Critic doctrine: the standing title/reference preference (PC-15), native prebuild strategy, catalog reuse, "
     "titles, sequence review and the step-4 independent strategy critic questions (content, graphics, "
     "transitions, copy, claims, eye-line, envelope)."),
    ("docs/PIPELINE.md", PIPELINE_CRITIC, "Canonical route directions that bind native Short review."),
    (NATIVE, NATIVE_PLAN,
     "Request authority, strategy v3 (rhythm, pacing, story, asset use), caption corrections, reveals "
     "and the audioFinishing decision the plan must justify. Guided-proposal/app sections do not apply."),
    ("docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md", PREBUILD_PLAN, "The prebuild critique contract."),
    ("docs/producer/RENDER_READINESS.md", (heading("## Review bundle"),
                                           heading("## Native continuous preview and regional review")),
     "Eight coverage assessments; a plan pass does not approve moving previews or full rendering."),
    ("docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md", (
        heading("## Establish the edit the user wants"), heading("### Assemble the source-supported story"),
        heading("### What counts as a journey payoff"), heading("## Plan visual explanation at the important moments"),
        heading("## Review the assembled Short before polishing it")),
     "Retained message, payoff and visual explanation criteria."),
    ("docs/producer/WEB_BROLL_WORKFLOW.md", (heading("## Establish the real subject before inventing its representation"),),
     "Real subject decision and the independent strategy verification of scouting evidence."),
    ("docs/producer/REFERENCE_SHOT_REUSE.md", tuple(when("reference-route", heading(title), REFERENCE_ONLY, pin=pin) for title, pin in (
        ("## When to use this", "9efeea0f954aa255"), ("## Inspect and complete decisions", "257ad84fc78bb6b7"),
        ("## Consume it in native work", "f55c8210b7ba3e70"))),
     "Applies only when the operator explicitly targets a reference shot/style."),
    ("docs/producer/NATIVE_TITLE_CARD_TEMPLATE_2026-09-10.md",
     (except_(whole(), drop(heading("## Retained corrections for the three edits"),
                            "Corrections to three specific September 10 edits of another project, recorded as completed; "
                            "not a rule for this plan.", pin="abd5a2dfd9b64fe5")),),
     "Title copy, exact user titles and layout."),
    ("docs/producer/VISUAL_PLAN.md", (heading("## Catalog and evidence boundaries"),),
     "What visual-plan evidence does and does not establish."),
    ("resources/references/shorts/FORMAT_FOUNDATIONS.md", WHOLE, "Reference function the plan adapts."),
    ("resources/references/shorts/sequences/DIRECTING_GUIDE.md", WHOLE, "Sequence directing guide."),
    ("resources/director/README.md", (heading("## Opening criteria (Director plan schema v2)"),),
     "Opening/title criteria."),
    ("docs/studies/MEASURED_EDIT_GRAMMAR.md", WHOLE, "Handed to the step-4 strategy critic."),
    ("scripts/producer/docs/findings/FAILURE_LEDGER.md", (heading("## Brain lessons"),),
     "Re-check every LESSON in each audit round."),
    (STORY, STORY_SHARED + (span('  "plan-review": [', '  "rendered-review": ['),),
     "Composed by visualStorytellingInstructions('short', 'plan-review')."),
)

RENDERED_NATIVE = (heading("### Visual storytelling: choose how concrete each beat should be"),
                   heading("### Script and delivery set the rhythm"), heading("### Author the pacing record"),
                   heading("### Bind the authored story to executable visuals"),
                   heading("### One asset decision across images and video"), heading("### Build and export"),
                   heading("### Avoid wasted work without lowering quality"),
                   span("Treat the review deliverable as one complete", "### Visual storytelling: choose how concrete"))
RENDERED_COMMON = BASE + (
    (SKILL, SKILL_CRITIC + (SKILL_VERIFY,), "Critic doctrine plus step 7 (verify) and 7.5 (Audit C)."),
    ("docs/PIPELINE.md", PIPELINE_CRITIC, "Canonical route directions that bind native Short review."),
    (NATIVE, RENDERED_NATIVE, "Review obligations for moving media: rhythm, holds, story checkpoints, "
     "logos/inserts, preview review, audio QC semantics and the complete-answer review."),
    ("docs/producer/RENDER_READINESS.md", (heading("## Review bundle"),
                                           span("Native Short and Long automatically check representative",
                                                "## Native continuous preview and regional review"),
                                           heading("## Native continuous preview and regional review")),
     "Coverage fields; samples and receipts are not playback or listening review."),
    ("docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md",
     (heading("## Standing directing requirements — September 16, 2026"),),
     "Final review watches entrances, movement, holds and exits continuously."),
    ("docs/producer/NATIVE_PREFLIGHT.md", (heading("## Read the result correctly"),),
     "A static-checks-pass result is never render or quality approval."),
    ("docs/producer/WEB_BROLL_WORKFLOW.md", (when("supporting-media", heading("### Bind the selected shot"),
                                                 "Applies only when the plan binds supporting-video or image inserts.",
                                                 pin="b6c19df7da701f39"),),
     "Applies to website/repository inserts: identity, fit, claims and readability need playback review."),
    ("docs/producer/NATIVE_TITLE_CARD_TEMPLATE_2026-09-10.md", (heading("## Exact user-supplied titles"),),
     "Exact user wording is preserved."),
    ("scripts/producer/docs/findings/QC_CHECKLIST.md", WHOLE, "Standing QC panel brief."),
    (STORY, STORY_SHARED + (span('  "rendered-review": [', "};"),),
     "Composed by visualStorytellingInstructions('short', 'rendered-review')."),
)

MOTION_CRITIC = RENDERED_COMMON + (
    ("docs/producer/STUDIO_REVIEW_LANE.md", (heading("### Verify the browser that receives the handoff"),),
     "Playback verification: seek both directions, continuous play, live audio transport."),
)

FINAL_CRITIC = RENDERED_COMMON + (
    ("docs/producer/STUDIO_REVIEW_LANE.md", (heading("## Required review handoff: local playback and Studio"),),
     "Local playback and Studio handoff checks, including browser verification."),
    ("docs/producer/NATIVE_REVIEW_BUNDLES.md", WHOLE, "Checked-MP4 review surface and its approval limits."),
    ("docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md", (heading("## Review the assembled Short before polishing it"),),
     "Watch the complete assembly as a cold viewer."),
)

INSTRUCTIONS = {"clip-owner": OWNER, "plan-critic": PLAN_CRITIC,
                "motion-critic": MOTION_CRITIC, "final-critic": FINAL_CRITIC}

NS = "docs/producer/NATIVE_SHORTS_WORKFLOW.md"
CHECKS = {
    "plan-critic": (
        ("PC-01", "Read the resolved request (SHORT-REQUEST.json, AGENT-BRIEF.md) and any job brief listed; confirm "
         "the plan keeps the requested scope, duration, enabled/disabled lanes and source permissions. Reject a "
         "silently narrowed source policy or a blanket no-insert decision.", f"{NS}#Preserve the actual request"),
        ("PC-02", "Read the complete retained speech as a new viewer: who/what, why it matters, and whether the ending "
         "answers the opening. A title is not spoken context.", "AGENTS.md#Producer work"),
        ("PC-03", "Open the actual reference images, catalog sources and supplied assets the plan names; a reference ID "
         "or catalog name is not evidence of a match.", f"{SKILL}#Visual storytelling"),
        ("PC-04", "For every scene listed under subject.scenes, check cue, viewer question, visible object, action, "
         "result, readable hold and exit, crop/face clearance and title/caption hierarchy. Write one note per scene.",
         f"{STORY}#plan-review"),
        ("PC-05", "Treat as material: unexplained repeated footage, a context-free product example, an omitted important "
         "argument or ending, an unspecified or discontinuous presenter handoff, an unreadable product/destination hold.",
         f"{STORY}#plan-review"),
        ("PC-06", "Visual sources are catalog-first; a reference route needs this job's selected reference and a custom "
         "route an inspected capability or quality gap. Assess it in coverage.visualSourceSelection.",
         "docs/producer/VISUAL_SOURCE_POLICY.md"),
        ("PC-07", "Copy and claims: every title, card and caption matches the kept words (spelling, ASR mishears, "
         "declared caption corrections); numbers and qualifications are faithful; exact user titles are unchanged.",
         f"{SKILL}#4b"),
        ("PC-08", "Pacing: holds fit each visual's job, known entrances finish before holds, future reveals start hidden, "
         "and deliveryReview states truthfully whether source listening occurred.", f"{NS}#Author the pacing record"),
        ("PC-09", "Story and asset-use bindings: real-artifact/real-operation jobs use real inspected media; a metaphor "
         "never claims evidence; claim limits are recorded.", f"{NS}#Bind the authored story to executable visuals"),
        ("PC-10", "Feasibility: required assets exist and were inspected, fonts/geometry/runtime are supported, and an "
         "unresolved capability gap is a material issue.", "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md"),
        ("PC-11", "Audio: the audioFinishing decision (cleanup, gain windows, channel mode) is justified by source "
         "evidence; signal checks are not listening.", f"{NS}#Avoid wasted work without lowering quality"),
        ("PC-12", "Re-check every Brain lesson in FAILURE_LEDGER.md against the plan.",
         "scripts/producer/docs/findings/FAILURE_LEDGER.md#Brain lessons"),
        ("PC-13", "Return all material findings together, each with its scene/cue and the smallest required repair. "
         "A pass needs zero material issues and is not motion, playback or listening approval: record any stills, "
         "playback or listening you did as typed inspection entries and leave approves []. The submission computes "
         "planHash (nativeShortPrebuildPlanHash) and refuses a sessionId equal to plannerSessionId.",
         "src/app/api/producer/auto-edit/review-contract.ts"),
        ("PC-14", "Write all eight coverage assessments from the evidence you actually inspected; state a reason when "
         "a lane is not applicable.", "docs/producer/RENDER_READINESS.md#Review bundle"),
        ("PC-15", "Title reference: the opening title follows the operator's standing "
         "title/reference preference from the project instructions and accepted brief (backing, prominence, readable "
         "hold); compare it with the actual reference images, not a name.",
         f"{SKILL}#Collaboration preset before dependent work"),
        ("PC-16", "Speaker and picture evidence: for each retained interval the plan "
         "establishes who speaks and who is visible from source playback or reliable source information; a listener "
         "reaction has an editorial reason and never implies the listener is speaking.", f"{SKILL}#Visual storytelling"),
        ("PC-17", "Names and caption identities: products, brands and people are spelled "
         "and displayed identically in title, captions and graphics, with canvas.captionCorrections for ASR "
         "misspellings, and caption identities match the actual speakers.", f"{NS}#Build and export"),
    ),
    "motion-critic": (
        ("MC-01", "Review exactly the preview frozen in this packet; the submission refuses changed media. Never "
         "transfer approval from another preview or encode.", "docs/producer/RENDER_READINESS.md#Native continuous preview"),
        ("MC-02", "Play every window listed under subject.windows from its start to its end at normal speed in a real "
         "player, including its two seconds of context; record frame-numbered observations for each window and a typed "
         "motion-playback entry on that window's exact clip. Frame sheets are still-frames entries, never playback.",
         f"{SKILL}#Executable readiness"),
        ("MC-03", "Listen to the actual mastered audio of each window when the review surface has sound and record typed "
         "audio-listening entries; otherwise leave audio out of approves and state the limitation. Decode, loudness "
         "and sample checks are not listening.",
         "docs/producer/STUDIO_REVIEW_LANE.md#Verify the browser"),
        ("MC-04", "Check phone-size title and caption readability, face and gesture clearance through entrances, movement "
         "and exits (not only settled states), and the caption/title hierarchy.", f"{SKILL}#Visual storytelling"),
        ("MC-05", "Check the rendered-review failure classes: purposeless repetition, context-free products, uncovered "
         "beats including the ending, abrupt or occluded handoffs, unreadable holds, redundant text panels.",
         f"{STORY}#rendered-review"),
        ("MC-06", "Audit C on what you see: spelling in every rendered text, graphics landing on their words, nothing "
         "occluding the focal subject at payoff, legible captions.", f"{SKILL}#7.5"),
        ("MC-07", "Native capture stills (subject.capture.stills maps frame to still) can confirm exact states such as a title exit but cannot "
         "prove motion. Carry subject.uncovered intervals and events into the final review as open obligations.",
         "docs/producer/RENDER_READINESS.md#Native continuous preview"),
        ("MC-08", "Story checkpoints and real inserts appear on their spoken cues with readable detail.",
         f"{NS}#Bind the authored story to executable visuals"),
        ("MC-09", "Return all material findings together with frames and the smallest repair. A pass needs zero material "
         "issues and approves picture on every window (sparse stills are reported as a sampled review); only a pass "
         "approving motion, backed by typed playback of every window, admits full rendering. A picture-only pass is "
         "recorded and admits nothing.",
         "src/app/api/producer/auto-edit/review-contract.ts"),
        ("MC-10", "Write all eight coverage assessments from what you actually observed.",
         "docs/producer/RENDER_READINESS.md#Review bundle"),
        ("MC-11", "Do not hand-build or hand-check the record: submit-motion validates with the same reader against the "
         "preview's extracted .packet (passing the whole motion-previews.json to check-motion-reviews fails with "
         "'native region project must be a non-empty string').", "src/lib/server/native-motion-review.ts"),
    ),
    "final-critic": (
        ("FC-01", "Review exactly the checked export frozen in this packet (delivery status native-short-checked-for-review "
         "and the MP4 hash); the submission refuses changed media.", f"{NS}#Build and export"),
        ("FC-02", "Play the complete MP4 from start to end at normal speed and record it as a typed motion-playback entry on "
         "the exact MP4; then seek backward and forward at the opening, a middle scene and the final passage and "
         "confirm future or expired elements stay hidden. Frame sheets are still-frames entries, never playback.",
         "docs/producer/STUDIO_REVIEW_LANE.md#Verify the browser"),
        ("FC-03", "Inspect every event under subject.events (joins, title window, scene changes, ending) and especially the "
         "intervals the moving previews did not cover (subject.uncovered).",
         "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md#Standing directing requirements"),
        ("FC-04", "Listen to dialogue seams, the intro/outro and every audio-QC row listed under subject.audioReview when "
         "the surface has sound and record typed audio-listening entries; otherwise leave audio out of approves and "
         "state the limitation. Never upgrade humanListeningApproved.",
         f"{NS}#Avoid wasted work without lowering quality"),
        ("FC-05", "The title promise is answered, the example develops coherently, and identity/page-context inserts are "
         "not presented as demonstrated operations or achieved results.", f"{NS}#Treat the review deliverable"),
        ("FC-06", "Audit C: spelling in every rendered text, graphics on their words, no occlusion of the focal subject at "
         "payoff, framing/brand consistency, caption legibility.", f"{SKILL}#7.5"),
        ("FC-07", "Check the rendered-review failure classes on this exact encode.", f"{STORY}#rendered-review"),
        ("FC-08", "Report failing or warning technical rows from the delivery and audio receipts as recorded; do not "
         "reinterpret them as passes.", "scripts/producer/docs/findings/QC_CHECKLIST.md"),
        ("FC-09", "Return all material findings together with frames and the smallest repair. A pass needs zero material "
         "issues and picture approved on the MP4 (sparse stills are reported as a sampled review). Only a pass approving "
         "picture, motion and audio with typed whole-program evidence is an editorially approved final; a checked MP4 "
         "is a technical pass only.",
         "src/app/api/producer/auto-edit/review-contract.ts"),
        ("FC-10", "Write all eight coverage assessments from what you observed; the two-view handoff (checked MP4 plus live "
         "Studio) belongs to the owner, so record which of its checks you performed.",
         "docs/producer/STUDIO_REVIEW_LANE.md#Required review handoff"),
    ),
    "clip-owner": (
        ("OW-01", "Read every listed governing file completely before dependent work; the Producer skill and native "
         "workflow are required in full for authoring.", ".agents/skills/producer/SKILL.md"),
        ("OW-02", "Preserve the stored intent, scope, lanes and source permissions; freeze the request with "
         "native-short.ts prepare and bind requestPacket.", f"{NS}#Preserve the actual request"),
        ("OW-03", "Prepare selected media before visual iteration; author strategy v3 with pacing, assetUse and story, "
         "then measure and bind their hashes.", f"{NS}#Author the pacing record"),
        ("OW-04", "Obtain the independent plan review through a plan-critic packet and typed submission; bind it with "
         "native-review.ts bind-prebuild. Never review your own plan.", "docs/producer/NATIVE_PREBUILD_STRATEGY_2026-09-10.md"),
        ("OW-05", "After build, run the static preflight on the exact staged project before any preview or export.",
         "docs/producer/NATIVE_PREFLIGHT.md"),
        ("OW-06", "Run the preview-only export, obtain the motion review through a motion-critic packet and typed "
         "submission, and fix every material finding in one consolidated repair.", "docs/producer/RENDER_READINESS.md"),
        ("OW-07", "Run the final export with --preview-reviews; native-short-checked-for-review is a technical pass only.",
         f"{NS}#Build and export"),
        ("OW-08", "Obtain the independent final review through a final-critic packet, then hand off the checked MP4 and "
         "the matching live Studio project; report unperformed listening/playback honestly and never present a checked "
         "MP4 as an editorially approved final unless check-final reports editorialFinal approved.",
         "docs/producer/STUDIO_REVIEW_LANE.md#Required review handoff"),
        ("OW-09", "Reference staged dependencies from mounted composition HTML as project-root paths (for example "
         "assets/<file>): the static preflight resolves sub-composition paths with the SDK's rewriteAssetPath and reports "
         "missing or unbound dependencies otherwise. Stage unmounted catalog sources with a non-HTML extension (for "
         "example references/<name>.html.txt): every .html/.htm file the SDK lint did not cover is reported "
         "native_unlinted_html.", "docs/producer/NATIVE_PREFLIGHT.md#What it checks; "
         "scripts/producer/studio/native_preflight_dependencies.mjs"),
        ("OW-10", "Authored motion must render identical pixels when seeked backward: the native capture compares forward "
         "and reverse frames. Keep transformed lockups off GPU-composited state (for example GSAP force3D:false with "
         "will-change:auto), prefer opaque backgrounds behind numbers and diagrams over translucent layers, and verify "
         "with the reverse check.", "scripts/producer/studio/native_picture_references.py (qualify_reverse_frames); "
         f"{NS}#Author the pacing record"),
        ("OW-11", "Start every future term, stroke or connector explicitly hidden and reveal it on its spoken cue; a "
         "future GSAP fromTo with immediateRender:false does not hide it before its tween starts.",
         f"{NS}#Build and export"),
        ("OW-12", "Check labels and diagram text at delivery size on the phone canvas; a legible still at full "
         "resolution does not establish phone-size readability.", f"{SKILL}#Visual storytelling; {SKILL}#7. Verify before presenting"),
        ("OW-13", "Caption views are horizontally centred on the canvas (the native capture check asserts each caption's "
         "centre at the canvas midline; centeredNativeCaptionView builds one), and every picture-view crop has exactly "
         "its box's aspect (the composition validator refuses a crop that would stretch or contain the presenter).",
         "scripts/producer/studio/native_short_capture_checks.mjs; src/lib/server/native-short-composition.ts"),
        ("OW-14", "Apply the operator's standing title/reference preference from the project instructions and accepted "
         "brief, inspect the actual reference images, and establish who speaks and who is visible for each retained "
         "interval before choosing a crop.", f"{SKILL}#Collaboration preset before dependent work; {SKILL}#Visual storytelling"),
        ("OW-15", "Add canvas.captionCorrections for recurring ASR misspellings of names and brands, keeping the source "
         "timing and the original transcript.", f"{NS}#Build and export"),
        ("OW-16", "Bind strategy v3 hashes in dependency order - pacing, assetUse, story, then visualSources - and rerun "
         "native-short.ts measure after each change.", f"{NS}#Author the pacing record; {NS}#Bind the authored story to "
         "executable visuals"),
        ("OW-17", "visualPlanApplication decisions carry exactly the validator's keys, including binding, and each "
         "binding equals the executable facts of the mounted element that realizes the opportunity.",
         "src/lib/server/native-visual-plan-application.ts; src/lib/server/native-visual-execution-binding.ts"),
    ),
}

SHARED = "sharedEvidence"
REVISION = "approved-content-production-2026-09-27"
# Added to a role's checks only when the packet binds a sealed SHARED-EVIDENCE record (role_packet_evidence).
EVIDENCE_CHECKS = {
    "plan-critic": (
        ("PC-18", "Shared evidence (sharedEvidence): only its engineObserved identities (manifest, source and transcript "
         "hashes) are facts you may reuse without re-deriving. Every authored field (scan facts, speakers and "
         "visibility, reference statement, decisions such as spellings, audio treatment or layout) is the "
         "coordinator's claim with cited provenance: use it to direct your own inspection, check what your judgment "
         "rests on, and raise a wrong, unsupported or harmful claim or decision as a material issue. A shared scan "
         "claim (for example 'no insert footage') never overrides PC-01's source-permission and insert checks. For each "
         "scene set evidenceBasis to 'inspected' when you examined its source frames, or 'shared-evidence-only' when "
         "your note rests on the shared evidence alone, and say so in your limitations. Only the given title and script "
         "(PC-19) are not reopened.", "scripts/producer/role_packet_evidence_record.py"),
    ),
    "motion-critic": (
        ("MC-12", "Shared evidence: reuse only its engineObserved identities; its authored claims and decisions direct "
         "your checks and may be raised as material. It never replaces playing and listening to every window (MC-02, "
         "MC-03).", "scripts/producer/role_packet_evidence_record.py"),
    ),
    "final-critic": (
        ("FC-11", "Shared evidence: reuse only its engineObserved identities; its authored claims and decisions direct "
         "your checks and may be raised as material. It never replaces complete playback and listening (FC-02, FC-04).",
         "scripts/producer/role_packet_evidence_record.py"),
    ),
    "clip-owner": (
        ("OW-18", "Shared evidence: its engineObserved identities are facts; its authored claims and decisions are the "
         "coordinator's inputs with provenance. Check them against the source before relying on them and tell the "
         "coordinator when the source contradicts one.", "scripts/producer/role_packet_evidence_record.py"),
    ),
}

# Added when the packet's `given` block is bound (requirement revision approved-content-production-2026-09-27): the
# batch authority's approved title and script for the named clip (--batch/--clip), handed over at batch start when the
# clock starts. They are inputs never re-decided inside it; the authority's typed approval-changed events are the only
# change record. `given` reports title {status exact|normalization-only|different, material} and selection,
# captionText and timing, each {matches, details}.
GIVEN = ("The packet's `given` block (read from the batch authority) reports, by identity and arithmetic against the "
         "verified approval: title (status exact, normalization-only or different; material only when different), "
         "selection (same source and transcript version, exactly the given words in order; missing, extra, repeated, "
         "out-of-range words), captionText (each kept occurrence's source word versus the transcript; declared display "
         "corrections listed with whether they change a given word's displayed spelling) and timing (occurrence frames "
         "under the writer's rule, segment mapping, cut seconds).")
SCOPES = ("Record each departure as a material issue scoped approved-content-contradiction with its smallest repair: no pass "
          "is possible until the subject matches. A problem inside, or a change you would propose to, the given words "
          "themselves (a misstatement, a wrong name) is a findings entry scoped proposed-change: surfaced for the operator, "
          "never withholding execution approval and never another approval round; only the operator records a change.")
APPROVAL_CHECKS = {
    "plan-critic": (
        ("PC-19", "Given title and script. " + GIVEN + " A different title, a selection that is not the given words in "
         "order, a kept word whose source text differs, or a timing mismatch is a material issue; a normalization-only "
         "title difference is not, and a declared display correction that changes a given word's spelling is yours to "
         "judge. Skip the Director hook and title critique for a given title, and do not re-decide the selection: "
         "PC-02, PC-05, PC-07 and PC-15 judge how the plan presents the given words (treatment, readability, "
         "hierarchy, spellings), not whether other words should have been chosen. " + SCOPES,
         "scripts/producer/role_packet_speech.py"),
    ),
    "motion-critic": (
        ("MC-13", "The preview shows exactly the given title words and captions of the given kept words at their "
         "timing; a departure is material. " + GIVEN + " " + SCOPES, "scripts/producer/role_packet_speech.py"),
    ),
    "final-critic": (
        ("FC-12", "The encode shows exactly the given title words and plays exactly the given kept words; a departure "
         "is material. " + GIVEN + " " + SCOPES, "scripts/producer/role_packet_speech.py"),
    ),
    "clip-owner": (
        ("OW-19", "Given title: use it verbatim through the exact user-supplied title path (createUserTitleCopy) and skip "
         "the Director hook fill and title critique; this block overrides the brief's hook workflow. Build exactly the "
         "given kept words in order with their transcript text and timing. " + GIVEN + " A different title or "
         "selection is a new operator approval recorded by the batch authority, never an authoring choice.",
         "docs/producer/NATIVE_TITLE_CARD_TEMPLATE_2026-09-10.md#Exact user-supplied titles"),
    ),
}

# Added when the subject uses the feature (role_packet_native.plan_features).
FEATURE_CHECKS = {
    "caption-suppressions": {
        "plan-critic": (
            ("PC-20", "Caption suppressions (subject.captionSuppressions lists each window, its reason and the kept words "
             "spoken inside it): judge from the plan and source frames whether each reason is true for the whole window "
             "and whether the uncaptioned speech stays followable; a window whose reason does not hold for all of it, or "
             "whose uncaptioned speech is not followable, is a material issue with the smallest repair.",
             "src/lib/server/native-caption-display.ts"),
        ),
        "motion-critic": (
            ("MC-14", "For each caption-suppression window a preview shows (subject.captionSuppressions, 'caption "
             "suppression' events): confirm on playback that its reason holds on every frame, no caption paints inside it, "
             "captions resume at its end, and the listed uncaptioned speech is followable with sound.",
             "src/lib/server/native-caption-display.ts"),
        ),
        "final-critic": (
            ("FC-13", "For every caption-suppression window (including those outside the previews): its reason holds on "
             "every frame of the encode, no caption paints inside it, captions resume at its end, and the listed "
             "uncaptioned speech is followable with sound.", "src/lib/server/native-caption-display.ts"),
        ),
    },
}

# Explicit obligations every packet states beside its checks; each cites the checks that carry it.
OBLIGATIONS = {
    "plan-critic": {
        "independence": ("A fresh critic that did not author the plan; the typed submission refuses a declared session "
                         "equal to a recorded author (authorSessionIds).", ("PC-13",)),
        "sourceInspection": ("Open the actual source frames, reference images, catalog sources and assets; names, IDs, "
                             "stills sheets and shared evidence do not replace inspecting this plan's retained intervals. "
                             "With shared evidence bound, each scene records its evidenceBasis.",
                             ("PC-03", "PC-15", "PC-16")),
        "playbackListening": ("A plan pass is not motion, playback or listening approval: record any source frames you "
                              "looked at (still-frames with samples), playback (motion-playback) or listening "
                              "(audio-listening) as typed inspection entries and leave approves []; stills do not "
                              "establish who is speaking.", ("PC-08", "PC-11", "PC-13")),
    },
    "motion-critic": {
        "independence": ("A fresh critic that did not author the work; the submission refuses a recorded author.", ("MC-09",)),
        "sourceInspection": ("Review exactly the frozen preview media; stills cannot prove motion.", ("MC-01", "MC-07")),
        "playbackListening": ("Play every window to its end at normal speed and record a typed motion-playback entry on "
                              "its exact clip; frame sheets are still-frames entries and never establish motion. Record "
                              "audio-listening only when you heard the actual audio; otherwise leave audio out of approves "
                              "and state the limitation. Only a pass approving motion admits full rendering.",
                              ("MC-02", "MC-03", "MC-09")),
    },
    "final-critic": {
        "independence": ("A fresh critic that did not author the work; the submission refuses a recorded author.", ("FC-09",)),
        "sourceInspection": ("Review exactly the checked MP4 frozen here, including intervals the previews did not show.",
                             ("FC-01", "FC-03")),
        "playbackListening": ("Play the complete MP4 at normal speed as a typed motion-playback entry on the exact MP4 and "
                              "record audio-listening only when you heard the actual audio; still-frames never establish "
                              "motion. Never upgrade humanListeningApproved; only a pass approving picture, motion and "
                              "audio over the whole MP4 is an editorially approved final.", ("FC-02", "FC-04", "FC-09")),
    },
    "clip-owner": {
        "independence": ("Never review your own work; every review comes from a fresh critic through a role packet.",
                         ("OW-04", "OW-06", "OW-08")),
        "sourceInspection": ("Inspect the actual reference images and source before choosing crops and attributions.",
                             ("OW-14",)),
        "playbackListening": ("Report unperformed playback or listening honestly at handoff; a checked MP4 is a technical "
                              "pass, never an editorially approved final unless check-final reports editorialFinal "
                              "approved.", ("OW-08",)),
    },
}

# How a role uses each frozen artifact (artifacts[].read); every row stays hash-bound whatever its class.
READING = {
    "inspect": "Read or view it for the checks that name it.",
    "entries": "Consult only the located entries (artifacts[].entries pointers); the rest of the file is bound "
               "for staleness and open to you if your judgment needs it.",
    "bound": "Frozen for staleness, not assigned reading (runtime libraries and fonts, sealed receipts, files the "
             "shared evidence binds or an index the subject does not use).",
    "history": "Earlier review records: what was already found; never current approval.",
}
# Class by key prefix (first match wins); asset rows by their role; anything else stays "inspect".
ARTIFACT_READING = (
    ("request:CATALOG-INDEX.json", "entries"), ("request:DIRECTOR-LIBRARY.json", "entries"),
    ("prepared-sources", "bound"), ("shared-evidence:", "bound"),
    ("previous:", "history"), ("bound-prebuild-review", "history"), ("prior-motion-reviews", "history"),
)
ASSET_READING = {"runtime": "bound"}

LIMITS = (
    "The packet lists governing instructions and exact artifacts; it does not read them for you or approve anything.",
    "Sections under instructions[].excluded were judged not applicable to this role and subject by the maintained "
    "catalog, each with its reason; if the subject actually uses what an excluded section governs, read it and say so.",
    "Size estimates count assigned text bytes (about four bytes per token); they are not a tokenizer count or a "
    "measure of review time.",
    "Hashes are observations at resolution time. The typed submission refuses the record if any listed artifact "
    "or instruction changed since then.",
    "Media larger than the rehash limit are listed with the hash their receipt declares and are not rehashed here; "
    "the exporter and builders keep verifying them.",
    "Reviewer identity is declared, not authenticated; the submission only refuses a declared identity equal to a "
    "recorded author identity.",
)
