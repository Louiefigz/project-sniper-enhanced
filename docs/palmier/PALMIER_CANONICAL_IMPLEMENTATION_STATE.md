# Palmier-canonical implementation state

**Audit date:** 2026-07-12  
**Palmier inspected:** Palmier Pro 0.6.3 (build 64)  
**Evidence:** current repository plus a read-only Palmier MCP handshake and
tool-schema inspection. No Palmier mutation, model edit, render, or user-project
write was used for this audit.

## Product invariant

Palmier is the authoritative **working timeline**. Sniper may keep plans,
receipts, audits, and approved exports, but none of them may silently replace a
newer Palmier readback.

- A manual Palmier change advances the working revision and invalidates the
  prior approval; it is not translated backward into an older Sniper plan.
- An AI request starts from a complete readback of that Palmier revision and
  edits a full-copy candidate, never a flattened preview or stale plan.
- The last QC-approved revision remains a separate delivery checkpoint. The
  working revision may be newer while review is pending.
- The managed Palmier project identity is fixed. Sniper must not adopt a
  timeline from another active project merely because it is visible.
- Outside a short, labeled AI transaction, the active managed Palmier timeline
  is the working source of truth. Palmier exposes no hidden-timeline mutation
  API: `create_timeline` and `set_active_timeline` visibly switch the timeline.

This requires two ids, not one overloaded “latest” id:

| Field | Meaning |
|---|---|
| `workingHeadTimelineId` | What future manual and AI edits start from |
| `approvedTimelineId` | Last revision that passed deterministic and rendered QC |

## What works in the current tree

### Deterministic Sniper pipeline

The current controller is real and bounded:

1. Author `edit_plan.json`.
2. Run operator-intent, plan-lint, hook, claims, and optional reference gates.
3. Run at most four independent plan-review rounds. Produced/full edits require
   two clean reviews of the same plan authority.
4. Render an isolated candidate, bound to the plan, manifest, intent,
   reference, renderer, and QC authority digest.
5. Run deterministic Audit B and two rendered critics (`composition` and
   `editorial`).
6. If repairable findings remain, revise the plan and rerun every planning gate
   before another render. At most three render/QC rounds are allowed.
7. Promote only a hash-current candidate with schema-v2 approval evidence.

Checkpoint/resume, stop-with-checkpoint, durable logs, authority-change aborts,
and fail-closed approval are already implemented. Today, however, this pipeline
still treats `edit_plan.json` and the Sniper render as its inputs of record.

### Palmier bridge

The current verified handoff can:

- create/select a bound Palmier project;
- import/reuse content-addressed media;
- create an unclobberable shadow timeline;
- place one approved `final.mp4` master as an exact visible clip;
- read back clip identity, timing, canvas, FPS, duration, and frame count;
- export a named `timelineId`, wait for the async file to stabilize, probe its
  duration, finish audio, and publish atomically;
- serialize Palmier operations and preserve/restore the prior human timeline;
- open the current working timeline without a separate ownership ceremony;
- create a non-authoritative, source-only managed working view after ingest.

That mirror remains a useful bootstrap. The native candidate path now starts a
Palmier-canonical AI edit, but delivery promotion is not connected yet.

### Native adapter coverage

The existing `Executor` calls only a subset of Palmier's available edit tools:
`add_clips`, `set_clip_properties`, `set_keyframes`, `add_texts`,
`remove_clips`, `get_timeline`, and export. Its non-mirror translator covers
single-source cuts, speed, baseline transforms, limited punch keyframes,
pre-rendered overlays, basic text, and a simple music bed. The production sync
currently rejects that reconstruction path and requires the one-clip approved
visual master.

For projects without a managed Palmier workspace, `/ai-edit` remains plan-first.
For managed Palmier projects, it now routes to the native candidate controller:
reconcile the visible working head, plan an allowlisted lane-scoped delta, run a
fresh doctrine-aware critic, and execute into a copied candidate timeline.
Unsupported asset-generation lanes fail closed without falling back to the old
plan or changing the working timeline.

## Connected native candidate foundation

The Ask-AI controller is now wired to these low-level seams:

- `palmier.timeline-authority.json` snapshot/fingerprint support reads the
  active managed project with `captionDetail: true`, records a full and a
  copy-insensitive semantic hash, and classifies project/timeline/content drift.
- `fork_candidate` checks the saved baseline, calls
  `create_timeline({name, from: timelineId})`, re-reads the new active timeline,
  and verifies that it is a semantic copy with new ids.
- The two-phase native CLI first reconciles and records newly observed manual
  revisions, then rejects a stale planner parent before any candidate fork.
- Native plans use exact envelopes, declared lanes, allowlisted Palmier tools,
  current clip/group ids, bounded frames, and per-operation revalidation against
  the latest candidate readback.
- The executor remaps copy-regenerated ids, rejects no-op mutations and
  unexpected structural additions/removals, retains the canonical parent, and
  writes an atomic candidate receipt with QC explicitly pending.
- Project writer leases, non-queuing native Palmier locks, process-tree timeout
  escalation, and authoritative manifest resolution prevent the known
  concurrency and stale-input fallbacks.
- Existing locks, identity guards, readback verification, async export waiting,
  and QC artifacts can be reused by the canonical controller.

This foundation now executes a requested supported AI delta and resumes from a
manual Palmier baseline. It deliberately does **not** yet approve or promote the
candidate. Native candidate export, deterministic/rendered QC, compare-and-swap
promotion, and durable native resume are still required before this becomes a
complete Palmier-canonical delivery loop.

## Verified Palmier MCP surface

The installed app exposes these relevant facts:

| Primitive | Verified behavior | Integration consequence |
|---|---|---|
| `get_projects` | Lists known/open/active projects. | Bind and recheck the managed project before every read or mutation. |
| `open_project` | Opens by name/id/path and makes the project active. | User-visible project switch; never use as an unnoticed recovery. |
| `get_timeline` | Reads only the active timeline; accepts optional windowing and `captionDetail`. | Canonical readback primitive. Re-read after out-of-band/manual change, timeline switch, or failed mutation. |
| `inspect_timeline` | Renders the composited active timeline at `startFrame`, or samples `[startFrame,endFrame)` with `maxFrames` (max 12). | Visual spot-check primitive. Current Python client discards non-text MCP content, so image-block support remains to be added. |
| `create_timeline` | `{name?, from?: timelineId}`; a `from` call makes a full copy, gives every clip/track new ids, and makes the copy active. | Required non-destructive AI revision primitive. It is user-visible, not a background/hidden fork. |
| `set_active_timeline` | `{timelineId}` switches the active/read-edit target. | Required for parent/candidate verification; always re-read afterward. |
| `export_project` | Accepts `timelineId` for video/XML/FCPXML; video export is asynchronous. `timelineId` is invalid only for self-contained Palmier-package mode. | QC can export the exact candidate without relying on whichever id was previously saved. Existing stable-file polling is reusable. |
| `undo` | No arguments; undoes only this assistant session's latest assistant edit. It refuses if the latest edit was manual. | Not a transaction or general rollback. Preserve the parent timeline and abandon/rebase a failed candidate. |

There is no exposed `redo` tool and no atomic compare-and-swap or hidden-timeline
mutation primitive.

Palmier also exposes these undoable native mutation tools:

- placement/structure: `add_clips`, `insert_clips`, `move_clips`,
  `remove_clips`, `manage_tracks`, `split_clips`, `ripple_delete_ranges`;
- clip/composition: `set_clip_properties`, `set_keyframes`, `apply_layout`,
  `sync_clips`, `set_project_settings`;
- text/audio/look: `add_texts`, `update_text`, `add_captions`, `apply_color`,
  `apply_effect`, `denoise_audio`, `remove_words`, `remove_silence`;
- media/library: `import_media`, `organize_media` (including timeline delete),
  plus search/inspection and confirmed-cost generation tools.

Palmier's mutation contract returns deltas in `get_timeline` vocabulary
(`clips`, shifts, removed ids, created tracks, and notes). A canonical executor
must validate and apply those deltas to its expected model; unexpected removals,
track changes, or id changes abort the batch.

## Target state machine

| State | Authority | Honest UI | Safe transition |
|---|---|---|---|
| `NO_WORKSPACE` | Source manifest | Prepare media | Create/open source-only Palmier view. |
| `PALMIER_HEAD` | Full normalized active-timeline readback | Open/edit in Palmier; Ask AI | Manual drift advances the head and clears approval. AI request snapshots the head. |
| `AI_TRANSACTION` | Frozen parent fingerprint plus expected mutation deltas | AI is changing a copied revision; avoid simultaneous edits | `create_timeline(from=head)`, validate copy, apply bounded mutations. A manual/out-of-band delta stops and rebases; it is never erased. |
| `QC_PENDING` | Candidate timeline readback and export hash | Review in Palmier; last approved delivery remains available | Structural readback, composited inspection, explicit-id export, deterministic audit, two rendered critics. Repair creates another full-copy revision or applies a separately gated delta. |
| `APPROVED_HEAD` | Candidate readback + QC approval | Current in Palmier; approved | Record candidate as both working and approved head. |
| `MANUAL_ADVANCE` | Newly observed Palmier readback | Manual changes saved; approval needs review | Persist as working head, invalidate the old approval, then allow another AI request from this exact revision. |
| `CONFLICT` | Preserved parent and observed Palmier state | Palmier changed while AI/QC ran; nothing overwritten | Adopt the visible managed revision or explicitly return to the preserved parent, then rerun. |
| `BLOCKED` | Last complete readback | Explain the one missing prerequisite | Wrong active project, incomplete readback, MCP unavailable, or unsupported material property fails closed. |

## Phase-by-phase integration

### 1. Bootstrap

After ingest, create the source-only Palmier working view. Immediately capture a
complete normalized readback as `workingHeadTimelineId`. Do not call it approved.

### 2. Reconcile before every action

On project open, Ask AI, render/QC, and export:

1. verify the active project id;
2. read `get_timeline(captionDetail: true)`;
3. compare id and fingerprint to the saved working head;
4. if Palmier changed, save that readback as the new working head and invalidate
   the prior approval before doing anything else.

Palmier exposes no change notification in the inspected MCP contract, so
“manual edits become truth” is guaranteed at these reconciliation boundaries,
not by pretending Sniper receives instantaneous events.

### 3. Plan an AI delta from Palmier

Replace the current plan-only prompt with a bounded `PalmierMutationPlan`:

- input authority: project id, working timeline id, full fingerprint, transcript
  and media-read hashes;
- requested semantic change and affected time range;
- allowlisted Palmier tool calls with exact preconditions and expected effects;
- no model-invented clip, track, media, caption-group, or timeline ids;
- generation calls separated behind explicit cost confirmation.

The existing operator-intent, hook, claims, and reference gates remain useful,
but the current `plan_lint` is not sufficient. Add deterministic validation for
tool schemas, id membership, track/media compatibility, half-open ranges,
linked A/V behavior, overlaps/ripples, expected removals, and readback coverage.

### 4. Fork and execute

Freshly re-read the parent, then call
`create_timeline({name, from: workingHeadTimelineId})`. Verify semantic equality
before the first mutation. Apply only the validated calls, one bounded batch at
a time, and reconcile every returned delta. On a failure or unexpected manual
change, preserve both timelines and stop; `undo` is not a safe cross-session
rollback.

### 5. Review and QC

Use `get_timeline` for structural/property checks and `inspect_timeline` for
targeted composited frames. Export with the candidate's explicit `timelineId`,
wait for the file, bind its hash to the candidate fingerprint, then reuse Audit
B and the composition/editorial critics. A repair must be another authority-
bound mutation plan; it may not fall back to editing stale `edit_plan.json`.

### 6. Commit

Re-read the candidate after QC. If its fingerprint differs from the reviewed
one, manual work occurred and QC must rerun from that new working revision. If
it matches, atomically record the candidate as the working head and the approved
head with its export/QC proof. The old timeline remains intact as history.

## Remaining end-to-end work

1. Split the authority record into durable working-head, approved-head, and
   pending-candidate records; do not overwrite the canonical baseline merely by
   forking a candidate.
2. Page caption-detail readback instead of permanently blocking groups above
   Palmier's 200-row detail cap. Define and test which omitted/default fields are
   normalized into the fingerprint.
3. Extend `PalmierClient` to retain image/content blocks from
   `inspect_timeline`; it currently concatenates text only.
4. Extend the connected typed mutation-plan validator/executor as additional
   Palmier lanes earn deterministic adapters; unsupported lanes stay fail-closed.
5. Extend the connected planner + fresh critic into a bounded candidate repair
   loop while preserving the controller-owned lane envelope.
6. Export the explicit candidate timeline and bind existing deterministic and
   visual QC evidence to its readback fingerprint.
7. Implement conflict/rebase and candidate commit without using assistant-only
   `undo` as rollback.
8. Finish replacing the legacy `ownership: sniper|palmier` storage model with
   working-vs-approved revision status. “Open in Palmier” is the normal path; manual
   edits invalidate approval, not ownership.
9. Add offline contract tests for manual drift adoption, full-copy id churn,
   concurrent manual edit during execution/QC, partial mutation failure,
   caption paging, explicit-id export, repair loops, and restart/resume.

Until these are complete, the safe behavior is to preserve every manual Palmier
revision, route supported Ask-AI requests into a non-destructive native
candidate, and reject unsupported lanes without falling back to the stale plan.
No native candidate may claim delivery approval yet.
