# Provider capabilities must be probed end to end

## Finding

A local CLI accepting a model or reasoning value does not prove the remote model
build accepts it. Provider aliases can rotate to a build with a narrower runtime
contract while the client-side enum and preflight keep passing.

On 2026-07-18, Project Sniper configured:

```text
model = gpt-5.6-sol
reasoning = ultra
codex-cli = 0.144.1
```

The local `features list`/login preflight passed, but a tools-disabled live call
failed before inference with HTTP 400. The provider revealed the resolved build
as `gpt-5.6-sol-1p-codexswic-ev3` and allowed only:

```text
none, low, medium, high, xhigh
```

Changing only the probe effort to `none` completed in 6.4 seconds. Its terminal
event reported 8,164 input tokens, 0 cached input tokens, 9 output tokens, and 0
reasoning-output tokens. It still exposed no cost, cache-creation counter, or
resolved model/build identity on the successful JSONL event.

Claude showed a related reason not to collapse one requested model into one
actual model. A tools-disabled `--model opus` probe used both
`claude-opus-4-8` and `claude-haiku-4-5-20251001`; the result attributed tokens
and provider-reported estimated cost to each model separately.

## Rule

Before admitting work, probe the complete tuple that will execute:

```text
CLI build × requested alias × resolved model signal × effort × event schema
```

Keep client syntax/auth checks as cheap diagnostics, but never treat them as a
runtime-capability gate. The real probe must use the production argv policy,
disable tools and side effects, retain failed calls in evidence, and assert the
required telemetry fields. Reassert observable model/schema identity on every
measured call because one successful probe does not freeze an alias.

## When not to use this approach

Do not place a paid live probe on every interactive request when the provider
offers an immutable build contract or a cached capability receipt with an
observable rotation signal. Reuse that receipt until its frozen expiry or the
signal changes. Never infer capability from latency, a login check, or a local
configuration parser alone.
