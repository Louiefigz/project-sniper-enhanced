# Host capability gate (orchestration review §6), run 2026-09-27

**Result: the gate is not passed for either host.** Neither Claude Code nor Codex, as installed on
this Mac, supports the unattended AI deadline guarantee. No host adapter is approved by this
evidence, including the conditional `production/host_codex.py` reservation in §7 E. Per the §6
decision rule, Sniper must report the missing capabilities as unsupported and keep the safe local
media/task features. It must not bring back the retired provider-CLI auto-edit lane, and it must
not ship a replacement model service.

Evidence records: `docs/producer/host-capability-gate/*.json` (one per scenario, paths
neutralized). Machine-readable verdicts: `host-capability-gate/gate-verdicts.json`. The harness that
produced them is `scripts/producer/studio/production/host_conformance/` (maintainer tooling,
withheld from the buyer package by `release/package_spec.py`).

## How the probes were run

- **Hosts:** Claude Code CLI `2.1.247` (`~/.local/bin/claude`) and Codex CLI `codex-cli 0.144.1`
  (Homebrew). The desktop apps bundle newer builds: Claude desktop runs `2.1.281` for the operator's
  conversation, and ChatGPT.app bundles `codex 0.155.0-alpha.16.3`. Those bundled builds were not
  probed.
- **Isolation:** every child was started by the probe in its own session with a minimal
  environment. Only HOME, USER, LOGNAME, SHELL, TMPDIR, LANG and PATH were passed. No provider key and
  no host-session variable reached a child (`CLAUDE_CODE_SESSION_ID`, messaging socket and token,
  `ANTHROPIC_BASE_URL`), so nothing attached to the running desktop session. The working directory
  was a scratch directory.
- **No auth file was read.** Identity was taken only from `claude auth status --json`,
  `codex login status`, the Claude `init` event's `apiKeySource`, and Codex `account/read`, with
  the email field dropped.
- **No existing session, thread, app-server or daemon was touched.** Every Codex app-server
  (stdio, and one `--listen unix://`) was launched by the probe. The ChatGPT app's own app-servers
  and the operator's daemon were never contacted. Signals went only to identities the probe
  recorded (PID, `lstart` and PGID).
- **Budget used:**
  - **Claude: 13 CLI invocations, 0 model calls.** One reached the real endpoint without a
    credential and was refused before any API call (`duration_api_ms: 0`). One was an argv error
    with no network. The other eleven ran against a loopback stub of the Messages endpoint on
    `127.0.0.1` with the placeholder key `stub-not-a-key`.
  - **Codex: 5 `turn/start` calls on the ChatGPT subscription.** Two were rejected by the service
    (see [Findings for other units](#findings-other-units-must-handle)). Three executed with
    `effort: low`. Account, model list, thread read and resume calls ran with no turns.
- **Stub caveat:** Claude mechanics were measured against the stub. That proves host process and
  stream behaviour (session ids, interrupts, tool cleanup, orphan behaviour, usage plumbing). It
  proves nothing about subscription billing, real-model behaviour or service limits.
- **`--dangerously-skip-permissions`:** it was used only as `--permission-mode bypassPermissions`
  with `--tools Bash`, in the scratch directory, against the stub. The only command the stub
  requests is `/bin/sleep N`.

## Claude Code CLI 2.1.247

Tool scenarios use this child argv, with stdin carrying a stream-json user message:

```
claude -p --output-format stream-json --verbose --safe-mode --model sonnet \
  --session-id <uuid> --input-format stream-json --permission-mode bypassPermissions --tools Bash
```

Stub runs add `ANTHROPIC_BASE_URL=http://127.0.0.1:<port> ANTHROPIC_API_KEY=stub-not-a-key` and the
telemetry-off variables. The stub's first reply requests `Bash {"command": "/bin/sleep N"}`.

| Contract item | Verdict | Command | Observed evidence |
|---|---|---|---|
| Subscription identity without API fallback | **FAIL** | `claude auth status --json`<br>`claude -p "Reply with the single word OK" … --session-id U --tools ""` (clean env, real endpoint) | Auth status reports `loggedIn:false, authMethod:none` (`host-status.json`); the desktop-bundled 2.1.281 reported the same when checked by hand in this session (not recorded in a JSON file). The turn fails closed: `init.apiKeySource:"none"`, result `is_error:true`, "Failed to authenticate: OAuth session expired and could not be refreshed", `terminal_reason:"api_error"`, `duration_api_ms:0`, exit 1 (`claude-identity-no-key.json`). With a key in the child env, `init.apiKeySource:"ANTHROPIC_API_KEY"` and the turn runs on that key without asking (`claude-session-binding.json`). The host does not prevent API billing; an adapter would have to scrub the environment and refuse unless `apiKeySource=="none"`. `--bare` forbids OAuth outright. The operator must re-login (`claude auth login`) before any subscription turn is possible. |
| Launch idempotency (caller-supplied session id) | **PASS** | Same `--session-id U` launched twice | The second launch is refused before any model request: stderr `Error: Session ID U is already in use.`, exit 1, 0 stub requests. `--resume U` continues the same session (`claude-session-binding.json`). |
| Attach is exclusive while the first process is live | **FAIL** | `claude -p "Reply…" --resume U` while process 1 is mid-tool | Not refused. The second process ran a full turn (1 model request, `result:"OK"`) concurrently with process 1. Both appended to one transcript (`claude-resume-while-live.json`). A restarted coordinator must never `--resume` until the old identity is proven dead. |
| Known host concurrency | **UNPROVEN** | none possible | No CLI surface declares a session or turn concurrency limit. No real turns could run; stub runs say nothing about service limits. |
| Exact child handle (pid + session/turn id) | **PASS** with gap | launch + `ps` | Handle = launched PID, `lstart` and PGID plus the caller's session id, echoed in `init` and `result`. Every event carries a `uuid`. **Gap:** the Bash tool's processes are not reported in the stream, and they run in their own process group: CLI PGID 75641 vs tool `zsh`/`sleep` PGID 75806 (`claude-control-interrupt.json`). `killpg` on the CLI's group misses them. |
| Event replay after disconnect | **FAIL** (partial) | read `~/.claude/projects/<slug>/<session>.jsonl` | No attach to a running print-mode stream. After coordinator death, the orphan kept writing the on-disk transcript: tool_use, tool_result and the final text (`claude-coordinator-death.json`, `finalReplay`). That file is an internal format (`queue-operation`, `atis-latch`, `attachment` rows) with no terminal `result` row. `--resume` starts a new turn; it does not replay. |
| Interrupt followed by terminal confirmation | **PASS** | stdin `{"type":"control_request","request_id":"probe-interrupt-1","request":{"subtype":"interrupt"}}` | `control_response` success after 2 ms, then `result` `error_during_execution`, `is_error:true`, `terminal_reason:"aborted_tools"` after 7 ms. No further model request. The final-code recheck gives 6 ms and 12 ms. SIGINT also yields a `result` within 46 ms but **exits 0**: exit status is not the terminal signal (`claude-signal-sigint.json`). |
| Tool cleanup, cooperative interrupt | **PASS** | same, then track the exact `sleep` identity | The `/bin/sleep 301` descendant is gone 0.279 s after the interrupt (recheck 0.302 s). After SIGINT it is gone in 0.036 s. |
| Tool cleanup when the CLI process is killed | **FAIL** | `SIGKILL` to the CLI PID mid-tool | The `/bin/sleep 305` (own PGID) survived 15 s and was removed by the probe. The transcript ends at `assistant:tool_use` (`claude-signal-sigkill.json`). |
| Nested subagent cleanup | **UNPROVEN** | not run | Task/subagent descendants were not exercised. |
| Coordinator death, restart delayed past deadline | **FAIL** | coordinator spawns the child, then `SIGKILL`s itself; deadline 20 s, restart 45 s | The CLI and its tool were alive at 20.5 s and at 45.4 s. The tool finished at 66.9 s, the orphan made **another model request** at that point (stub request 2) and completed the turn, then exited at 69.1 s on stdin EOF (`claude-coordinator-death.json`). In run 1 the stub asked again: the orphan started a **second** tool process and kept going until the probe terminated it at about 120 s (`claude-coordinator-death-run1-stub-reasked.json`, transcript "Exit code 137"). Nothing host-side enforces a deadline; there is no expiry flag. |
| Separated usage attribution | **PASS** (plumbing) | `result.usage` / `result.modelUsage` | Per invocation and per model: input 11 and output 7, exactly as the stub reported. A resumed turn reports its own 11/7, not a cumulative total. `total_cost_usd` is a list-price estimate (`costBasis:"list"`), not subscription billing. Real-model and subagent usage separation are unobserved. |

## Codex CLI 0.144.1

App-server launch: `codex app-server --listen stdio:// -c mcp_servers={} --disable plugins --disable apps`.
The JSON-RPC sequence was `initialize`/`initialized`, `thread/start {cwd, approvalPolicy:"never", sandbox:"workspace-write", model}`
and `turn/start {threadId, input, effort:"low"}`. The model is the CLI's own `model/list` default,
`gpt-5.6-sol`. The survival scenario used a probe-owned `codex app-server --listen unix://<tmpdir>/sniper-hg-*/p.sock`,
which speaks WebSocket over the Unix socket.

| Contract item | Verdict | Command | Observed evidence |
|---|---|---|---|
| Subscription identity without API fallback | **PASS** | `codex login status`<br>`account/read {refreshToken:false}`, `account/rateLimits/read` | Status: "Logged in using ChatGPT". `account/read` returns `type:"chatgpt", planType:"pro"` in a clean env, with a placeholder `OPENAI_API_KEY` in the env, and with `-c forced_login_method="chatgpt"`. Credits are `hasCredits:false, balance:"0"` (`codex-identity.json`). The executed turns updated the ChatGPT rate-limit window. Caveat: the auth mode is not reported per turn; an adapter should pin `forced_login_method` and check `account/read` first. |
| Launch idempotency (caller-supplied id) | **FAIL** | two back-to-back `turn/start` with the same `clientUserMessageId` | `ThreadStartParams` has no caller-supplied id. Both calls returned `inProgress` with **different** turn ids. Both user messages were recorded (with the same `clientId`) inside the first turn. The second turn id never received `turn/started` or `turn/completed` within 120 s, and `thread/read` lists one turn (`codex-turn-duplicate.json`). A retried `turn/start` produces a phantom handle. |
| Attach while live | **UNPROVEN** (attach works) | new client: `thread/resume {threadId}` | Reattach succeeds and returns the live turn with its `commandExecution` item (`codex-socket-coordinator-death.json`). Exclusivity against a second live client was not tested. |
| Known host concurrency | **UNPROVEN** | – | No declared concurrent-turn limit. One active turn per thread was observed: the second `turn/start` folded into the active turn. `account/rateLimits` exposes a usage window (10080 min, 75% used), not a concurrency figure. Multi-thread concurrency was not run (budget). |
| Exact child handle | **PASS** with gap | `turn/start` response, `ps` | Thread id plus turn id (UUIDv7), and the app-server PID (a Node wrapper plus the native server child). **Gap:** `commandExecution.processId` (`"41778"`) is a unified-exec PTY session id, not an OS PID. The real `sleep 302` was a direct child of the native server in its own PGID (`codex-interrupt.json`). |
| Event replay after disconnect | **PASS** (state, not missed notifications) | fresh client: `thread/read {includeTurns:true}`, `thread/resume` | After coordinator death a fresh app-server reads the persisted turn and its status (`codex-coordinator-death.json`). With the surviving socket server, the reattached client saw the turn `inProgress` and, through resume, its in-flight `commandExecution`, then received later notifications (`tokenUsage`, `turn/completed`). Notifications emitted while no client was connected are not re-sent. `thread/read` omitted the in-flight command item that resume showed. |
| Interrupt followed by terminal confirmation | **PASS** | `turn/interrupt {threadId, turnId}` | The reply `{}` arrived after 9 ms and `turn/completed` `status:"interrupted"` 1 ms later. `thread/read` confirms `interrupted` (`codex-interrupt.json`). From the reattached socket client: `{}` after 7 ms, then `turn/completed` interrupted. |
| Tool cleanup, cooperative interrupt | **FAIL** | same, then track the exact `sleep` identity | The unified-exec `sleep 302` **survived** the interrupt for 15 s with no `commandExecution` `item/completed`; the probe removed it. In the socket run the interrupted turn's `sleep 93` ran to its natural end, about 48 s after the interrupt, and a `terminalInteraction` notification still arrived 12.4 s after the interrupt. |
| Tool cleanup when the host process ends | **UNPROVEN** (SIGKILL) | – | SIGKILL of the app-server was not tested. When the stdio server shut itself down on client EOF, the tool was already gone at the first sample (`codex-coordinator-death.json`). |
| Nested subagent cleanup | **UNPROVEN** | not run | `multi_agent` children were not exercised. |
| Coordinator death, restart delayed past deadline | **FAIL** (no expiry) | coordinator `SIGKILL`s itself mid-tool; deadline 20 s, restart 45 s | **stdio:** the app-server exited 1.13 s after the coordinator died, the tool was gone, and the turn was persisted as `interrupted`. This is fail-stop: no runaway, but no continuation either. **Probe-owned socket server:** the turn and its tool were still running at 20.9 s and 45.2 s. Reattach plus interrupt at 45 s produced a terminal state, but the tool kept running to its end. `TurnStartParams` has no expiry field. |
| Separated usage attribution | **PASS** | `thread/tokenUsage/updated` | Keyed by `threadId` and `turnId`, with `last` and `total` breakdowns. The interrupted turn reported input 16646, cached 0, output 121, reasoning 0; `cachedInputTokens` is a subset field (`codex-interrupt.json`). |

## §6 decision

- **Claude Code: unsupported for unattended AI deadlines on this Mac.** It fails subscription
  identity (the standalone CLI's OAuth session has expired), so no subscription turn can run. Even
  signed in:
  - `--resume` is not exclusive while a turn is live.
  - An orphaned child keeps working and calling the model after its coordinator dies, and nothing
    in the host expires it.
  - Tool process groups leak when the CLI is killed.

  What works: the stdin control-protocol interrupt, with terminal confirmation and tool cleanup,
  while the coordinator is alive. That supports only a bounded supervised mode.
- **Codex: unsupported for unattended AI deadlines.** Identity, terminal interrupt, per-turn usage
  and reattach/replay through a surviving socket server all hold. But:
  - `turn/interrupt` does not remove the turn's unified-exec processes.
  - Launch is not idempotent, and a retried `turn/start` returns a phantom turn id.
  - There is no expiry field.
  - Concurrency limits are unknown.

  Codex is the closer candidate. A Codex adapter would additionally need Sniper to terminate
  unified-exec descendants of an app-server it owns, by exact identity. That is a new product
  decision, not an implementation detail.
- **Must be reported as unsupported,** in the A1 `host_contract.py` capability record and to the
  operator:
  - Absolute AI expiry, for both hosts.
  - Enrolment of the already-running director: the operator's conversation is the desktop-hosted
    session, and a launched child cannot join or govern it.
  - Exactly-once launch (Codex).
  - Exclusive attach (Claude).
  - Tool cleanup after interrupt (Codex) and after host death (Claude).
  - Host concurrency limits (both).
  - Terminal-result replay after disconnect (Claude).
  - Standalone Claude subscription identity on this machine, until the operator re-logs in.

## Findings other units must handle

- **Clean environment is mandatory.** An inherited `ANTHROPIC_API_KEY` silently switches Claude to
  API billing (`apiKeySource` shows it). Inherited host-session variables would bind a child to the
  running desktop session.
- **Terminal state must be read from events, not status fields or exit codes.** On auth failure
  Claude's `result.subtype` is `"success"` with `is_error:true`, and an interrupted `claude -p`
  exits 0 after SIGINT. Read `is_error`/`terminal_reason`, or the Codex `turn.status`.
- **Model version mismatch.** The operator's Codex config selects `gpt-6-astra` with effort
  `xhigh`. The installed 0.144.1 fails that model with HTTP 400 "requires a newer version of
  Codex", and the thread goes to `systemError`. Pin a model from the running CLI's own `model/list`,
  or require CLI/app parity.
- **Detach the server.** A Codex app-server exits when its stdin closes. That held for the stdio
  server and for the plumbing check of a Unix-socket server launched with a stdin pipe. Unix socket
  paths must fit `SUN_LEN`.
- **Unexpected helpers.** Codex app-servers start `node_repl` (from ChatGPT.app) and
  `codex-code-mode-host` helpers even with plugins and apps disabled. They exited with the server.
- **A6 usage linkage.** Claude reports usage once per invocation (`result`). Codex reports
  per-turn `last` and thread `total`. Both are subsets of what the §5 reservation needs; missing
  usage must stay `unknown`.

## Not done / limits

- No real Claude model turn ran. Every Claude mechanics result comes from the loopback stub, and
  the Claude subscription path is unverified until the operator signs the CLI in.
- The following were not tested:
  - Concurrency limits, subagent (Task, `multi_agent`) cleanup and usage separation.
  - SIGKILL of a Codex app-server.
  - Codex attach exclusivity.
  - Claude `--bg` / `claude agents`, which would register a session in the operator's agent list.
  - The desktop-bundled CLI builds.
- `codex-turn-duplicate.json` was captured before the harness pinned `model/list`'s default, so it
  records the operator's configured model failing. Its duplicate-submission finding still stands:
  both messages were accepted and the second turn id never completed.
- The two stdio coordinator-death records name the restart result `replay`; later records call it
  `action`.
- `claude-session-binding.json` and `codex-socket-coordinator-death.json` were re-run through the
  path neutralizer after capture. Only path strings changed.

## Rerun

From `scripts/producer`, using a scratch directory and **spending real Codex turns** for the
`codex-turn-*`, `codex-interrupt` and `*coordinator-death` Codex scenarios:

```
../../.venv/bin/python3 -B -m studio.production.host_conformance.run_gate \
  --work <scratch>/work --out <evidence-dir> host-status claude-session-binding codex-interrupt …
```

Scenarios:

- `host-status`
- `claude-identity-no-key`, `claude-session-binding`, `claude-control-interrupt`
- `claude-signal-sigint`, `claude-signal-sigkill`
- `claude-coordinator-death`, `claude-resume-while-live`
- `codex-identity`, `codex-turn-duplicate`, `codex-interrupt`
- `codex-coordinator-death`, `codex-socket-coordinator-death`

Unit tests (no host, loopback only): `PYTHONPATH=.:tests python3 -B -m unittest test_host_conformance`.
