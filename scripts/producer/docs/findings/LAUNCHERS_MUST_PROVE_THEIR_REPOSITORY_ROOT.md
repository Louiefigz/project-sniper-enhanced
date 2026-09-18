# Launchers must prove their repository root

## Assertion

A launcher that resolves its own executable correctly can still be unusable if
it derives the application root from the wrong directory depth. Test the
resolved dependency path, not only argument parsing and process supervision.

## The incident

`npm install` completed successfully with **702 packages** present, but
`npm run dev -- --port 3101` still stopped immediately with:

```text
[sniper:supervisor] Next is not installed; run npm install first
```

The supervisor lives at `scripts/infra/next_supervisor.mjs`. Its root used:

```js
path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
```

That resolves to `PROJECT_SNIPER/scripts`, so the launcher looked for:

```text
PROJECT_SNIPER/scripts/node_modules/next/dist/bin/next
```

The installed executable was actually:

```text
PROJECT_SNIPER/node_modules/next/dist/bin/next
```

The argument, heap, restart, lock, and process-group tests all passed because
none asserted the resolved repository root.

## Correction

Resolve both directory levels from `scripts/infra` and expose the calculation
as a testable function:

```js
export function supervisorRoot(moduleUrl = import.meta.url) {
  return path.resolve(
    path.dirname(fileURLToPath(moduleUrl)),
    "..",
    "..",
  );
}
```

The regression test now asserts that `supervisorRoot()` equals the repository
working directory. After the correction, the same server reached
`Ready in 946ms`.

## Principle

For every self-locating launcher, test at least one path that must exist at the
resolved root:

1. derive the root from the launcher's real module location;
2. assert the expected root in a regression test;
3. construct the executable/dependency path from that root;
4. perform the existing existence and identity checks;
5. fail before acquiring long-lived locks or spawning children.

Argument tests cannot catch a wrong filesystem anchor.

## When not to use this approach

- Do not climb a fixed number of parent directories when the launcher is
  intentionally installed independently of the repository. Accept an explicit,
  validated root instead.
- Do not infer the root from the caller's current working directory for a
  launcher that must work from arbitrary directories.
- Do not weaken the dependency check merely because package discovery succeeds
  through Node's upward resolution; the spawned executable should still be the
  intended repository-pinned file.
