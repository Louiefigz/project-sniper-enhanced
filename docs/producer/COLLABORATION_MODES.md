# Producer collaboration presets

These presets control which editorial decisions the operator keeps and where
the agent stops to talk. They are conversation workflows shared by Codex and
Claude Code, not visual styles, render modes or new engine state. Use the
existing Producer, source admission, intent, review and export paths.

## Choose how to work together

Read the current request and accepted decisions before selecting a preset.
For new long-source clip discovery with no delegated choice, use **Walkthrough**.
Preserve an established route on resume. An explicit request to choose and
proceed supplies delegation within its stated scope; do not ask it again.

| Preset | Operator keeps | Agent continues through |
|---|---|---|
| **Walkthrough** (`walkthrough`; **Review** is an alias) | Worthwhile clip concepts, selected scripts, each clip's treatment, and the production go-ahead | The next unsettled conversation checkpoint |
| **Pick & Go** (`pick-and-go`) | Which clip concepts to make | After selection, scripts, treatment and production within the original request |
| **Auto** (`auto`) | The requested outcome and any explicit constraints or held decisions | Selection, scripts, treatment and production within that request |

**Fast** alone is ambiguous between Pick & Go and Auto. If the conversation
does not resolve it, ask whether the operator wants to choose the clips first
or delegate selection too. Do useful source discovery while that answer is
pending; do not interpret silence as delegation.

The request still sets the stopping point. “Auto: tell me which clips are worth
making” ends at analysis; “Pick & Go: prepare scripts” ends with scripts.
Neither preset turns a plan-only request into authorization to render. “Auto
everything” in a caption/style question delegates that question's choices, not
the selection or script review that the operator kept. A held checkpoint stays
held unless the operator clearly releases it, including when switching routes.

Examples using the existing entry points:

- Codex: `$producer Walkthrough: find worthwhile Shorts in this recording.`
- Claude Code: `/produce Pick & Go: show me the options, then make the ones I pick.`
- Either agent: `Auto: select and produce the strongest two Shorts; keep them natural.`

These are conversation arguments, not CLI flags. Natural language such as
“walk me through the clips before editing” chooses the same workflow.

## Discovery: decide what deserves work

Establish the editorial assignment from the accepted brief: extract existing
sections, clean them up, or assemble standalone Shorts with truthful reordering.
Apply the [selection playbook](SHORTS_JOURNEY_SELECTION_PLAYBOOK.md) within that
assignment. Review the full available transcript, including distant context and
payoffs. Apply the playbook's
[source-reuse rules](SHORTS_JOURNEY_SELECTION_PLAYBOOK.md#reuse-passages-across-different-stories):
shared timestamps or the same intro with a different body can support separate
stories. Judge the whole narrative; do not count a cosmetic change as a new
concept or discard a distinct story solely because its footage overlaps.

Discovery permits source inventory, reuse of source-bound transcripts, necessary
local transcription/content inspection, and rough paper assemblies. Follow
source admission and local-media rules. A content transcript with coarse timing
can support a provisional shortlist: label approximate ranges, duration estimates
and uncertain wording. Do not run timing repair or demand edit-grade word
boundaries merely to discuss which ideas are worthwhile. Missing content that
changes the meaning remains a real limitation. Exact source/timing gates still
apply before cuts and production.

**Establish speaker-to-picture alignment.** Before promising a presenter-led
shot, record who speaks each retained passage and who is visible. Use inspected
source playback or explicit reliable source information; transcripts without
speaker IDs and still images do not establish identity or lip synchronization.
Keep uncertain attribution visible during discovery, without inventing speaker
labels or blocking a content-only shortlist. Resolve the picture decision before
visual planning: off-camera dialogue defaults to purposeful supporting visuals;
a listener reaction needs a specific editorial purpose and must not imply that
the listener speaks those words. Recheck speaker changes and brief replies at
actual retained joins, then verify the encoded picture/dialogue relationship.
For recordings with multiple microphones, apply the existing
[dialogue-routing finding](../findings/TWO_ACTIVE_MICROPHONES_NEED_DIALOGUE_ROUTING.md):
balanced channels or mono correlation do not identify the speaker or prove a
clean microphone choice. Do not infer microphone ownership from camera framing.

Present a compact, ranked set of **distinct ideas** in the conversation. Each
candidate has a stable ID and enough substance to judge:

- The point and viewer question; why it is worth a clip and what is weak/missing.
- The proposed hook, development and payoff using source excerpts, plus a rough
  spoken assembly when needed to make the idea understandable.
- Recommended on-screen title-card wording and meaningful alternatives from
  the same Director pattern, with the source-based reason for the recommendation.
- Ordered source references and estimated edited length; mark backward jumps,
  missing timing and unverified joins rather than inventing precision.
- Shared ranges and their purpose in each distinct story; same-story alternate
  openings/cuts grouped under that idea with their tradeoff.
- A brief optional visual opportunity, without committing to a treatment.

**Choose title copy during candidate/script review.** Apply the full editorial
flow in the [Director library](../../resources/director/README.md) before making
recommendations: read all six library files named there: formats, hook anchors,
reference openings, formula/disqualification index, and both awareness training
files. Quote the
retained payoff; identify the viewer, problem and awareness; choose a supported
format and anchor/example while rejecting alternatives for source-based reasons.
Bind every formula slot (or the anchor's slots when no formula exists) to exact
contiguous retained words. Compare two or three meaningful fills of that same
pattern, check every disqualifier, and audit each against `supportedClaim`,
`answerablePromise`, `viewerStake`, `concreteDetail`, `channelAgreement` and
`glanceReadable`. Have a separate critic review the decision and assembled speech
before recommending it. Do not substitute a topic label or invent a source claim
to fill the pattern. Preserve exact user-supplied wording under Producer's
user-title exception rather than attaching a false formula provenance.

Show the recommended **written title** beside the actual **spoken opening** and
payoff, its same-pattern alternatives, and a concise explanation of why it fits
this viewer and clip. Retain source references, slot quotes, library IDs,
rejected options and audit/critic evidence in the existing review notes. Title
copy is proposed editorial text, not a claim that the speaker said that sentence.

This can be a provisional editorial decision from a coarse transcript: use real
quotes and honest source pointers, never invented word-occurrence IDs, native
Director records or passing receipts. Evaluate channel agreement against the
known or explicitly proposed first picture and assess readability as a copy
plan; mark uninspected picture, exact timing and rendered readability pending.
Do not claim all execution criteria passed from text alone. Card styling,
placement, actual reading hold and exit/lifetime validation follow the selected
treatment and production route. No graphic, asset generation or render is
required to discuss the wording. A changed script/opening/payoff reopens the
affected title recommendation and review.

**Consume standing title preferences separately from copy.** Read the operator's
existing project instructions and accepted brief for a selected title/reference
family. Preserve that choice across Walkthrough, Pick & Go and Auto; delegated
treatment is not permission to silently replace it. Before designing the card,
open the actual selected reference frames and sequence, then read their entries.
Record stable case/version, durable evidence paths/hashes, observed backing,
type hierarchy, entrance/hold/exit, and deliberate adaptations. A creator name,
catalog name or prose description is not a viewed or qualified implementation.
Do not infer motion from stills or call an operator-requested reveal observed
behavior when the reference is static. Use the current
[visual source policy](VISUAL_SOURCE_POLICY.md) and, for an explicitly targeted
reference, the [reference reuse map](REFERENCE_SHOT_REUSE.md). Personal references
remain task/operator assets; do not add historical third-party studies to the
packaged library or resurrect retired presets. If required evidence is missing,
state that specific gap rather than substitute a generic card. Check the actual
encoded entrance, complete readable state and exit against the chosen evidence.

Separate source quotes from editorial summaries and any proposed new speech.
Never present an editor's connective line as words the speaker recorded.
Report the worthwhile candidate pool and distinguish ranked favorites from
additional viable stories or same-story variants. Do not force a quota or stop
at an unrequested small count; explore a requested count subject to story
quality. Source previews can help assess delivery: reuse existing watchable
source links or bounded inspection when useful, and state when only transcript
analysis has been performed. A discovery-only request need not create edited
preview exports to earn a shortlist.

No exact cut plan, selected-media preparation, graphic authoring, expensive asset
staging or render begins at this checkpoint. In Walkthrough and Pick & Go,
recommend favorites and stop for selection. Ranking is not selection. In Auto,
make the delegated selection and record its rationale before continuing only as
far as the request authorizes.

## Walkthrough: discuss the selected clips

1. **Select ideas.** Record the chosen IDs, rejected/parked ideas and any desired
   alternative. Selection authorizes developing those scripts; it is not
   production approval. If the user requests complete scripts for one, several
   or all candidates before choosing, show that requested batch in the
   conversation with ordered source references, keep selection open, and stop
   for their editorial response. Reading scripts does not select those clips.
2. **Review scripts in the conversation.** Show the complete proposed spoken edit
   for each selected idea, usually one at a time unless the operator wants a
   batch. Include the Director-reviewed title copy and its meaningful alternatives;
   walk through how the title, spoken hook, context, development and ending agree.
   Keep ordered source references and version labels in the existing notes;
   include meaningful alternate arrangements and unresolved joins. Discuss and
   revise until the operator accepts that script or explicitly delegates the
   remaining script decisions. A file link or a hook/payoff summary alone is not
   the requested script walkthrough.
3. **Choose each treatment.** After its script is settled, discuss a natural
   presenter-led edit, light supporting visuals, or more developed visual
   storytelling. Explain what a proposed visual would help the viewer understand
   and where the speech should carry the moment. These are creative descriptions,
   not new style enums. Resolve the actual enabled lanes, captions, framing,
   music and source permissions from the user's choices and Producer's existing
   contracts. Natural does not require one locked shot; visual does not require
   a graphic for every sentence. Reuse settled choices and honor per-clip
   differences. Do not open this questionnaire before the operator has seen
   which ideas deserve work.
4. **Proceed when authorized.** Present the settled script version and treatment
   with the next production action. Continue when the operator gives the
   go-ahead or has already clearly authorized that exact continuation; do not
   repeat the same approval. Accepting a script by itself leaves an undecided
   treatment or held production checkpoint open. Several decisions can be
   settled in one message when the operator is explicit.

Pick & Go shares discovery and selection, then the agent owns the remaining
unheld editorial decisions within the original scope. Auto delegates selection
too. Both still keep the operator informed about the chosen ideas and approach;
neither requires waiting at every Walkthrough checkpoint. Ask only for a material
missing input or a decision the operator retained. Selecting clips in a
Pick & Go **production** request authorizes the delegated continuation; selecting
them in a planning request does not expand its deliverable.

## Resume and revise without losing decisions

Keep a compact collaboration section in the project's existing `BRIEF.md` or
`WORKING-NOTES.md`, whichever already holds the brief. For discovery without a
production project, use the existing task notes; create a small discovery note
only when there is no durable place for the work. Do not bootstrap render state
just to discuss candidates, and do not maintain duplicate decision ledgers.

Record before media production and after each operator decision:

| Record | Content |
|---|---|
| Request and route | Requested deliverable/ceiling, selected preset, explicit delegation and constraints |
| Current stage | Discovery, selection, script review, treatment review, production or output review |
| Candidates | Stable IDs, source/transcript references, alternatives, selected/parked/rejected status |
| Script, title and treatment | Current per-clip version, Director copy decision/evidence, standing title-reference choice and evidence, agreed choices, speaker/picture alignment, pending questions and source uncertainties |
| Decisions | What the operator actually accepted or delegated, for which clip/version, with a short quote or conversation reference |
| Next stop | Next action, who owns the decision and the precise held checkpoint |

On resume, read these notes alongside the latest conversation and the real
project artifacts. An absent note is not blanket permission. Resolve only a
material conflict or missing decision, and retain previously accepted choices.
When a revision changes meaning, the hook/payoff, or the agreed treatment,
reopen only the affected held checkpoint. A route switch does not retroactively
approve changed scripts or remove explicitly retained choices.

Store concrete production choices through the existing project intent command
before authoring/execution as Producer requires; do not put new collaboration
fields into `target.scope`, visual-style enums or admission receipts. Notes
record conversation decisions and never mint engine approval.

## Production and output review

**Default treatment for clip production:** use purposeful visual storytelling
when the user has not requested a natural, simpler or restricted treatment.
Keep the speaker central where performance carries the point; use source-faithful
supporting visuals to explain relationships, examples and payoffs. Respect the
existing catalog-first, source-permission and enabled-lane rules. This default
does not advance a discovery/script-only job or waive a retained checkpoint.
Once the user accepts this default and says to proceed, do not reopen the same
treatment interview. Resolve the remaining shot decisions within that delegation.

**Default execution for clip batches:** work on independent clips in parallel.
Share source admission, transcription and reusable preparation; give workers
disjoint clip/project ownership and keep one lead responsible for the brief,
source clocks, shared decisions and integrated review. Parallel authoring and
review can continue while heavy media work waits for capacity. Respect existing
resource-supervisor limits and tool leases. Reduce concurrency or serialize
heavy stages when memory pressure, CPU/disk contention, lock conflicts or
failures warrant it, and tell the operator what changed. Never bypass a resource
guard or duplicate a costly transcription merely to claim simultaneous work.

All presets retain source fidelity, current intent, independent plan/strategy
review, timing gates, moving previews, render admission, final QC and actual
playback/listening required by the selected route. A faster conversation is no
quality waiver, spending permission, publishing instruction or promise of a
shorter render time. Default video handoff remains the checked local MP4 plus
its matching live editable Studio project. Report unfinished checks honestly.
