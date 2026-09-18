# Palmier-Primary Skilled-Agent Orchestration Handoff

> **STATUS: SUPERSEDED** by [PALMIER_LIVE_BUILD_SPEC.md](PALMIER_LIVE_BUILD_SPEC.md) (normative for current state). Kept for history; statements below may be stale.

Status: implementation handoff, not a future-looking product essay  
Date: 2026-07-13  
Repository: `/path/to/PROJECT_SNIPER`

## Headless skill + MCP proof completed

On 2026-07-13, `scripts/producer/tests/live_headless_claude_mcp_smoke.py` passed against a disposable matte-only Palmier project:

- noninteractive Claude invoked the project `producer` skill;
- explicit `palmier-pro` MCP connected without `--safe-mode`;
- the first turn streamed `get_timeline` and `add_texts` and placed one editable text clip in 25.522 seconds;
- `--resume` reused the same Claude session and streamed `get_timeline` plus `set_keyframes` in 16.592 seconds;
- Palmier readback proved the text clip and exact scale keyframes `[0,1.0]`, `[12,1.08]`, `[36,1.0]`;
- the prior Palmier project was restored and the disposable project was removed.

This clears the core A2 transport/session risk with an enumerated tool allowlist. At the time of that smoke it did not yet prove direct Claude media import/cut construction, a complete Produced edit, or the GUI route/UI wrapper; the implementation update below supersedes the wrapper portion only.

## GUI live-build implementation update

The additive GUI path is now implemented and offline-verified:

- `src/app/api/producer/live-build/` validates a current approved plan and exact active Palmier parent, forks a controller-owned visible candidate, resumes only a stream-proved Claude session (otherwise starts a fresh skilled session), uses strict enumerated MCP tools, and streams normalized operation/result events;
- project creation/navigation and export are excluded from the model allowlist, so Claude can mutate only the already-bound candidate and the controller owns exact-candidate export/QC;
- `.palmier-live-build.state.json` and `.palmier-live-build.jsonl` preserve the retained session, candidate, operation counts, and stop/resume evidence;
- the candidate checkpoint binds fresh semantic readback to the approved plan, planning reviews, pinned doctrine/pipeline, parent, journal, and session;
- deterministic candidate checks run before independent composition/editorial critics, which execute in parallel against the same exact export;
- a live-build QC failure never creates a wholesale replacement. Its exact issues, rejected fingerprint, and evidence paths are fed to the retained session for a scoped repair, followed by a complete fresh export/QC pass;
- the Producer Palmier bar exposes build, resume, stop-and-keep, streamed operations, latency, QC progress, and the existing explicit promotion action.

Verification completed: TypeScript type-check and targeted lint pass; the Next production build succeeds; focused live-build/session/QC tests pass; the full Python Producer suite passes 1,454 tests. Every TypeScript test outside two unrelated concurrent graphics-governance gates passes. Those two gates currently report four invalid catalog defaults (three too-short holds and one empty avatar identity) and a missing duration-floor instruction in the graphics-governance prompt.

This was not the full Produced-video proof. At the time, the next milestone was
an isolated complete first-60-seconds run. That later run exercised substantial
transport and mutation mechanics but failed product-quality review after
56m48s: QC remained pending, seven captions lost karaoke timing, and the wrong
3840×2160 canvas was accepted. It is historical falsification evidence, not
connected P5 qualification.

The remaining sections preserve the pre-implementation diagnosis and target rationale. Statements below that describe `--safe-mode` or the GUI wrapper as current are historical; the implementation update above and `PALMIER_LIVE_BUILD_SPEC.md` are normative for current state.

## Read this first

The product goal has always been the successful Claude Code + Palmier MCP workflow:

1. An editor brain reads the Producer skill, transcript, project intent, reference evidence, and accumulated failure lessons.
2. It makes an editorial plan.
3. One doctrine-aware Claude Code build session executes that plan directly and incrementally through Palmier MCP.
4. The operator sees cuts, graphics, motion, transitions, framing, and audio work arrive while the build runs.
5. Palmier is the source of truth. A manual Palmier change becomes the next AI edit's starting point.
6. Deterministic gates and independent critics protect quality, but they do not hide all work behind an in-house render or repeatedly restart the entire job.

The legacy finished-video route still does not deliver that workflow; the new additive live-build route is its offline-verified implementation. Do not conflate further hardening of the legacy plan -> in-house render -> late Palmier checkpoint path with proving the new route end to end.

## The historical implementation mistake (fixed for current authoring)

The GUI prompt text told Claude to read a pinned Producer skill and failure ledger, but the Claude process was launched with `--safe-mode`. Claude Code defines that mode as disabling `CLAUDE.md`, skills, plugins, hooks, MCP servers, agents, and other customizations. That flag has now been removed; current authoring explicitly allows `Skill(producer)`, and the live mutation turn adds strict enumerated Palmier MCP.

The GUI can still manually read a copied `SKILL.md` as an ordinary file because the prompt names its path. That is useful evidence injection, but it is not equivalent to running Claude Code with the Producer skill and Palmier MCP enabled. The existing prompt wiring is:

- `src/app/api/producer/auto-edit/authoring-prompt.ts` embeds the pinned skill and ledger in the visual-authoring instructions.
- `src/app/api/producer/auto-edit/cut-authoring-prompt.ts` does the same for transcript cutting.
- Plan and cut critics receive immutable doctrine snapshots.

After that manually instructed authoring pass, Palmier execution is handed to deterministic Python translation. The full Produced edit also takes a branch that deliberately avoids the current native Palmier path:

- `src/app/api/producer/auto-edit/palmier-primary-selection.ts:62-72` classifies graphics, transitions, credibility, b-roll, music, and reference mechanics as requiring a rich plan.
- `src/app/api/producer/auto-edit/palmier-primary-selection.ts:139-145` returns `kind: "governed-plan"` for those lanes.
- `src/app/api/producer/auto-edit/palmier-primary.ts:154-168` returns to the legacy pipeline for that result.
- `src/app/api/producer/auto-edit/pipeline.ts:269-285` then runs authoring, whole-plan reviews, in-house candidate rendering, QC, and late checkpoints.
- `src/app/api/producer/ai-edit/palmier-native-runner.ts:119-137` uses Claude only to draft a native operation list.
- `src/app/api/producer/ai-edit/palmier-native-runner.ts:261-280` executes that list through `native_delta_cli.py`; Claude is not driving Palmier MCP as it did in the successful CLI conversation.

This is the material difference. It is not accurately summarized as “the GUI has no context.” It has prompt context, but it deliberately disables the Claude Code skill/MCP environment, repeatedly creates fresh bounded subprocesses, and removes the skilled agent from the live execution loop.

The normative implementation design already exists in `docs/palmier/PALMIER_LIVE_BUILD_SPEC.md`. Its A2 path—one headless Claude process with explicit Palmier MCP configuration—is the shortest route to reproducing the proven CLI behavior. This handoff adds authority/adoption requirements around that design; it must not replace A2 with a new multi-writer agent framework.

## Why the CLI feels immediate

The successful CLI path keeps a Claude Code agent in one working conversation. That agent:

- has already read and retained the Producer skill and project evidence;
- directly calls Palmier MCP tools;
- sees readback from the same project after each operation;
- performs small mutations instead of waiting for an entire in-house render;
- can adjust the next operation using the live timeline;
- exposes every imported asset, cut, text element, and keyframe as it lands.

The GUI currently pays for fresh cut authoring, cut critics, visual authoring, plan critics, deterministic gates, rendering, rendered critics, and possible full-plan repair. Historically, it also repeated approved work after interrupted resumes. This is why a sequence of individually reasonable safeguards became a multi-hour controller with little visible output.

## How to increase quality and reduce wall time together

Quality and speed are not opposing goals here. The fast path removes duplicate cognition and hidden rendering; it does not remove editorial safeguards.

The required critical path is:

1. One skill-enabled Claude session performs transcript-first planning, including cut proof, intro-retention mapping, graphics/template decisions, motion, transitions, framing, and audio intent.
2. Deterministic gates run on that exact plan.
3. Required read-only critics run concurrently against the same immutable plan. One merged revision is sent back to the same session only when necessary.
4. Resume that session and apply the approved plan directly through Palmier MCP, operation by operation. The operator sees each result immediately.
5. Pre-render independent graphic/HyperFrame assets concurrently while earlier approved cuts are being placed.
6. Run deterministic readback checks after each batch.
7. Export the exact Palmier candidate once and run composition/editorial QC concurrently.
8. Repair only failed operation IDs or the failed lane, then recheck the affected evidence.

The wall-time model should be approximately:

```text
plan
+ max(plan critics)
+ max(independent asset generation, serialized visible MCP placement)
+ max(rendered QC critics)
+ scoped repairs
```

It must not remain:

```text
cut author + cut critic A + cut critic B
+ visual author + plan critic A + plan critic B
+ full in-house render
+ visual critic A + visual critic B
+ whole-plan restart after each failure
```

The skill supplies learned craft judgment. Deterministic contracts prevent known failures. Independent critics catch soft editorial defects. Exact Palmier readback/export proves the result. Direct MCP execution and concurrency remove waiting without removing those quality layers.

## Live state at this handoff

Re-read live state before doing anything; these facts are a snapshot.

- The GUI job at `/path/to/run/producer/.sniper-auto-edit-job.json` is `status: "interrupted"`, checkpoint `authoring`. There is no running GUI worker capable of publishing new edits.
- Claude Code is editing Palmier project `<PALMIER_PROJECT_A>`, named `C0679 First 60s - Claude Build`, at `/path/to/C0679-claude-build.palmier`.
- Its active timeline was `<PALMIER_TIMELINE_A>`, named `Claude edit — my cuts`, with four tracks and eleven clips at audit time.
- Sniper's sidecar is bound to a different Palmier project, `<PALMIER_PROJECT_B>`, at `/path/to/C0679-sniper-build.palmier`, timeline `<PALMIER_TIMELINE_B>`.
- Therefore the GUI is not slowly editing the project visible in Palmier. It is disconnected from it.

Do not click or programmatically invoke GUI Resume, Retry, Review Saved Plan, or GUI Open Palmier while the external Claude Code session is still writing. Do not run a live Palmier smoke against the user's active project.

Existing compare-and-swap guards should prevent a silent overwrite, but the GUI can still waste minutes operating on stale `edit_plan.json` before the later Palmier boundary fails closed.

## Non-negotiable product invariants

### Palmier authority

1. One Sniper project is bound to exactly one Palmier project and one current working timeline.
2. The current verified Palmier readback is the editing source of truth.
3. Every AI mutation declares a parent `{projectId, timelineId, fingerprint}`.
4. Every mutation is rejected or rebased when that parent no longer matches.
5. A manual change inside the bound Palmier project is adopted as the next working head after readback; it is never overwritten by stale plan state.
6. A different active Palmier project is not silently adopted. Launch blocks immediately and offers an explicit Adopt/Open choice.
7. Sniper plan artifacts are planning and audit records. They are not allowed to outrank newer Palmier state.

### Skilled agents

1. One planner/build conversation must run with Claude Code skills enabled, not `--safe-mode`.
2. It must load the complete Producer skill, relevant style/reference doctrine, failure ledger, transcript, manifest, operator intent, and current Palmier readback.
3. Every independent critic receives the same immutable authority packet and the relevant complete doctrine. Critics may be separate read-only agents.
4. The agent that executes edits must be the skill-loaded, MCP-connected Claude Code session. Do not stop intelligent participation at JSON plan generation.
5. The build session should retain the approved plan and live readback throughout a run. Do not launch a new general-purpose editor brain for every tiny step.

### Live execution

1. Planning and read-only criticism may run concurrently against immutable authority.
2. Palmier mutations are serialized through one project-scoped lease/queue. Multiple agents must never write the same timeline concurrently.
3. Each applied batch is small, visible, idempotent, and readback-verified.
4. The UI streams the current operation, completed operations, next operation, elapsed time, and remaining lane count.
5. Stop keeps the last verified Palmier checkpoint. Resume starts from Palmier readback, not from an assumed plan checkpoint.
6. No “complete” status is allowed unless the operator-requested lanes are present or explicitly reported as unsupported/waived.

### Quality

1. Transcript-safe cutting is approved before downstream visual timing is committed.
2. The intro retention contract is fail-closed for Produced long-form work.
3. Graphics require semantic binding, template diversity, identity-correct assets, readable contrast, complete entrance/dwell/exit timing, and safe framing/recompose.
4. Motion and transitions require supported Palmier realization and readback evidence. Unsupported behavior is explicit; it is never silently omitted or mislabeled exact.
5. Rendered QC uses the exact Palmier candidate export and targets the affected lane for repair.
6. A graphics defect does not restart transcript cutting. A motion defect does not re-author every graphic. Repairs are scoped.

## Target architecture

```text
Operator intent + transcript + references + current Palmier readback
                              |
                              v
      one skill-enabled Claude Code planning conversation
                              |
             transcript-first complete edit plan
                              |
          deterministic gates + parallel read-only critics
                              |
                              v
       resume the same Claude session as the only MCP writer
                              |
       cuts -> graphics -> motion -> transitions -> audio
       each: MCP apply -> readback -> journal -> UI event
                              |
                              v
       exact Palmier export + parallel read-only QC critics
                              |
                    scoped repair when required
```

The deterministic layer remains important, but its correct jobs are validation, capability checks, authority hashing, operation journaling, readback verification, and QC evidence. It must not replace the skilled MCP writer.

## Required agent topology

### 1. One skill-enabled planner/build session

Use one long-lived/resumable Claude Code session per build. It owns global editorial coherence, produces the plan, and resumes as the sole Palmier MCP writer after approval. This is the proven CLI interaction wrapped by the GUI, not a new editor architecture.

The noninteractive launch must remove `--safe-mode` and explicitly constrain what is enabled:

```text
claude -p <prompt> \
  --session-id <run-uuid> \
  --output-format stream-json \
  --mcp-config '{"mcpServers":{"palmier-pro":{"type":"http","url":"http://127.0.0.1:19789/mcp"}}}' \
  --strict-mcp-config \
  --allowedTools 'Read,Glob,Grep,<pinned gate commands>,mcp__palmier-pro__*'
```

Use `--resume <session-id>` for execution/repair turns so the agent retains its plan and reasoning. `--strict-mcp-config` prevents inheritance of unrelated MCP servers. If wildcard MCP allowlisting is not accepted, enumerate the required Palmier tools as specified in `docs/palmier/PALMIER_LIVE_BUILD_SPEC.md`.

Required output includes:

- approved transcript cuts and removal evidence;
- intro retention beats and visual obligations;
- graphic/card/template selection with semantic reasons and asset bindings;
- framing/recompose obligations;
- punch/zoom/keyframe and transition intent;
- captions/audio/music/b-roll decisions;
- dependencies between operation batches;
- expected QC evidence for each lane.

The planning turn does not mutate Palmier until deterministic gates and required independent critics pass. After approval, resume that same session with Palmier mutation tools enabled and the exact approved-plan hash.

### 2. Parallel helpers are read-only or produce assets

Do not create several primary editing agents that compete for timeline ownership. Extra agents are useful only for work that cannot collide:

- cut and plan critics may review the same immutable plan concurrently;
- HyperFrames/graphic asset rendering may occur concurrently after template decisions are approved;
- composition and editorial QC critics may inspect the same exact Palmier export concurrently;
- a scoped repair critic may explain one failed lane without touching Palmier.

All of their results return to the one build session. They do not acquire independent write ownership.

### 3. The resumed Claude session is the persistent MCP writer

The resumed Claude session is the only writer. It must:

- connect to the same Palmier MCP server used by successful CLI sessions;
- retain/load the Producer skill and exact approved plan;
- acquire a project-scoped lease;
- verify the expected parent fingerprint;
- apply a small operation batch using MCP;
- read the timeline back;
- record the new fingerprint and operation evidence;
- emit progress immediately;
- release or renew the lease;
- continue from the new readback.

The GUI streams every `tool_use`/`tool_result` event from this process so the operator sees the same progress they see in Claude Code. Do not implement execution as a succession of unrelated `claude -p` calls that each reread the entire project.

## Operation journal

Add an append-only, atomic build journal in the producer directory. Suggested file: `.palmier-live-build.jsonl` plus a compact state sidecar.

Each record needs:

- `runId`
- `operationId`
- `lane`
- `planHash`
- `doctrineHash`
- parent project/timeline/fingerprint
- requested MCP operation or batch hash
- status: proposed, gated, applying, verified, rejected, superseded
- start/completion timestamps
- resulting project/timeline/fingerprint
- readback evidence path/hash
- QC evidence or failure code
- rollback/candidate timeline identity

Operation IDs must be stable and idempotent. Resume skips already verified operations only when their resulting authority is still the current Palmier ancestor.

## P0: bind or adopt the Palmier project before any model work

There is currently no route that adopts the project visible in Palmier as the Sniper project's working authority. Build this first.

Suggested surface:

- `POST /api/producer/palmier/adopt`
- a read-only preflight used by every Auto Edit/Resume/Retry launch
- UI dialog: `Palmier is showing a different project` with `Adopt current Palmier project`, `Open linked project`, and `Cancel`

Adoption must:

1. Read the active Palmier project and complete active timeline through MCP.
2. Require explicit operator confirmation when its project ID differs from the stored sidecar.
3. Capture a complete fingerprint and semantic fingerprint.
4. Atomically update `palmier.sync.json` and the timeline-authority record.
5. Mark origin as a Palmier/operator adoption, not a Sniper-generated checkpoint.
6. Preserve the previous binding as history; never delete either project.
7. Invalidate stale candidate/plan authority without deleting audit artifacts.
8. Emit a receipt that later AI operations must bind.

Reuse the authority and CAS primitives in:

- `scripts/producer/palmier/timeline_authority.py`
- `scripts/producer/palmier/timeline_guard.py`
- `scripts/producer/palmier/ownership.py`
- `scripts/producer/palmier/native_io.py`
- `scripts/producer/palmier/mcp_client.py`

Every expensive launch must compare the active Palmier project ID with the sidecar in the first few seconds. Do not wait until a late checkpoint to discover the mismatch.

## Implementation sequence

### Phase 0 — freeze and prove authority

- Do not mutate the user's active CLI project while their Claude Code session owns it.
- Add immediate active-project preflight.
- Add explicit adoption with atomic receipt.
- Add project-scoped writer lease covering GUI and externally registered writers.
- Test same-project manual edits, different-project mismatch, interrupted adoption, and stale sidecar recovery.

Exit criterion: the GUI can bind to the exact Palmier project the operator is watching, and cannot start against a different project silently.

### Phase 1 — one approved global plan

- Keep transcript-first cutting, deterministic contracts, and immutable authority packets.
- Keep the newly implemented concurrent read-only cut/planning critics.
- Remove duplicate cut/visual authoring on resume when the saved cut still passes deterministic validation.
- Produce an operation DAG suitable for lane execution.
- Store one bounded evidence packet so agents do not repeatedly traverse the repository.

Exit criterion: one plan is reviewed once per authority, resumable, and does not re-author unchanged lanes.

### Phase 2 — skilled MCP conductor

- Add a persistent/resumable Claude conductor with the Palmier MCP config and mutation-tool allowlist.
- Give it the pinned Producer skill, failure ledger, approved DAG, current authority receipt, and lane contracts.
- Move rich Produced jobs away from the `governed-plan -> legacy in-house render` fallback.
- Keep Python native gates and CAS checks around every proposed operation batch.
- Emit progress and readback after each batch.

Exit criterion: an approved cut, graphic, and motion batch visibly lands in the same open Palmier timeline before final QC.

### Phase 3 — lane orchestration and scoped repair

- Plan independent lanes concurrently after cut authority is fixed.
- Serialize only Palmier writes.
- Run lane gates before application.
- Run exact-export QC after meaningful milestones.
- Route each finding to its owning lane.
- Re-plan/reapply only the affected operation IDs.

Exit criterion: a blue-on-blue graphic failure repairs graphics only; it does not re-run transcript cutting or all planning critics.

### Phase 4 — honest UI

Show:

- linked Palmier project/timeline and authority owner;
- current agent/lane/operation;
- completed and remaining operations;
- current readback fingerprint;
- safe Stop and Resume;
- visible project-mismatch/adoption state;
- explicit capability limitations;
- exact QC status and scoped repair status.

Palmier opens as the primary working surface once the source view is bound. The GUI is the conductor/status/ask interface, not a competing NLE.

### Phase 5 — retire misleading paths

- Do not use a flat MP4 mirror as the primary editable result.
- Do not create disposable hidden timelines as the normal live-build experience.
- Keep in-house rendering only as an optional deterministic export/fallback and test oracle.
- Remove or relabel any UI that promises live Palmier work while routing Produced jobs to delayed checkpoints.

## File-level change map

Start with these files; do not invent a second orchestration stack before checking the existing native and authority modules.

- `src/app/api/producer/auto-edit/palmier-primary-selection.ts`
  - Stop classifying rich lanes as a reason to abandon live Palmier execution.
  - Select the governed skilled-conductor path instead.
- `src/app/api/producer/auto-edit/palmier-primary.ts`
  - Orchestrate global plan approval, persistent conductor execution, exact candidate QC, and promotion.
- `src/app/api/producer/auto-edit/pipeline.ts`
  - Make Palmier-primary the normal Produced path once a source workspace is bound.
  - Keep legacy fallback explicit and operator-visible.
- `src/app/api/producer/auto-edit/authoring.ts`
  - Reuse a resumable planner/conductor session instead of repeated unrelated whole-job subprocesses.
- `src/app/api/producer/ai-edit/palmier-native-runner.ts`
  - Evolve from model-drafts/Python-executes into skill-loaded conductor-proposes-and-applies through governed MCP batches.
- `src/app/api/producer/ai-edit/palmier-native-process.ts`
  - Add session lifecycle, MCP config, heartbeat, cancellation, and resume support.
- `src/app/api/producer/auto-edit/authoring-stage.ts`
  - Fix fresh Review Saved Plan behavior so valid saved cuts are revalidated/reviewed without rerunning cut and visual writers.
- `src/app/api/producer/palmier/workspace/route.ts`
  - Add active-project mismatch preflight or share it with the new adoption route.
- `src/app/api/producer/palmier/view/target.ts`
  - Surface linked-vs-active identity instead of resolving only the sidecar target.
- `scripts/producer/palmier/native_delta.py`
  - Retain as deterministic operation validation/application support and idempotency engine, not the editorial brain.
- `scripts/producer/palmier/timeline_authority.py`
  - Extend atomic adoption and operation-parent receipts.
- `src/components/producer/*`
  - Add Adopt/Open/Cancel mismatch UX and operation-level progress.

## Existing WIP worth preserving

The worktree is intentionally very dirty. Do not reset, checkout, or discard unrelated changes.

Useful completed work at handoff:

- Cut and planning critics now batch safely in parallel against one immutable authority. Gates run once, critics receive separate hash-bound packets, issues merge deterministically, and writers remain serialized.
- Composite visual QC now detects missing base reference, no-op/invisible graphics, poor actual-footage contrast, and missing/uniform transition evidence.
- Template visual contracts enforce named-brand color assets, avatar identity, and visible completion/dwell/exit floors.
- Recompose, smooth-ramp, keyframe, and transition translation has been tightened and fails closed where Palmier fidelity is not proved.
- Working Palmier checkpoints no longer publish raw unreviewed visual plans.
- Progress events include elapsed time for authoring/review stages.

Known test state:

- Focused motion/recompose/transition tests: 253 passing.
- Auto-edit concurrency, loop, type-check, and targeted lint tests pass.
- The full npm suite currently reaches an unrelated `comps-catalog-coverage.test.ts` failure caused by newly tightened Nate Herk/avatar default-spec floors. Do not misattribute that failure to critic concurrency.
- A disposable live Palmier smoke exists at `scripts/producer/tests/live_palmier_canonical_smoke.py`, but do not run it while the user's active CLI build is open/writing.

## Acceptance test: the first 60 seconds

Use the same C0679 source only after the current CLI session is finished or explicitly paused and its project has been adopted.

The test passes only when all of these are true:

1. Sniper preflight proves it is bound to the exact project visible in Palmier.
2. The lead planner and every lane agent record the pinned Producer doctrine hash they used.
3. Transcript cuts are evidence-backed and independently approved.
4. The intro retention map identifies all earned visual beats before execution.
5. Cuts arrive visibly in Palmier, followed by separate graphics/assets/text, motion/keyframes, transitions, framing, and audio/caption elements as their batches pass.
6. The UI names the exact operation in progress and never sits on a stale generic status.
7. Manual Palmier movement/text edits between batches are reconciled and become the next parent authority.
8. Graphics use varied compatible templates, correct OpenAI/Claude/Gemini identity colors, readable contrast, complete animation timing, and correct recompose/framing.
9. QC exports the exact editable candidate, catches the previously observed choppiness/contrast/timing/framing failures, and scopes repairs to their lanes.
10. Stop preserves the last verified timeline; Resume continues from its readback without redoing approved work.
11. No requested lane disappears merely because Palmier lacks a native primitive. It is either represented as a separate imported/baked element with an honest fidelity label or blocks with a specific actionable capability message.
12. GUI wall time and first-visible-edit latency are measured against the successful CLI baseline on the same footage/model. The GUI may add bounded review time, but it must not spend tens of minutes with zero visible operations or repeat unchanged stages.

## Tests the next agent must add

- Active Palmier project mismatch blocks before model spawn.
- Explicit adoption atomically changes sidecar + authority and preserves history.
- Adoption failure leaves the old binding intact.
- Same-project manual edits advance working authority.
- Different-project activity never silently changes binding.
- Persistent conductor loads the pinned Producer skill and MCP server.
- Rich Produced lanes select the skilled live path, not legacy fallback.
- Read-only agents may run concurrently; MCP mutations cannot overlap.
- Each operation uses expected-parent CAS and produces verified readback.
- Resume does not replay verified operation IDs.
- A scoped QC finding invokes only the owning lane repair.
- Stop retains the last verified operation and terminates the conductor tree.
- UI progress reports operation/remaining count and project identity.
- End-to-end disposable Palmier test proves cut -> graphic -> motion appears incrementally and survives readback/export.

## Self-improvement contract

The system must learn, but a live run must not mutate its own doctrine.

1. Record deterministic failures, critic findings, operator corrections, and Palmier manual changes as structured observations.
2. Cluster observations into candidate lessons after the run.
3. Evaluate proposed doctrine/template changes against regression fixtures and prior approved projects.
4. Promote a versioned doctrine snapshot only after tests pass.
5. Bind every new run to one immutable doctrine version.
6. Never let a mid-run code/doctrine change invalidate or silently redirect the active build.

## Definition of done

This work is not done when a spec exists, when a plan passes, when a flat video renders, or when a hidden checkpoint is created.

It is done when a user can click Auto Edit, see the exact linked Palmier project open, watch doctrine-governed edits arrive incrementally as separated elements, manually change any of them, ask the AI for another change based on that current Palmier state, stop/resume safely, and receive exact-export QC without the controller restarting unrelated work.
