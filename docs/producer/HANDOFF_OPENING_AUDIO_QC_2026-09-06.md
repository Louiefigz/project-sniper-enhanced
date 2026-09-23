# Opening, audio and QC handoff — 2026-09-06

Stop requested by the user because of credits. No new implementation or media jobs were started for this handoff. Preserve the dirty worktree and every retained failure. This is an implementation checkpoint, **not** a released two-hour editor, creator-quality result, opening approval or delivery approval.

## What exists

- F1 has an explicit `source-float-v2` ordinary-render/assembly/current-graph lane. Source-derived dialogue and mixed-program intermediates preserve float headroom and exact retained sample clocks; shared mastering has its limiter latency corrected. Full-program music/master selection is separate from the raw source bus. Old byte-changing policies/caches are invalidated rather than relabeled. Legacy defaults remain intact; no blanket GUI/default qualification is claimed.
- Relevant audio modules are under `scripts/producer/audio/`: `render_audio_authority.py`, `render_audio_cache.py`, `assemble_source_audio.py`, `assemble_picture_reuse.py`, `program_master_bus.py`, `program_master_selection.py`, `program_master_excerpt.py`, plus the existing shared master/delivery/normalization seams. `current_render_graph_audio.py` and the existing graph candidate/store paths consume these proofs. Reusable buses and pictures require separately held execution/graph authority, not mutually consistent private pointers. Unproven graphics/explicit-caption picture reuse conservatively declines and recomposites.
- The private Python opening worker actually reuses the ordinary full base, selects the actual full-program float master, extracts exact PCM and composites an exact video range. Source/plan/readiness/frame/occurrence/tool bindings are checked before and after. Its new `guided_opening_*.py` modules are implementation, not a second general renderer or permission to bypass legacy template-history approval.
- Core files: `guided_opening_inputs.py`/`pipeline.py`/`frames.py` (closed input and supported class), `prepare.py` (ordinary base and actual master return), `picture.py`/`mux.py` (exact picture range and AAC), `graphic_proof.py`/`graphics.py` (explicit at-rate ordinary OCI invocation and independently held proof), `claim.py`/`cleanup.py` (exact owned resource recovery), `media.py` (worker), `read.py`/`result.py` (strong read-only actual-return validation). These names have the common `guided_opening_` prefix.
- Shared `graphics/composite_core.py` has an opt-in exact rational-rate, half-open integer-frame gate and range trim after the global graph. Legacy timing behavior is unchanged. Original full-duration animations and actual stable `(outStart, original index)` compositor order are retained; candidate index is not silently reinterpreted as artist z-order.
- `audio/program_master_excerpt.py` uses absolute `round_ties_even(frame * 48000 * denominator / numerator)` endpoints. No snippet normalization, added fades or independent intro master. A late whole-program mix/master/policy change invalidates the excerpt. The actual held selection event binds the whole candidate plan; reusable audio alone is not a current selection event.
- The private base still performs extra legacy AAC picture transport. The selected audible lane uses the source-derived float bus, not that transport audio. This remaining work/cost is disclosed, not described as literally one encode across all incidental artifacts.

## First executable class and what is still blocked

The first development profile is `unity-source-float-own-screen-v1`: unity speed, no J-cuts, explicitly bound own-screen/full-canvas graphics, normal composite mode, preserved base. At most eight intersecting graphic entries. Real canvas/rational rate must match authority; the fixture now creates actual 1920×1080 sources before admission, at 30000/1001. Accepted `target.fps:30` metadata is not permission to change that actual clock.

Captions, titles, PiP, grading, b-roll, punch/reframe/transitions and unqualified SFX/gain/enhancement are explicit unsupported requests in this first profile. Do not delete those intents to obtain a green run. Nonzero/unknown J-cut speech-window support remains blocked until actual two-source occurrence/fade evidence exists; F1 sample correctness is not that semantic evidence.

Next expansion, after the first authentic result and timings: bounded ordinary punch/zoom with frame/ROI/easing/audio invariance proofs, then explicit captions with actual early/late placement and own-screen interaction evidence. Sound treatment must enter the same full-program master. None is blanket-enabled here.

## Evidence actually obtained

All paths below are retained local evidence, not durable copies of creator media. Later source changes stale earlier source-bound proofs; do not update their digests to make them current.

| Checkpoint | Actual result | Retained log/path |
|---|---|---|
| Expanded F1 before opening work | 276/276 PASS, 255.70 s wall | `/private/tmp/sniper-f1-final-expanded-20260906.log` |
| F1 historical/current receipt and registries | 53 PASS, 12.49 s wall | `/private/tmp/sniper-f1-final-registry-v2-20260906.log` |
| Final Python opening submodule cohort | 32 PASS, 39.93 s wall | `/private/tmp/sniper-opening-readback-final-20260906.log` |
| Initial new readback tuple-canonicalization defect | 25 PASS, 2 errors, 29.39 s | `/private/tmp/sniper-opening-readback-initial-20260906.log` |
| Corrected same readback cohort | 27 PASS, 31.06 s | `/private/tmp/sniper-opening-readback-json-array-20260906.log` |
| Typed sealed-input tuple defect before fix | 1 error, 0.57 s | `/private/tmp/sniper-opening-seal-tuple-before-20260906.log` |
| Corrected boundary/clock tests | 15 PASS, 0.59 s | `/private/tmp/sniper-opening-readback-boundaries-20260906.log` |
| Full-versus-range raw moving-pixel oracle | 1 test / 9 comparisons PASS, 1.54 s | `/private/tmp/sniper-opening-compositor-oracle-initial-20260906.log` |
| Independent stopped-process/cleanup/claim review | 13 PASS, 0.60 s, including real venv imports | `/private/tmp/sniper-opening-four-fix-review-20260906.log` |
| Original no-process sidecar forgery | Accepted incorrectly in 0.63 s | `/private/tmp/sniper-stopped-process-forgery-result.log` |
| Same forgery after durable actual-return binding | Correctly rejected in 0.18 s | `/private/tmp/sniper-stopped-process-forgery-recheck.log` |
| Current fixed-30 V2 OCI smoke, not private fractional-rate opening | 75-frame / 2.5 s ProRes4444, PASS 16.816 s with exact cleanup | `/private/tmp/sniper-render-build-v2-live-i70jnf0m` |
| Earlier V2 late-create reconciliation failure | FAILED 74.974 s; original ledger/evidence retained | `/private/tmp/sniper-render-build-v2-live-4fhk2y9d` |

The 32-test Python cohort includes real synthetic ordinary base → actual source bus/full master → PCM excerpts → picture-copy/AAC; exact reopened master event, full picture/audio readback, wrong sample intent and moving-pixel/collision oracles. Those fixtures enter **below** the authenticated TS fourteen-document gate. They do not prove real speech, perceptual quality or an actual opening catalog render.

Older wrong-environment attempts remain in `/private/tmp/sniper-opening-audio-final-cohort-20260906.log` (72 passed, missing-SciPy error, 74.85 s; sibling environment was wrong). The affected registry was rerun with the actual project venv: eight PASS, 7.45 s, `/private/tmp/sniper-opening-audio-effect-registry-project-venv-20260906.log`. Do not merge this into an invented clean full run. Early preparation import failures and the corrected eight-test19.40 s run are retained in `/private/tmp/sniper-opening-preparation-initial-20260906.log` and `/private/tmp/sniper-opening-preparation-path-corrected-20260906.log`.

Useful detailed notes: `/private/tmp/sniper-opening-media-readback-20260906.md`, `/private/tmp/sniper-opening-process-review-20260906.md`, `/private/tmp/sniper-opening-slice-a-qualification-20260906.md`. The 276-test F1 checkpoint has not been rerun after every subsequent new opening/QC helper.

## No authentic opening success yet

1. First full synthetic workflow setup failed after10.83 s before opening input/claim/worker/container. The inherited TEST helper deleted its early failure directory; only the terminal failure survives. This loss was fixed in the TEST helper, not concealed.
2. Fresh attempt failed after11.98 s at catalog loading: `matrix is stale: motion source digest changed`. Retained: `/private/var/folders/3m/8rxbwgds5z7c3r72ccfqb9280000gn/T/sniper-human-cut-rJjmn3/test-only-cut-review-07df4ff4/TEST-SETUP-FAILURE.json`. The generic runner said `cut preview exited 1`, but the actual failed child was the catalog assertion. Process group stopped; no opening worker/Docker launched.
3. Gibbs completed genuine current53-default/probe-spec capability recomputation at `/private/tmp/sniper-capabilities.SHd8Fp/run`, not the full424-case matrix. The initial `/private/tmp/sniper-capabilities.eScwuG/run` attempt failed after49.838 s due missing explicit `SNIPER_NODE_PATH`; exact container removal was observed and nothing published. Intermediate continuations reached six then eight valid current rows; the final continuation revalidated eight and completed45 fresh renders. At final handoff the owner reported the rebuild and independent full readback PASS: published `templates/motion/comp_capabilities.json` SHA256 `e65e1e6d45d809446ed7b7b4670355aa7f941d0600450aadd73afd18736e98ce`, independent evidence `/private/tmp/sniper-capability-final-readback-lh1r_clp/result.json`. All owned probe containers were verified REMOVED; no active catalog work. This owner-reported final result clears the stale default-capability blocker only, not the424-case matrix, private fractional-rate opening or per-input visual qualification.

The catalog owner released the captured source freeze on completion. A new source-bound opening attempt still needs a coordinated stable window and current validation; no job was launched after the user's stop request. Never use a hash waiver or reinterpret a fixed30 proof as private at-rate qualification.

## Exact next protocol (do not launch until authorized to resume)

From `PROJECT_SNIPER`, use its `.venv/bin/python` for every Python producer test, with `PYTHONPATH=scripts/producer:scripts/producer/tests`. Do not execute the resolved base interpreter instead of the venv invocation path.

First verify the catalog is genuinely current, exact runtime controls still match the approved image/socket/executable, no unresolved prior claim exists, and coordinate a stable full source window. The server fixture is:

```sh
node --import tsx src/lib/server/__tests__/_guided-opening-media-fixture.ts --run-worker --cleanup-cas-faults
```

It requires explicit `SNIPER_DOCKER_PATH`, `SNIPER_DOCKER_SOCKET`, `SNIPER_RENDER_IMAGE_ID`, `SNIPER_RENDER_UID_GID`, and `SNIPER_RUNTIME_REPO_ROOT`. Prior controls were `/Applications/Docker.app/Contents/Resources/bin/docker`, `/Users/maintainer/.docker/run/docker.sock`, `sha256:bc56d3860d2ec1c843f7184bcecd21137aa79fe9fe19c90a67136d3052222ba8`, `501:20`, and the actual repo root. These are historical identities to reobserve, not permission to substitute an arbitrary runtime or repin approval. The fixture uses actual synthetic picture/tone impulses and TEST-only transcript/compiler/critics/human decision; never call it creator/listening evidence.

The actual TS production sequence is guarded input construction → durable pre-spawn claim → actual owned media process → separately journal-held actual return → protected exact cleanup/CAS → actual strong readback under the original remaining budget. `--cleanup-cas-faults` adds three distinct actual cleanup attempts (held-start mutation, held-output mutation, backward time at the second CAS) before a fourth clean attempt, without rerendering media or restoring failed evidence. This fault cohort is wired but **not executed** yet.

Low-level commands below are protocol documentation, not a replacement for the actual server-held lease/claim and return hashes:

```sh
.venv/bin/python scripts/producer/guided_opening_media.py INPUT OUT --input-sha256 INPUT_SHA --execution-claim CLAIM --execution-claim-sha256 CLAIM_SHA --timeout-seconds ORIGINAL_REMAINING
.venv/bin/python scripts/producer/guided_opening_cleanup.py INPUT OUT --input-sha256 INPUT_SHA --execution-claim CLAIM --execution-claim-sha256 CLAIM_SHA --timeout-seconds PROTECTED_CLEANUP_REMAINING
.venv/bin/python scripts/producer/guided_opening_read.py INPUT OUT --input-sha256 INPUT_SHA --execution-claim CLAIM --execution-claim-sha256 CLAIM_SHA --receipt-sha256 ACTUAL_RETURN_RAW_SHA --receipt-hash ACTUAL_RETURN_CANONICAL_SHA --timeout-seconds ORIGINAL_REMAINING
```

- INPUT holds14 closed, byte-bound documents and full pinned pipeline inventory. Timeline-map semantic hash is not its document byte hash. Raw source admission includes silent/unused rows. OUT is a new server-derived private directory, never public final.
- Media/read stdout is exactly one closed completion; reused progress goes to stderr. Preserve both. No “last JSON wins” parser.
- Cleanup is a separate protected≤300 s allowance, not renewed render credit, and only after exact owned-group stop. It uses held claim/control/order records, not recursive resource discovery or current mutable source freshness.
- Strong read requires the actual returned raw and canonical receipt hashes, failure-marker absence, exact current plan/source/master/picture/graphics dependencies, actual complete decode and final rechecks. Orphan/self-resealed JSON is not authority.
- TS `guided-opening-process-activation.ts` now binds actual raw return bytes into `openingProcessOutcomeHash`. `guided-opening-cleanup.ts` compares held bytes/failure marker/stop/high-water immediately before CAS and removes both transient pointers. The four original review blockers are corrected; actual CAS fault coverage remains pending.
- New `guided-opening-readback.ts` retains actual owned verification as private, non-selectable evidence. Its latest full pre/post service path and fault seam were not independently executed in this handoff. No ready/playback-selection pointer or approval may be invented from `verified.json`.

Complementary server handoff: `docs/producer/HANDOFF_OPENING_SERVER_2026-09-06.md`. Its owner reports18 protocol/actual-venv tests PASS0.76 s, type-check2.28 s and lint1.98 s, plus four status tests; those are not an actual opening worker/CAS/fault run. The exact prior command used `/usr/local/bin/docker`, whose canonical executable was independently observed as the Docker.app path above; retain explicit control validation rather than assuming alias identity.

## Ownership and hard-kill caveat

This quality agent and the server owner have no live child process, renderer or media job. The two failed full opening fixtures never created opening Docker resources. Gibbs's final catalog notification reports all exact owned probe containers REMOVED and no active catalog work. This handoff did not issue a broad process/container cleanup.

**Unqualified hard-kill case:** `headless/media_probe.py` calls `process_runner.run_text`, which uses `start_new_session=True` at `headless/process_runner.py:89`. A hard outer Python-group kill can therefore leave a detached local ffprobe group outside the TS negative-PGID stop check. Normal return reaps that child; no actual leak is asserted from successful normal return. But owned outer-group stop plus Docker absence is not proof that all detached local groups stopped. Track/reconcile exact nested groups before claiming comprehensive crash/timeout cleanup. Do not weaken the contract by renaming this uncertainty as verified cleanup, and do not change captured101 files mid-catalog run.

## Creator source now readable, not qualified

Main's read-only ffprobe now succeeds in0.119 s for `/Users/maintainer/Downloads/C0679.MP4`: 10,280,473,262 bytes; duration834.335 s; H2643840×2160, yuv420p, limited/tv range,24000/1001,20004 frames, start0; matrix/primaries bt709, transfer `iec61966-2-4`; stereo48 kHz PCM_s16be and a data stream.

No full source hash, complete decode, admission, model or render job was run. This is a large xvYCC-class source, **not** the already-qualified small normal-SDR fixture class. Current F2 rejects its >8 GiB size and transfer; the explicit xvYCC mezzanine contract exists but is not qualified for this file. Do not infer a LUT, label it ordinary BT709 SDR solely from matrix/primaries, or silently downscale/reencode it to fit admission. The old91.967 s derivative is not raw footage or a ten-minute benchmark.

## Critical unfinished QC patch

Main owns dirty `audit/audit_glitch.py`, new `audit/audit_glitch_scan.py` and `tests/test_audit_glitch_scan.py`. Original defect: nonzero/partial FFmpeg logs could make all three detectors PASS; terminal freeze was dropped by zip; missing luma silently disappeared; invalid duration allowed black as tail. New strict separate scans check exit, positive terminal progress and complete luma, returning FAIL/unmeasured while keeping valid thresholds unchanged. Eleven pure tests passed0.16 s, **no actual media parity/decode cohort**.

Stop state is intentionally unfinished: the ordered freeze parser must validate start/duration/**end** events; the terminal-freeze early return currently hides prior closed unplanned spans; scan/parser nesting needs the repository≤2 pass. The updated Palmier private mock still needs a `freeze_end` fixture. Finish these before release, then actual corruption/empty/tail/boundary media and legacy threshold parity. Shared-one-decode optimization is only a proposal: filter negotiation can alter pixels, so no performance or result-equivalence claim exists. Adjacent unchecked `audit_probe.video_frame_count` and `audit_motion._ff_output` remain separately recorded debt; a global `run_ff(check=True)` is not a tested fix.

## Still required for the user outcome

An authentic current catalog graphic → full-program master → exact range → encoded A/V → cleanup → strong-readback run is still missing. So are creator-footage full-output blind comparisons, speech intelligibility/music balance/SFX listening, mixed camera/profile/color qualification, representative short and ten-minute long runs, and measured two-hour end-to-end throughput with edits. Mechanical sample/PTS/hash checks do not substitute for hearing and watching the result. The one-request workflow may stage internal checks, but failed hard gates and unsupported requested lanes cannot be waived to meet time.
