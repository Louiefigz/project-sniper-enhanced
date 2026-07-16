# Requested Intent Is Not Pipeline State

## The incident

Producer showed `LONG · Produced` beside projects that had only been ingested and
transcribed. The word “Produced” came from the requested edit scope, but its
placement made it look like a completion status. A generic `Open` action was also
shown before either `edit_plan.json` or `final.mp4` existed, so clicking it produced
only a swallowed 404.

One historical run made the distinction concrete:

- Auto Edit started at 10:25:25.
- `speech_cleanup.json` landed at 10:26:39.
- `edit_plan.json` landed at 10:36:59 with a 651.33-second target.
- `graphics_proposal.json` landed at 10:37:10.
- No `base_final.mp4`, fingerprint, or `final.mp4` was written.
- By 11:00, no Codex, render, assemble, or FFmpeg process remained.

That project was not “Produced.” Its truthful state was `Plan ready`, and its next
safe action was `Render plan`. These observations prove that the run stopped before
render; they do not identify the exact process or failure boundary. This incident
predates the detached worker, durable job journal, and bounded review/QC controller.

## Use four separate state dimensions

1. **Source provenance** — raw upload, Segmenter, Clipper, or legacy.
2. **Requested intent** — Short/Long and Trim/Light/Produced/Full.
3. **Artifact state** — manifest, transcripts, plan, base, and final files that
   actually exist on disk.
4. **Transient execution state** — authoring, validation, rendering, QC, or a
   recorded failure.

Never put requested intent in the same unlabeled visual vocabulary as artifact
completion. `REQUESTED · Long (16:9) · Produced edit` and `STATUS · Plan ready`
can coexist without contradicting each other.

## Derive actions from artifacts

| Artifact state | Truthful status | Available action |
| --- | --- | --- |
| no manifest | Needs ingest | Ingest |
| manifest, incomplete transcripts | Needs transcript | Ingest/transcribe |
| transcripts, no plan | Ready to generate | Generate edit |
| plan, no approved candidate/final | Plan ready or review pending | Resume/review plan |
| isolated candidate, no approval | QC pending or failed | Resume QC / repair plan |
| base, no approved final | Final render pending | Resume render/QC |
| plan + hash-matched QC approval + final | Finished | Open editor; Palmier only if parity also passes |

A registry entry or folder modification time is not a pipeline stage. Registering a
project at ingest makes it recent, not edited.

## Long jobs need durable evidence

An in-memory spinner is not job observability. Hot reloads and local server restarts
erase it, leaving the user unable to distinguish “still running” from “died.” Store a
bounded event trail beside the project, display phase plus elapsed time, and turn a
run owned by a dead server process into an explicit interrupted failure. Clear that
state only after successful completion or when a new run intentionally replaces it.

## When not to use artifact existence alone

`final.mp4` proves that bytes were written; it does not prove that post-render QC
passed. New quality-policy jobs therefore render into an isolated candidate
directory and expose `final.mp4` as finished only after deterministic Audit B and
both visual critics pass, the candidate is promoted, and
`.sniper-qc-approved.json` matches the plan, manifest, and final hashes. Preserve
legacy or failed-QC artifacts as diagnostic evidence, but do not label them
finished. Likewise, never infer successful generation from the requested scope, a
project registry row, a spinner disappearing, or a newer directory timestamp.
