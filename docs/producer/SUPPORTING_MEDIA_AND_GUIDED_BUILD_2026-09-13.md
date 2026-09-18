# Supporting-media and guided-build integration — September 13

This continues the September 12 organic B-roll batch. The original three review
exports are unchanged. Private transcripts, footage and editing context stayed
local. This batch does not create a new finished or editorially approved Short.

## Implemented behavior

- The app has a dedicated supporting-image/video picker. It stages PNG/JPEG/WebP
  or MP4/MOV with stable copying and a hash receipt, then uses existing sandbox
  admission. Staging is distinguished from admitted inventory.
- Both supporting-media UI rescan actions preserve verified transcript bytes.
  The scanner retains externally referenced primary recordings and all previous
  admitted supporting media, including source-lane images and external B-roll or
  music. Existing IDs persist; new IDs avoid collisions. Changed or missing
  originals and invalid new media fail before manifest publication. No ASR fallback.
- The V10 proposal contract freezes admitted supplied raster inventory and source
  policy, keeps unresolved requirements typed, and resolves each required
  scene/asset pair through the existing v3 asset-use decision. V9 behavior stays
  unchanged. Unknown IDs, inappropriate origin/policy, wrong speech/display/crop
  bounds, missing decisions and no-insert substitutions fail explicitly.
- The shared native writer persists the guided binding and includes it in its
  hashed inputs. Cold read reconstructs the actual current proposal and replays
  the same requirements. Reserved guided paths and their symlink aliases cannot
  opt out by stripping optional metadata.
- `native-short.ts build-guided <producer-dir> <visual-plan.json>` now reaches the
  shared writer under an actual checkpoint mutation lease. It derives token and
  journal hashes from current state, retains the original generation clock and
  a 120-second local assembly bound, and writes attempt start/result evidence.
  A passing result is ready for native QC; it grants no approval and starts no
  render. Final clock observations must still be valid when success is recorded.

## Structural and local-file verification

- V10 compiler/evidence/history and legacy dispatch slice: 52 focused checks.
- Guided persistence/resolution, request/HTTP, service and CLI slice: 64 checks.
- Supporting intake: 11 tests, including real stream copy, a file changed into
  a FIFO, a live lease guard error, request restrictions, client reuse dispatch
  and incomplete/failed SSE responses. Existing picker/source-placement suites
  also pass. The native OS picker dialog itself was not driven in this batch.
- Retained inventory, transcript reuse, existing resume and format tests: 31 pass.
- Full TypeScript check, targeted ESLint and diff whitespace checks pass.
- Independent review approved all three implementation slices. Review found
  defects that were fixed before qualification: lost external/old supporting
  inputs, stream callback errors escaping cleanup, missing persistent guided
  binding/alias checks, and a final deadline observation that could expire after
  an earlier check.

These groups overlap some existing contracts; their counts are not a single
unique repository-wide test total. No test-only cut acceptance, source admission
or independent critic receipt is represented as production authority.

## Actual media qualification

The real-media helper suite passed under a NativeRun heavy-work lease. It uses real H.264/AAC and PNG fixtures, the currently approved Docker
image, networkless sandbox admission and exact transcript-byte checks. Its
synthetic words over a tone are explicitly test-only, not speech recognition.
The three cases cover copied source plus a new image, referenced source plus
retained old supporting assets, and invalid new media/changed original rejection.

All three passed in **11.137 seconds** of worker time. The complete owner took
**58.967 seconds**, including **46.891 seconds** independently reconciling every
requested container after normal cleanup. All **14 exact container names** were
proved absent, the helper process group was reaped, and the heavy lease was
released with verified cleanup. The **95 pinned files** and source/SDK/sandbox
hashes were unchanged at completion. There were no skips, errors or ASR calls.

| Actual media case | Time | Result |
| --- | ---: | --- |
| Invalid raster / changed original leaves old manifest and words intact | 2.450s | Pass |
| Copied primary recording plus supplied PNG | 2.068s | Pass |
| Referenced recording plus existing reclassified/external B-roll and new PNG | 6.584s | Pass |

Evidence: [test results](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-01/results.json),
[owner receipt](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-01/supporting-rescan.render.json),
and [exact container cleanup](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-01/container-cleanup.json).
The test uses tiny synthetic fixtures; these timings are not full Short editing
or production-footage throughput measurements. Host process footprint does not
include the Docker VM; the admission containers retain their independently
attested 768 MiB memory/4-CPU bounds and network isolation.

This suite qualifies admission and additive rescan helpers.

### Actual main-entry publication

Two additional tests passed through real `ingest.main()` argument parsing,
rescan, admission and `atomic_write_json`, in **5.608 seconds** worker time.
The complete supervised owner took **24.908 seconds**, including **18.892
seconds** exact cleanup. All **six** requested containers were proved absent;
the **99 prepared pins** stayed current and the heavy lease released cleanly.

- Successful supplied-PNG rescan: **4.039s**. The newly published manifest has
  a different inode, while an open descriptor to the old manifest still returns
  its exact old bytes. The new manifest cold-verifies against admitted snapshots,
  includes the PNG, preserves source identity and exact transcript bytes, and
  emits `done` after publication.
- Invalid-PNG rejection: **1.535s**. The main entry exits nonzero, emits no `done`,
  preserves both old manifest bytes/inode and transcript bytes, and leaves no
  publication temporary file. The old manifest still verifies.

Evidence: [publication results](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-publication-01/results.json)
and [owner/cleanup receipt](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-publication-01/supporting-rescan-publication.render.json).
Both tests invoke the real main function inside the supervised worker. They do
not qualify a separate CLI process launch, full HTTP transport, speech recognition
or a guided final export. They use the same test-only tone/transcript fixture
and forbidden-provider assertions as the helper suite.

Together these two runs pass five real-media tests and verify cleanup for all
20 requested containers. All original review exports remain unchanged.

## Remaining acceptance

There is no legitimate saved production guided lineage in the current local
artifacts. Actual cut acceptance and service-backed Director/critic lineage are
required by that route, and the user's local-only choice remains in effect.
Structural fixtures cannot replace those steps. No finished guided Short has
therefore been newly qualified here.

Creator identity/quotation cases, a real operation or repository demonstration,
and complete fast/measured/changing-delivery playback remain on the
[work plan](SHORTS_REMAINING_WORK_PLAN_2026-09-12.md). The prior official-identity
and provided-only exports remain available on the local review page at port 3996.
No new claim of automatic selection across every style follows from this batch.

## Continuation: actual HTTP route qualification

The completed HTTP qualification runs an isolated real Next.js server, actual HTTP
requests and the ordinary spawned Python ingest CLI. Private provider calls
remain disabled; fixture words over a tone retain their explicit test-only label.
The existing app workspace, normal Next cache and configuration are preserved.

Pre-launch review found and fixed a target/checkpoint mismatch: competing target
fields, a managed source-folder output or a nested output could check a different
journal from the project being changed. Target selection now derives canonical
managed ownership, retains that ownership alongside the actual lease guard, and
checks both again before the child and result read. Redirected project folders
and foreign managed directory catalogs are rejected; ordinary individual file
imports remain supported. Seven new and 43 existing checks pass, with full
TypeScript, targeted lint and changed-function size checks.

All **four actual HTTP/SSE tests passed** in **11.120 seconds**. They exercised
the unmodified production API source in an isolated app copy, the real Next proxy,
seven separately spawned Python ingest processes, Docker full-decode admission,
atomic manifest publication, and independent cold reads of saved media authority.
Four CLI starts used `--no-transcribe`; three used `--reuse-transcripts`.
Every observed process exited and there were **zero ASR child processes**.

| Actual HTTP case | Test time | Result |
| --- | ---: | --- |
| Fresh copied recording → supporting PNG POST → transcript-preserving rescan | 4.950s | Pass |
| Live writer and guided checkpoint reject staging/rescan before child launch | 1.395s | Pass |
| Existing referenced recording → supporting PNG POST → preserved source/transcript | 2.251s | Pass |
| Staged invalid PNG → explicit stream error, old manifest/transcript preserved | 2.524s | Pass |

The complete worker, including app startup and shutdown, took **13.940 seconds**.
The existing NativeRun owner took **49.854 seconds**, including **34.803 seconds**
independently reconciling all **10 exact container names**. Owned process cleanup
and heavy-lease release were verified. All **11,444 prepared file pins** (plus
the owner's prepared-file pin) and input hashes remained unchanged. The peak
sampled owned host footprint was **0.761 GiB**, excluding the Docker VM. The
original resource bounds and original 600-second run clock were retained.

Evidence: [HTTP results](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-02/results.json),
[owner and cleanup receipt](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-02/supporting-rescan-http.render.json),
[actual CLI observation](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-02/python-observer.jsonl),
and [per-request evidence](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-02/fixtures/).
The first prepared harness was rejected during review **before launch** because
a generic HTTP response did not prove server ownership. The passing revision
uses a pinned test-only nonce/cwd/workspace/PID endpoint in the disposable copy;
every mutation stays on its verified connection with reconnects disabled. That
endpoint is absent from production source. Both preparation records are retained.

This closes the separate CLI-process and HTTP-transport coverage gaps for these
cases. The referenced test uses an existing project with external source media;
it does not exercise the automatic >2 GiB placement threshold. These tiny synthetic
fixtures do not establish production throughput, ASR accuracy, native picker UI,
visual suitability, or a finished guided/editorially approved Short. The original
five media tests remain additional scoped evidence.

### Real supporting clip and raster formats

A separate **one-test, four-format HTTP case passed** for real H.264/AAC MP4,
H.264/AAC MOV, JPEG and WebP fixtures. It stages all four through the actual app,
checks each stable copy and staging-only receipt, then performs one additive
rescan. The new cold-verified manifest contains four distinct supporting IDs,
correct image/video classification, executable snapshot hashes and media
dimensions/durations. The primary recording and its exact transcript remain
unchanged. Video audio stays `hasSpeech: null`; the existence of a tone does not
establish speech. Burned-text/visual suitability stays unknown until inspection.

The test took **4.946 seconds**, including synthetic fixture generation and six
actual HTTP requests. Full worker time with server startup/shutdown was **7.536
seconds**. The shared NativeRun owner finished in **28.404 seconds**, including
**19.972 seconds** exact cleanup. Both Python ingest children were observed
through exit, with one initial no-transcribe invocation and one reuse invocation;
no ASR child launched. All **six** requested containers were proved absent,
owned process cleanup and heavy-lease release passed, and **11,446 prepared
file pins** plus the prepared-file pin remained unchanged.

The first format attempt remains **failed**, with verified cleanup. Four newly
born child identities exhausted immediate monitor retries in 0.545 seconds and
the owner interrupted that attempt before its rescan. The shared retry window
now waits 0.1/0.2/0.4 seconds between retryable failures, retaining four samples,
the original 18-second/run deadlines, identity checks and resource caps. All
**87 focused monitoring tests pass**. The rerun recovered a turnover sample
after an observed 0.110-second wait. This is evidence for this workload, not a
general reliability or performance claim.

Evidence: [format HTTP results](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-formats-02/results.json),
[owner and cleanup](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-formats-02/supporting-rescan.render.json),
and [retained failed attempt](../../artifacts/native-short-organic-2026-09-12/supporting-rescan-http-formats-01/failure-analysis.json).
The previous four HTTP cases were not repeated. Together the two passing HTTP
runs cover PNG/JPEG/WebP images, the tested MP4/MOV codecs, source placement,
stream errors, transcript retention and checkpoint fences. This is not coverage
of every codec that can inhabit MP4/MOV, long-file throughput, the native picker
dialog, or final edited playback.
