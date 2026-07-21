# Headless execution adversarial audit — 2026-07-18, round 6

> **STATUS: FROZEN AUDIT SNAPSHOT.** This records the sixth adversarial wave and its cross-examination. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md), not by rewriting this record.

## Scope and method

Reviewed only the Claude Code/Codex planning and repair path into deterministic MP4, approved-plan rendering to MP4, and the protocol boundary that would later permit Palmier. GUI work remained excluded.

Three independent attacks tried to disprove the round-five plan:

1. A renderer attack on the proposed `R0` color-only reuse class, its cache/runtime closure, request-fulfillment oracle, and Audit B.
2. A review-latency attack on critic topology, prompt size, model/effort comparisons, child-process recovery, and defect aggregation.
3. An experiment-operations attack on corpus independence, cache/work isolation, forced-full controls, disk, network/MCP containment, and statistics.

The primary agent then traced the proposed path through the current `ai-edit`, planning, render, quality, and authority code and challenged every proposed optimization with a cheaper falsification test. No production code changed. This round changed documentation only.

Read-only diagnostics found:

- the 22 baseline planning-doctrine files total **464,568 raw bytes** before the plan/manifest/transcript packet or an optional style file;
- the retained repository has seven `edit_plan.json` files, only one short-form plan, and **zero** retained `text-element` plan rows;
- four major retained artifact directories point to the same `C0679` source and are one source/project cluster, not four independent samples;
- the default shared graphics cache is **8.4 GiB**, the repository is roughly **18 GiB**, and the filesystem has roughly **49 GiB free at 98% use**;
- all 46 motion-composition HTML files reference remote GSAP, so a deterministic offline render is not presently runtime-closed;
- the repository registers a Palmier MCP endpoint in `.mcp.json`, and a listener was present at `127.0.0.1:19789` during the audit.

## Round-six verdict

The bounded deterministic-MP4 direction survives, but the experiment order and repair boundary change again.

**The first fast-path primitive should be a controller-applied typed repair, not a whole-plan LLM writer.** A mechanical request such as replacing one known graphic color token can be represented as a compare-and-swap over one stable element and one expected old value. Letting a model rewrite the complete plan adds latency and a much larger mutation surface without adding editorial judgment.

**The largest newly exposed review lever is context construction, not model downgrade.** Each planning critic receives about 116k raw-token-equivalents of doctrine before dynamic job evidence. A two-wide batch repeats about 232k doctrine-token-equivalents per cycle. The plan must first measure actual provider token/cache behavior, then test an exact-content stable prefix, then shadow a controller-compiled stage-specific doctrine packet. Provider/model/effort experiments are uninterpretable until session, schema, tool, evidence, and context policies are separated.

**`R0` is demoted from a product-representative study to a synthetic renderer falsifier.** The current headless planner does not emit `text-element`, no retained plan uses it, ordinary color language may not route to the graphics lane, and the request contains neither a target ID nor an exact pointer. One five-to-ten-second fixture should try to kill the mechanism before any six-project spend. Product value must later be tested on repair classes observed in real headless feedback.

**Failure handling is itself a latency optimization.** A rendered critic infrastructure failure can leave its sibling alive until the 25-minute cap, a system/Audit failure can be sent to a 20-minute plan writer, and same-code defects at different timestamps can be merged into one incomplete repair. These paths create the reported “same amount again” behavior without any renderer bottleneck.

Live Palmier mutation remains temporary no-go. The deterministic MP4 experiment must not merely avoid calling Palmier intentionally; it must start with an empty MCP configuration, explicit deterministic-MP4 realization, a Palmier tripwire, and no ambient checkpoint/mirror path.

## Findings that overturn or narrow round five

### `R0` should not pay for a whole-plan writer

The current surgical request contains `dir`, natural-language `request`, a top-level lane scope, plan/canvas/manifest paths, and provider. It contains no target graphic ID, expected plan hash, expected old value, or JSON pointer in [`prepare.ts`](../../src/app/api/producer/ai-edit/prepare.ts). The prompt limits only top-level fields in [`prompt.ts`](../../src/app/api/producer/ai-edit/prompt.ts), and [`assertSurgicalPlanChange`](../../src/lib/producer/surgical-edit.ts) permits the entire `graphicsTrack` whenever the graphics lane is selected.

The deterministic router also does not recognize generic `color`, `palette`, `lemon`, or hex language. “Make it lemon” can fail before the model runs, while “change the graphic text color” grants the model access to the whole graphics array.

The replacement contract should be controller-owned:

```json
{
  "schemaVersion": 1,
  "effectClass": "R0_TEXT_COLOR",
  "realizationKind": "deterministic-mp4",
  "expectedPlanHash": "sha256:...",
  "target": { "lane": "graphicsTrack", "id": "g-..." },
  "op": "replace",
  "relativePointer": "/spec/color",
  "expectedOld": "#FFFFFF",
  "value": "#054BC9",
  "requestId": "..."
}
```

The controller resolves the ID uniquely, verifies the expected parent and old value, applies the operation to a private normalized copy, runs the exact effect allowlist and gates, and emits the canonical diff. A model may compile ambiguous prose into this read-only proposal, but it never writes the plan. Explicit ID/token requests need no second writer spawn.

Missing, duplicate, reminted, or nonconforming IDs make `R0` ineligible. Array indexes never authorize the mutation. Case-only color changes normalize to no-op and must not render.

### Current AI edit invalidates a good generation before a candidate exists

[`surgicalAuthorityFailure`](../../src/app/api/producer/ai-edit/prepare.ts) calls `invalidateAiEditAuthority` before candidate staging or model configuration. [`invalidateApprovedPreview`](../../src/lib/server/auto-edit-quality-artifacts.ts) writes the durable stale marker and deletes the approval. Rollback restores plan text but does not restore the prior approval or remove the stale marker.

Therefore ENOSPC during staging, provider configuration failure, timeout, invalid JSON, no-op, critic rejection, cancellation, or a Palmier invalidation race can destroy the current approved authority even when canonical plan bytes never changed. `preparePlanForAi` also snapshots and reconciles IDs before the writer, and rollback rewrites the unchanged root plan.

The correct generation behavior is:

- keep the previous approved generation immutable and addressable as the prior generation;
- mark only a private candidate as pending;
- never present the prior output as the requested new edit;
- on rejection/no-op/crash, discard the candidate and leave prior approval intact;
- invalidate/advance current authority only in the accepted candidate's atomic commit;
- if Palmier remote state was touched or is ambiguous, quarantine that delivery separately rather than restoring unproved remote authority.

An already-satisfied typed request returns an idempotent no-op receipt. It does not invoke a writer, clear approval, or rerender.

### The proposed “isolated clone” still shares live runtime and cache state

The TypeScript assemble command does not expose `--cache-dir`; `assemble.py` therefore defaults to `templates/motion/renders/cache`. `graphics_render.py` also writes `_gs-<key>.html` into the shared composition tree, executes `npx --yes hyperframes@0.7.33`, and writes cache misses directly to their final shared key path before proof.

The package name pins only the requested top-level version. `npx --yes` may fetch/install into ambient npm cache, and the installed npx tree has its own transitive lock resolution. HyperFrames telemetry/config is ambient. `text-element.html` fetches GSAP from jsDelivr, while the graphics key does not bind that response, the actual package bytes, Node/browser/font rasterizer, or OS runtime.

Project-directory copies therefore do not isolate either arm. The experiment needs:

- one immutable SHA-256 CAS for source media, manifests, plans, doctrine, templates, installed dependencies, browser, model weights, and toolchain, with absolute manifest paths rebased into it;
- fail-closed copy-on-write clones for mutable attempt state, verified for distinct writable inodes/link count one; never hardlink writable files because `assemble.py` truncates `base_plan.json` in place;
- an immutable, hash-bound toolchain with exact lock/integrity data and an absolute local HyperFrames executable;
- vendored/content-addressed GSAP and every loaded local/remote runtime dependency;
- pinned local browser and model-weight bytes; exclude any preset whose first run would download undeclared weights;
- renderer/QC network denial and telemetry disabled;
- attempt-local pipeline/runtime, cache, work, output, temp-composition, and trace roots;
- identical cloned starting-cache snapshots for paired arms;
- atomic cache publication plus per-key exclusion before concurrency is tested.

Model phases require provider egress, but they use strict empty MCP configuration, no inherited project/user MCP, enumerated tools, and a loopback Palmier tripwire. Deterministic render/QC children run network-denied.

### The retained corpus is not ready for the claimed pilot

The four C0679 Palmier/facebridge artifact trees share the same source and are technical repeats within one source/editorial cluster. Variants, arms, model samples, and retries do not increase the independent project count.

The present repository supplies one retained short plan and no `R0` row. A synthetic row can falsify renderer mechanics, but cannot estimate field eligibility, latency economics, or editorial noninferiority. Before an integrated pilot, collect at least six distinct source/editorial-project/feedback clusters and record the real frequency of feedback by typed repair class.

Absolute mutable media paths inside retained manifests must be rebased to an immutable input CAS. A directory clone that still reads the original absolute source is not frozen.

### Forced full rebuild needs an explicit control

Deleting only `base.fingerprint.json` is not a forced rebuild. With a base present and no fingerprint, `assemble.py` classifies it as `unverifiable` and reuses it. Manufacturing a stale fingerprint can invoke plan refit and replace plan bytes, invalidating the identical-plan control.

The control arm must directly run `render.py --skip-graphics` into a fresh attempt-local base directory using the exact revised plan, then use the same assemble path and z-order as treatment. It asserts that base/fingerprint files were created after the attempt began and that a complete base-build receipt exists. The treatment asserts `base_current`, the exact approved-parent base hash, and zero refit. Any other event path invalidates the trial.

The oracle is fresh graphics-free base plus assemble, not a monolithic full render: the latter composites graphics and captions in a different order and would confound the mechanism.

### `R0` has no request-fulfillment oracle

Audit B's graphic color extraction recognizes `accent` and `accentColor`, not `text-element.spec.color`. Asset proof validates shape, alpha, duration, and hashes, not rendered copy or intended color. Two revised arms can therefore match perfectly while both render the wrong color.

`brand_lint.py` rejects off-token colors, but it is not part of the current planning gate wall or embedded render lint. The normal template contract accepts any syntactically valid `#RRGGBB`. Brand membership also does not prove contrast over moving footage or noncollision with captions.

The minimal oracle is three-way:

1. old approved output;
2. revised reused-base output;
3. revised fresh-base-plus-assemble output.

Both revised outputs must match under the calibrated equivalence policy. Exact old→revised change locality is proved at the lossless overlay/pre-encode composition boundary. A legitimate overlay change can alter H.264 bit allocation outside the box or across a GOP, so the final decoded boundary permits only preregistered, full/full-calibrated immaterial codec spill—not strict global pixel identity—and rejects any material off-target effect. The pre-encode overlay/template must contain the exact normalized requested token/raster value. Decoded H.264/YUV pixels use a calibrated color-distance tolerance rather than impossible byte-exact RGB; they must preserve alpha/timing/bbox/placement, meet actual moving-background contrast, and avoid caption/title regions.

### Audit B is not a fail-on-error complete decode

Audit B counts video packets without decoding them. Several FFmpeg-driven glitch/motion/loudness probes discard or do not fail on nonzero return codes. A truncated or corrupt candidate can yield partial probe output that looks like a clean result.

Every experiment and production approval needs an explicit fail-on-error full video and audio decode, expected decoded frame/sample counts, and a receipt. Probe, glitch, and visual checks remain useful, but they do not substitute for this gate.

`cover.png` is also copied from the root and checked only for existence, dimensions, and luma. Extract it from the exact final candidate, bind its hash to the final hash and selected timestamp, and compare decoded cover pixels to that candidate frame.

### Review context is a first-order latency variable

The baseline doctrine snapshot includes 22 files totaling 464,568 bytes. `buildPlanReviewPrompt` embeds all of them per critic, before accounting for JSON escaping, the full plan, manifest, complete timestamped speech packet, reference material, and optional style doctrine. Cut critics separately repeat about 101,044 bytes of skill/ledger context.

Dynamic round, packet, hash, and run-specific `sourcePath` data precede the doctrine in the current prompts, defeating a simple exact stable prefix. The first review experiment keeps every semantic byte and moves canonical static trusted context ahead of dynamic untrusted job data. Measure provider-reported cache creation/read tokens, noncached input tokens, queue time, TTFB, and wall time. A one-byte doctrine mutation must invalidate the cache as expected.

Only after that may a `CriticDoctrineV1` compact the packet. It is controller-compiled from verbatim source spans with stable rule IDs, applicability tags, byte hashes, compiler version, parent doctrine hash, and an included/excluded coverage receipt. Unknown or cross-lane rules fail closed into the full packet. Mutation testing removes each known critical rule; seeded/natural/clean shadow comparisons must show zero unique critical misses.

### Model/effort Study C currently compares several variables

Current Claude and Codex runs differ in provider, model, effort, session reuse, structured schema, tool surface, and evidence access:

- Claude critic/revision work uses Opus/xhigh; Codex critic/revision work uses medium reasoning.
- Claude revisions resume the authoring session; Codex revisions are ephemeral.
- Codex reviews receive an output schema; Claude reviews currently rely on prompt plus parser.
- Rendered critics receive different tool behavior.
- plan/cut critics are packet-like, while writers and rendered critics read/mutate tool-visible files.
- the current writer prompt embeds a random candidate path and provider identity, so even two nominally equal model arms receive different prompt bytes.

Split the study:

- `C1`: exact-byte, sessionless plan/cut critic replay;
- `C2`: immutable hashed media/evidence bundles with identical access contracts for rendered critics;
- `C3`: isolated cloned filesystems for writers, first cold/sessionless and then production session policy as a separate factor.

Vary effort within one provider/model first, then model within provider, then compare providers only after schema/tool/session parity. A seeded packet mutation must recompute all authority roots.

Writer comparisons use a fixed logical path such as `edit_plan.json` and provider-neutral exact prompt bytes. Claude/Codex labels, random temp paths, or different tool/session policies are not allowed to stand in for a model factor.

### Review batch failure can strand expensive siblings

Rendered lenses use `Promise.all`. A `revise` or `block` verdict resolves normally, but an infrastructure/timeout/invalid-JSON/authority failure rejects immediately while the sibling keeps running. Worker catch marks the job failed; only signal handling terminates tracked process trees. Resume refuses while the old worker group remains alive, so the sibling can hold the path until the 25-minute cap.

Required invariant:

> A review batch cannot reject outward, mark failed, or unlock retry until every launched child is terminal and reaped.

On infrastructure/authority/contract failure, abort unfinished siblings, TERM, bounded grace, KILL, await all settlement, prove group death, then fail. Never abort because one critic returns a material editorial verdict; aggregate every resolved `revise`/`block` result.

Planning/cut batches use `allSettled` but discard successful work after one transient sibling failure. Same-input critic receipts can avoid repayment on retry, provided plan/evidence/model/effort/tool/schema roots all match. This remains tail-reliability work, not a normal happy-path wall-time claim.

### Defect identity and failure routing can manufacture extra cycles

Planning reviews merge issues solely by the model-provided `code`. Two defects with the same label at different seams can collapse to the first message/action, causing the writer to repair one and pay another full cycle for the other. Use controller identity such as `{rule, lane, timeWindow, evidenceRoot}`; model codes are labels, not keys.

The merged planning brief caps material issues at 50 and can reduce a larger set to a count-only deferred tail. Quality aggregation can exceed the 50-code revision receipt limit. Nothing may silently disappear: deterministically page atomic issues or fail before paying the writer when the complete repair brief cannot be represented.

Audit failures are also routed too broadly. A missing sidecar, corrupt composite reference, decode failure, or invalid evidence is a system/execution failure, not a plan-repair instruction. Classify machine findings before visual review/revision:

- plan-repairable: collect applicable critic evidence and revise;
- transient execution: retry the exact execution stage under the same authority;
- deterministic system/evidence-invalid: fail/block without a writer;
- ambiguous cause: full diagnostic review, never automatic plan mutation.

### A fast rendered critic may simply skip evidence

The prompt orders critics to inspect every frame and the final media, but the controller does not bind tool-read events to the verdict. A lower-effort model can appear faster by skipping the last frames or video.

Persist an evidence-access receipt keyed by critic and evidence hashes. Every mandated frame/global media shard must be observed before its verdict is valid. Seed a unique defect in the last required frame and prove both access and detection. Later, composition/editorial lens-specific shards may reduce evidence, but each retains a mandatory global cross-lane shard and runs in shadow first.

### The current 35% target may be impossible for some baselines

The retained rendered-critic range is roughly 5–20 minutes. A 35% target on a 60-minute control is 21 minutes; a 20-minute rendered critical path leaves about one minute for request interpretation, revision, governance, planning review, assembly, Audit B, and decode. A 35% target on a 40-minute control is 14 minutes, below the observed rendered upper range.

Before each trial, calculate a lower-bound budget:

```text
request/author or typed patch
+ affected planning wall
+ render/Audit/decode
+ max(required rendered lenses)
```

If the fixed-stage lower bound exceeds the target, that topology cannot pass. Do not call a correctly measured failure an implementation surprise.

## Ranked optimization plan

### P0 — correctness and high-leverage latency

1. Add complete stage/token/cache/queue/TTFB/process/storage telemetry and compute the fixed-stage lower bound.
2. Introduce `RepairIntentV1` plus exact stable-ID/value/plan-hash compare-and-swap for mechanical repairs; treat no-op as success without invalidation.
3. Keep prior approved generations intact while candidates compute privately; invalidate/advance only at atomic accepted commit.
4. Add batch-owned cancellation/drain/reap and classify execution/system failures before any writer spawn.
5. Run the exact-content stable-prefix critic experiment before changing models or deleting doctrine.
6. Add full decode, exact cover binding, brand-token membership, requested-effect landing, dynamic contrast, and protected-region checks for `R0`.
7. Add explicit deterministic-MP4 routing that touches zero Palmier state/MCP/checkpoint/mirror paths.

### P1 — shadow experiments with large upside

1. Shadow `CriticDoctrineV1` and lens-specific rendered evidence shards against the current full oracle.
2. Split model/effort tests into `C1/C2/C3` and equalize session/schema/tools before provider comparison.
3. Shadow a controller-built minimal cut plan from the existing deterministic speech proposal. If current gates and two critics find it clean, this could eventually skip the 3.5–26.4-minute initial cut-author tail; any defect falls back to the existing writer. Promotion needs blinded noninferiority, not critic agreement alone.
4. Persist same-input critic receipts for transient sibling retry, never changed evidence.
5. Replace model codes with atomic controller defect identities and page complete repair briefs.
6. Test affected-scope review only in shadow with the full planning/rendered wall as oracle.

### P2 — bounded renderer and headless-only savings

1. Defer the GUI preview proxy until after headless completion or omit it entirely for a no-GUI output policy. The retained 108-second graphics-only path spent about 3.0 of 19.9 seconds on proxy generation.
2. Instrument music/audio stages, then test stream-copy reuse of the exact prior approved audio only under a new audio-projection receipt and exact packet/timestamp plus decoded-PCM equality.
3. Record graphics count and composite pass count. The current batch size is eight, so 9–16 graphics re-encode the full video twice and 17–24 three times.
4. Run the one-fixture `R0` mechanism test. Expand to a common headless-emitted repair class only if it passes and field feedback shows demand.

These renderer wins are worthwhile but cannot explain or eliminate an hour-long review wall by themselves.

## Corrected experiment sequence

### Stage 0 — readiness and Amdahl screen

- Freeze unique source/editorial-project/feedback clusters in an immutable SHA-256 CAS and rebase manifests to it.
- Record field feedback by typed repair/effect class; do not select a class solely because it is easy to code.
- Calculate `portfolio ratio = eligible_rate × eligible_fast_ratio + fallback_rate × fallback_ratio`. With an eligible ratio of `0.20` and fallback ratio of `1.0`, eligibility must reach `81.25%` to hit `0.35`; even an instantaneous eligible path needs `65%`. Kill the class if its field-eligibility upper confidence bound cannot reach the target.
- Measure complete baseline stages and compute each proposed lever's perfect-savings ceiling.
- Reserve measured peak space plus rollback and an emergency trace margin atomically. A free-space check or sparse reservation alone is insufficient.
- Pin local toolchain/runtime bytes, vendor remote runtime, isolate caches/work/temp/output, disable telemetry, and pass a deny-network deterministic-render smoke test.
- Start model processes with strict empty MCP configuration and a Palmier tripwire. Explicit MP4 runs must launch zero Palmier subprocesses/tools and produce zero Palmier reads, events, or socket attempts attributable to the run whether an unrelated Palmier app/listener is absent, valid, invalid, open, or closed.

### Stage 1 — one cheap typed-patch/property harness

Use a five-to-ten-second 9:16 fixture with one stable pre-normalized `text-element`, explicit placement, mixed-luma moving background, captions outside its box, and deterministic audio.

Positive assertions:

- exactly one canonical pointer/value change;
- zero ID reconciliation or normalization widening;
- idempotent retry and normalized no-op behavior;
- exact pre-encode brand token/raster plus calibrated decoded-color landing;
- alpha/timing/bbox/placement equivalence;
- contrast over the complete moving window and protected-region separation.

Negative controls that must fail include duplicate/missing ID, stale parent hash, stale old value, `#FFFFFF`→`#ffffff`, off-brand `#123456`, dark-on-dark footage, caption overlap, wrong-color cached object, truncated candidate, runtime drift, and ambient Palmier state.

### Stage 2 — one renderer correctness pair

Create five bound objects: old overlay, revised overlay, old approved final/base, revised reuse candidate, and revised fresh-base-plus-assemble candidate. Clone the same verified pre-rendered-overlay cache snapshot into both correctness arms.

- Control directly builds an attempt-local graphics-free base, then uses the same assemble path.
- Treatment reuses the exact approved-parent base and proves `base_current` with no refit.
- Both candidates use candidate-private base references, regenerate cover, and pass fail-on-error full decode.
- Compare reuse to full revised output and both revised outputs to the old output.
- Run a full/full repeat first to measure renderer nondeterminism. If this control exceeds the equivalence margin, the reuse comparison is uninterpretable.

Stop after this fixture if request fulfillment, equivalence, or the measured complete-pass/Amdahl threshold fails. Do not spend six projects proving a low-ceiling mechanism.

### Stage 3 — plan/review experiments

Run plan-only tests before integrated video:

1. exact-content stable prefix: cold, sequential identical warm, simultaneous pair, and one-byte invalidation;
2. within-provider effort/model successive halving on frozen `C1` packets;
3. compact-doctrine and affected-review shadow against seeded/natural/human ground truth;
4. deterministic cut-proposal shadow with writer fallback recorded;
5. rendered `C2` evidence-access/sharding test on immutable bundles;
6. writer `C3` test on clean cloned filesystems, with session policy as its own factor.

Every failure, timeout, fallback, cache donation, and recovery remains in the denominator.

### Stage 4 — integrated paired pilot

Only surviving mechanisms enter at least six **distinct** source/editorial-project/feedback clusters. Run sequentially, randomize/counterbalance arm order, and keep technical repeats within cluster. Use an untouched later holdout sized from pilot discordance.

The independent unit is the unique cluster, not an artifact directory, retry, model sample, cache state, or render arm. Report every paired value, median, maximum, failures, active operator time, storage, tokens/cost, eligibility, and fallback cost. Six projects can kill a direction; they cannot prove p95 or greater-than-95% reliability.

Avoid six physical copies. Keep one immutable CAS and create only mutable attempt state with fail-closed copy-on-write cloning; never hardlink files that current code truncates in place. Use:

```text
runs/<study>/<cluster>/<block>/<arm>/<attempt-id>/
  state/
  runtime/
  cache/
  work/
  out/
  trace/
```

After verifying exported hashes/final/QC/trace manifests, cleanup may remove only manifest-listed disposable attempt paths. It never deletes the shared CAS, control reserve, failed forensic trace, or an unlisted path.

An atomic admission ledger does not itself reserve APFS blocks. Budget the measured p99 allocated peak plus retained output/proof, rollback/recovery, active reservations, and a physically allocated emergency control-plane reserve. Cleanup resolves every target beneath the run root and rejects symlinks, globs, empty paths, active leases, CAS paths, and the emergency reserve; it appends a cleanup tombstone.

Production also needs singleflight keyed by exact `{approvedParent, realizationDigest}`. Private generations prevent false publication but not duplicate spend. Stale losers stop at stage boundaries and never rebase onto a new parent.

## Edge-case register added in round six

| Edge case | Required behavior |
|---|---|
| Request already satisfied | Return typed no-op receipt; retain current approval; zero writer/render |
| Same request retried | Idempotently return prior intent/generation state; never duplicate work |
| Same parent/digest submitted concurrently | Join one singleflight; do not duplicate writer/render/provider spend |
| Parent plan changed | CAS fails; do not rebase or guess target |
| Expected old value differs | Fail with current value; no mutation |
| Missing/duplicate/nonconforming ID | Fast path ineligible; no remint during repair |
| Case-only color difference | Normalize to no-op |
| Off-brand syntactically valid hex | Controller token gate fails |
| Correct token shifts after YUV/compression | Prove exact pre-encode raster; use calibrated decoded color distance, not byte-exact RGB |
| Legitimate edit changes encoder blocks/GOP outside ROI | Prove exact pre-encode locality; allow only calibrated immaterial encoded spill |
| Brand token unreadable on footage | Dynamic contrast gate fails or broader repair required |
| Graphic overlaps caption/title | Protected-region gate fails |
| Normalization widens diff | Fast path fails closed |
| Candidate staging/provider failure | Prior approved generation remains intact |
| ENOSPC before/after candidate stage | No root invalidation or partial publish; retain trace |
| Claude resumed attempt partially edits then session fallback fires | Restore pristine staged candidate; include both attempt times/costs |
| One rendered critic infrastructure-fails | Abort/drain/reap sibling before job failure/retry |
| One critic returns `block` while sibling runs | Do not abort; aggregate both editorial verdicts |
| Same issue code at two timestamps | Preserve two controller-identified repair actions |
| More than 50 atomic issues | Page or fail before writer; no count-only loss |
| Audit sidecar/reference/decode failure | Classify system/evidence failure; zero plan-writer spawn |
| Lower-effort critic skips last frame | Evidence-access receipt invalid; result is not a speed win |
| Prompt exceeds safe model context | Preflight compact/fail before paid timeout |
| Shared cache miss interrupted | No final cache key until verified atomic publish |
| Two same-key renders race | Per-key exclusion; safe verified loser reuse |
| Cache snapshots differ across arms | Trial invalid |
| Source manifest still points outside CAS | Trial invalid |
| Base reference changes during Audit B | Candidate-private hash mismatch; trial fails |
| Delete fingerprint but retain base | Not a forced-full control; trial invalid |
| Forced-full path performs refit | Trial invalid |
| CDN/package/network access occurs during deterministic render | Trial invalid |
| Palmier MCP/state exists during explicit MP4 | Zero inspection/mutation; tripwire must remain untouched |
| Proxy fails or is omitted headlessly | MP4 approval unaffected; proxy is outside completion endpoint |
| Prior audio projection differs in any field/hash/fact | Rerun full audio/music pipeline |
| Stream-copied audio hash/PTS/PCM differs | Reject reuse and rerun full audio |
| More than eight graphics | Record extra full-video passes; do not extrapolate eight-graphic timing |
| Palmier media matches only basename/duration/dimensions | Do not adopt it; require exact content identity |
| Palmier timeout occurs after send | Reconcile or quarantine; zero automatic retry or queue drain |

## Round-six go/no-go

| Path | Decision after this round |
|---|---|
| Complete latency/token/cache/process/disk telemetry | Go first |
| Typed mechanical `RepairIntentV1` in a private candidate | Research go; highest-priority repair experiment |
| Exact-content stable-prefix critic test | Go before model downgrade or doctrine deletion |
| Controller-compiled compact doctrine | Shadow-only |
| Deterministic cut proposal replacing initial cut writer | Shadow-only with existing writer fallback |
| Provider/model comparison under current mixed settings | No-go; confounded |
| `C1/C2/C3` split model/effort experiments | Go after telemetry and parity controls |
| `R0 text-element` as a one-fixture renderer falsifier | Go after runtime/cache/oracle isolation |
| `R0 text-element` as a six-project product-value claim | No-go; no retained headless incidence |
| Six-project integrated pilot using current retained artifact dirs | No-go; pseudo-replicated and insufficient |
| Same-input critic receipt retry | Go for tail recovery after exact roots are defined |
| Selective planning/rendered review | Shadow-only |
| Skip/defer preview proxy for headless completion | Low-risk research go; measure separately |
| Reuse prior approved audio stream | Research go only after exact audio-projection receipt exists |
| Current Audit B as complete decode/effect proof | No-go |
| Current `ai-edit` invalidation order for atomic generations | No-go |
| Explicit MP4 run with ambient Palmier probes/checkpoints | No-go |
| Another live Palmier mutation | Temporary no-go |
| Greater-than-95% product-direction claim | Not supported |

## Confidence effect

This round raises confidence in the **optimization order** because it identifies two levers that can remove entire model calls or large repeated context and gives each a cheaper falsification test. It lowers confidence in the prior `R0` product framing, current experiment isolation, and current review/model study design.

The architecture remains below the requested greater-than-95% threshold. Authority/correctness is Red until candidate generations, request-effect proofs, runtime/cache closure, full decode, and failure routing are implemented. Latency/economics is Red until distinct source-cluster baselines and complete second-pass measurements exist. Editorial quality is Red until compact/selective/model changes pass seeded, natural, clean-negative, evidence-access, and blinded noninferiority gates.
