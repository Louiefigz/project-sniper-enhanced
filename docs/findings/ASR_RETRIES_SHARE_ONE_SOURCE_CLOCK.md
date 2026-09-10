# ASR retries must share one source clock

## The latency bug

The prior local Whisper implementation gave each attempt 3,600 seconds.
A GPU failure or unsafe word-timing result could trigger a CPU attempt with
another 3,600 seconds. Probe, audio extraction and provenance hashing were
outside that allowance. A setting that looked like a one-hour limit therefore
permitted two hours of model work plus preparation and verification.

This is independent of billing: the old path was local-only by default and
still did not authorize a paid fallback. Local execution can nevertheless
consume an unacceptable amount of production time.

## The correction

Capture one absolute monotonic expiry before the source's transcription work:

```python
deadline = LocalAsrDeadline.start()
before = observe_source(path, authority, deadline.guard)
result = run_worker(path, deadline)
after = observe_source(path, authority, deadline.guard)
atomic_write_json(output, result, deadline.guard)
```

The existing `WHISPER_CPP_TIMEOUT_SECONDS` setting is now an aggregate positive
integer from 1 through 3,600. Earlier caller deadlines can only shorten it.
Every probe, extraction, GPU attempt, CPU fallback, timing retry, bounded JSON
read and full provenance check consumes the same decreasing remainder.
Timeout is terminal, not a reason to acquire another attempt's full credit.
The installed model, eight-thread default, mono 16 kHz conversion and existing
word-timing quality rules are not reduced to meet the deadline.

## Cancellation has to follow actual process ownership

Wrapping a Python worker in a process-group timeout is insufficient if that
worker starts each FFmpeg/Whisper child in a separate session. Killing only the
wrapper can leave the expensive processes running.

For the local Producer/Study worker path, the parent uses the existing owned
runner to create one new session. The explicit private CLI flag enables a
shared group only after the worker proves its own PID, group and session are
the same. Its leaves stay inside that group. The parent cleans the complete
group on success, failure and expiry. Ordinary directly imported local ASR
retains independently owned leaf groups. No environment flag activates the
shared mode, and no caller's unrelated group is signalled.

The new six-test process cohort passed in 1.732 seconds. It included real tiny
Python children that ignore TERM, retain descendants after successful exit,
exceed a leaf deadline, or overflow output. The parent observed each exact
test group absent before returning. The broader runner cohort passed 23 tests
in 3.558 seconds. No ASR model or media was used in these fault tests.

## Limits of the claim

This is a per-source ASR work allowance, not a whole-editor throughput promise.
Fresh source admission remains a separate measured preparation stage. Multiple
sources need an explicit original parent deadline to share a larger request's
budget. Clipper's separate channel preparation and caller-owned Study cache
writes are not automatically covered by a single core invocation.

Hashing and filesystem publication use cooperative checks around bounded
reads and immediately before atomic replacement; this does not promise that
an OS filesystem syscall cannot stall. Cancellation/reaping may consume a
small separate cleanup interval and never grants extra model work. The owned
parent must remain alive; arbitrary executables that deliberately create new
sessions or abrupt death of the owning parent are outside this qualification.

Do not accept partial output to meet a deadline. Expired, malformed, duplicate
or error-bearing worker output must remain a failed transcription, with no
new authoritative transcript replacing a prior valid one.
