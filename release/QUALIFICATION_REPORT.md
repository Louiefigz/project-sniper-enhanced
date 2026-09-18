# Qualification report — project-sniper-0.1.0-rc2

Built 2026-09-17 from the isolated release source recorded in `release/SOURCE.json`.

**Verdict: NOT QUALIFIED FOR SALE.** A real, reproducible, inspected archive now exists
where none did before, and the installation path is designed and partly proven. What is
missing is not paperwork: clean-machine installation, both-provider edits, full-length
and Short output with playback, Studio round-trip, the outside-operator run and
authenticated delivery have **not** been performed. Two provenance blockers and one
identifier migration also stand between this candidate and a sellable one, and one of the
provenance blockers is a component whose own text forbids redistributing it.

Every row below cites a command that was run and an output saved under `evidence/`.
Where something was not run, the row says so and does not imply a result.

## The archive

| | |
|---|---|
| File | `project-sniper-0.1.0-rc2-mac.zip` |
| Size | 17,044,225 bytes (17.0 MB) |
| SHA-256 | `e5f10b499276d39c3f3b05b56cf214acb639d4a7495a2c4afefa7a4abd64c78b` |
| Entries | 5,049 files under one top-level folder |
| Upstream source | HEAD `8ebcdfc4e37a4503082cbc64839752bf241f4a08` plus the working tree as of 2026-09-17 14:06 local |
| Sellable | **false** — recorded inside `RELEASE.json` with its blockers |

The hash above is the archive's own and is published only **outside** it, in `SHA256SUMS`
and `release-manifest.json`. `RELEASE.json` inside the archive deliberately contains no
self-referential hash.

An earlier candidate, `0.1.0-rc1` (17,865,038 bytes, `15e620c2…7579`, 5,126 entries), was
built before the provenance withholdings and the maintainer-path redaction. Changing the
bytes produced a new hash and a new candidate number, which is the rule working rather
than an accident: rc1's qualification does not transfer to rc2's bytes.

## Acceptance matrix Z1–Z11

| ID | Result | Evidence and what it does not show |
|---|---|---|
| **Z1** Archive and dependency closure | **PASS** | `release/audit_archive.py` on a fresh `unzip` of the final candidate: **69 checks passed, 0 failed, exit 0** (`evidence/26-z1-final.log`). One top-level folder; no symlinks; no path escaping it; `.env`, `.git`, `node_modules`, `.venv`, `.next*`, `artifacts/`, `.sniper-*`, `.DS_Store`, `.mcp.json`, `*.pyc` and `vendor/hyperframes-skills/` all absent; every required agent, runtime, installer and manual file present, including all ten `SKILL.md` files across both `.claude` and `.agents`; the render runtime's patch set is present and its `sdkVersion` matches the pinned lockfile. The first run of this audit (`evidence/21-z1-archive-audit.log`) surfaced two real defects, both then fixed: `app/AGENTS.md` linked to a parent repository the buyer never receives, and the maintainer's home path appeared in 25 staged files. Does not show that the extracted tree installs or runs. |
| **Z2** Installation | **NOT RUN on a clean Mac.** Partial evidence only | On the developer Mac: `npm ci` root 727 packages exit 0 in 6.7 s (`evidence/02`); `npm ci` `templates/motion` 138 packages exit 0 in 1.8 s, 371 MB (`evidence/03`); `python3 -m venv` + pinned install exit 0 in 12.9 s (`evidence/04`). App-local pinned CLI provisioning verified: `@openai/codex@0.144.1` and `@anthropic-ai/claude-code@2.1.247` installed into a package-local prefix report **exactly** `codex-cli 0.144.1` and `2.1.247 (Claude Code)`, the two strings the admission policy demands, in ~6 s and 520 MB (`evidence/11`). **The installer script itself has not been executed end to end on any machine**, and this machine is a developer Mac with Homebrew, four cached browsers and both CLIs already present, so it cannot satisfy Z2 by definition. |
| **Z3** Both providers | **NOT RUN.** No provider-authenticated edit was performed for either route. Neither route may be inferred from the other. |
| **Z4** Long-form | **NOT RUN.** No 16:9 educational edit was produced or reviewed. |
| **Z5** Shorts | **NOT RUN.** No Short was produced from fresh footage. |
| **Z6** Delivered-video and Studio review | **NOT RUN.** No export was played, and no Studio project was opened, edited, synced, reopened or rebuilt. |
| **Z7** Included secondary tools | **NOT RUN** as an exercise. Their contracts are covered by the automated suites (Segmenter stream-copy and Clipper frame-accuracy invariants have dedicated tests), but no buyer-shaped run happened. `separate` is correctly reported **gated** because Demucs is absent; Frame Review is correctly reported as needing the buyer's own paid API key. |
| **Z8** Recovery and lifecycle | **PARTIAL.** The mechanisms are implemented and the resume/port/cleanup/uninstall paths are written and syntax-checked (`bash -n` on all seven `.command` files plus `common.sh`). **No interruption, port conflict, resume, update, rollback or uninstall was actually exercised.** |
| **Z9** Manual and provenance | **PARTIAL PASS.** All ten manual pages exist and are scanned at build time: the build fails closed on "first edit in minutes", "student-kit", "hands-off", "nothing leaves your computer", the "only the text is sent" privacy claim, a teacher name, a developer path or an unresolved `{PLACEHOLDER}`. Third-party notices are complete for every shipped component, with the Apache-2.0 text fetched from source. **Not done:** a buyer read-through following the instructions from the extracted archive, and three components remain uncleared (`PROVENANCE-BLOCKERS.md` B3, B4, and B1 which is withheld). |
| **Z10** Outside operator | **BLOCKED_INPUT.** No second operator and no clean supported Mac. The protocol itself was strengthened to revision 18 by the commercial session and now requires both providers, a full-length edit, a Short, a correction and Studio persistence. Materials a candidate needs are prepared; the run is not. |
| **Z11** Delivery and updates | **BLOCKED_CAPABILITY.** Hash and size are recorded. Authenticated delivery of these exact bytes has not been tested. One useful new constraint: the SamCart digital-file UI shows a **1 GB** maximum, and this archive is 17.0 MB, so the direct-file route fits comfortably; the Courses/entitlement route still needs its own probe. |

## Test suites — what actually ran

### Python engine (`selftest.py`)

```
Ran 7584 tests in 1938.337s
FAILED (failures=8, errors=4, skipped=16)
```

`evidence/05-selftest-baseline.log`. **Twelve failures. Zero of them introduced by this
work.** Classified by re-running each one in the live working tree
(`evidence/08-failure-classification-aarons-tree.log`):

| Test | Live tree | Class |
|---|---|---|
| `test_p5_compositor_artifact` | fails identically | stale receipt: recorded source closure no longer matches the tree |
| `test_p4_exit_closure_artifact` | fails identically | stale receipt: same |
| `test_p0_adversarial_ingress_artifact` | fails identically | stale receipt: same |
| `test_p2_row1_claim_artifact` | fails identically | stale receipt: same |
| `test_p5_review_repair_artifact` | fails identically | stale receipt: recorded toolchain pins `chrome-headless-shell` 152.0.7928.2; the machine now resolves 152.0.7977.30 |
| `test_comp_rate_matrix` | fails identically | stale receipt: "rate matrix sourceDigest is stale or malformed" |
| `test_learning_loop` | fails identically | stale receipt: `LESSON-048` ordering |
| `test_current_system_inventory_check` | fails identically | stale receipt: measured baselines not closed |
| `test_p0_render_effect_parity_artifact` | fails identically | stale receipt: retained parity evidence root unavailable |
| `test_private_graphics_audit_reference` | fails identically | **current runtime defect**: "source-float assembly full Audit B failed" — a real assembly runs and its own Audit B rejects the result |
| `test_p2_visual_lip_sync_artifact` | **passes** | snapshot drift: the retained receipt in the gitignored `scripts/producer/artifacts/` was regenerated against a newer implementation closure than this snapshot. Exactly two leaves differ — `positiveReceipt.implementationClosureHash` and the derived `acceptanceHash` — out of 126 |
| `test_grade_observation_policy` | passes | flaky under suite load: a real-daemon cleanup deadline. Passes 3/3 standalone in the release checkout (`evidence/09-flakiness-recheck.log`) |

**Nine stale receipts, one real runtime defect, one snapshot-drift artefact, one
load-dependent flake.** No test was deleted, skipped or weakened, and no receipt was
regenerated by hand. Regenerating them legitimately means running the real render and
media exercises that produced them, which needs the render-capable exercises listed under
Z4–Z6.

### TypeScript (`npm test`)

```
next_supervisor.test.mjs       all assertions passed
skill_surface.test.mjs         all assertions passed
test:sdk                       14 tests, 14 pass, 0 fail
test:native                    144 tests, 144 pass, 0 fail (+2, +16 in adjacent blocks)
TS loop                        14 files passed, then ABORTED
```

**A finding worth more than the failure itself:** `npm test` runs the TS files in a
`for … || exit 1` loop, so the first failure stops everything after it. The first failure
is `src/lib/producer/__tests__/auto-edit-authority-cross-language.test.ts`, which is 15th
alphabetically. **`npm test` therefore reaches 14 of 476 TS test files — about 3% — and
the state of the other 462 is invisible.** The repository's own instruction that "two
test suites, both must stay green" is not currently achievable, and a single stale digest
is hiding the rest.

That failure is also pre-existing: it produces **byte-identical** digests in the live
working tree — actual `0a3659436db201f48721c7a9a7eaee6c13083329adf724d3cd909f2fdfaf816f`
versus expected `c20b8bbb31b492a2a0f96862833e5a83a292d3969880c6a433b4791c05b90da4`
(`evidence/13-crosslang-in-aarons-tree.log`). It is a stale stored pipeline digest, not a
parity break between the TypeScript and Python authority code.

Every TS file was then run individually, continuing past failures, without modifying the
suite (`evidence/14-ts-suite-full.log`, 2 h 22 m):

```
TS test files: pass=456 fail=20 total=476
```

**All 20 classified, none introduced by this work:**

| Count | Tests | Class |
|---|---|---|
| 18 | `native-*` and `guided-native-*` | **blocker B7**: they load the Director catalog from the sibling `youtube-automation/rag-system`. `ENOENT … lstat '<parent>/youtube-automation'`. Proven: they pass in the live tree where the sibling exists, and pass in the isolated checkout when `SNIPER_RAG_ROOT` points at it (`evidence/15-sibling-repo-dependency.log`) |
| 1 | `auto-edit-authority-cross-language` | pre-existing stale pipeline digest; byte-identical failure in the live tree |
| 1 | `guided-source-color-pipeline-pins` | pre-existing stale pin expectation; fails in the live tree too |

So the environment those 18 tests need is one a buyer may not be given — the failure is
environmental **and** the environment is itself a release blocker.

### Other checks

| Check | Result |
|---|---|
| `npm run type-check` | exit 0 (`evidence/06`) |
| `npm run lint` | exit 0 — 41 warnings, 0 errors (`evidence/07`) |
| Deterministic build | **two builds byte-identical**, for both candidates: rc1 `15e620c2…7579` and rc2 `e5f10b49…c78b`; file manifests identical entry for entry; only `built_at_utc` in the external manifest differs (`evidence/20-determinism.log`, `evidence/25-final-build.log`) |
| Post-redaction re-run | `selftest.py` again: **7,584 tests, failures=9 errors=3 — the same 12 tests**, with `test_p2_visual_lip_sync_artifact` moving ERROR→FAIL only because the gitignored evidence root was restored. Each of the 12 re-checked individually (`evidence/27-post-redaction-failure-set.log`). `type-check` and `lint` still exit 0. **No new failure from redacting 28,648 path occurrences across 136 files.** |
| Defect repaired | `scripts/producer/tests/test_render_layout_contract.py` had `ROOT` hardcoded to an absolute path, so in any other checkout it silently read a **different** tree. Made relative to the checkout under test: **19 tests recovered** (0 → 19 passing). Two opt-in harnesses (`test_layout_observer.mjs`, `studio_native_ui_regression.cjs`) had the same class of literal and now resolve from their own location and from `HYPERFRAMES_BROWSER_PATH`. |

## What this work changed in the product

| Change | Why it was needed |
|---|---|
| Pinned `requirements.lock.txt`, installed instead of `requirements.txt` | `requirements.txt` pins almost nothing. A fresh resolve produced a different set from the working venv, including `anthropic` **0.117.0 → 1.6.0**, plus `deepgram-sdk`, `opencv-python-headless`, `numpy` and `scipy` drift. A buyer installing next month would have got a third set. |
| Installer provisions `chrome-headless-shell` 152.0.7977.30 into the package and pins `HYPERFRAMES_BROWSER_PATH` | `render_tools.py:73-91` globs two user caches and **raises rather than downloading** during a render. This machine has four cached builds totalling 1.8 GB; a clean Mac has none. A render succeeding here proved nothing. |
| Installer provisions both provider CLIs at their exact admitted versions into the package, with their own config dirs and the auto-updater disabled | `subscription-invocation.ts:50` compares the CLI's `--version` output by **exact string equality**. Any auto-update to the buyer's own CLI breaks Sniper. Verified: the app-local npm installs report the exact required strings. This also materially reduces the risk of the selected N1 "purchased release only" update policy. |
| Install path validated against `,` `'` `:` `\` | `audio_enhance.py:61-67` refuses to build the `voice-rnn` filtergraph when the models directory contains those characters, and tells the operator to move the repository. The installer now refuses up front with the reason, and the doctor re-checks it. |
| A doctor that calls the product's own resolvers | Anything else drifts. It imports `graphics.render_tools.resolve_tools`, `local_whisper.resolve_whisper_binary/model` and `studio.native_runtime.install_runtime`, so it reports what a render would really use, and reports optional features as available/gated/needs-key rather than advertising them. |
| A ten-page offline manual, with the privacy page corrected | See below. |
| Package builder that fails closed | Credential shapes, maintainer paths, teacher names in paths or text, third-party creator source URLs, unsupported buyer claims and missing allow-listed paths all refuse the build rather than warn. |

## Input T settled against the code: the privacy claim was wrong

The shipped FAQ said only text leaves the machine. **It does not.** During the rendered
visual review, still frames extracted from the candidate video are sent to the selected
provider:

- Codex receives them as image attachments — `src/app/api/_lib/codex-cli.ts:131-133`
  pushes `--image <path>` for up to 12 controller-owned absolute paths.
- Claude is given the frame paths and instructed to look at them —
  `src/app/api/producer/auto-edit/rendered-review-prompt.ts:51-55` lists every frame and
  says "Inspect EVERY listed frame visually", with the `Read` tool granted
  (`brain-review-process.ts:14`).
- The reference-proposal route may additionally send reference stills
  (`src/lib/server/guided-proposal-compiler.ts:148-151`).

The correct statement, now in the manual: the video never leaves; transcription is local;
the transcript and plan text go to the provider; **and selected still frames of the
rendered result go to the provider too.** Frame Review and Deepgram are separate,
explicit, key-gated egress paths.

## Blockers, in the order they must be cleared

1. **Provenance B1 — the Shorts and long-form reference libraries** cannot ship: they are
   built from three named creators' copyrighted videos, complete with source URLs, hashes
   of downloaded copies and embedded extracted frames. They are also a **runtime
   dependency** of the native Short request path, so withholding them blocks that path.
   Three concrete options in `PROVENANCE-BLOCKERS.md`.
2. **Identifier migration B2** — 147 shipped files and 17 filenames carry teacher names,
   and the identifiers are written into saved project state. Full specification, mapping
   and ordered migration with a reader-side compatibility step in `RENAME_SPEC.md`.
3. **B3 YuNet model licence** and **B4 the music bed** (withheld) — small, but both need
   an answer before sale.
4. **Owner decisions** still open: final licence wording, the support route and response
   commitment, the supported-platform boundary, sample footage, and the upsell scope
   clarification. Listed in the package's own `PENDING-OWNER-DECISIONS.txt`.
5. **The render-capable exercises**: Z2–Z7 need a clean Mac, both subscriptions and real
   footage. Z10 needs a person who has not seen the repository.

## Two honest notes about this candidate

**It is already superseded.** The release source is a snapshot taken at 2026-09-17 14:06
local. A concurrent session added a whole `sniper-context` skill to the working tree
about 40 minutes later — four Python files, a doc, two skill files, a command, and edits
to `AGENTS.md`, `CLAUDE.md`, `README.md` and `scripts/tests/skill_surface.test.mjs`;
the dirty path count moved from 237 to 248. Nothing was pulled in mid-flight, because
those files were being written as the build ran. A release must be cut from a quiescent
tree. This is recorded, not worked around.

**The build's own scans are shape scans, not proofs.** The secret scan matches known key
prefixes above a length floor, with no entropy model; the length floor is set above the
short fixtures the product's own tests use to prove its trace writer refuses a key
(`test_attempt_trace.py:170`), which is why that fixture no longer trips it. It catches a
pasted credential. It would not catch an obfuscated or encoded one. The buyer-text scan
is a phrase list with the same kind of limit — it caught the specific claims the
integrations pass named, and a person still has to read the manual.
