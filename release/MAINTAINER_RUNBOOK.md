# Maintainer release runbook

Everything in this file is a command you run or a decision you record. It is for the
person cutting a release, not for a buyer. Nothing here is in the buyer package.

## 0. Before you start: the tree must be quiet

The release source is a **snapshot**. If another session is editing `PROJECT_SNIPER`
while you cut a release, the candidate is superseded before it is built — this happened
on 2026-09-17: a `sniper-context` skill (four new Python files, a doc, two skill files,
a command and edits to `AGENTS.md`, `CLAUDE.md`, `README.md` and
`scripts/tests/skill_surface.test.mjs`) landed 40 minutes after the snapshot was taken.

```bash
cd PROJECT_SNIPER
git status --porcelain | wc -l          # record it
git rev-parse HEAD                      # record it
```

Confirm with whoever else is working in the tree that it is quiescent. Then re-check the
dirty count at the end of the build and confirm it has not moved.

## 1. Cut an isolated release source

Never build from the working folder. Take a recorded snapshot instead:

```bash
REL=/path/to/release-src
mkdir -p "$REL"
cd PROJECT_SNIPER
git archive HEAD | tar -x -C "$REL"            # tracked files at HEAD
git diff HEAD --binary > /tmp/working.patch    # the uncommitted work; does not touch the index
( cd "$REL" && git init -q . && git apply /tmp/working.patch )
```

Then copy the **untracked** product files. `git status --porcelain | grep '^??'` lists
them. Two traps:

- Untracked is not the same as gitignored. `scripts/producer/artifacts/` is gitignored
  and holds retained acceptance evidence that several tests read. Copy it into the
  release source so the suites can run; the package builder withholds it anyway.
- A whole feature can live in untracked files. On 2026-09-17 the entire native long-form
  export lane was untracked. Archiving HEAD alone would have shipped a product without
  it.

Record the baseline in `release/SOURCE.json`: upstream HEAD, the release-source commit,
the SHA-256 of the working patch, the count of untracked entries included, and anything
deliberately excluded with its reason.

## 2. Install both dependency roots and the venv

```bash
cd "$REL"           && npm ci --no-audit --no-fund
cd "$REL/templates/motion" && npm ci --no-audit --no-fund
cd "$REL" && python3 -m venv .venv \
  && ./.venv/bin/pip install -r release/payload_files/install/requirements.lock.txt
```

Use the **lock**, not `requirements.txt`. `requirements.txt` pins almost nothing; a
fresh resolve on 2026-09-17 produced a different set from the working venv, including
`anthropic` 0.117.0 → 1.6.0.

To bump the lock deliberately: install from `requirements.txt`, run both suites, and
only then regenerate the lock with `pip freeze | sort`.

## 3. Remove the maintainer's identity from the source

```bash
cd "$REL" && ./.venv/bin/python3 -m release.redact_paths
./.venv/bin/python3 -m release.redact_paths --check    # must report 0
```

Recorded calibration contracts under `docs/producer/command-driven-editing/contracts/`
are **read by code** (`baseline_repeat_validation.py`,
`current_system_inventory_check.py`), so they cannot simply be withheld. Redaction
rewrites the path text and leaves every hash intact. **Run both suites afterwards** —
they, not the tool, establish that nothing broke.

## 4. Run the checks and record the output

```bash
cd "$REL"
npm run type-check
npm run lint
npm test
cd scripts/producer && PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py
```

`npm test` aborts at the first failing TS file, so a single stale expectation hides the
state of the rest. To see the real picture, run every file and continue past failures
(see `release/QUALIFICATION_REPORT.md` for the measured numbers). Do **not** change the
suite to make it continue; run the loop separately.

Classify every failure into one of three buckets and record which:

| Bucket | How you tell | What you do |
|---|---|---|
| Current runtime defect | fails for a behavioural reason, not a hash comparison | fix it |
| Stale qualification receipt | a retained receipt's recorded closure, digest or toolchain no longer matches the tree | regenerate the receipt **by running the real thing**; never hand-edit it |
| Environmental blocker | a missing gitignored evidence root, an absent optional tool, a timing-sensitive test under suite load | record it and say what it needs |

The cheapest way to separate the first two: run the same test in the live working tree.
If it fails identically there, your release source did not cause it.

## 5. Build the package

```bash
cd "$REL" && ./.venv/bin/python3 -m release.build_package --version X.Y.Z --out ../release-out
```

The build refuses rather than warns. It fails closed on a credential shape, a
maintainer path, a teacher name in a shipped path or text, a third-party creator source
URL, an unsupported claim in the buyer manual, or an allow-listed path that has gone
missing. `--allow-pending-rename` downgrades only the teacher-name rules to a recorded
pending blocker and stamps the release **not sellable**; never use it for a release you
intend to sell.

Then audit the archive as a buyer receives it:

```bash
./.venv/bin/python3 -m release.audit_archive ../release-out/project-sniper-X.Y.Z-mac.zip /tmp/extract
```

## 6. Prove the build is reproducible

```bash
./.venv/bin/python3 -m release.build_package --version X.Y.Z --out ../release-out2
diff ../release-out/file-manifest.json ../release-out2/file-manifest.json
shasum -a 256 ../release-out*/project-sniper-X.Y.Z-mac.zip
```

Both archives must be byte-identical. Entries are sorted, timestamps fixed at
1980-01-01, modes normalised to 0644/0755, and no directory or symlink entries are
written. The only value that legitimately differs between builds is `built_at_utc` in
the **external** manifest.

## 7. Checksums and what goes where

- `RELEASE.json` goes **inside** the archive: version, source commit, platform,
  component versions, and whether the build is sellable with its blockers. It must never
  contain the archive's own hash.
- The archive's SHA-256 is computed **after** assembly and published only outside it, in
  `SHA256SUMS` and `release-manifest.json`.
- `file-manifest.json` and `withheld.json` stay with the maintainer: the first is for
  reproducibility comparison, the second records every withheld path and its reason.

## 8. Release classification and who may receive it

Record the class before uploading anything:

| Class | What it is | Under the selected policy (N1, purchased release only) |
|---|---|---|
| New release | new features or workflows | buyers of the paid support and updates offer |
| Compatibility release | keeps an existing version working against a changed macOS or provider | **not owed to base buyers under N1** — a deliberate, stated consequence |
| Fix release | corrects a defect in a shipped version | same |

N1 means the $97 purchase buys exactly the downloaded version. Two risks are mitigated
by the installer — the buyer's own CLI auto-updating, and Python or Node packages
drifting — because the package installs its own pinned CLIs and installs from the lock.
Two are not, and cannot be under N1: the provider changing its authentication response
or retiring the pinned model, and a major macOS upgrade. Say so rather than discovering
it in a refund request.

## 9. Immutability

One folder per release, never overwritten. A change to the archive's bytes is a **new
candidate**: it gets a new version, a new hash, and it invalidates the old
qualification for the new bytes. "Just fixing the manual" in an already-qualified ZIP
and keeping its approval is exactly the thing not to do.

Keep customer and order records in the restricted commercial system. Never in this
repository and never in the package.

## 10. Rollback

There is no in-place rollback and none is wanted. Each release is a self-contained
folder with its own `runtime/`. To roll back, stop the new one and start the old one.
Both read the same `~/ProjectSniper`, so projects are shared; a project written by a
newer release may carry plan fields an older one does not understand, so copy the
project folder before going back.

## 11. Handing the archive to commercial delivery

Give them exactly this, and nothing inferred:

- the filename, the version, the byte size, the SHA-256 from `SHA256SUMS`
- `RELEASE-NOTES.md`, and the buyer manual's own entry point (`START-HERE.html`)
- the release class and which buyer cohorts it is for
- the acceptance state: which of Z1–Z11 passed, with evidence paths, and which did not

Note for the SamCart route: the digital-file UI shows a **1 GB** upload maximum. The
0.1.0-rc1 archive is 17.9 MB, so the direct-file route fits; the authenticated
Courses/entitlement route in integrations I1 still needs its own probe.

Do not fill a URL until it exists. An expiring link needs a tested renewal procedure,
not a pasted URL.
