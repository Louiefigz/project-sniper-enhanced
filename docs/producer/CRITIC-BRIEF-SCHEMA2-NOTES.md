# Critic brief replacements for typed review evidence (observations schema 2)

Replacement text for the qualification driver in
`outputs/shorts-sla-qualification/batch-driver/` (unit B2, requirement revision
`approved-content-production-2026-09-27`). The coordinator applies it; the engine refuses
schema-1 observations (`playback`, `listening`, `windows[*].playback`, `stills` counts).

## Shared rules (all three briefs)

Put this block in each brief directly before "Write the observations":

> **Typed inspection.** Record only what you actually did, as `inspection` entries. Each names
> the exact artifact `path` and `sha256` you covered (copy them from the packet: `subject.windows[*]`,
> `subject.export.video`, or a frozen artifact / `declaredMedia` row; a file you add yourself goes in
> `evidence` first) and a `span`: `"whole"` or `{"frames": [start, endExclusive]}` on a target the
> packet lists under `submission.inspection.targets`, otherwise `"whole"` or
> `{"seconds": [start, end]}`.
>
> - `still-frames`: add `samples`, the exact frames you looked at, ascending (program frames of a
>   target; seconds of other media; `[0]` for an image). A contact sheet of every second frame is
>   still frames, never playback. Stills cover only the sampled frames: the record reports a
>   *sampled* picture review, and you are not required to sample every frame.
> - `motion-playback`: continuous playback at normal speed in a real player, for the span you
>   actually watched.
> - `audio-listening`: hearing the actual audio at normal speed, for the span you actually heard.
>   Decode, loudness and sample checks are not listening. Agents without an audio feed record none.
>
> `approves` lists what a `pass` speaks for: `picture` (you looked at every target), `motion`
> (playback of every target frame) and `audio` (listening to every target frame). A `revise` or
> `block` approves nothing (`[]`). Every aspect you did not cover goes in `limitations`.
>
> The submission refuses: an approval without its matching evidence on the exact bytes; entries
> for other bytes than the target's (stale); a note, event note or located issue at a frame nobody
> looked at or heard; and playback plus listening that could not fit, summed over artifacts, between
> packet resolution and submission. Records keep the packet hash, its resolution time and the
> submission time, and every gate re-checks them. All of this is declared, not authenticated.
>
> **Given content.** The operator approved each clip's title words and script before the clock
> started; the packet's `given` block reports the engine's title comparison and whether selection,
> caption text and timing match. A subject that departs from the given content is a material issue
> scoped `"approved-content-contradiction"` with its smallest repair, and no pass is possible until
> it matches. A problem inside, or change you would propose to, the given words themselves is a
> `findings` entry scoped `"proposed-change"`: surfaced for the operator, never withholding
> execution approval and never another approval round. Only the operator records a change to
> approved content; a critic never does.

## MOTION-CRITIC-BRIEF.md

Replace the "What to inspect" bullet about coverage and the "Listening" bullet with:

> - Look at every window. Contact sheets of every second frame are a complete *still* pass:
>   `R ffmpeg -nostdin -loglevel error -i <core.mp4> -vf "select=not(mod(n\,2)),scale=270:-2,tile=8x6" -vsync vfr <scratch>/w<n>-sheet-%02d.jpg`
>   Record them as one `still-frames` entry per window whose `samples` are the exact frames on the
>   sheets you opened. Open full-size frames where needed and add them to `samples`.
> - Motion approval needs a real normal-speed playback of every window (for example the operator,
>   or an agent that can actually watch video). Record it as `motion-playback` only if it happened.
> - Listening: record `audio-listening` only if you heard the actual audio; otherwise leave `audio`
>   out of `approves` and say so in `limitations`.

Replace "Write the observations" with:

> For every `windows[*]`: frame-numbered `observations` of what you actually saw (each frame must be
> one you sampled or watched). Fill `inspection`, `approves`, `assessment`, all eight `coverage`
> fields, `verdict` (`pass` needs zero material issues and picture on every window), `summary`,
> `materialIssues` (frame + smallest repair, all together), `findings`, `limitations`, `evidence`,
> `reviewer` (`sessionId: $SESSION`, `independent: true`).

Replace the last paragraph of "Submit" with:

> Only a pass that approves `motion` (typed playback of every window) admits the final export or a
> draft promotion (`--preview-reviews $RECORD`). A stills-only pass is recorded as
> `recorded-motion-review-picture-only` and admits nothing; the clip then stays on its labeled
> review draft. Report the record path, status, verdict, material issues, proposed-change findings
> and the uncovered events to the coordinator.

## FINAL-CRITIC-BRIEF.md

Replace the first "What to inspect" bullet and the "Listening" bullet with:

> - Look at the complete MP4. The review player at `$PLAYER` labels checked MP4s
>   `CHECKED FOR REVIEW — technical checks pass; editorial approval: see native-review.ts check-final`
>   and drafts `REVIEW DRAFT`. Contact sheets of every second frame are a complete still pass
>   (about 16 sheets for a 50 s Short at 30 fps); record them as a `still-frames` entry whose
>   `samples` are the frames on the sheets you opened, plus each event frame you extracted. Seek
>   checks by extracted frames are stills too.
> - An editorially approved final needs real normal-speed playback **and** listening of the whole
>   MP4 (for example the operator). Record `motion-playback` / `audio-listening` only for what
>   actually happened; never upgrade `humanListeningApproved`.

Replace "Write the observations" with:

> `frameNotes` (frame-numbered notes of what you saw, each at a frame you sampled, watched or
> heard), one note per `events[*]` (every event frame must be one you looked at),
> `inspection`, `approves`, `assessment`, eight `coverage` fields, `verdict` (`pass` needs zero
> material issues and picture approved on the MP4), `summary`, `materialIssues`, `findings`,
> `limitations`, `evidence`, `reviewer` (`sessionId: $SESSION`, `independent: true`). Record which
> parts of the two-view handoff (MP4 plus live Studio) you checked.

Replace the report sentence after "Submit and check" with:

> `check-final` reports `editorialFinal: approved` only for a pass approving picture, motion and
> audio over the whole exact MP4; a stills-only pass reads
> `recorded-independent-rendered-pass-not-final` with the missing evidence listed. Report the record
> path, status, `editorialFinal`, material issues and proposed-change findings.

## PLAN-CRITIC-BRIEF.md

Replace the "Write the observations" paragraph with:

> Fill every judgment field of `$OBS` yourself: `reviewer` (`identity`, `sessionId: $SESSION`,
> `independent: true`; leave `plannerSessionId` as given), all eight `coverage` fields, one
> `scenes[*].note` per scene (with shared evidence bound, also `scenes[*].evidenceBasis`:
> `inspected` or `shared-evidence-only`), `verdict` (`pass` only with zero material issues and no
> departure from the approved title/script; otherwise `revise` or `block`), `summary`,
> `materialIssues` (each with its scene/cue and the smallest required repair; return all of them
> together; a departure from the given content is scoped `"approved-content-contradiction"`), `findings`
> (a proposed change to the given words is scoped `"proposed-change"`),
> `inspection` (the source stills you sampled as `still-frames` with their exact seconds; any
> listening as `audio-listening`), `approves: []` (a plan review approves only the plan),
> `limitations` and `evidence` you actually opened.

## COORDINATOR-RUNBOOK.md

- Row "motion pass": replace with *"typed motion approval (the submission reports
  `recorded-independent-motion-pass`) | Promote the draft (launch plan step 3) | unchanged command.
  A `recorded-motion-review-picture-only` result admits nothing: keep the draft."*
- Launch plan step 2, add: *"A promotion or final needs a motion review with real normal-speed playback
  of every preview window. Without such a reviewer (normally the operator) the labeled review draft
  is the deliverable; say so at handoff."*
- Row "25-38", add: *"`check-final` states `editorialFinal`; only `approved` may be called an
  editorially approved final. A checked MP4 is a technical pass."*
- Row "38-40": the player label for a checked MP4 is now `CHECKED FOR REVIEW — technical checks pass;
  editorial approval: see native-review.ts check-final` (it was `FINAL — checked for review`).
- Add under "Budgets": *"`--preview-reviews` with a motion review recorded before typed evidence, or
  one approving picture only, is refused during option validation, before the budget reservation
  charges the launch. Re-resolved motion packets drop untyped earlier rows (and TEST canary rows),
  so a revision of a clip reviewed before typed evidence cannot retain those units: it needs a
  complete fresh preview of them and a typed motion review."*
