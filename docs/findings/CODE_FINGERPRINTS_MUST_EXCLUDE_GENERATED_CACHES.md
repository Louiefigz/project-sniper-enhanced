# Code fingerprints must exclude generated caches

During the September 14, 2026 commit checks, the full application regression
run spent substantial time in legacy authority tests. The newer pipeline
capture excluded `artifacts` and `.sniper-native-runtime`, but the older
TypeScript and Python live-file walkers did not. They treated generated PNGs
and JSON receipts inside those directories as implementation inputs.

This creates two problems: verification reads unrelated generated media, and a
new render can change the supposed code fingerprint without any source change.
Ignoring files in Git does not exclude them from a custom filesystem walker.

The correction adds both directory exclusions to
`src/lib/server/auto-edit-authority-snapshot.ts` and
`scripts/producer/palmier/quality_hash.py`. It matches the existing exclusions
in the newer `auto-edit-pipeline-assets.ts` capture. Saved pinned snapshots
continue to verify their recorded files; this does not rewrite old receipts.

The regression creates a small disposable repository, takes both runtimes'
complete authority snapshots, adds a generated PNG and a generated JSON file,
and requires unchanged snapshots. It then changes a real Python source file
and requires changed, matching fingerprints. Both tests in
`native-pipeline-cache-exclusion.test.ts` passed in 403.8 ms, including the
existing current-repository capture check. That is test execution time, not a
before/after production benchmark.

Exclude only known output stores. Authored templates, implementation patches,
contracts, and required models still belong in the relevant source/asset
identity. Do not broadly ignore images or JSON, since both can be authored
inputs. Keep TypeScript and Python behavior covered by the same parity test.
