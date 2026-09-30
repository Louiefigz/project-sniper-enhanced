# Authorized Shorts production

Implementation entry points for the maintained engine. This document describes
wiring, not a completed end-to-end qualification. The September 28 completion
work defers test suites and real video qualification at the operator's request.

## Authorization and clock

After source inspection and candidate review, the operator's approved exact title
and transcript-bound selection become the input. Do not reopen those decisions
or ask for the same approval again. Record each approval using the closed input
shape in `scripts/producer/studio/production/inputs.py`, then run:

```sh
./sniper python3 -B scripts/producer/native_batch.py start --batch SESSION --clips A,B --approval A=/absolute/A.json --approval B=/absolute/B.json
```

The authorization is durable before capacity inspection, source hashing and
engine freezing. Those steps count. Repeating the same start resumes its
original clock and approvals. A conflicting start is refused or retained as a
staged authorization; `staged-starts` reports it and `discard-start --name NAME
--reason TEXT` records an explicit disposition. Earlier missed authorizations
remain visible. Do not create a fresh batch to erase elapsed production time.

Each newly authorized Short has 2,400 counted production seconds. Only intervals
observed by the heavy-work scheduler as waiting solely for occupied render
capacity can be excluded. Its durable `capacityClock` records settled credit,
active owners and uncertain observation gaps. Preparation, hashing, rendering,
encoding, review, revisions, human holds and handoff count. Other productive work
for that Short overlapping a wait counts too: live or ready AI and check tasks of
the Short or of the whole run, and ended work still holding its slot unless it
completed. The enrolled director counts as working on every Short until it
declares otherwise: `director-activity --batch SESSION --task DIRECTOR --epoch N
--token T --all --state idle` (or `--clip ID`), and `--state working` before it
authors or reviews itself. That declaration is the director's own claim, never an
observation. Unknown host pressure, disk
pressure, unsupported mixes, quarantined cleanup and missing heartbeats earn no
credit. Forecast queue delays do not themselves earn credit. The pool marks
which of its waits are for occupied capacity (`native_work_pool_credit.py`): a
heavy render's wait counts only while every live heavy slot is occupied, or
while a live exclusive, out-of-profile or older-engine exclusive member holds
the pool. Queue order or memory while a live slot is free, slots quarantined
for unverified cleanup, disk headroom, a qualification session and audio-class
work earn nothing.

The clock, launch allocations, task deadlines and status use the same settled
credit. A render owner waiting for the pool extends its own wait only by that
settled credit: a wait that earns none (other work of the Short runs, or the
wait is not for occupied capacity) ends after the owner's capacity patience (at
most 600 seconds) with `capacity-timeout`. Owners retain their independent active-work limits and cleanup reserve.
Retries and changed approval records preserve already spent time and counters.
Long outputs and older saved Short authorizations retain their existing clock
policy. A Long never borrows a Short's queue credit.

Budget records are schema 8, this release's one schema step. New Shorts get the
v2 `capacityClock` (`studio/production/queue_clock_schema.py`). A batch written
by an earlier engine (schema 5, 6 or 7) is lifted to 8 on read; its v1 clocks
earn no further credit and keep what they earned. The fields this release adds
are listed, with their owning steps, in the release field ledger in
`studio/native_budget_schema.py`'s docstring. Optional fields
(`production.storage`, `production.closure`, an attempt's
`admittedForecastSeconds` and `late`, a delivery's `late`) are absent until
their writer lands and are never defaulted. A schema-5 record in the A5-forecast
shape is refused by name. An older engine refuses a schema-8 record by version.

## Coordinator and media execution

The buyer's active agent coordinates AI authoring and independent review. The
media dispatcher is a separate supervised process; it does not create AI workers
or fabricate their results. Use the host capability and supervised-governance
requirements already enforced by `production/host_contract.py` and enrollment.

The coordinator enrolls its exact host handle with `native_batch.py enroll`,
submits the dependency graph with `enqueue --tasks FILE`, claims AI/check work
with `next`, and records real attached handles and artifacts through `attach` and
`complete`. Every task uses immutable input identity, prerequisites and fenced
claim epoch/token. `change-approval --approval FILE --reason TEXT` revokes stale
work; a superseded callback cannot satisfy a current dependency.

A logical AI slot is released only on termination evidence that identifies the
execution (`production/task_end.py`). A completed or failed host turn keeps its
slot until an end event of that host is proven (none is proven yet), and the
task's reason says why the slot is held. A process handle's slot is released
once reconcile sees that exact process identity gone with an empty group. A
claim whose launch call itself failed is released with the launch tool's own
output, verbatim: `release --launch-error TEXT`, or `complete --failure
launch-failed --detail TEXT --launch-error TEXT`; an AI release without it is
refused. An execution that attaches after its claim's deadline is refused, yet it
exists: its handle is bound and the task ends through the same rule, its slot
held. Cancellation wins: a result reported after a cancel request is kept as
history and never publishes.

Each media request names its exact batch, task, clip, project, fresh output
folder and allowlisted route/options (`production/media.py`). It carries no
arbitrary shell command. Start `native_batch.py dispatch --batch SESSION` after
submitting work. The dispatcher reconciles before claiming, queues supervisors
at the actual host pool, and records each exporter completion. The pool still
enforces measured capacity and FIFO order. A restarted dispatcher does not
relaunch an uncertain claim. The outer watchdog bounds the entire exporter,
including setup and publication, and cleans up owned process groups before
settling the task.

Use `status --batch SESSION` and `next --peek` for current work and refusal
reasons. Per-clip status distinguishes wall elapsed, counted production,
excluded render queue and uncertain intervals, with current forecasts and SLA
misses. Excluded time is bound to evidence: only the owner process that
registered a wait records it, and a wait earns credit only when it names its
pool ticket and the live members it waits behind; any other wait is counted as
uncertain. An owner whose process is gone while it worked is moved to the
clock's `orphans` (its children may still run, so its interval is counted as
uncertain); it no longer counts as the Short's work or toward the owner limit.
A waiting owner whose process is gone is simply removed: it launched nothing.
Every 300 credited seconds (at most 32 times per Short) the trail
gets a `capacity-checkpoint`, and `status` checks each Short's credit against
its trail (`capacityAudit`; per output `creditVerified`: false for a total the
trail cannot account for). This detects a hand-edited record, not a writer who
rewrites the record and its trail together. Deadline refusal is not a completed video. The default `status` reads each
visible hand-off from its recorded `clip-handed-off` trail event and needs no live page;
`status --handoff FILE` re-verifies that file against the live review page and Studio, so it
is valid only while both are open. `--full` prints every section; the default is compact.

### Pool capacity, qualification profiles and older installs

Utility owners (selected-source preparation, review recognition, source-cache aliasing, public web
capture and review-bundle media preparation, which is ffmpeg-only and uses the `audio` class) wait in the
pool FIFO like any owner (`studio/native_owner_queue.queued_owner`). They carry no
production task, so their wait earns no capacity credit and counts against the Short they serve; P1
reviews that accounting (P0 Step 5.11).

`start --pool-slots` cannot exceed the host's heavy capacity for Short renders
from the pool qualification record (one job until `studio/pool_qualification.py`
records more), so forecasts are never more optimistic than the pool. The legacy
schema-1 host record keeps serving Short batches, their supporting owners and
older installations' owners until a schema-2 profile covers Shorts. A schema-2
profile is bound to the engine identity and to the longest output it exercised:
`start` caps `--pool-slots` at the best Short capacity, and every launch forecast
uses the batch's longest known output of each format, so a Short longer than the
profile forecasts one slot. At admission, work no profile covers (a Short longer
than its profile, an unexercised stage or class, another engine, a Long) starts
only on an idle pool; beside running work it fails at once with
`NativeWorkUnsupportedMix`, never queuing ahead of the batch. The reasons are in
the owner receipt (`pool.modeRecord.unmatched`).
`studio/pool_qualification.py show` prints the host identity, the pool mode it
currently yields and the policy constants.

Write a v2 profile only from a real qualification batch on this host: first
`studio/pool_qualification.py serial --jobs FILE --evidence DIR --deadline-seconds N`
for the serial references, then `run` with the same jobs, `--heavy-slots N`,
`--class-mix heavy-only|mixed` and `--record`. The profile
(`studio/pool_qualification_profile.py`) is written only when every job passed as
a complete, non-reused full export that matched its reference, N jobs held heavy
work at the same instant, every job recorded its format, duration, picture size
and source-cache state, the engine identity did not change, and a `mixed` claim is
backed by the jobs' own audio-stage owners overlapping heavy owners. Each owner
receipt's `queueSeconds`, `pressureWaitSeconds` and `cpu` summary are the
evidence it reads.

Mixed installations on one host: an older pool client (for example an rc4
install) reads only the schema-1 record and a member's class, memory and root
disk, keyed by device. Work it cannot understand (an exclusive Long, schema-2
members, off-root disk, and any disk reserved in an APFS container, whose other
volumes it keys separately) holds a compatibility fence: tickets with sequence 0
that every older request counts as ahead of it. **Trade-off:** this engine's
fenced work keeps overlapping, and the older client waits (on APFS it never
starts while any of this engine's members runs; if new work keeps arriving it
fails with its own capacity error). **Retire older installs (or let their work
finish) before starting a clocked batch.** Every fenced member records the whole
memory budget as the charge older clients read, so while any fenced member of
this engine exists, live or quarantined, older clients do not start until
`native_work_recovery.py` recovers it. While any fence is held, none of this
engine's requests waits behind an older client's queued request; counting them
would deadlock. Upgrade every install before relying on schema-2 profiles.

Test runs: every test method, whether run through `selftest.py` or as a single
module, gets its own private authority root and pool namespace, created on first
use and removed after it (`scripts/producer/tests/_live_state_isolation.py`). A
private namespace also means the host pool qualification record is never read, so
forecasts in tests see one heavy slot unless a test says otherwise. Any read or
write of the real `~/.project-sniper/production-budgets`,
`~/.project-sniper/native-pool` or the host pool namespace, and any write elsewhere
under `~/.project-sniper`, is refused before the system call: inside a test method
as `LiveStateTouched`, which fails that test even when it is caught; in a class or
module fixture as a class-level error. Python child processes a test starts carry a
child tripwire: a refused child exits 97 and its report fails the test or the run. A
child started with `-I`, `-S` or `-E`, or with an environment that drops `PYTHONPATH`,
is not armed; such children are reviewed one by one.
The supervised real-media scripts in `scripts/producer/tests/` use a private
authority root but the real host pool, so they share its heavy-slot limit.

## Build, reviews and delivery

Run `context.py --role clip-owner` with the exact plan/project and `--batch
SESSION --clip A`. Share source/reference evidence through its evidence-draft
and evidence-seal commands. Role packets carry current approved words and source
identity. They assign governing instructions and generate empty observation
structures, never reviewer findings.

1. The independent plan critic receives `context.py --role plan-critic --plan
   /absolute/plan.json --batch SESSION --clip A`. Submit actual observations
   using the packet's `native-review.ts submit-prebuild` command, then bind a
   passing record with `bind-prebuild` before `native-short.ts build`.
2. Run static preflight and the preview export. The exporter runs early static
   checks and sealed audio preparation before picture work. A motion critic
   receives `--role motion-critic --preview /absolute/motion-previews.json`;
   typed playback evidence and current approval identity gate a full export.
3. Export using `--preview-reviews /absolute/MOTION-REVIEW.json`. Source capture,
   picture, audio, encoded verification and owned cleanup remain separate gates.
   The final critic receives `--role final-critic --export /absolute/attempt`.
   `native-review.ts check-final` reports exactly what the record establishes.
4. Open the delivered video and matching editable project using
   `native_handoff.py open ATTEMPT --owner OWNER --record NEW.json`, then confirm
   the actual browser views through its `confirm` command. Only that confirmation
   can satisfy `native_batch.py handoff --batch SESSION --clip A --confirmation
   /absolute/confirmation.json`. Then close the batch. While media work is live,
   `close` drains instead and is run again once that work ends. At closure the
   enrolled director's assignment ends, every other live AI task is revoked, and
   every task still holding a slot or an unresolved resource is listed in
   `production.closure` and in the host record `unresolved-executions.jsonl`,
   where it stays charged until termination evidence resolves it. Until
   admission counts that record, a closed batch with unresolved AI work refuses a
   new batch by name, and so does an archived one while that record is missing.
   While the batch is active or draining, `settle-resource --task ID --statement
   TEXT` records the operator's words on unresolved work, or on revoked work not
   yet settled; it releases nothing and is refused once the batch is closed.
   State whether each is a checked MP4 (a technical pass, CHECKED FOR REVIEW) or a
   review draft, with its open findings.

Every critic packet also names its author session and shared evidence when
available. Review submissions reject stale media, changed approved words and
unsupported inspection claims. Stills, playback and listening are distinct
forms of evidence. Technical checks never certify that somebody watched or
listened. Follow the existing whole-video review and title/reference duties.

Resolving a role packet for a batch clip (`context.py --role ... --batch --clip`) appends
one `packet-resolved` event (packet SHA-256, role, clip, batch-clock seconds; at most
512 bytes) while the batch is active. It changes no record field and is new work, so it
is refused once the trail reaches its reserve. Review submissions and gates time a
review's claimed playback and listening from it on the batch clock.

If a complete labeled review draft is the appropriate next artifact, use
`native-short.ts build-draft` for a plan with pending or nonpassing review, then
`native_export.py PROJECT NEW_ATTEMPT --review-draft`. Its receipt preserves
pending findings and does not claim final QC. A draft from a final-eligible
project can be promoted using `--promote-draft ATTEMPT --preview-reviews FILE`
after current motion review; promotion preserves the exact encoded bytes and
still runs final gates. A draft-built project cannot become final through that
shortcut; revise the plan and create a properly reviewed final-eligible build.

Build revisions into fresh directories with `--parent PREVIOUS_PROJECT` to
preserve logical clip lineage. Studio host IDs are assigned before project
hashing, preventing Studio opening from changing the authored package. Handoff
holds are per project/owner and never close another clip's active view.

## Repair and delegation boundaries

Short revisions built with `--parent` retain verified clip lineage. The preview
reader follows that lineage, compares content dependencies and retains unchanged
preview judgments. Scoped compositions invalidate their affected preview windows
with context; an unproved composition scope makes its entire content a global
dependency. Changed source/timing/audio or global executable inputs invalidate
all dependent work. A legacy schema-1 Short preview must be regenerated with
typed review evidence before it admits new full-picture work. Long packet and
section contracts retain their own route.

New standard Short exports retain every picture frame through bounded native
capture sessions. A sealed same-clip ancestor can donate unchanged frames when
current dependency proofs isolate the changed composition. The renderer captures
only that complete affected interval, plus sparse QC samples; copied good frames
retain their exact bytes. It then assembles/encodes the new picture and runs final
QC. Unchanged audio masters and source frames are independently reusable. A checked
promotion can use its exact sealed draft's retained frames. A terminal attempt
whose picture/audio stage completed but final QC failed may donate unfinished
picture work only after its stage, inputs and every owner cleanup revalidate;
its qualification stays `rendered-awaiting-final-qc`, never an inherited pass.
Every current final check still runs. Unsupported or incomplete old evidence
cannot donate. Proof chains exceeding the request reader's 16 MiB limit are
refused before publishing a new attempt.

New Shorts also acquire source PNGs through the same content-addressed store as
Longs. Source bytes, exact selected range, frame clock, colour transform and
extractor identity determine reuse, so a new staged project path alone does not
trigger decoding. The store admits every frame digest and retains the existing
exclusive publisher/reader leases. Historical path-keyed SDK entries are never
adopted. Cold extraction requires the current owner's disk expansion grant.
Default whole-composition acquisition retains SDK SDR/HDR negotiation; explicit
sequential acquisition supports SDR only. The SDK streaming opt-out reads the
same leased content view. None of these source changes has a rendered Short
qualification yet.

Retained frames consume disk space. Picture and draft owners reserve a conservative
full-frame allocation plus encoding headroom before starting; copied revision
frames also need space in the new attempt. No cache or prior attempt is deleted
to make the new work fit. The changed default's storage and speed are not yet
qualified by a real render.

A one-frame visual defect does not itself prove a one-frame dependency: a change
to an animation or caption can affect its whole visible interval. Changes to shared
HTML, source/timing, geometry, unproved scopes or global executable inputs require
a complete picture rebuild, with the reason recorded. The legacy `--sdk-streaming`
opt-out and historical outputs without retained picture frames cannot donate
local repairs; they need a new retained baseline. Exact completed whole stages
still reuse their existing recovery routes when all their inputs match.

This changed-region wiring has not been qualified with a rendered revision. It
does not establish a measured speedup or replace final encoded-output review.

The active coordinator creates and attaches the real planning, graphics/audio
specialist and independent critic subagents required by the brief and doctrine.
The task graph and role packets track those assignments and submissions; the
media dispatcher does not itself launch AI subagents or guarantee that a separate
specialist exists for every lane of every clip. Technical audio checks are wired
separately and never certify listening.
