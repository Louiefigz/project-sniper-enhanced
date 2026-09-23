# Qualification report — project-sniper-0.1.0-rc3

> **Superseded by rc4 (2026-09-19).** This is the rc3 report, kept for history. The rc4 state — final candidate
> `bae842a` (ZIP SHA-256 `7fed9cfd…`), its results and open items — is in
> `outputs/project-sniper-release-rc4-2026-09-18/evidence/final/INDEPENDENT_REVIEW_RESPONSE.md` and
> `release/qualification/matrix.json` (read by `python -m release.sale_gate`). Both rc3 blockers below are
> resolved in rc4 (native media admission; original styles and doctrine).

Built 2026-09-18 UTC from the isolated release checkout (commit `3744f6a`). The checkout is a verified snapshot of
the live tree at upstream `8ebcdfc` plus its 2026-09-17 working tree: 6,133 captured files, byte-identical to the
live files at capture time. rc2 and its evidence are unchanged in `../project-sniper-release-2026-09-17/`.

**Verdict: NOT QUALIFIED FOR SALE. Two product decisions block it, and no real edit could be run.**
1. **Producer cannot admit footage on a buyer's Mac.** Every media file is admitted inside a Docker container
   with one approved image, which the native package doesn't provide (`DECISION-SANDBOX-RUNTIME.md`).
2. **The saved styles and several doctrine studies are still derived from specific creators' videos or one
   teacher's material.** The rename replaced the listed teacher names in identifiers only; other creator names,
   reel and video IDs, a creator tagline and the material itself remain. The independent review found this; my
   rc3 rename work had wrongly claimed it resolved.
3. **No real edit could run here.** The Codex subscription is out of quota until 2026-09-24 13:44, and Sniper's own
   Claude login isn't signed in.

Everything else the continuation brief asked for is implemented and exercised on this Mac, with the exceptions
listed under "Open items".

"Developer Mac" means this machine (macOS 26, Apple M3 Max, Homebrew, Docker Desktop, both CLIs). It is not a
clean Mac and not a qualified baseline. Evidence paths are relative to `evidence/`.

## The archive

| | |
|---|---|
| File | `project-sniper-0.1.0-rc3-mac.zip` |
| Size | 18,454,561 bytes |
| SHA-256 | `bd33082736c6f8dc64374421ac9d3b3194a7fb97d1e885ea85f50d8205124071` (in `SHA256SUMS`, outside the archive) |
| Entries | 5,020 under one top-level folder |
| Reproducible | two builds of commit `3744f6a` are byte-identical (`60b-final-determinism.txt`) |
| Source commit | read from git by the build, which refuses an uncommitted checkout (`release-manifest.json`) |
| Sellable | `false`; `RELEASE.json` lists 8 blockers |

**How the evidence maps to these bytes.**
- **The app code is byte-identical to commit `15dac37`**, on which the full suites ran. Every later commit changed
  only `release/`.
- **Run on these exact bytes (`bd330827`):**
  - the Z1 audit (`60-`);
  - the fresh install (`61-`);
  - launcher acceptance (`62-`);
  - the 24 in-package closure tests (`63-`);
  - the interrupted-runtime and unsafe-path tests (`54c-`).
- **The R7 lifecycle run** (`56b-`) used the previous installer scripts. They differ from the final ones only in
  two extra unset variables, two comments and one message line.
- **R5 cases A–H** (`54b-`) and the repeat-install and disk figures (`53b-`) ran on an earlier rc3 install with
  earlier installer scripts.
- **The in-package Python selftest** (`65-`) ran in an install of build `fd26bacb`; its app code is identical.

## Requirement-to-evidence table

### Archive shape and dependency closure

| Req | Result | Evidence | What it does not show |
|---|---|---|---|
| **Z1** archive and closure | **Archive shape and runtime closure: PASS. Content rule: FAIL** (see B2) | `60-final-z1.log`: 98 passed, 0 failed, on a fresh `unzip` into a path containing a space and `ü`. The audit now reads Auto Edit's own required files, prefixes and source paths from the shipped `auto-edit-pipeline-assets.ts` (43), checks data files reached by path segments (6), resolves all 53 compositions with the package's own resolver, and loads the capability matrix with the package's loader. `63-installed-closure-tests.log`: 24 of 24 TypeScript closure tests pass inside the installed package with an empty HOME, `SNIPER_RAG_ROOT` unset and no sibling repository. `65-package-selftest.log`: in-package Python selftest with the install's own settings, 7,595 tests; all 13 failures read development evidence or Docker build inputs deliberately not shipped (listed below). | That Producer can admit media (it cannot; see Z3). |
| **B1/B7** packaged Director and reference resources | **PASS** | Original `resources/director` (11 formats, 48 anchors, 40 examples, 24 formulas, 12 categories) and `resources/references` (78 frames rendered from Sniper's own templates). Tests `36-`, `37-` and the in-package tests. | The reviewer notes the new library reuses the withheld studies' case IDs (N04, N26, …); its "not adapted" provenance wording needs a person's check. |
| **B2** no teacher names or paid corpus | **FAIL** | The listed teacher names are gone from identifiers, and the build fails closed on that fixed list (`32-`, `35-`). But other creator names (MKBHD, Trahan, Dude Perfect, MrBeast in `EDITCRAFT_LESSONS.md` and in `producer_config.py` comments), reel and video IDs and a creator tagline still ship. Still shipping and pinned as editor doctrine: `RESTRAINED_STYLE.md`, `PUNCH_STYLE.md` (two copies), `SLIDEWARE_STYLE.md`, `MODULE_STUDY.md`, `MODULE_CARDS.md`, `EDITCRAFT_LESSONS.md` (a teacher's taught curriculum), `SHORTFORM_LESSONS.md` (a tutorial), `REFERENCE_STYLE_STUDY.md` (third-party Shorts). `75-creator-provenance-inventory.txt`, `76-independent-review.md`, `77-focused-rereview.md`. | — |
| **B3** YuNet | **Cleared** | MIT (OpenCV Zoo); hash matches upstream; notice shipped. | — |
| **B4** music | **Replaced; not yet heard** | The old bed hummed at 111 Hz (`49-`). The new bed comes from `scripts/producer/audio/default_bed.py` (deterministic, no mix filter). Hum check PASS: strongest line in the 40–240 Hz band at −110.7 dBFS. −22.2 LUFS, balanced channels (`64-`). | A person listening to it. |

### Installer behaviour (developer Mac only)

| Req | Result | Evidence | What it does not show |
|---|---|---|---|
| **Z2** installation | **Developer Mac: PASS. Clean Mac: NOT RUN** | `61-final-install.log`: fresh extraction; empty HOME; Finder's minimal PATH; 81.2 s including every download. The doctor passes everything except two required checks: `media admission sandbox` (the blocker) and Sniper's own sign-in (empty as designed). `53b-`: repeat install 6.9 s, 2.6 GB installed. `47-`: Python floor 3.12 from the lock. `48-`: builds with remote network denied. | A clean Mac, other macOS versions, Intel, or a Node from nvm/fnm/volta (see Open items). |
| **R1** build and launch | **PASS (developer Mac)** | `62-final-r1-launch.log`: start from Finder PATH; serves this build and the page; start while running; stop; relaunch; port held by another program; `SNIPER_PORT` override (was ignored, fixed); a foreign PID is not signalled; a missing build receipt refuses. | — |
| **R2** wrappers and provider choice | **PASS, with one unverified point** | Isolated config; the provider choice persists and drives app and doctor. `CLAUDE_SECURESTORAGE_CONFIG_DIR`, inherited API/OAuth keys and the Bedrock/Vertex/base-URL switches are cleared from the shell environment. A key placed in `runtime/sniper.local.env` or `app/.env.local` is still read. The Codex version check no longer writes to the buyer's `~/.codex`. | `sign-in.command` for Claude doesn't pass `--setting-sources ""`; unverified whether it reads the buyer's `~/.claude` settings. No real sign-in through Sniper's wrapper has run. |
| **R3** doctor uses production admission | **Fixtures PASS; real Codex admission PASS with the owner's global login** | `provider-admission-cli.test.ts` covers valid, API-key, logged out, CLI exit 1, malformed, wrong or newer version, stderr noise, missing CLI and provider mismatch; no account metadata in any report. Real: `codex-cli 0.144.1 admitted and signed in`, with Sniper pointed at the owner's existing `~/.codex` login, on build `f96f25a0` (the admission code is unchanged since) (`69-`). | Admission of a login made through Sniper's own wrapper; Claude. |
| **R4** model and transcription | **PASS (developer Mac)** | A hash mismatch refuses. The doctor transcribes a local sample through `transcribe_media` (9 timed words, 5/5). A real download resumed from byte 62,337,024 and verified (`54b-`). | — |
| **R5** resumable install | **PASS for the cases tested** | `54b-`: moved or copied folder; `npm ci` killed; lockfile changed; model corrupted; download failed; real download interrupted and resumed; build interrupted; build failing then repaired; settings kept. `54c-` (final bytes): an interrupted render-runtime step used to leave an `installing/` folder that failed every rerun. The installer now removes it when no process holds a file there (tested). It refuses while a file there is held, then recovers once released (tested). Paths containing `$`, a backtick or `"` are refused before any install step starts; only the refusal is logged (all three tested). Such paths could break or inject into the settings file. The removal assumes the app is stopped: renders and the doctor can also build the runtime, and a concurrent build between file writes could be removed. | Interrupting the Python-environment, browser or CLI steps; the browser step's handling of a partial download. |
| **R6** prerequisites and claims | **PASS** | Homebrew guidance; Finder PATH; ffmpeg features checked on the actual binary; Python floor from `Requires-Python`; the "fifteen minutes" claim removed and blocked; path limits documented; Next.js and HyperFrames telemetry off. | Download integrity: pip installs without hashes; the CLIs install from npm without a lockfile; the browser has no checksum (see Open items). |
| **R7 / Z8** lifecycle | **PASS (developer Mac)** | `56b-final-r7-lifecycle.log` on the final scripts. Cleanup refuses during a render, an open cache file or an unfinished export, and removes only caches. Diagnostics leak none of a sensitive fixture by default. Rollback between release folders. Moved folder. Uninstall of a copy leaves the original running. Uninstall refuses during a background edit. Real uninstall. Global login state unchanged. | That uninstall deletes the export-recovery pointers and the buyer's `sniper.local.env` settings (by design, but worth saying in the manual); that a failed sign-out still prints "Removed"; signing out Sniper's own Claude Keychain item (never created here). |

### Real editing

| Req | Result | Evidence |
|---|---|---|
| **Z3** both providers | **BLOCKED** | Without the sandbox, Producer ingest stops. A developer-only harness approved a locally built image inside the test install (never shipped): ingest and local transcription passed (88 words, correct), and cut authoring reached Codex, which refused with its usage limit. The app now shows that reason; it previously showed an unrelated log line (fixed). Claude: Sniper's login isn't signed in. (`69-`, `69b-`) |
| **Z4** long-form, **Z5** Shorts, **Z6** playback and Studio | **NOT RUN** | Blocked as above. The manual now has buyers record their own 45-second first clip from an original script. Playback with sound is a person's check. |
| **Z7** secondary tools | **NOT RUN** | Segmenter and Clipper don't need the sandbox. On the Claude route their AI steps call the paid Anthropic API through the SDK, so without a key they don't work, and with one they bill per call. The installer creates `app/.env.local` from a template that invites that key. Shell keys are now ignored; the manual now says this. |

### Outside person and buyer delivery

| Req | Result | Evidence |
|---|---|---|
| **Z9** manual and provenance | **FAIL** | Fixed: no mention of the switched-off paid offer; no invented refund effect; home page no longer promises Palmier; the start and install pages now say which features can bill an API key; uninstall text names what it deletes; "streaming level" rather than "broadcast level"; both blockers stated in the doctor, the installer's closing message, PENDING, troubleshooting and first-edits. Still wrong: the privacy page against the code (review items: frames reach Codex by folder read access, not `--image`; the "reference video" row; yt-dlp downloads, website capture and Chrome-cookie access undisclosed; the app's own "Where does my footage go?" panel), and the B2 material. |
| **Z10** outside operator | **BLOCKED_INPUT** | Needs a person, a clean Mac and their own subscription and footage, after both decisions. |
| **Z11** delivery and updates | **BLOCKED_CAPABILITY** | Hash and size recorded; authenticated delivery not tested. |

## Test suites on the frozen app code (commit 15dac37; unchanged through 3744f6a)

| Check | Result | Evidence |
|---|---|---|
| `tsc --noEmit` | exit 0 | `71-final-tsc-lint-build.log` |
| `npm run lint` | exit 0 (0 errors, 41 warnings) | `71-` |
| `npm run build` | exit 0 | `71-` |
| `npm test` stages: supervisor, skill surface, `test:sdk` | all pass (`test:sdk` 14/14) | `72-final-npm-test-stages.log` |
| `npm test` stage: `test:native` | 144 tests pass; one file, `native_source_cache.test.mjs`, never exits and is cancelled at 120 s. Its 10 tests pass, then the process stays alive when HOME holds this Mac's 861 MB HyperFrames cache. With an empty HOME it finishes 10/10 in 0.2 s. It passed here at `811c706` too. This is a test-isolation problem, not a product failure; the test should not touch the real user cache. | `72-`, `72b-native-source-cache-rerun.log` |
| Every TypeScript test file (`npm test`'s loop), each in its own process, 4 at a time | **477 of 477 pass** | `ts-final/73-final-ts-files.log` |
| Python selftest (source) | 7,600 tests; 5 failures and 1 error, exactly the six blocked retained-receipt checks (below). Everything else passes, including Audit B, the cleanup-signal test, the ledger, the caption fixture and the treatment digests fixed this round. | `74-final-selftest.log` |
| Python selftest inside the installed package (the install's own settings, `TMPDIR` set) | 7,595 tests; 13 fail. All read development evidence or Docker build inputs the package deliberately withholds: retained receipts under `docs/.../contracts`, `templates/motion/container/`, `.dockerignore`. | `65-package-selftest.log`; earlier runs without the install's settings, `65-…plain-env…`, `65b-`, `65c-`, show why those settings matter |

The six blocked receipt checks are listed in "Open items".

## Defects found and fixed in this round (in the final bytes)

1. **Auto Edit could not start from any package (rc2 and early rc3):**
   - the required contracts and `assets/music/` weren't shipped;
   - three runtime registries, a calibration file, the route matrix and the catalog study were missing;
   - `module-pipeline.js` was missing;
   - the capability matrix could never be fresh in the package, because its digest covered a withheld
     third-party screenshot.

   The screenshot is removed from the release source and the matrix regenerated. The Z1 audit now checks all of
   this with the package's own code.
2. **Capability matrix and several pinned values went stale through the rename.** All were regenerated by their
   own tools or proven equivalent:
   - capability matrix: regenerated by the probe;
   - cleanup pins: regenerated from the import graph;
   - authority golden: rewritten only after TypeScript/Python parity passed;
   - treatment digests: identical once the renamed kinds are mapped back.
3. **Audit B false failure.** The audit hashed a plan it had mutated, so sealed cut lineage never verified; now
   fixed.
4. **Load-dependent cleanup test.** 248/300 runs failed with stray threads; after the fix, 0/300.
5. **Installer and launchers:**
   - accented-path PID identity;
   - regex matching of folder names containing `(1)`;
   - moved or copied installs acting on the other folder;
   - `SNIPER_PORT` ignored;
   - stale build and model receipts;
   - `npm ci` repair;
   - Codex writing to the buyer's `~/.codex`;
   - Next.js telemetry;
   - uninstall under a running edit;
   - the interrupted runtime step;
   - shell-unsafe paths;
   - inherited API keys.
6. **The doctor said "All required checks passed" on an install that can't edit.** It now checks the admission sandbox's prerequisites (runtime and approved image), not a real admission of a clip.
7. **Codex failures were misreported.** The app shows Codex's own reason.
8. **Content and fixtures:** ledger order; a scrubbed caption fixture; the music generator's `amix`; three retained
   receipts regenerated by their own generators.

Details: `59-defect-fixes.md`, `57-`, `66-`, `64-`.

## Open items (not fixed in rc3)

- **The two blocking decisions:** `DECISION-SANDBOX-RUNTIME.md`, and the creator-derived doctrine (re-author it
  as original material, or drop the saved styles).
- **Privacy page and in-app privacy panel** against the code (Z9 above).
- **Download integrity:** hash-pinned pip install, a lockfile for the pinned CLIs, and a browser checksum.
- **Node:** the installer checks the `node` on the buyer's PATH, but `sniper.env` fixes PATH to Homebrew and
  system folders, so nvm/fnm/volta users can run a different Node. The Node floor, 22.0, is below the lockfiles'
  `>=22.12`.
- **Segmenter and Clipper on the Claude route** should go through the subscription CLI, not the SDK.
- **Minor items from the review:**
  - troubleshooting step numbers and quoted messages;
  - the Studio commands in `review-and-studio.html` call the venv directly, bypassing the settings file and the key unset;
  - `START-HERE.html` points to the two blocker files but doesn't name the blockers;
  - a developer hostname in `next.config.ts`;
  - HeyGen Studio screenshots under `scripts/producer/tests/.artifacts`;
  - owner-specific notes in the producer skill and a playbook;
  - `docs/audits` shipping although listed as withheld;
  - `RELEASE.json` lacks the source commit (it is in `release-manifest.json`).
- **P4/P5 receipt lanes** need a new HyperFrames 0.8.31 fixture. **P0 ingress and the rate matrix** need the approved
  image. **P0 render parity** needs 21 GB of local evidence. All nine already failed at HEAD `8ebcdfc`
  (`58b-receipts-at-live-head.log`).

## Owner inputs needed
1. **Choose the sandbox route** (A, B or C in `DECISION-SANDBOX-RUNTIME.md`).
2. **Decide the saved styles:** re-author them as original doctrine, or drop them.
3. **A provider for qualification edits:** Codex quota returns 2026-09-24 13:44, or run
   `install/sign-in.command claude` in a test install.
4. **Final licence wording and a support route** (input D).
5. **A clean Mac and an outside operator** (Z2, Z10), and an authenticated delivery test (Z11).
6. **Listen to the 60-second music bed once.**
7. **Remove one test entry from your Codex config.** The developer test added two lines to `~/.codex/config.toml`:
   `[projects."…/scratchpad/work3/devws/test-clip-20260918/producer"]` and `trust_level = "trusted"`. They mark
   only that scratch folder as trusted and are safe to delete. The permission guard stopped me from editing your
   global config.

## Not changed
- rc2 and its evidence.
- Your real projects.
- Global Codex auth, Claude settings and the Claude Keychain item: hash-checked; only the config entry above
  changed.
- The live `PROJECT_SNIPER` tree. Fixes to port there are listed in a separate task.
