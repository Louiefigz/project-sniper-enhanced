# Private metadata guards are not receipt serializers

Date: 2026-09-07

One tiny, instrumented presenter/caption cold read decreased from **4.863s to
1.236s** after removing repeated canonical receipt serialization from its
private metadata guard. No callback or file-verification pass was removed.
This is a finding about one TEST fixture, not a render-speed, full-program,
two-hour-target, media-quality or approval qualification.

## Why two caption cues produced hundreds of checks

The fixture contained two cues, two caption pages, 15 local caption files,
45 external files, and one binding dependency in addition to the plan,
manifest and timeline references. Its held metadata serialized to 24,778 bytes.
It used real tiny held files, with V8 selection and original decoder facts
explicitly TEST-stubbed. The diagnostic did not launch a decoder or renderer.

`held_cues` calls the existing strong `read_caption_projection`. Its guarded
file reads are intentional. The expensive part was the work attached to each
callback, rather than the two cue/envelope geometry comparisons:

1. Four inventory verification passes observe four bound input references
   twice and 60 local/external references twice: 128 file observations.
2. Four document holds and 12 JSON reads bring the total to 144 observations.
   The JSON reads cover three input documents, four projection documents,
   four cue/page receipts, and the final candidate-plan comparison.
3. Each file fits in one chunk in this fixture. A read checks the guard before
   and after the observation, and before and after the chunk: 576 callbacks.
4. JSON post-parse checks and phase, graph, cue and final checks bring the
   outer guard count to 605.
5. That outer guard checks held metadata both before and after the original
   caller callback, plus once when constructing its original hold:
   `2 × 605 + 1 = 1,211` held-metadata checks.

The nested presenter guard also canonicalized the original input documents,
arguments and captured reference projections on every callback. Receipt
serialization includes cross-runtime number and Unicode rules. Repeating that
work hundreds of times dominated this small read.

## Same diagnostic, before and after

Both accepted observations used the same invocation, fixture constructor,
original 30-second diagnostic limit, and single profiled read. Only the log
destination differed. Setup was outside the profiled read but inside the
diagnostic timer. Imports and interpreter startup preceded that timer and are
included in the complete-command wall time. Cleanup and profile-result
collection are included in the setup-through-cleanup measurement; final JSON
printing and the log pipeline are included only in command wall time.

| Measurement | Before | After |
| --- | ---: | ---: |
| Fixture setup | 0.178966s | 0.180681s |
| One cProfile-instrumented read | 4.862824s | 1.236425s |
| Setup through cleanup | 5.044560s | 1.420180s |
| Complete command wall | 5.31s | 1.72s |
| Outer guard cumulative time | 4.688223s | 1.095759s |
| Nested presenter guard cumulative time | 3.853348s | 0.318009s |
| Caption `_held_hash` cumulative time | 0.445142s | 0.417396s |

Cumulative profile times **overlap**: a parent includes its descendants. Do
not add the last three rows or subtract their sum from elapsed time. The
before profile attributed 3.772297s cumulatively to cross-runtime canonical
serialization. The after result includes profiler overhead too; fewer Python
calls also change that overhead. These are single observations, not a latency
distribution or an uninstrumented production benchmark.

| Work counter | Before | After |
| --- | ---: | ---: |
| Outer guard callbacks | 605 | 605 |
| Nested presenter guard callbacks | 610 | 610 |
| Held-metadata checks | 1,211 | 1,211 |
| File observations | 144 | 144 |
| Inventory verification passes | 4 | 4 |
| `lstat` calls | 117,369 | 117,369 |

All fixture counts and the 24,778-byte held-metadata size matched. This
optimization left `guided_presenter_caption_read.py` unchanged, including its
two-sided callback checks and its strong caption read. It changed only the
private comparison work beneath `guided_presenter_read.py`.

An earlier exploratory profiling attempt was **invalidated** when the existing
caption dependency fence detected a concurrently changed production dependency.
Its partial profile is not a successful measurement and is excluded from this
comparison. The failure remains in the task tool output. The shared dependency
was restored and independently checked against retained original bytes before
the accepted work continued. No new held hash was substituted into that failed
read. This is also why fault tests must target validated TEST-owned files, never
an arbitrary entry in an external-dependency inventory.

Earlier seven-test and expanded ten-test cohort wall times were different
workloads, not an A/B comparison. Likewise, the later removal of a redundant
outer opening-reader numeric spelling check is not part of the paired
measurements above.

## Two different identities serve two different purposes

A persisted receipt needs the existing canonical JSON and SHA domains so that
Python and TypeScript agree on the same document. A private callback guard
needs to answer a narrower question: **did these exact original in-memory
arguments change while the callback ran?** It need not recreate a portable
receipt on every invocation.

The private implementation uses `hold_read_metadata` and `same_read_metadata`
in `scripts/producer/guided_presenter_read_fingerprint.py`. Despite the module
name, the hold is a detached, type-tagged tree, not a persisted content hash.
It copies dataclass fields recursively rather than retaining a supposedly
immutable record as its own reference value. Comparisons still run on every
callback.

The ordinary initial `capture_input_binding` and canonical argument validation
remain in `_read_guard`, as do the initial file-reference checks. Thus the
private helper's ability to represent bytes, tuples and large stat integers
does not admit those values into a JSON contract that previously rejected
them. Public receipt constructors, canonical hash domains and source admission
are unchanged.

The detached comparison preserves distinctions that canonical receipt JSON
intentionally cannot use as a Python mutation detector:

- An integer becoming an equal-valued float or boolean is a change.
- A list becoming a tuple is a change; JSON object insertion order is not.
- Added, removed or changed JSON fields are rejected. Mapping keys remain strings.
- Finite float values retain their binary representation, including signed
  zero. Nonfinite initial metadata is rejected.
- Captured entry bytes and every original source/stat field remain held.
  Nanosecond integers are compared exactly, not converted to JS numbers.
- Mutating a frozen dataclass through `object.__setattr__` does not mutate its
  detached hold. Input/capture object and original callback identity checks
  remain separate and active.

Every original source, namespace, byte and deadline callback remains. All
strong caption inventory and JSON reads remain. The outer caption guard still
checks its metadata and original file identities on both sides of callbacks,
including the final callback after report reconstruction. A snapshot is not a
new source observation, a stopped-process fact, an execution capability, a
face/framing observation, or an approval.

## Regression evidence and boundaries

The new 11 focused tests passed in 0.430s suite / 0.69s command wall. They cover
unchanged callback counts, no per-callback receipt canonicalization, initial
JSON/ref refusal, numeric/container changes, frozen-record mutation, full
capture/stat values, original object identities and unchanged exception/time
propagation.

The subsequent shared pure/stub regression ran 84 tests in 34.940s suite /
38.01s command wall: 83 passed and one stale message expectation failed. The
negative correctly rejected an integer-to-float substitution earlier with
`presenter cold read original arguments changed`; its assertion expected the
later local `original argument types changed` message. That failure was retained
and reported, not converted into a successful check or a relaxed guard. All
new focused tests and the selected caption/body/legacy mutation cases passed.
Any later corrected test run is separate evidence.

Do not use this pattern to cache source freshness, skip another byte read,
reuse a deadline after expiry, or trust serialized observations as execution
ownership. Do not retain a private hold across a different request or reader
lifetime. Do not compare only object identity or Python dataclass equality:
both can miss relevant mutations. Initial schema, size, type and reference
validation must still happen before constructing the hold. If a callback can
change files, keep the caller's actual file/parent checks; metadata equality
does not prove file equality. This does not defend against arbitrary same-user
code introspection or a hostile process rolling back the machine state.

The optimization is useful when profiling shows repeated serialization of
already held metadata inside a dense callback loop. It is not a reason to
replace canonical serialization at a persistence, cross-language or authority
boundary, and it offers no measured benefit for large real media from this
tiny-file result alone.

## Opening dependency lifetime follow-up — September 8

The new internal `guided_opening_lifetime.py` retains the initial successful
source-hash pass and independently holds bounded input/claim/code/tool files.
Repeated guards inspect those original file and ancestor identities; they do
not hash source media or tools again. The original opening clock is borrowed,
not restarted. Final whole-byte and audiovisual verification is still required.
This helper is not yet connected to production media execution.

In a synthetic fixture with524 held files and32 original sources, one hold took
252.448ms and26 subsequent guards took273.006ms (10.500ms average), with zero
subsequent file hashes. A tiny fixture's100 guards took34.009ms. The actual
14-test command passed in1.03s wall. These are one-run local metadata results,
not proof of a render-speed improvement or of the two-hour video target.

Two permanent adversarial tests caught mistakes in the first implementation:

- Sealing a secondary source alias only after dependency capture let a hash
  callback replace it with an empty source set during construction. Bind the
  original aliases **before** those callbacks, including the initial empty
  file-collection state; change that state only at the explicit internal commit.
- Calling a replaceable instance check method let a test override that method
  and skip input-mutation checks. Internal security boundaries now call the
  class implementation directly and reject unexpected instance fields.

The original metadata/retained-field snapshots live in private weak-key maps,
not on a replaceable `original` property of the holder. This is a same-process
correctness boundary, not defense against arbitrary code execution. Full
metadata comparisons bracket the source sweep; each source's cheap clock
callback does not repeatedly traverse the entire plan and pipeline. Avoid
turning an O(files) check into O(files × complete-plan-size) by attaching the
full parent guard to every low-level clock check.

The Unix-socket fixture needed a short canonical TEMP path on macOS and an
explicit local-only socket test permission. Failed setup attempts were retained;
they did not exercise behavior. No real daemon, decoder, provider or footage
was used. The test's mutation helper accepts only explicitly named, originally
created, canonical single-link regular TEMP files—not an implementation
inventory path selected at runtime.

## Retained logs and reproducible invocation

The local evidence files are:

- Before: `/private/tmp/sniper-presenter-caption-cold-profile-20260907.log`
- After: `/private/tmp/sniper-presenter-caption-cold-profile-after-20260907.log`
- Shared regression, including the stale assertion failure:
  `/private/tmp/sniper-presenter-read-private-guard-regressions-20260907.log`

The diagnostic command below is the measured invocation. The before run used
the first log path and the after run used the second. Choose a **new** log path
for any repeat; do not overwrite retained evidence. Run from `PROJECT_SNIPER`
under a coordinated source-stable window. A source-fence failure invalidates
the observation. Running this against later code creates new evidence; it does
not reproduce the historical source version or authorize reverting a shared
checkout. No command here should be treated as media or provider authorization.

```sh
set -o pipefail
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts/producer:scripts/producer/tests /usr/bin/time -p .venv/bin/python -c 'import cProfile,json,pstats,signal,time; from dataclasses import asdict; from _presenter_caption_read_fixture import CaptionReadFixture; from guided_presenter_caption_read import verify_presenter_caption_picture
started=time.perf_counter(); prof=cProfile.Profile(); fixture=None; result={"scope":"TEST tiny-file diagnostic; V8 selection and original decoder facts stubbed; no media qualification","limitS":30}
def expired(signum,frame): raise TimeoutError("Original 30s diagnostic deadline expired")
signal.signal(signal.SIGALRM,expired); signal.setitimer(signal.ITIMER_REAL,30)
try:
 fixture=CaptionReadFixture(); held=fixture.held; result.update(setupS=time.perf_counter()-started,cues=len(held.data["shards"]["entries"]),pages=len(held.data["pages"]["entries"]),localFiles=len(held.files),externalFiles=len(held.external),dependencies=len(held.binding.dependencies),heldMetadataBytes=len(json.dumps(asdict(held),sort_keys=True,separators=(",", ":")).encode()))
 read_started=time.perf_counter()
 with fixture.selected(): prof.runcall(verify_presenter_caption_picture,fixture.pictures,fixture.read,held,fixture.layers)
 result.update(state="passed-diagnostic-only",profiledReadS=time.perf_counter()-read_started)
except Exception as error:
 result.update(state="failed-invalid-diagnostic",error=str(error)); raise
finally:
 prof.disable(); stats=pstats.Stats(prof); rows=[{"file":key[0],"line":key[1],"name":key[2],"calls":row[1],"selfS":row[2],"cumulativeS":row[3]} for key,row in stats.stats.items()]; result["topCumulative"]=sorted(rows,key=lambda row:row["cumulativeS"],reverse=True)[:24]; result["topSelf"]=sorted(rows,key=lambda row:row["selfS"],reverse=True)[:10]
 if fixture is not None: fixture.close()
 signal.setitimer(signal.ITIMER_REAL,0); result["setupThroughCleanupS"]=time.perf_counter()-started; print(json.dumps(result,indent=2))' 2>&1 | tee /private/tmp/sniper-presenter-caption-cold-profile-after-20260907.log
```
