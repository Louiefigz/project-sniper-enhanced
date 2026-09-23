# Maintainer runbook — building and checking a Sniper release candidate

This `src/` checkout is the maintained release source. See `../CURRENT.md` for
the source/install status. Earlier working copies are historical; installations
are generated from this source and must not receive direct engine patches.
Tooling lives in `release/`, which is never shipped.

## Build
```
./sniper python3 -m release.build_package --version 0.1.0-rc4 --out <dir>
```
- Refuses to run from a checkout with uncommitted changes, and records the built commit from git in
  `release-manifest.json`.
- Refuses to write an archive when the staged tree fails inspection: secrets, developer paths, teacher or creator
  names, restricted buyer claims.
- Writes the archive, `SHA256SUMS`, and the release, file and withheld manifests.
- Build twice and compare `SHA256SUMS`; the archive is deterministic.

## Audit a fresh extraction (Z1)
```
./sniper python3 -m release.audit_archive <zip> "<new folder with a space and ü>"
```
Beyond the archive's shape, it checks what the running app needs, using the package's own code:
- Auto Edit's required files, prefixes and source paths, parsed from `auto-edit-pipeline-assets.ts`;
- data files reached by path segments;
- every composition's local sources;
- that the composition capability matrix is fresh for the shipped tree.

## Install and exercise (developer Mac)
```
env -i HOME=<empty dir> USER=$USER TERM=xterm PATH=/usr/bin:/bin:/usr/sbin:/sbin ./install/install.command --provider codex
```
The harnesses used for R1, R5, R7 and the suites are in `evidence/scripts/`. Run
in-package test modules with the install's own settings loaded (`set -a; . runtime/sniper.env; set +a`) and with
`TMPDIR` set. Without `TMPDIR`, Leptonica rewrites `/tmp` paths and OCR tests fail.

## Things that go stale after source edits (regenerate with their own tools, never by hand)
- `templates/motion/comp_capabilities.json` — run
  `./sniper python3 scripts/producer/graphics/comp_capability_native.py --out <new-evidence-dir> --publish`.
  It runs all current compatibility ports under the shared native resource owner,
  keeps real render/decode/alpha measurements and publishes only a complete fresh
  matrix. Its 30fps scope does not qualify the separate multi-rate matrix.
- `src/lib/producer/__tests__/fixtures/auto-edit-authority-golden.json` —
  `./sniper env SNIPER_UPDATE_AUTHORITY_GOLDEN=1 node --import tsx src/lib/producer/__tests__/auto-edit-authority-cross-language.test.ts`,
  which writes only after TypeScript/Python parity passes.
- Retained qualification receipts — each `scripts/producer/tests/live_*_acceptance.py --artifact …`
  (see `evidence/59-defect-fixes.md`).
- `src/lib/server/guided-source-color-cleanup-pins.ts` — the list the pin test computes from the import graph.
- `assets/music/default-bed.mp3` — `scripts/producer/audio/default_bed.py`, which is deterministic.
- Native media runtime approval and adapted SDK receipts must match the actual
  packaged runtime. Docker image receipts are historical and are not the current
  install or qualification route.

## Commercial record
New ledger rows go into `build/ledger.md`. Run the five check tools in a copy of `research/maria-wendt` first:
they write `evidence/*-rev<N>.txt` and would overwrite the current revision's reports.

## Historical rc3 snapshot recovery
`rc3-release-checkout.bundle` beside this file holds its full history: the snapshot commit `8534d9c` through
`f82088a`. Restore it with `git clone rc3-release-checkout.bundle rc3-src`. Build tooling and the venv are
recreated as in the steps above (`npm ci` at the root and in `templates/motion`, and a venv from
`release/payload_files/install/requirements.lock.txt`).
This restores historical evidence, not the current maintained source or release.
