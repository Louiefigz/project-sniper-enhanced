# Headless execution adversarial audit — 2026-07-18

> **STATUS: FROZEN AUDIT SNAPSHOT.** This file records what was observed during this review. Corrections belong in the living [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md) and must link back here rather than silently rewriting this snapshot.

## Scope

Reviewed only these paths:

- Claude Code/Codex planning and execution into Palmier.
- Approved-plan realization and QC into MP4.

Excluded GUI implementation, layout, and interaction work.

The review used three specialist adversarial lanes—job/crash recovery, authority/cache integrity, and latency/quality economics—followed by cross-examination between their proposed corrections. Claims were checked against current code and retained artifacts.

## Offline baseline

At the reviewed checkout:

- The complete TypeScript `npm test` baseline passed.
- `scripts/producer/selftest.py` passed all **1,559 Python tests** in 52.167 seconds.
- The worktree was clean after the checks.

This is a useful regression baseline, not evidence that the proposed architecture is already safe. One current test deliberately expects source-media mutation not to alter the authority digest: [auto-edit-authority-policy.test.ts](../../src/lib/producer/__tests__/auto-edit-authority-policy.test.ts).

## Surviving P0 findings

### A1 — source and media bytes are outside complete authority

[ingest_probe.py](../../scripts/producer/ingest_probe.py) identifies the main source using size plus SHA-1 over only the first 8 MiB. A same-size mutation after that window is invisible. Ingested B-roll and music primarily retain path/metadata identity rather than complete content hashes. Rendering later consumes mutable paths.

Consequence: a run or cache can be approved against bytes different from those represented by its authority record. A later recheck also cannot eliminate a mutate-read-restore TOCTOU window.

Required correction: snapshot complete inputs from the same open descriptor into immutable/content-addressed run storage, use full SHA-256, reject unsafe symlinks, and make normalized manifests reference immutable blobs.

### A2 — current cache receipts do not authorize exact output bytes

[fingerprints.py](../../scripts/producer/fingerprints.py) truncates SHA-256 fingerprints to 16 hexadecimal characters, may omit absent inputs, and stage-current checks focus on input fingerprints and output existence rather than exact output bytes.

Consequence: replacing a cached file while retaining its receipt can be accepted. Missing dependency edges can also create unsafe reuse.

Required correction: every stage receipt binds exact input root, implementation/toolchain identity, output SHA-256, size/media facts, and receipt digest; missing inputs fail explicitly.

### A3 — cross-target fresh retry can adopt a prior realization

[launch.ts](../../src/app/api/producer/auto-edit/launch.ts) can bootstrap a fresh run from a parseable mutable `edit_plan.json` after a failed or interrupted job.

Consequence: a failed Palmier-target realization can seed a later MP4 request, or vice versa, even when the new request key contains a target.

Required correction: reuse only an immutable target-neutral editorial approval across targets. A target-specific realization is reusable only when target, request key, capability profile, and realization digest all match.

### A4 — the persisted snapshot and executing controller can diverge

[auto-edit-pipeline-authority.ts](../../src/lib/server/auto-edit-pipeline-authority.ts) captures selected pipeline files. [auto-edit-worker-launcher.ts](../../src/lib/server/auto-edit-worker-launcher.ts) still launches the detached TypeScript worker from the current repository; Python also comes from the live `.venv`, while Node dependencies, ffmpeg, browser/runtime libraries, and fonts remain live.

Consequence: a V1 job may resume under new controller semantics while attesting older captured bytes.

Required correction: execute the controller from a pinned release/snapshot or fail closed through a verified migration adapter. Record the complete relevant runtime/toolchain identity. Drain or fail legacy resumable jobs instead of defaulting them to MP4.

### A5 — sink commits and external effects are not atomic

Current MP4 quality promotion in [auto-edit-quality-artifacts.ts](../../src/lib/server/auto-edit-quality-artifacts.ts) updates final artifacts sequentially. Palmier candidate creation in [timeline_authority.py](../../scripts/producer/palmier/timeline_authority.py) performs the external create before its durable local receipt. Outer completion happens after sink work in [worker.ts](../../src/app/api/producer/auto-edit/worker.ts).

Consequence: crashes can lose a prior approved MP4 generation, replay already-committed work, or leave an unprovable Palmier orphan.

Required correction: immutable sink generations with intent/receipt records, fencing, and a CAS `CURRENT` pointer. Palmier also needs remote idempotency/query-by-operation-ID. If its API cannot provide that, exactly-once recovery is not provable; ambiguous results must be quarantined.

### A6 — Palmier execution proof does not prove plan coverage

[live-build/process.ts](../../src/app/api/producer/live-build/process.ts) accepts a session with the expected skill, a timeline read, at least one successful mutation, no failed tool result, and the matching session. [prompt.ts](../../src/app/api/producer/live-build/prompt.ts) permits the executor to report an unsupported lane and continue.

Consequence: a harmless successful mutation can satisfy execution proof while a material approved plan element is omitted. The journal also cannot exclude an out-of-band mutation that appears in the final candidate.

Required correction: a deterministic plan-element-to-fidelity-to-operation-to-readback coverage map, 100% disposition for required elements, and rejection of unexplained mutations or unapproved material approximations.

### A7 — native initial cuts bypass their own authority limitation

[palmier-native-capabilities.ts](../../src/app/api/producer/ai-edit/palmier-native-capabilities.ts) reports that native cuts lack transcript/cut-approval binding. Initial selection still includes cuts, and [palmier-native-runner.ts](../../src/app/api/producer/ai-edit/palmier-native-runner.ts) bypasses the capability failure for the initial-auto-edit workflow.

Consequence: current native gates can prove structural bounds and identifiers, but not that the selected cut is the approved transcript-semantic cut.

Decision: native initial auto-edit with cuts is a no-go until deterministic transcript/cut mapping exists. Narrow non-cut surgical operations may be evaluated separately.

## Real Palmier acceptance artifact

The audit corrected an earlier belief that no full first-60 Palmier proof existed. The staged artifact at `artifacts/palmier-live-acceptance-20260715` contains 45 verified mutations.

Observed evidence:

- Operations elapsed from timeline capture to desktop completion: **56m48s**.
- Recorded Claude turns totaled approximately **10m20s**.
- The visual turn alone took **418.879 seconds**.
- Capability classification in [palmier.timeline-candidate.json](../../artifacts/palmier-live-acceptance-20260715/producer/palmier.timeline-candidate.json) was 4 exact, 8 baked, 7 approximate, and 3 unsupported, with `approved:false`.
- Runtime QA in [.live-first60-runtime.json](../../artifacts/palmier-live-acceptance-20260715/producer/.live-first60-runtime.json) reports that seven corrected captions lost per-word karaoke timing and would render as plain text.
- [edit_plan.json](../../artifacts/palmier-live-acceptance-20260715/producer/edit_plan.json) requires `wordReveal`.
- [rendered-reviews.json](../../artifacts/palmier-live-acceptance-20260715/producer/rendered-reviews.json) nevertheless records `wordLock: pass`.
- The legacy authority writer in [desktop_authority.py](../../scripts/producer/palmier/desktop_authority.py) binds caller-supplied verdict JSON to artifact hashes but does not establish exact provider/model/prompt/evidence provenance.

Interpretation: this artifact proves substantial staged Palmier transport and execution. It does **not** prove the current direct live-build route, production latency, complete plan fidelity, or trustworthy QC. It actively disproves the claim that this specimen solved the one-hour problem.

## Performance findings

### Critical path

The governed flow contains eight model subprocesses across approximately five serial model groups: cut authoring, parallel cut critics, visual authoring, parallel plan critics, render/Audit B, and parallel rendered critics. The governed critics are already parallel within their rounds.

The likely hour-long drivers are model latency, large repeated context, revisions, and full replay. Sink selection and MP4 encoding are not demonstrated as the primary bottleneck.

### Snapshot economics

The currently captured controller scope measured:

- 553 files.
- 6,179,171 bytes.
- About 70.7 KB for a compact flat receipt.
- Warm full read-and-SHA: 11.5 ms median, 10.6 ms minimum, 110.7 ms maximum over ten passes.

Full hashing over this explicit closure is negligible relative to a 24–60 minute run. The full `templates/motion` tree is approximately 8.8 GB before exclusions, so a broad snapshot-everything approach would create severe storage and I/O costs.

### Cache-placement regression

[graphics_render.py](../../scripts/producer/graphics/graphics_render.py) derives the graphics cache beneath the per-run pipeline root. Because cache directories are excluded from snapshot capture, each unique snapshot appears to begin with an empty cache.

Consequence: the current immutable-root design likely defeats cross-run graphics cache reuse.

Required correction: a separate mutable content-addressed cache root keyed by exact content, renderer implementation, and toolchain authority. Mutable cache bytes must never live inside the directory described as immutable authority.

### Quality-sensitive context optimization

[plan-review-packet.ts](../../src/app/api/producer/auto-edit/plan-review-packet.ts) supplies complete utterance, kept-word, and seam context to critics, while [plan-review-prompt.ts](../../src/app/api/producer/auto-edit/plan-review-prompt.ts) gives them no tools beyond the embedded evidence.

Semantic compaction can hide abandoned takes, retakes, dangling referents, repeated phrases, semantic-join failures, ASR uncertainty, and unsupported claims. Hashing a compact packet proves what was shown, not that it was sufficient. Only lossless representation changes are presumptively safe; semantic omission requires blinded noninferiority testing.

## Critic independence and provenance

[planning-review-batch.ts](../../src/app/api/producer/auto-edit/planning-review-batch.ts) launches the same review path concurrently, and [brain-review-runner.ts](../../src/app/api/producer/auto-edit/brain-review-runner.ts) selects the same provider/model configuration for both. Separate processes avoid shared session state, but not correlated blind spots.

Required evidence includes defect-level correlation, `P(critic 2 misses | critic 1 misses)`, incremental recall from the second critic, and verdict stability across repeated runs.

Provider/tool identity is also incomplete. [ai-provider.ts](../../src/app/api/_lib/ai-provider.ts) uses the moving Claude `opus` alias by default. [preflight.ts](../../src/app/api/producer/live-build/preflight.ts) initializes Palmier but does not retain a durable server/capability identity.

Required provenance: CLI version, requested and resolved model/build where exposed, effort/reasoning configuration, Palmier server version, MCP tool-schema/capability hash, and executor/compiler identity.

## Cross-examined architecture decision

The surviving correction is:

- Keep `sourceAuthority` and `deliveryTarget` separate.
- Share only immutable editorial approval between targets.
- Compile a target-specific realization approval.
- Start with one integrated detached JobV2 worker and durable target sink generations.
- Derive outer completion from verified sink commits.
- Use coherent flat SHA-256 authority roots over explicit dependencies rather than a generic filesystem Merkle DAG.
- Do not require local signatures for the ordinary accidental-drift threat model.
- Build the trustworthy MP4 path first.
- Treat editable Palmier as experimental until coverage, cut authority, remote idempotency, crash recovery, quality, and latency gates pass.

## Audit conclusion

The direction is promising but not above the requested confidence threshold. The authority/JobV2/atomic-MP4 foundation is the next reversible, evidence-producing investment. Rich Palmier execution is not currently justified as the production speed solution.

