# Headless execution adversarial audit — 2026-07-18, round 10

> **STATUS: FROZEN AUDIT SNAPSHOT.** Corrections belong in the living
> [headless optimization dossier](../producer/HEADLESS_EXECUTION_OPTIMIZATION_DOSSIER.md).

## Scope boundary

This round covers only:

1. Claude Code or Codex Desktop to Palmier through a machine-facing
   API/MCP/protocol; and
2. Claude Code or Codex Desktop to a deterministic MP4.

It excludes every GUI, Next.js, dashboard, SSE, active-window, and desktop-click
path. No finding below should be read as a GUI recommendation.

## Verdict

The overall architecture is **not at 95%**. The evidence now supports one narrow
statement with high confidence: the frozen G2 container adapter can render one
exact offline overlay correctly and repeat it from an attempt-owned warm cache.
It does not support a production controller, full one-minute quality pass, or
editable Palmier release.

| Layer | Round-10 disposition | Why |
|---|---|---|
| G2 exact clean overlay | PASS for the frozen specimen | Independent attempt 008 passed the exact media, visual, runtime, network-denial, and cleanup contract. |
| G2b explicit headless renderer root | PARENT PREFLIGHT PASS / INDEPENDENT PASS ABSENT | The corrected wrapper ignores ambient renderer/cache values and reproduced the exact output, but no independent result was completed. |
| G1 evidence primitives | ISOLATED TEST PASS / INTEGRATED GATE BLOCKED | Admission, trace, OS boot identity, and terminal-result binding exist, but no controller calls them. |
| Deterministic MP4 product | BLOCKED | No controller, sealer, fence, publisher, startup recovery, R0, full-quality candidate, or qualifying field job exists. |
| Palmier machine path | PRODUCTION NO-GO | Current execution and QC can accept the wrong effect, leave remote ambiguity, and approve self-attested evidence. |
| Frozen 95% release claim | BLOCKED | Zero qualifying product units; G3 onward remains closed. |

## Review deployment and evidence hygiene

Separate review streams attacked local durability/terminal semantics,
renderer-lane isolation, cancellation/restart behavior, Palmier machine
execution, and plan-to-code reachability. Two additional delegated local reviews
were stopped by the review runner before they executed. They produced no
admissible result and are counted as neither pass nor failure.

The executed local regression after the G1 correction ran **136 tests in 1.783
seconds**, with one sandbox-only loopback test skipped. The skip emits a transient
unclosed-socket warning because the frozen positive-control helper allocates its
socket before a denied bind. The qualifying G2 attempt ran where bind succeeded
and closed the helper; changing that frozen helper now would require a fresh G2
qualification.

## New falsification: terminal disposition did not bind terminal result

The first G1 terminal design wrote only
`TERMINAL_SEALED {disposition: FAILED}` to the durable trace. If the process died
before `terminal-manifest.json` was replaced, recovery could attach any result
object to that already-terminal trace. Referencing the trace digest from the
manifest proved order but not result content.

The correction now:

- canonicalizes the result before the terminal append;
- records a domain-separated `resultDigest` in the terminal event and manifest;
- refuses recovery with different result bytes;
- revalidates manifest sequence, trace digest, disposition, result digest, and
  attempt/unit/request identity against the actual trace on every replay; and
- bounds the terminal manifest before committing the terminal event.

Because the digest is now required, trace frames and terminal manifests were
explicitly advanced to pre-release schema version 2; old version-1 records fail
closed rather than being silently reinterpreted.

The 39-test G1-focused suite passed in 0.733 seconds, including changed-result recovery and
post-manifest trace-change counterexamples. Exact corrected source hashes are:

| File | SHA-256 |
|---|---|
| `terminal_manifest.py` | `28fdf219dc5e0de2ba443586cd33c63500620061bd4f8e629122ae9c88122ae3` |
| `trace_state.py` | `60a83bc12e21e5fe9e6ef366e0c2f0a63cd2980714c64fada9a10d22e3553781` |
| `trace_frames.py` | `72ed62a5ca720d1d8dba7215757831c8dfeea0a00a9f5d3637d2df1f01756191` |
| `attempt_trace.py` | `edbc41d4b19cf69561f1ed53525ef11dcc393c10543276a7b10473e2d2390649` |

The general lesson is recorded in
[TERMINAL_RESULTS_MUST_BE_COMMITTED_BEFORE_RECOVERY.md](../../scripts/producer/docs/findings/TERMINAL_RESULTS_MUST_BE_COMMITTED_BEFORE_RECOVERY.md).

## G1 is still not a controller

Repository-wide non-test call-site searches find only the definitions of
`admit`, `seal_terminal_manifest`, `read_boot_id`, and `launch_overlay`. No
machine-facing composition root invokes them. Consequently, the passing
primitives do not yet prove:

- durable acceptance before returning a job identity;
- startup scanning and scheduling of an admission whose attempt directory or
  worker was never created;
- controller-derived boot identity in each trace event;
- one active fence and one publisher-capable attempt;
- expected-parent `CURRENT` publication and pointer-before-terminal recovery;
- result sealing from the actual committed generation;
- cancellation, process-group death, or resource cleanup; or
- a real daemon restart, process crash, or host/VM reboot campaign.

The next valid G1 slice is therefore an internal controller skeleton, not more
unit tests around disconnected helpers.

## G2b wrapper: first design falsified, corrected design not yet qualified

The first G2b preflight was correctly rejected. It exposed two local authority
bugs:

1. a symlink result inside the cache became acceptable after `realpath`, and the
   caller received the resolved target; and
2. a restrictive umask could create a mode-000 owner receipt on first use.

The corrected wrapper now explicitly sets new directory/file modes, requires an
absolute canonical direct child, opens the output by cache directory descriptor
with `O_NOFOLLOW`, requires an owned mode-0600 single-link regular inode, hashes
the open descriptor, and returns device/inode/hash/size binding. The frozen
corrected hashes are:

- `render_lane.py`: `cd0cc18ccddb016aaabf2c1ab39c0c7fc34de7ef9546214b90197826a3b6a683`;
- `render_lane_cache.py`: `64be94bc3938f2ead8a86f810099e58e23066e092dcfc65aade76f5bd99fb75e`;
- `render_worker.py`: `33ef98f62e929ac72e071af283849b22ada1e85fdd419e3069e76db8c6eae43c`.

The retained parent preflight is explicitly `qualifying:false`:
[preflight-result.json](../../artifacts/headless-gates/g2b-render-lane-20260718/attempt-002-parent-preflight/preflight-result.json).
It passed exact known MOV/tar identity, a 13.181-second cold miss, 0.666-second
warm hit, a separate-attempt 11.902-second cold miss, output inode bindings,
ambient-environment poisoning, and pre/post container absence.

That proves useful behavior, but not independent qualification. It also leaves
four production blockers visible in
[`render_lane.py:183`](../../scripts/producer/headless/render_lane.py#L183):

- `subprocess.run` has a deadline but no new process group, TERM/grace/KILL/reap
  contract for descendants;
- `buildDigest` is accepted from the caller but not calculated from the worker,
  policy, and runtime closure by this module;
- worker output `kind`, `fmt`, and `proof` are schema-shaped but are not matched
  here to a controller-owned expected effect/capability manifest; and
- the validated cache inode is closed before any trusted generation sealer owns
  or copies it.

## Cancellation and restart attack

The exact G2 adapter launches a detached container through one combined Docker
run in [`container_renderer.py:215`](../../scripts/producer/headless/container_renderer.py#L215).
An absence check after a 60-second client timeout cannot rule out a delayed
create that lands after the check. It can also leave a created-never-started
container outside entrypoint cleanup. Controller `SIGTERM`/`SIGKILL` bypasses
ordinary `finally` cleanup, and current Docker output streaming is not a durable
owned child resource.

The media proof path can recreate the original hour-long stall: ffprobe,
occupancy decode, full decode, and terminal-frame ffmpeg calls have no explicit
deadline or process-group ownership in
[`asset_proof.py:61`](../../scripts/producer/graphics/asset_proof.py#L61),
[`asset_proof.py:110`](../../scripts/producer/graphics/asset_proof.py#L110),
[`asset_proof.py:127`](../../scripts/producer/graphics/asset_proof.py#L127), and
[`frame_oracles.py:10`](../../scripts/producer/graphics/frame_oracles.py#L10).

The integrated supervisor must split create from start, durably record launch
intent and the exact container ID before start, own every local child in a
process group, apply stage deadlines, TERM/grace/KILL/reap, persist
cleanup-pending resources, and re-attest daemon identity at terminal recovery.
Required tests include cancellation before/after create/start, client death,
worker death, verifier hang, Docker daemon restart, controller `SIGKILL`, and
real restart/reboot recovery.

## Palmier machine path: implemented surfaces and decisive counterexamples

The current repository has two non-GUI families:

- Claude Code can call Palmier MCP directly through `.mcp.json`, the
  `/produce-palmier` command, and Pre/Post hooks.
- A Python/native path accepts a plan through `native_delta_cli.py`, applies it
  through `native_delta.py`, and runs QC through `native_qc_cli.py`.

Codex does not have a direct rich-MCP execution path. Its intended role is to
plan machine operations that the Python executor applies. This is the safer
topology: Claude and Codex should be planners behind one controller-owned
executor, not separately qualified mutation authorities.

### Readback proves change, not the requested effect

[`native_delta.py:131`](../../scripts/producer/palmier/native_delta.py#L131)
accepts an operation when the candidate fingerprint changes and forbidden
structural additions/removals are absent. It does not compare the requested
property/value to exact before/after readback. A fake-server check requested
`opacity:0.5`, changed `speed` to `2`, and still reached candidate status
`edited`. Exact effect oracles are required for every operation family.

Lane validation is also only nonempty intersection at
[`native_plan.py:267`](../../scripts/producer/palmier/native_plan.py#L267), not
exact containment of all affected properties. Color/effect strings are bounded
text rather than typed capability values. A declared lane can therefore cover a
different mutation family than the actual arguments imply.

### Remote intent is not durable before the remote effect

Desktop begin creates the remote candidate before the operation manifest,
journal, and desktop state are durable at
[`desktop_authority.py:107`](../../scripts/producer/palmier/desktop_authority.py#L107).
The lower fork sends `create_timeline` before saving the candidate receipt at
[`timeline_authority.py:257`](../../scripts/producer/palmier/timeline_authority.py#L257).
Apply-then-disconnect can therefore leave an unlocatable remote fork.

Native execution similarly accumulates operation receipts in memory and saves
them only after operations complete at
[`native_delta.py:254`](../../scripts/producer/palmier/native_delta.py#L254).
Process death after a landed mutation but before local persistence leaves no
durable per-operation intent/receipt bridge.

### Desktop hooks are neither atomic nor exact-response-correlated

PreToolUse loads, checks, and rewrites the pointer without a lock/CAS in
[`desktop_hook.py:153`](../../scripts/producer/palmier/desktop_hook.py#L153).
Two concurrent reservations can both observe no pending operation. PostToolUse
matches only the tool name at
[`desktop_hook.py:224`](../../scripts/producer/palmier/desktop_hook.py#L224); it
does not compare the event arguments to the stored `argsHash` or bind a response
ID/session/fence.

The hook governs only names beginning `mcp__palmier-pro__`. The repository also
allows broad `Bash(python3 scripts/*)` execution in
[`.claude/settings.json:21`](../../.claude/settings.json#L21), so direct Python
mutation CLIs can bypass the MCP hook. Authority belongs in the executor, not in
one invocation surface.

### QC can approve self-attestation and the wrong target

Desktop approval requires two JSON rows whose checks all say `pass`, but has no
reviewer identity, independent model/session provenance, or evidence that a
reviewer actually opened the frames
([`desktop_authority.py:269`](../../scripts/producer/palmier/desktop_authority.py#L269)).
It marks Desktop state `complete`; it does not promote the native candidate,
which can remain `edited` with `qc.pending`.

The retained first-60 evidence demonstrates the contradiction:

- Desktop authority says `operationCount:45` and complete;
- [the candidate receipt](../../artifacts/palmier-live-acceptance-20260715/producer/palmier.timeline-candidate.json)
  remains `status:edited`, `qc.status:pending`;
- [rendered reviews](../../artifacts/palmier-live-acceptance-20260715/producer/rendered-reviews.json)
  say `wordLock:pass`, while the retained runtime records seven corrected
  captions losing word-level karaoke timing; and
- the native audit accepts a 3840×2160 canvas because it compares the export to
  Palmier's candidate, not to a controller-owned 9:16 short request.

The run took 56m48s from capture to Desktop completion. It is a product
falsifier, not a successful speed specimen.

### MCP client negotiation is incomplete

[`mcp_client.py:45`](../../scripts/producer/palmier/mcp_client.py#L45) discards
the initialize result and never calls `tools/list` to bind server build,
capabilities, or tool schemas. It concatenates text blocks and discards other
content types at lines 53–70. The SSE parser does not expose a durable response
ID correlation contract. A resumable mutation executor must freeze and recheck
server version, negotiated protocol, tool-list/schema hash, session identity,
and exact request/response IDs.

## Optimization result: what can actually remove the hour

The corrected G2b warm cache turns an exact 12–13-second overlay into roughly
0.67 seconds. That is worthwhile, but even eliminating a measured 190-second
base rebuild saves only about 4.7% of a 60-minute pass. It cannot explain or fix
the hour by itself.

The higher-value order remains:

1. route stable-ID color/text/value repairs through typed controller patches,
   avoiding a semantic writer and full plan replay;
2. overlap independent critic/render work inside one bounded `qualityPass`
   controller and cancel/drain on the first authoritative failure;
3. shrink and cache only exact stable critic prefixes when provider counters
   prove a hit; Claude supports the telemetry experiment, current Codex does not;
4. use affected-scope review only after exact dependency invalidation and hidden
   quality tests prove it safe; and
5. if Palmier remains justified, replace per-operation Desktop hook processes
   with one controller-owned arbiter and one healthy MCP session, plus safe typed
   batches and exact postconditions.

The retained 45-operation Palmier run implies at least 90 Pre/Post hook-side MCP
handshakes and 180 initialize/initialized authority calls before counting the
actual mutation and readback calls. Session consolidation is therefore a real
latency lever, but it cannot ship until durable intent, exact-effect oracles, and
ambiguity recovery exist.

## Round-10 go/no-go

**Go:** preserve G2 attempt 008; keep the corrected G2b parent specimen
nonqualifying; finish one non-GUI controller skeleton that wires admission,
trusted boot identity, trace, explicit renderer policy, terminal sealing, and
startup recovery; then execute the cancellation matrix before R0.

**Research go:** one offline Palmier capability/schema capture, typed
exact-delta compiler, fake-server apply-then-disconnect matrix, persistent
arbiter prototype, and adversarial QC corpus. No live mutation is needed for
these tasks.

**No-go:** another live Palmier canary, direct Claude rich-MCP production,
Codex direct rich-MCP claims, MP4 publication, or any 95% statement. The next
confidence increase must come from integrated execution evidence, not another
paper review of disconnected modules.
