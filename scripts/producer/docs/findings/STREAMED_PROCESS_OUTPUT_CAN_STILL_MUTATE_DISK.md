# Streamed process output can still mutate disk

## Assertion

An API route that only streams a child process's stdout can still create
durable files. Inventory the callee's default output behavior, not only the
route's JavaScript filesystem calls.

## The incident

`src/app/api/frameio-review/review/route.ts` launches
`scripts/frameio/review.py` and forwards NDJSON as server-sent events. The
route passes `--input` and review settings but does not pass `--out-dir`.
Looking only at the TypeScript route makes this appear to be a read/stream
boundary.

The Python callee chooses this default:

```python
out_dir = os.path.abspath(args.out_dir) if args.out_dir else os.path.dirname(input_path)
results_path = os.path.join(out_dir, "results.json")
report_path = os.path.join(out_dir, "report.html")
```

It then overwrites both files. A web review therefore writes two fixed-name,
mutable sidecars beside caller-selected media. Two different videos in the
same directory compete for the same output names.

## Evidence

- The route's process audit contributes one child-process boundary.
- The callee writes `results.json` and `report.html`.
- The route never supplies `--out-dir`, so the selected media's parent is the
  effective output root.
- Extracted frames use `<system-temp>/frameio-<source-path|size|mtime|fps>`
  and are swept after one hour; those frames are cache, while the two sidecars
  persist.

The P0 inventory now binds the route and callee to the
`frameio-review-report` family instead of classifying the process as unknown.

## The principle

For every spawned tool, record:

1. executable and fixed/caller-supplied arguments;
2. effective input roots;
3. explicit and default output roots;
4. stdout/stderr versus durable outputs;
5. overwrite, cleanup, and promotion behavior.

Prefer an explicit revision-scoped `--out-dir`, source SHA-256 in the artifact
identity, create-then-rename publication, and a receipt binding the report to
the exact media and model configuration.

## When not to use this approach

Source-adjacent fixed names can be acceptable for a one-off local CLI when the
operator explicitly requests replaceable sidecars and no project revision,
automation run, or concurrent review consumes them as authority. They are not
appropriate as implicit web-route outputs or durable QC evidence.
