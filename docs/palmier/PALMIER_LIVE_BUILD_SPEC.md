> Authored 2026-07-13; implementation status updated 2026-07-30. Implementation
> spec for the experimental "Build live in Palmier" GUI mode and its target
> connected behavior. Grounded in the live WIP; every claim carries a file:line.
> Sections that retain `NEW`, `create`, or `modify` labels are the original
> build blueprint, not a current-file inventory.

# Build Live in Palmier — Implementation Spec

> **STATUS: LOCAL/OFFLINE PREREQUISITES IMPLEMENTED; CONNECTED PRODUCT
> UNQUALIFIED.** The route, controller, strict operation journal, fail-closed
> resume, candidate export/QC, explicit promotion, and GUI control exist and are
> production-callable. `BUILD VERIFIED` in this document means local UI/build
> verification only. Editable/hybrid Palmier delivery remains isolated and
> P5-blocked; a representative connected short/long cohort has not qualified
> it. The approved exact `final.mp4` plus its flat mirror remains the safe
> delivery path.

**Experimental feature contract:** A GUI "Build live in Palmier" mode where a
spawned local `claude` agent reads the producer doctrine and drives the Palmier
Pro MCP directly and incrementally into a visible candidate. The controller,
not the model, owns authority, QC, and promotion. This describes the implemented
local protocol and its target connected behavior; it is not a release claim
that every planned lane already lands in a qualified editable timeline.

---

## 1. Goal & the precise gap

**Goal.** Reproduce, inside the PRODUCER GUI, the interactive CLI session where a local `claude` agent read the producer doctrine and drove the Palmier Pro MCP (`http://127.0.0.1:19789/mcp`) call-by-call, growing one live timeline the operator watched populate in real time — each `add_clips`, `add_texts`, `set_keyframes`, `apply_color` landing visibly, one at a time, in the timeline the operator keeps.

**2026-07-13 Phase-0 update.** The disposable `live_headless_claude_mcp_smoke.py` test proved noninteractive skill invocation, explicit HTTP MCP connection, auto-approved enumerated MCP tools, streamed `tool_use` events, direct `add_texts`, same-session `--resume`, direct `set_keyframes`, exact Palmier readback, prior-project restoration, and disposable cleanup. First turn took 25.522s; resumed mutation took 16.592s. The wildcard allowlist, direct media import/cut construction, full Produced-plan scale, and GUI wrapper remain unproved.

**2026-07-13 Phase-1 historical update (offline verified; full live build was
then unproved).** The GUI gained an additive `Build live in Palmier`
route/control, a stable UUID Claude session, strict enumerated Palmier tools, a
controller-created visible candidate, streamed operation evidence, durable
stop/resume state, and hash-bound plan/journal/readback authority. The
controller, rather than the model, owned exact-candidate export, deterministic
checks, independent critics, repair, and promotion. The test counts and missing
lane statements recorded at that date are historical. A later first-60 attempt
did exercise transport and mutation mechanics, but failed product-quality
review after 56m48s: QC remained pending, seven captions lost karaoke timing,
and the wrong 3840×2160 canvas was accepted. It is not connected P5
qualification.

**2026-07-30 authority update (local/offline verified).** The journal now parses
every bounded JSONL row strictly, fsyncs appended transitions, binds each
operation ID to one canonical tool/input hash, distinguishes mutations through
an explicit allowlist, and records `applying`, `applied`, `failed`, or
reconciled `not-applied` lifecycle. Controller heads bind the fresh candidate
fingerprint to every verified applied mutation. Resume observes Palmier
read-only first: torn/corrupt history, foreign identity, ambiguous visible
effect, manual drift, a reported apply with no candidate delta, or unsafe
same-payload replay changes state to `reconciliation_required` instead of
replaying. Desktop mutations separately retain immutable, content-addressed
pre-operation timeline snapshots.

Adjacent hybrid-delivery prerequisites are also implemented locally: Exact
Master can prepare one dedicated linked A/V pair and require complete
hidden/muted/sync-locked readback for admitted integer-rate projects; native and
Desktop Audit B enforce full-stream frame/timing/SSIM/audio parity with exact
hash-bound approximation approvals; and one standard scene-binding revision can
replace one clip while preserving every unrelated clip. These are not connected
qualification. Production authority readback now recursively partitions
`[0,totalFrames)` through `get_timeline(startFrame,endFrame,captionDetail:true)`,
deduplicates boundary-spanning captions by ID, and fails closed on missing
coverage, inconsistent overlaps, identity drift, or incomplete group counts.
Connected cohort evidence for that reader and Exact Master at fractional
project rates remain blocked. The local Desktop compiler now issues a ready
`mastered-stereo` declaration only with its complete hash-bound PCM derivation,
dedicated full-length placement, and dynamic routing steps. It persists route
authority only after complete placement and routing readback proves the exact
delta and keeps the separate Exact Master hidden/muted/locked. This production
path remains unqualified against connected representative short/long projects,
and editable stems still lack stable role/output-bus readback.

**What the GUI already does (the three governed touch-points the other agent added).** All three are orchestrated from `runAutoEditPipeline` in `src/app/api/producer/auto-edit/pipeline.ts` and gated by the `palmier.sync.json` sidecar via `managedWorkspace` (`palmier-checkpoints.ts:51-69`):

- **(1) PLAN / REVISION checkpoint** — fired after authored/revised plans and replayed through real MCP calls into a fresh non-authoritative timeline. Smooth aliveness ramps and eased pushes are now sampled into verified scale/position keyframes; automatic transitions and bracket/static motion fail closed. The remaining lossy subset strips b-roll, reframe, captions, music, audio processing, chapters, and grade. This is still a deterministic Python batch replay, not one persistent agent-driven timeline.

- **(2) RENDER checkpoint** — `pipeline.ts:258-262` (`stage:"render", mediaPath:candidatePath`). `stage=="render"` routes to `_render_steps` (`checkpoint_inputs.py:107`), a single hardcoded `{"op":"mirror"}` wrapping the in-house-rendered candidate mp4; `Executor._op_mirror` (`executor.py:97`) places it as the timeline's **one flat clip**. Pure flat-mp4 mirror.

- **(3) QC-APPROVED final mirror** — `pipeline.ts:255` & `:265` (`deps.approvedMirror`) → `publishApprovedPalmierMirror` (`palmier-checkpoints.ts:178`) → `push.py … --export DIR/final.palmier.mp4` → `run_sync` (`sync.py:230`), which **requires a mirror lane and rejects a cuts lane** (`sync.py:238-239`); `publish_master` (`mirror.py:178`) **byte-copies** the approved `final.mp4` as one flat clip.

**The remaining architectural gap.** The original gap was the absence of a
persistent agent-driven path. The current tree now has the additive live-build
route, strict enumerated MCP spawn, retained session, visible candidate,
operation stream, journal, resume controller, exact-candidate QC, and explicit
promotion control. What remains is release proof: full-fidelity connected lane
coverage, connected proof of complete paged readback, released-rate Exact Master
and audio-route
authority, a representative short/long cohort, disconnect-at-every-boundary
recovery, and a resolved human co-edit/manual-advance model. Flat-mp4 mirror
delivery remains a separate compatibility path rather than proof of the hybrid
editable product.

---

## 2. Target architecture

### End-state control/data flow

```
Operator (PRODUCER editor)
   │  clicks "Build live in Palmier"  (openPalmierWorkbench brings Palmier to front)
   ▼
POST /api/producer/live-build            [NEW SSE route]
   │  guardProjectMutation(projectRoot, "building live in Palmier")   ── 409 if a run/lease is held
   │  classifyPalmierWorkspace / managedWorkspace eligibility check
   ▼
STAGE 1 — GOVERN THE PLAN (unchanged existing machinery)
   │  captureAutoEditDoctrine(ctx,runId)            pin SKILL.md + FAILURE_LEDGER + PIPELINE.md + studies
   │  runPlanningReviewLoop:                         author edit_plan.json  →
   │     runPlanningGateBundle (operator_intent_contract, plan_lint,
   │        hook_contract, claims_contract, reference_profile_lint)  →
   │     runProducerReview (independent read-only critic, tools='none')  →
   │     runProducerRevision  → re-gate … ≥2 clean rounds, cap 4
   │  ── plan is APPROVED and byte-stable. This is the determinism boundary. ──
   ▼
STAGE 2 — EXECUTE THE PLAN LIVE, ELEMENT-BY-ELEMENT
   │  acquire SyncLock (python Palmier transaction lock)
   │  bind to the operator's ONE visible project/timeline:
   │     get_projects → open_project → set_active_timeline   (do NOT new_project)
   │  fork_candidate(from=parent)  → build INTO a fork the operator watches
   │  spawn `claude` agent   [NEW]   with --mcp-config palmier-pro + --allowedTools mcp__palmier-pro__*
   │     prompt = doctrine + the APPROVED edit_plan.json + "execute faithfully, one element at a time"
   │  agent loops:  get_timeline (once) → for each plan element:
   │     add_clips / remove_words / add_texts / import_media+add_clips /
   │     set_keyframes / apply_color / add_captions …           ← one MCP call per element
   │  each tool_use / tool_result stream-json line → SSE `palmier_op` event → GUI LiveBuildPanel
   │  per-op CAS verify (fingerprint changed, structural delta within bounds) via _apply_operation pattern
   ▼
STAGE 3 — POST-BUILD READBACK QC (drift check)
   │  get_timeline / get_transcript readback → native QC + optional back-translated gate re-run
   │  fidelity/omission findings → SSE warning events → WarningsStrip
   ▼
STAGE 4 — ACCEPT / ABANDON  (operator-driven)
   │  accept → ownership.py --handoff (persist_handoff_to_palmier)   → operator owns the live timeline
   │  abandon → discard_candidate / restore parent
   ▼
export_project {mode:'video'|'fcpxml'|'palmier'}   (optional, native — NOT a byte-copy mirror)
```

### The governance decision (stated and recommended)

Two options exist (from reader 6's analysis):

- **Option A — author+gate a plan FIRST, then execute it live.** The full `edit_plan.json` is authored and driven through `runPlanningReviewLoop` (`planning-loop.ts:223`) — `plan_lint.py`, `hook_contract.py`, `claims_contract.py`, `operator_intent_contract.py` + independent critic to ≥2 clean rounds — **before any Palmier mutation**. Then the agent executes that approved plan live.
- **Option B — let the agent improvise ops live and gate the resulting timeline** via `get_timeline` readback.

**Recommendation: Option A**, executed live by the agent. Justification, grounded:

1. **Only Option A preserves every existing editorial doctrine gate.** `plan_lint`/`hook_contract`/`claims_contract` are written against the `edit_plan.json` schema in the **OUTPUT/SOURCE-seconds** time domain; they **cannot parse Palmier timeline JSON**, which is in **project frames** (reader 6, gap §4). Option B has *no* editorial gates for a timeline — only the native vocabulary gate + `native_content_gate` + native QC readback, with **no** hook-contract front-load wall, **no** claims numeric-grounding, **no** operator-intent lane-coverage, **no** pacing gate.
2. It is exactly what SKILL.md already means by *"the plan is the determinism boundary."* The novelty is *how* the plan reaches Palmier (live, incrementally, agent-driven), not *what* gets decided.
3. It reconciles the operator's UX ask with the hard rule "every edit must be doctrine-governed." **The agent still drives the MCP directly and incrementally** (reproducing the CLI feel), but the editorial *decisions* were gated in the plan; the agent's job in Stage 2 is faithful *execution*, and Stage 3 readback QC catches any drift from the approved plan.

**Two executor sub-variants** (pick per phase, see §9):
- **A1 (deterministic Python live executor):** `live_build.py` reuses the `_apply_operation` CAS loop (`native_delta.py:140`) to walk the approved plan into the live fork, emitting one NDJSON event per element. Cheapest, most deterministic, but "no agent in the Palmier loop."
- **A2 (spawned `claude` agent executes the approved plan):** the agent is handed the approved `edit_plan.json` + doctrine + MCP access and told to execute it element-by-element. **This is the target that reproduces the CLI experience.** Ship A1 first as the proven engine, then A2 as the operator-visible mode; A2's tool calls resolve to the same MCP shapes A1 uses.

---

## 3. The MCP wiring

**Current state:** the live-build spawn now passes a strict inline Palmier MCP
configuration and an enumerated auto-approved tool surface. The controller, not
the model, binds the managed project, forks the exact parent, owns lifecycle
state, and performs readback/reconciliation. The remaining uncertainty is
connected full-plan behavior and release evidence, not absence of MCP spawn
wiring.

**The mcp-config value** (exactly the entry already working in the operator's `~/.claude.json`, but passed explicitly because Claude Code keys project-scoped MCP by exact `cwd` and the spawned agent's `cwd = REPO_ROOT = …/PROJECT_SNIPER`, which does **not** inherit the parent-dir server):

```json
{"mcpServers":{"palmier-pro":{"type":"http","url":"http://127.0.0.1:19789/mcp"}}}
```

Source the URL from `PALMIER_MCP_URL` (`palmier/_lib.ts:20`) / `DEFAULT_URL` (`mcp_client.py:19`) so there is one source of truth. `claude 2.1.207` accepts `--mcp-config` as an **inline JSON string** (no temp file needed) and supports `--strict-mcp-config`.

**Spawn-arg diff.** Current authoring args, verbatim (`authoring.ts:59-66`, `allowedTools` at `:30-40`):

```
-p <prompt> --output-format stream-json --verbose (--add-dir <dir>)…
--permission-mode acceptEdits
--allowedTools Bash(<patterns>)…,Edit(<planPath>),Write(<planPath>),Read,Glob,Grep
```

New `buildLiveBuildArgs(prompt, readDirs, mcpConfigJson)`:

```
-p <prompt> --output-format stream-json --verbose
--mcp-config '{"mcpServers":{"palmier-pro":{"type":"http","url":"http://127.0.0.1:19789/mcp"}}}'
--strict-mcp-config
--permission-mode acceptEdits
--allowedTools Read,Glob,Grep,mcp__palmier-pro__*
(--add-dir <readDir>)…
```

**Critical facts:**
- `--permission-mode acceptEdits` covers **file Edits only — NOT MCP tool calls.** The `mcp__palmier-pro__*` entry in `--allowedTools` is what makes the MCP calls **auto-approve non-interactively** (headless, no prompt). This is the load-bearing line.
- `--strict-mcp-config` prevents the agent inheriting any other user/project MCP servers (determinism).
- If the `mcp__palmier-pro__*` **wildcard** is not honored for auto-approval (see spike), fall back to **enumerating** each tool the doctrine permits: `mcp__palmier-pro__get_projects,…__open_project,…__set_active_timeline,…__get_timeline,…__get_transcript,…__import_media,…__add_clips,…__insert_clips,…__split_clips,…__move_clips,…__remove_clips,…__ripple_delete_ranges,…__set_clip_properties,…__set_keyframes,…__add_texts,…__update_text,…__add_captions,…__apply_color,…__apply_effect,…__apply_layout,…__manage_tracks,…__sync_clips,…__remove_silence,…__remove_words,…__denoise_audio,…__detect_beats,…__inspect_timeline,…__export_project,…__undo`.

**Env:** reuse `claudeProcessEnv()` (`ai-provider.ts:115`) **verbatim** — it is an allowlist that passes `HOME` + `CLAUDE_CONFIG_DIR` + `CLAUDE_CODE_*` (subscription OAuth) and **omits `ANTHROPIC_API_KEY`** → $0. `NO_PROXY` is allowlisted so localhost egress to `127.0.0.1:19789` is not proxied. **Do NOT add `ANTHROPIC_API_KEY` to the allowlist — the $0 guarantee depends on its omission.**

**cwd:** pass `--mcp-config` explicitly so `cwd` is irrelevant for MCP resolution; keep `cwd = REPO_ROOT` for doctrine `--add-dir` reads. Wrap the spawn in `trackProcessTree` / kill via `terminateProcessTree` (`child-process-lifecycle.ts:34/76`), detached per `shouldDetachProcessGroup()` (`:29`).

**Resolved spike.** `live_headless_claude_mcp_smoke.py` proved the headless HTTP-MCP transport, streamed tool events, noninteractive enumerated auto-approval, editable text, retained-session keyframes, and exact readback. The wildcard is unnecessary: production uses an enumerated allowlist. The controller—not the model—now binds and forks the verified active project/timeline, and navigation tools are unavailable during mutation. Full-plan tool coverage remains the next live proof.

---

## 4. Editorial-operation → MCP-tool mapping table

This is the heart of what the live build actually does. Every arg shape is proven in `executor.py` / the catalog; "native-editable" means the operator can later drag/trim/restyle it in Palmier, "baked-clip" means it enters as a flattened imported clip.

| Editorial move | MCP tool + arg shape | Native vs baked | Source / notes |
|---|---|---|---|
| **Trim / kept-span cut** | `add_clips {entries:[{mediaRef,startFrame,source:[startSec,endSec]}]}` — **one entry per call**, kept clip id retained | **Native, exact** | `executor._op_cuts` `:69-82` (`add_clips` `:76`); parity "exact" L71. TIMELINE=frames, SOURCE=seconds (never multiply) |
| **Speed change** | `set_clip_properties {clipIds,speed}` | Native | `executor._op_cuts` `:80` |
| **Splice / insert (ripples)** | `insert_clips {trackIndex,atFrame,entries:[{mediaRef,source|durationFrames}]}` | Native, non-destructive | catalog |
| **Split / move / delete** | `split_clips {splits:[{clipId,atFrame}]}` · `move_clips {moves:[{clipId,toFrame,toTrack}]}` · `remove_clips {clipIds}` | Native | catalog |
| **Filler / flub removal** | `get_transcript {}` → `remove_words {words:[idx|[s,e]],cutAggressiveness:'tight'|'balanced'|'loose'}` — **re-read transcript after (indices shift)** | **Native** (replaces the in-house speech-cleanup **bake**) | catalog; `native_plan` ALLOWED_TOOLS already lists `remove_words` |
| **Dead-air removal** | `remove_silence {}` (no args; ripple-closes gaps) | Native | catalog |
| **Non-word range delete** | `ripple_delete_ranges {trackIndex,ranges:[[f0,f1]],units:'frames'}` | Native | catalog |
| **Static zoom / recenter** | `set_clip_properties {clipIds,transform:{width,height,centerX,centerY}}` | Native | `executor._op_baseline` `:117-120` |
| **Keyframe motion (punch/zoom/pan)** | `set_keyframes {clipId,property:'scale'|'position',keyframes:rows}` — scale `[f,z,z,'smooth']`, position `[f,x,y,'smooth']`, **clip-relative** frames | Smooth ramps and eased pushes are sampled per frame from renderer math and readback-verified; baseline transforms compose. Bracket/static holds fail closed until exact semantics are proven. | `palmier/translate_math.py`; `palmier/verify.py` |
| **Native text / title card** | `add_texts {entries:[{content,startFrame,endFrame,animation,color,fontName,fontSize,isBold,alignment,backgroundColor,borderColor,highlightColor,transform:{centerX,centerY,width,height}}]}` (omit `trackIndex` to auto-create top track) | **Native** — executor passes only content/frames/`fadeIn` today; live agent should pass **full styling** to reach near-exact. Bespoke kinetic/branded typography beyond presets → bake | `executor._op_text` `:225`; animations: off/fadeIn/popIn/slideUp/typewriter/wordReveal/wordSlide/wordPop/wordCycle/highlightPop/highlightBlock |
| **Edit existing text later** | `update_text {clipIds|captionGroupId,content,…}` | Native | catalog |
| **HyperFrames graphic overlay** | pre-render HTML → **alpha ProRes 4444 .mov** (`graphics_render`) → `import_media {source:{path}}` → `add_clips {entries:[{mediaRef,startFrame,endFrame,trackIndex:0}]}` on **forced top track** (`add_texts` placeholder trick to spawn the top track, then `remove_clips` the placeholder) | **Baked-clip** — internal shapes/animation flattened; editable **only as a clip** (position/scale/opacity/timing) | `executor._op_overlays`/`_place_overlay` `:129-182`, `_make_overlay_track` `:129-137`; parity "baked" L122-123. index 0 renders on top |
| **Transition** | **NO native primitive.** Automatic transitions block the checkpoint instead of substituting a baked/approximate visual. Explicit non-automatic preview tooling stays labeled; `zoom-pull` still needs a verified cross-cut keyframe merge. | **Fail closed for automatic lanes** | `palmier/checkpoint_plan.py`; `palmier/transition_preview.py` |
| **Captions** | `add_captions {animation,maxWords,textCase,color,highlightColor,fontName,fontSize,isBold,alignment,transform:{centerX,centerY},censorProfanity}` → returns `captionGroupId`; restyle `update_text {captionGroupId,…}` | **Native primitive exists but RE-TRANSCRIBES** — does **not** accept Sniper's own word timing/emphasis cues → **tradeoff**: native editable captions (Palmier timing) OR bake Sniper's exact cues (not both natively) | parity "unsupported" L260-261; `translate.py:185-189` warns |
| **Color grade** | `apply_color {clipIds,exposure,contrast,temperature,tint,saturation,vibrance,highlights,shadows,whites,blacks,shadowsHue/Amount,midsHue/Amount/Gamma,highsHue/Amount/Gain,masterCurve/redCurve/…,hueCurves,lut:{path,strength},reset}`; measure with `inspect_color` | **Native, fully editable** — named grade preset knob-mapping is **unmeasured** → agent grades by knobs OR ships a real `.cube` via `lut{path}` | `translate.py:81-85` "unmeasured"; parity "unsupported" L99-101 |
| **B-roll** | `import_media {source:{path}}` → `add_clips {entries:[{mediaRef,startFrame,endFrame|source:[s,e],trackIndex}]}` on a track over base; trim via `set_clip_properties {trimStartFrame,trimEndFrame}`; `search_media`/`inspect_media` to pick | **Native** — "unsupported" verdict is only the translator refusing (`translate.py:242-246`), **not** a missing primitive → **reclassify native** | parity L262-264 |
| **Music bed** | `import_media` → `add_clips {entries:[{mediaRef,startFrame,endFrame}]}` (tiled) + `set_keyframes {property:'volume',keyframes:[[frame,vol]]}` for ducking/fades; `detect_beats {mediaRef}` for beat-sync | **Native placement** | `executor._op_music`/`_place_music_tiles` `:196-223` |
| **Denoise** | `denoise_audio {clipIds,strength(0-1)}` (DeepFilterNet3) | Native (equiv of in-house noise pass) | catalog |
| **Loudness / voice-priority ducking / EBU** | `set_clip_properties {volume}` or volume keyframes (approximate) | **Baked** — no exact native equivalent | parity "baked" L217-225; `translate.py:176-180` warns export replaces Palmier mix |
| **Reframe — static** | `set_project_settings {aspectRatio:'9:16'}` (re-fits) · `apply_layout {layout,slots:[{slot,mediaRef|clipIds,anchorX,anchorY}]}` · crop via `set_keyframes {property:'crop'}` | Native (static) | catalog; note `native_plan:113-116` restricts `apply_layout` to `clipIds`-only today |
| **Reframe — bounded face/center/blur-pad** | — | **Baked**; bounded face selection with center-crop or blur-pad fallback, not continuous subject tracking | parity contract |
| **Export** | `export_project {mode:'video'|'fcpxml'|'xml'|'palmier',codec,resolution,outputPath,timelineId}` | Native (NOT a byte-copy) | `export.py:257` |
| **Verify / read-back** | `get_timeline {}` (`totalFrames`/`tracks`/`canGenerate`) · `inspect_timeline` (composited preview) · `get_transcript` | — | `executor` verifies via `get_timeline`; `canGenerate=false` ⇒ generate/upscale fail |

**Session invariants the agent MUST obey** (MCP server contract, `mcp_client.py`): call `get_timeline` **once** and patch its model from each mutation's returned delta (`clips/shifted/removedClipIds/createdTracks`) — do **not** re-read between its own edits (except `get_transcript` after every `remove_words`); TIMELINE positions are integer project frames at `round(fps)`, SOURCE positions are seconds (never `×fps`); IDs are short prefixes, pass back exactly; index 0 renders on top; `undo {}` reverts only the agent's own last edit.

---

## 5. Original file-by-file build checklist

The action labels below are preserved as the design history from 2026-07-13.
Several listed files and behaviors now exist. Current implementation status is
the authority update above and the build-order ledger in section 9; do not use a
`create` label here as evidence that the current file is absent.

### (a) MCP + spawn wiring

| Path | Action | Change | Effort |
|---|---|---|---|
| `src/app/api/producer/live-build/route.ts` | **create** | New SSE POST route (`export const maxDuration=1800; dynamic='force-dynamic'`). Model the ReadableStream/spawn skeleton on `claudeAiEditStream` (`ai-edit/route.ts:111-198`): keepalive 10s, `trackProcessTree`/`terminateProcessTree`, `cancel()→terminateProcessTree`, terminal `event:build_done` / `event:error`. Runs `guardProjectMutation` + `classifyPalmierWorkspace` before starting; runs Stage-1 governance, then Stage-2 live execution. Header `X-Sniper-Edit-Mode: live-build`. | large |
| `src/app/api/producer/live-build/args.ts` | **create** | `buildLiveBuildArgs(prompt, readDirs, mcpConfigJson)` returning the §3 arg vector. `mcpConfigJson = JSON.stringify({mcpServers:{'palmier-pro':{type:'http',url:PALMIER_MCP_URL}}})` (`PALMIER_MCP_URL` from `palmier/_lib.ts:20`). Wildcard `mcp__palmier-pro__*` in `--allowedTools`; fallback to enumerated list per spike. | small |
| `src/app/api/producer/live-build/prompt.ts` | **create** | `buildLiveBuildPrompt(input)`: doctrine-first, hands the agent **the APPROVED `edit_plan.json`** and instructs: (1) `get_projects`/`open_project`/`set_active_timeline` to bind to the operator's ONE visible timeline (**never `new_project`**); (2) `get_timeline` once, then apply each plan element incrementally via `mcp__palmier-pro__` tools, patching its model from each returned delta; (3) follow `doctrinePromptLines(scope)` (`ai-edit/doctrine.ts`) + `.claude/skills/producer/SKILL.md`. | medium |
| `src/app/api/producer/live-build/stream.ts` | **create** | Forward each stream-json line via the `forwardLine` pattern (`authoring.ts:74-83`), but specifically surface `tool_use` (name=`mcp__palmier-pro__*`, input) and `tool_result` so the UI shows each Palmier op; include `operationCount`/`elapsed`. | medium |

### (b) Agent prompt & governance

| Path | Action | Change | Effort |
|---|---|---|---|
| `.claude/skills/producer/SKILL.md` (+ mirror `.agents/skills/producer/SKILL.md`) | **modify** | Add a **"LIVE BUILD IN PALMIER"** doctrine section: the plan is **still authored + gated to convergence first** (steps 1-4 unchanged), then executed live element-by-element; the agent must read SKILL.md workflow 1-3 + FAILURE_LEDGER "## Brain lessons" **before any MCP call**; enumerate the plan-lane → native-tool map from §4 and which lanes are un-executable live (transitions error by design). Auto-pins because SKILL.md is in `PRODUCER_CORE_DOCTRINE_PATHS`. | small |
| `src/lib/server/auto-edit-doctrine.ts` | **modify** | If a standalone live-build `.md` is added, append it to `PRODUCER_CORE_DOCTRINE_PATHS` (`:17-23`) so `captureAutoEditDoctrine` (`:179`) sha-pins it; no other change. | trivial |
| `scripts/producer/palmier/checkpoint_plan.py` | **modify** | `prepare_checkpoint_plan` (`:101`) strips transitions/brollTrack/reframe/captions/music/audioEnhance/audioGain/chapters/ramp-punches/grade (`:106-119`). For full-fidelity live build these must be **passed through** (not stripped) so the live executor/agent can apply them natively per §4 (or map to `add_captions`/`apply_color`/`denoise_audio`/`detect_beats`) — several need real translator work. Keep the stripping path for the legacy checkpoint. | large |
| `src/app/api/producer/ai-edit/palmier-native-runner.ts` | **modify** | Add a **post-hoc read-back QC** path: after the agent finishes, read the resulting timeline via `get_timeline`/`get_transcript` and run the critic (`criticPrompt`/`reviewDraft`) + gates against the **observed** state rather than a proposed draft. Keep the existing plan-first native path for non-live mode. | large |

### (c) Live execution & streaming

| Path | Action | Change | Effort |
|---|---|---|---|
| `scripts/producer/palmier/live_build.py` (+ `live_build_cli.py`) | **create** | The **A1 deterministic engine**: given an APPROVED `edit_plan.json` + manifest, `fork_candidate` the working head, translate each plan element into **one** MCP call, apply via the `_apply_operation` CAS pattern (`native_delta.py:140`), emit NDJSON per element. **Does not** `create_shadow` a disposable timeline nor stamp `authoritative:False`; targets the operator's live fork and leaves it editable. Reuse `guard_sniper_baseline` + `record_candidate`; **never build on the parent**. | large |
| `scripts/producer/palmier/live_vocabulary.py` | **create** | Agent-facing doctrine + thin wrappers exposing `Executor`'s proven op→MCP mappings as standalone primitives (`place_cut`/`set_speed`/`set_transform`/`punch`/`place_overlay`/`place_text`/`place_music`), bodies lifted **verbatim** from `executor.py:69-235`; the only change is `target = live timeline id`, not a hidden shadow. | large |
| `scripts/producer/palmier/native_plan.py` | **modify** | Add build-from-scratch vocabulary to `ALLOWED_TOOLS` (`:14`) and `MAY_ADD` (`:22`): `add_clips, insert_clips, import_media, create_timeline, manage_tracks, move_clips, remove_clips, sync_clips, detect_beats, export_project` + the `mediaRef` form of `apply_layout`; add `_KEYS`/`_REQUIRED`/`_TOOL_LANES` entries; **raise/relax `MAX_OPERATIONS=24`** (`:10`) for a full build (or make the executor commit in batches). Keep `_validate_ids`/`_validate_frames`/`_validate_shape` — the reusable core. **Biggest single build item; the determinism-boundary decision lives here.** Consider forking a parallel validator so surgical-edit gates stay untouched. | large |
| `scripts/producer/palmier/native_delta.py` | **modify** | Generalize `execute_native_candidate`/`_apply_operation` (`:254`/`:140`) so the loop can (a) run against a live build target the operator watches (not a staged candidate revealed only on promote), (b) emit a per-op NDJSON event (`mcp_client.emit`) after each `client.call_json`, (c) tolerate legitimate ADD ops (`add_clips`) that today trip the `MAY_ADD` guard (`:154`). Keep fork/quarantine/restore-parent semantics. | large |
| `scripts/producer/palmier/sync.py` | **verify/document** | The mirror-only guard at `:238` (`if not lanes.get("mirror") or lanes.get("cuts"): raise`) is why incremental cut placement is forbidden in the shipped push. **Live-build must NOT route through `run_sync`** (it builds hidden + swaps). Document this boundary so no one accidentally reuses it. | small |
| `scripts/producer/palmier/translate.py` | **verify** | `translate()` with `master_path` returns **only** `_mirror_steps` (`:235-238`); the native emitter (`_project_steps`/`_motion_steps`/`_media_and_overlay_steps`/`_tail_steps` `:143-193`) is reachable only when `master_path is None` — a code path no shipped caller uses. Confirm whether live-build authors placements via the agent (bypassing `translate`) or reuses this dormant branch; they diverge on **who owns the frame math**. | small |
| `scripts/producer/palmier/live_transition.py` (or doctrine note) | **create** | Resolve the transitions gap per §4: a real mapping (opacity-crossfade on stacked tracks / matte fade / whip via `apply_effect blur.motion`) or explicit scope-out with an honest `warn` — **do not silently drop**. | medium |
| `src/lib/producer/palmier-op-event.ts` | **create** | Pure normalizer: `{type:assistant,…tool_use,name:mcp__palmier-pro__X,input}` → `{event:'palmier_op',id,tool:X,lane,target,summary}` (e.g. `add_texts`→"Title card at 0:45", `ripple_delete_ranges`→"Cut 0:18-0:26", `set_keyframes`→"Zoom keyframes on c3"); matching `tool_result` marks applied/failed. Model the copy table on `palmier-bar.tsx:79-100`. Unit-tested pure reducer like `warnings.ts collectWarnings`. | medium |

### (d) GUI live-build view

| Path | Action | Change | Effort |
|---|---|---|---|
| `src/components/producer/editor/live-build-panel.tsx` | **create** | Client panel driving `/api/producer/live-build` via `readEventStream` (`sse.ts:25`), rendering an ordered `AppliedOp[]` list (reuse the `LogLine[]` accumulation from `render-step.tsx:32-99`). Each row: lane/tool icon, human summary (from `palmier-op-event.ts`), status pill (pending/applied/failed), timestamp, click-to-seek. Auto-pin to newest (`StreamLog` `endRef.scrollIntoView`, `stream-log.tsx:18-20`). Persistent header "Watching Palmier build — N elements applied". Route warning/fidelity events into `WarningsStrip` via `addWarningEvent` (`use-plan-actions.ts:136`). `build_done` → done state. | large |
| `src/components/producer/editor/editor-view-sections.tsx` | **modify** | Add `<LiveBuildSection>` between `PalmierSection` (`:257`) and `EditorWorkspace` (`:261`) in `EditorSurface` (`:253-267`); add a **"Build live in Palmier"** launch affordance that first calls `openPalmierWorkbench(dir,mode)` (`use-editor-runtime.ts:49`) then opens the live-build stream. Gate with the same `editingLocked`/`externalLockReason`/`aiBusy` guards threaded through `AskEditor` (`:195-215`) and `PalmierSection` (`:76-103`). | medium |
| `src/lib/producer/project-state.ts` | **modify** | Extend `streamProgressMessage` (`:279`) to map the currently-invisible `palmier_op` and `palmier_checkpoint_*` events (started/detail/ready/skipped) to readable copy so they also surface in the stage-actions `RunProgress`/`LocalRun` status line. | small |
| `src/components/producer/editor/open-palmier-button.tsx` | **modify** | Extend the existing affordance into a "Watch build" launcher (view→workspace fallback already present). | small |

### (e) Ownership / lifecycle / rollback

| Path | Action | Change | Effort |
|---|---|---|---|
| `src/app/api/producer/auto-edit/palmier-checkpoints.ts` | **modify** | `managedWorkspace` (`:51`) requires `workspaceMode=='managed-draft'` and `ownership!='palmier'` and **skips all touches otherwise**. Add a live-build workspace mode (or concurrency model) so automated element placement and human edits can share one authoritative timeline instead of pausing on human ownership. | medium |
| `scripts/producer/palmier/live_build.py` (rollback path) | **modify** (part of the create above) | Carry the `native_delta` rollback contract: on any op failure or SIGTERM, quarantine the partial candidate (`record_candidate` + `status quarantined`) and `set_active_timeline` back to parent asserting `compare_authority=='unchanged'` (`_restore_parent`/`_quarantine` pattern, `native_delta.py:176/207`). Handle the poisoning hazards: human-switched-away → **preserve** their timeline (do NOT stomp, `native_delta.py:183`); incomplete recovery → wedge with recover/discard affordance (`:235`); **prefer incremental commit** — each op-batch becomes a working-checkpoint via `checkpoint.publish_checkpoint` so a mid-build death keeps landed progress instead of an all-or-nothing 24-op rollback. | medium |
| `scripts/producer/palmier/ownership.py` + `mirror.py` | **verify/reuse** | Reuse `persist_handoff_to_palmier`/`persist_reclaim_for_sniper`/`persist_ai_edit_invalidation` (`mirror.py:163-175`) and the `--handoff/--reclaim/--invalidate` CLI for accept/abandon. Confirm live-build hands off **only on explicit operator accept** and that reclaim forces a **fresh fork** (the known one-way-trap the edge-case register flags). | trivial |
| `pipeline.ts` (call-site guard) | **verify** | The live-build path must **not** fire the flat render checkpoint (`:262`) or flat `approvedMirror` (`:255`/`:265`). Branch before these. | trivial |

### (f) Tests

| Path | Action | Change | Effort |
|---|---|---|---|
| `scripts/producer/tests/test_live_build.py` | **create** | stdlib `unittest` (no pytest, run under `selftest.py`): plan→per-element op sequence, CAS verify, quarantine/restore, incremental checkpoint commit, human-switched-away preservation, SIGTERM path. | medium |
| `scripts/producer/tests/test_native_plan_build_vocab.py` | **create** | Assert `add_clips`/`import_media` now pass `validate_native_plan`; surgical-only gate still rejects them if the fork-validator route is chosen; `MAX_OPERATIONS` relaxation. | small |
| `src/lib/producer/__tests__/palmier-op-event.test.ts` | **create** | Pure normalizer: each `tool_use`→summary/lane/target; `tool_result` applied/failed folding. Run under `npm test`. | small |
| `src/lib/producer/__tests__/live-build-stream.test.ts` | **create** | `streamProgressMessage` maps `palmier_op`/`palmier_checkpoint_*`; `readEventStream` terminal-guarantee with `requiredEvent:'build_done'`. | small |

---

## 6. Governance: keeping every edit doctrine-governed

The operator's hard rule — *every edit must be doctrine-governed; understand good editing BEFORE acting* — is satisfied by **gating the plan before Palmier is touched**, then executing the gated plan live.

**Doctrine pinning (unchanged).** `captureAutoEditDoctrine(ctx,runId)` (`auto-edit-doctrine.ts:179`) sha256-copies `PRODUCER_CORE_DOCTRINE_PATHS` (`:17-23` = both `SKILL.md`s, `docs/PIPELINE.md`, `FAILURE_LEDGER.md`, `QC_CHECKLIST.md`) + `PRODUCER_REFERENCED_DOCTRINE_PATHS` (`:25-36`) + the chosen style doc into the run's `doctrine/files/`; `restoreAutoEditDoctrine` (`:232`) re-verifies the sha lock before any writer/critic runs. Add the new live-build doctrine `.md` to `PRODUCER_CORE_DOCTRINE_PATHS` so it auto-pins. The live-build agent reads doctrine via `doctrinePromptRoot`/`doctrinePromptPath` (`:256/:260`) — **from the pinned snapshot, never the mutable repo** — including the mandatory `FAILURE_LEDGER "## Brain lessons"` read (`authoring-prompt.ts:255`).

**Gates run on the PLAN (before any MCP call).** `runPlanningGateBundle` (`planning-gates.ts:242`) spawns, in stable order (`:92-107`): `operator_intent_contract.py --expected-json` (lane-coverage vs stamped intent), `plan_lint.py`, `hook_contract.py` (front-load wall — HARD gate), `claims_contract.py` (numeric grounding from transcript), optional `reference_profile_lint.py`; each emits `{ok,errors,warnings}`, combined by `combinePlanningGateVerdicts` (`:219`). These **only parse `edit_plan.json`** in the OUTPUT/SOURCE-seconds domain — which is precisely why the plan must be gated *before* it becomes a frame-domain Palmier timeline.

Gate CLIs (verbatim signatures):
- `plan_lint.py <edit_plan.json> <asset_manifest.json> [transcripts_dir]` (`:369`)
- `hook_contract.py <plan> <transcripts_dir> <manifest>` (`:243-257`)
- `claims_contract.py <plan> <transcripts_dir> <manifest>` (`:319-331`)
- `operator_intent_contract.py <plan> --expected-json '<json>'` (`:192-204`)
- `reference_profile_lint.py <plan> <profilePath> --reference-id <id> --mode <mode> --strategy <strategy>` (`planning-gates.ts:64-78`)

**Independent critic (before Palmier is touched).** After gates are green, `runProducerReview({stage:'plan',…})` (`brain-review-runner.ts:185`) spawns a **fresh read-only** agent (`tools='none'`, `:154`) with a hash-bound packet + pinned doctrine via `buildPlanReviewPrompt` (`plan-review-prompt.ts:57`). The full convergence loop is `runPlanningReviewLoop` (`planning-loop.ts:223`): author → gate → critic → `runProducerRevision` on material issues → re-gate; **min 2 clean rounds** for produced/full (`round-policy.ts:13`), cap `MAX_PLANNING_REVIEW_ROUNDS=4` (`:3`). **Reuse this loop unchanged** as the Stage-1 wall.

**Readback QC (after live execution — drift catch).** Because the agent executes rather than re-decides, the residual risk is *drift from the approved plan*. Stage 3 reads the timeline (`get_timeline`/`get_transcript`) and runs the native content/vocabulary gates + critic against the **observed** state: `validate_native_gate` (`native_gate.py:259`), `validate_native_content` (`native_content_gate.py:49`, rejects new numeric/URL claims not grounded in the request/visible text), `validate_native_plan` (`native_plan.py:238`). For deeper editorial re-checks, add either timeline-schema versions of hook/claims/pacing **or** a Palmier-timeline→edit_plan back-translator so the existing gate CLIs re-run on readback (needed only if Option B is ever chosen — under recommended Option A, readback QC is a drift check, not the primary gate).

---

## 7. Ownership, concurrency, rollback

**JS writer lease.** The route acquires `guardProjectMutation({projectRoot: mutationProjectRoot(dir), producerDir, operation:'building live in Palmier'})` (`project-mutation.ts:36`, root via `:19`), which wraps `acquireProjectMutationLease` (`project-mutation-lease.ts:79`) — a mkdir-based `.sniper-project-mutation.lock` keyed by pid+nonce (single fail-fast writer) — and **also 409s if a detached `producerRun` is `running`** (`:52`). Hold it for the whole build, release once (mirror `ai-edit/route.ts:206`/`:214`).

**Python Palmier transaction lock.** Independently, acquire `SyncLock.acquire(out_dir, key, queue_if_busy=False)` (`checkpoint_cli.py:37`, `native_delta_cli.py:126`) to serialize Palmier MCP transactions across mirror/checkpoint/native/live-build.

**Palmier ownership state.** Lives in `palmier.sync.json` (schemaVersion 4): `ownership ∈ {sniper,palmier}` (`mirror.py:15`), `workspaceMode ∈ {managed-draft,verified-mirror}`. Every Sniper→Palmier write requires `ownership==sniper && workspaceMode=='managed-draft'` (`managedWorkspace` `palmier-checkpoints.ts:51-69`; `checkpoint.py _workspace_state:81`; `guard_sniper_baseline` `timeline_guard.py:101`). **Live build stays `sniper`/`managed-draft` for the whole build**, builds on a **fork** (`fork_candidate` `timeline_authority.py:257`, `create_timeline {name,from:parentTimelineId}`), and **hands off to `palmier` only on explicit operator accept** via `ownership.py --handoff` (`persist_handoff_to_palmier` `mirror.py:163`). Reclaim (`--reclaim`) forces a **fresh fork** (avoids the known one-way trap).

**Coexistence with the mirror path.** The live build **does not touch** `run_sync`/`push.py` (mirror-only by construction, `sync.py:238`) and **does not fire** the flat render checkpoint (`pipeline.ts:262`) or flat `approvedMirror` (`:255`/`:265`). The two paths share the lease + `SyncLock` + ownership sidecar, so only one writer runs at a time.

**Partial-failure rollback (carry the `native_delta` contract, avoid its poisoning hazards).** The proven engine is `execute_native_candidate` (`native_delta.py:254`) applying ops one at a time via `_apply_operation` (`:140`) with per-op CAS (fingerprint changed, structural delta within `MAY_ADD`/`MAY_REMOVE`). On failure/SIGTERM: `_quarantine` (`:207`) records the candidate `status:'quarantined'` + partial receipts, then `_restore_parent` (`:176`) `set_active_timeline` back to parent asserting `compare_authority=='unchanged'`. **The four hazards to handle explicitly:**
1. `_restore_parent` (`:183`) refuses to switch back if a human moved Palmier to a **third** timeline mid-build — **preserve** the human's timeline, don't stomp it.
2. If restore/quarantine-write fails it raises "candidate recovery was incomplete" (`:235`), leaving a quarantined candidate that **blocks the next AI edit** (`timeline_guard._candidate_change:32-34` → `TimelineConflict`). Surface `native_delta_cli.py --recover-parent`/`--discard-candidate` (`:47-49`) as GUI affordances.
3. SIGTERM → `_cancel` (`native_delta_cli.py:142`) routes into the same quarantine+restore path — the live route's `cancel()`/timeout must send SIGTERM, not SIGKILL, so recovery runs.
4. `MAX_OPERATIONS=24` (`native_plan.py:10`) makes an all-or-nothing fork **not scale** to a full build — a mid-build death rolls back everything. **Fix: incremental commit** — each op-batch becomes a new working-checkpoint via `checkpoint.publish_checkpoint`, so a mid-build death keeps landed progress. This is the single most important change to make the live build survivable.

Keep `shadow.py` identity guards (`assert_project`/`assert_build`/`assert_human` `:156-179`) — the `Executor` already calls them before every mutation, so a human project/timeline switch aborts the run cleanly.

---

## 8. Coexistence & migration

**Recommendation after qualification: two modes side-by-side, not a
replacement.** Today only the render-in-house-then-mirror path is the dependable
delivery. The live build stays isolated until the P5 connected cohort passes:

- **"Autonomous finished video"** (existing) — one click, the pipeline authors + gates + renders in-house with `assemble.py`/ffmpeg and publishes a flat visual-master mirror to Palmier. Best when the operator wants a hands-off deliverable. **Do not remove it** — it is the working render path (per CLAUDE.md: "do not simplify the in-house renderer away while it is still the working path").
- **"Build live I watch/steer"** (experimental) — the same gated plan, executed
  element-by-element into a visible Palmier candidate. It may be exercised in
  an isolated target, but must not be marketed as a released editable/hybrid
  handoff before connected short/long qualification.

Both consume the **same gated `edit_plan.json`** — the determinism boundary is
shared; only the delivery differs (flat mirror vs. native incremental build).
Shared governance does not make their evidence equivalent: exact-master mirror
publication is qualified, while the native incremental path is P5-blocked.

**UI presentation.** The local UI/build includes a delivery choice after
Auto-edit authors the plan: **"Render finished video"** (default, safe) vs
**"Build live in Palmier"** (experimental). The live-build choice: (1) calls
`openPalmierWorkbench(dir,mode)` to bring Palmier to front, (2) opens
`<LiveBuildSection>` with the streaming applied-ops list, and (3) on
`build_done` offers **Accept** (`ownership.py --handoff`) or **Abandon**
(`discard_candidate`). Presence in a successful local production build does
not mean the connected workflow is release-qualified.

**Migration:** none of the existing checkpoint/mirror code is deleted. The live-build path is additive; the `pipeline.ts` call-sites (`:249`/`:262`/`:255`/`:265`) are branched, not replaced.

---

## 9. Build order

Each phase is independently demoable.

- **Phase 0 — COMPLETE.** The disposable smoke proved skill invocation, strict HTTP MCP, enumerated auto-approval, streaming, editable text, retained-session keyframes, exact readback, restoration, and cleanup. Direct `add_clips` remains part of the Phase-3 full-plan proof.

- **Phase 1 — IMPLEMENTED / OFFLINE VERIFIED.** `live-build/args.ts`, `process.ts`, and `route.ts` use strict enumerated MCP, the subscription-safe environment, process-tree cleanup, retained session IDs, and normalized SSE operation events. The route is present in a successful production build; it has not been invoked against the user's active project.

- **Phase 2 — IMPLEMENTED / OFFLINE VERIFIED.** The controller validates the approved plan and active authority, forks the exact parent, retains the visible editable candidate, and preserves it on stop. Every operation lifecycle is written to strict fsynced JSONL with a stable ID and canonical payload hash; controller heads bind verified applied IDs to fresh readback. Resume performs a read-only observation first and fails closed to `reconciliation_required` on torn history, foreign identity, ambiguous effect, no-delta apply, unsafe replay, or manual drift. The live writer is the proven A2 Claude session; the controller owns candidate lifecycle and checkpoint authority, not editorial mutation.

- **Phase 3 — NEXT LIVE MILESTONE.** Exercise the enumerated imports/cuts/graphics/motion/captions/color/audio tools on the complete approved first-60-seconds plan. Unsupported transition semantics must fail explicitly. **Demo:** every planned lane lands visibly in the retained candidate and survives exact readback.

- **Phase 4 — IMPLEMENTED / OFFLINE VERIFIED.** Launch requires current deterministic gates and planning-review evidence. Plan, doctrine, pipeline, journal, parent, session, readback, and exact candidate export share one immutable QC authority. Deterministic audit precedes parallel composition/editorial critics. Failure preserves the candidate and creates a retained-session scoped-repair turn.

- **Phase 5 — IMPLEMENTED / BUILD VERIFIED LOCALLY.** The Producer Palmier bar
  exposes build/resume/stop, live operation/result rows, first-mutation latency,
  exact-candidate QC progress, and explicit promotion through the existing
  candidate control. Here `BUILD VERIFIED` means the local UI compiles and its
  build contracts pass; it does not mean a connected editable short or long was
  delivered.

- **Phase 6 — PARTIAL.** Candidate fork/resume, unchanged-parent checks, stop preservation, QC archival, explicit promotion, A2 execution, strict local journal reconciliation, and immutable Desktop pre-mutation snapshots are implemented. A connected kill/resume exercise, disconnects at every mutation boundary, external adoption/fork resolution, and real human co-edit/manual-advance preservation remain unproved.

---

## 10. Open questions / risks

1. **Full-plan A2 coverage (highest remaining risk).** Headless strict HTTP-MCP, enumerated auto-approval, streaming, text, retained sessions, and keyframes are proved. Direct imports, cut construction, graphics, audio, and full-plan scale are not. The first-60-seconds disposable/isolated run must measure first-mutation latency, batch behavior, exact readback, export, critics, scoped repair, and resume without touching the user's active external build.

2. **Determinism loss with a direct-drive agent.** A2 produces no pre-validatable artifact between decision and mutation. Mitigated by Option A (gate the plan first; the agent only *executes*) + Stage-3 readback QC, but the agent can still deviate from the plan mid-execution. Risk: the readback QC must be strong enough to catch drift, and there is no per-op pre-gate as there is for the Python `_apply_operation` CAS. A1 has no such gap.

3. **Transitions & branded graphics native-expressibility.** **No `add_transition` primitive exists**, so automatic transitions fail closed until a verified native/keyframe merge exists. HyperFrames graphics remain baked alpha-ProRes clips. Smooth ramp/aliveness motion is native keyframe data; bracket/static hold motion remains unsupported. Never claim exact native expression without readback proof.

4. **Concurrent Codex / native-edit paths.** The concurrent Codex Palmier-canonical WIP guards on **sidecar existence, not ownership** (edge-case register). The live build's new `managed-draft`-during-build + fork model must not collide with that path; the shared lease + `SyncLock` + `managedWorkspace` gate are the coordination points, but the ownership state machine now has more transitions (build→fork→handoff→reclaim-fresh-fork) and needs explicit reconciliation with `reconcile_working_authority` (`timeline_guard.py:72`).

5. **Batch scale and mid-build death.** The A2 path is not limited by the old 24-operation native-plan cap, but a full build still needs bounded same-tool batches and durable verified checkpoints. The local strict journal rejects blind replay and the Desktop path retains an immutable before-snapshot, but a connected kill/resume run must still prove that every landed operation is reconciled exactly once.

6. **Co-edit while the agent builds.** The operator "watching" can become the operator "touching." Today any human touch flips ownership to `palmier` and pauses automation (`palmier-checkpoints.ts:59-64`). True simultaneous co-edit (agent and human writing the same timeline) is a **larger concurrency model** than this spec fully resolves — the recommended v1 is "operator watches, then accepts/steers after `build_done`," with mid-build human touches treated as an abort (preserve their timeline, do not stomp).

---

**Bottom line for the next live test:** the A2 spawn/session, strict tool surface,
candidate lifecycle, operation streaming, fsynced lifecycle journal,
fail-closed resume, immutable Desktop before-snapshots, exact-export QC, full-
stream parity contract, local Exact Master and scene-replacement contracts,
parallel critics, and retained-session repair loop are implemented or
offline-verified prerequisites. Do not claim a Produced-video or hybrid-delivery
success yet. The next proof is a complete isolated governed build, followed by
representative connected short and long projects, including direct
imports/cuts/graphics/audio, complete paged readback, exact export, a
production-reachable one-audible-route receipt, Exact Master at every released
rate, one-scene preservation, at least one intentional QC rejection and scoped
repair, disconnect/kill-resume at every mutation boundary, manual-edit
preservation, and explicit promotion only after the exact candidate passes.
