# Empty environments do not seal renderers

## Finding

Deleting obvious API-key variables before launching a renderer is necessary but
not sufficient. Runtime code can repopulate state from its working directory,
OS account directory, executable search path, browser cache, or localhost.

HyperFrames 0.7.33 provided concrete examples during Project Sniper's G2 proof:

- before command dispatch, it unconditionally attempts to parse
  `process.cwd()/.env` and fills any missing environment keys;
- telemetry/config, registry cache, browser discovery, and credentials have
  account-directory fallbacks;
- ffmpeg, ffprobe, Node through the CLI shebang, and the browser can fall back to
  mutable path/cache discovery;
- the render file server binds a random loopback port, while Puppeteer uses a
  second random TCP CDP port.

The production adapter now uses an isolated working directory, exact absolute
Node/CLI-module/browser/ffmpeg/ffprobe paths, task-specific cache/config roots,
closed stdin, deterministic flags, and telemetry/update/download denial. A
checked-in Node preload also redirects both CommonJS and ESM `os.homedir()` to
attempt scratch without changing the process's standard account variable.

That still does not seal non-Node descendants or localhost. A macOS Seatbelt
profile allowing all localhost let the renderer run but could reach ambient host
services. A profile allowing one fixed test port denied a decoy port, but stock
HyperFrames could not use it because both required ports are random. Passing
decode and pixel oracles therefore did not advance G2.

## Rule

Seal all discovery channels, not only the environment:

```text
bytes + argv + environment + cwd + account/config view + filesystem mounts
+ executable resolution + process tree + network namespace + loopback peers
```

For this renderer, the clean product boundary is an attempt-exclusive container
started directly by the trusted controller from an immutable image digest with
`--pull=never --network none --read-only`, a fixed nonroot user, dropped
capabilities, no-new-privileges, bounded tmpfs, frozen read-only inputs, and only
attempt-owned writable mounts. Container loopback remains available to the two
random renderer sockets, while host localhost and external networks disappear.

Do not use HyperFrames' bundled Docker helper for this proof. Its current path
does not enforce `--network none`, immutable images, read-only root, privilege
drops, or the complete telemetry policy, and its sample image resolves mutable
base/apt/browser/npm inputs.

## When not to use this approach

A full container is unnecessary for a pure in-process transform whose complete
dependency graph and system calls are already controlled. It is also not a
substitute for content hashes, media oracles, or admission evidence. If a
renderer exposes first-class fixed ports and pipe-based CDP, a smaller proven OS
sandbox may be adequate; avoid monkeypatching third-party networking internals
unless that fork becomes an explicitly versioned, tested runtime product.
