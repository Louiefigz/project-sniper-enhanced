# STUDIO REVIEW LANE — manual control over the graphics layer

The default manual-control/review surface after a Producer render. HyperFrames
Studio (shipped by the pinned `hyperframes@0.7.33` —
`templates/motion/node_modules/hyperframes/dist/cli.js`) opens a generated
review project as a full timeline editor: the graphics-free base footage on
track 0, every `graphicsTrack` entry as a timed, panel-editable clip above it.
The operator (or an agent through the bridge) adjusts graphics there; the
edits are diffed back into `edit_plan.json`; `assemble.py` recomposites.

A trim-only plan with no graphics also opens in this view. It shows the exact
graphics-free base and an empty graphics layer; it does not invent a treatment.
Cut changes still belong in `edit_plan.json`, followed by a base rebuild and
Studio regeneration. The base clip is playback context, not an editable cut
timeline. Unsynced Studio edits retain the same overwrite protection.

**The render boundary is unchanged.** `hyperframes render` remains the only
render use of HyperFrames (`graphics/graphics_render.py`); footage stays
ffmpeg; Studio never renders the deliverable and footage never re-encodes in
a browser. The color doctrine is untouched. The generated studio dir is a
VIEW — never `hyperframes render` it.

The primary interactive entry point is the Producer skill in Codex or Claude
Code. This lane does not require the custom Sniper web UI. Continue the same
stored-intent, cut/review, render and QC contracts through the stage CLIs.

## Required review handoff: local playback and Studio

**Standing operator preference, September 15, 2026:** for Shorts and long-form,
show both views for each ready candidate or revision unless the user explicitly
requests a different handoff:

- **Local video review:** open the existing local review page/player with the
  exact checked MP4. Verify the current source, duration and playback; retain
  source comparison when the review page already provides it.
- **HyperFrames Studio:** open the matching editable project at its verified
  live Studio URL, so the user can make small adjustments. Check the project,
  duration, loaded footage and timeline seeking. Opening `index.html` via
  `file://`, pasting a project path, or showing a flattened MP4 does not complete
  this step.

Opening Studio must not change a delivered project. Pinned Studio (HyperFrames 0.8.31) gives every
element without a `data-hf-id` a minted id when it serves the project and writes the file back
re-serialized: `persistHfIdsIfNeeded` for `index.html`, `stampFileHfIds` for each previewed
`compositions/*.html`. The delivered MP4's receipts then stop verifying ("current authored project
differs from supervised sources"), and a promotion or export of that project is refused. New native
Short builds therefore refuse an index or mounted composition with an element Studio would stamp
(`src/lib/server/native-studio-host-ids.ts`); authors add the ids with `native-short.ts studio-ids`
before hashing a catalog adaptation or extension markup. Projects built before this rule still rewrite
when opened; hand them off only after their MP4 is delivered, and expect their receipts to stop
re-verifying once Studio has loaded them. Evidence: a stamped and an unstamped copy of one build,
opened and previewed side by side; only the unstamped copy's three files changed.

Use the operator's requested browser or established browser preference. Keep
both views available in separate tabs; preserve an active review position until
the next candidate is ready. Start a newly presented candidate at the beginning.
Include both labeled live URLs in the handoff and record which candidate/project
they show plus the checks actually performed in the existing review notes.

### Local playback for a batch of native attempts

`review_player.py` serves the delivered MP4s of named attempts on one loopback page,
from a review-bundle manifest or `--attempt ID=/absolute/attempt` pairs:

```bash
./sniper python3 scripts/producer/studio/review_player.py serve --manifest /abs/review-manifest.json
./sniper python3 scripts/producer/studio/review_player.py serve --attempt A=/abs/A/final-v1 --attempt B=/abs/B/draft-v1
```

It prints its `http://127.0.0.1:<port>/` URL (`--port`, and `--serve-seconds` for a
bounded run), binds 127.0.0.1 only, refuses other Host headers, loads nothing from the
network and serves each attempt's recorded MP4 read-only, with byte ranges for seeking.
Labels come from each `delivery.json`: **CHECKED FOR REVIEW — technical checks pass;
editorial approval: see native-review.ts check-final** only when the review-bundle receipt
admission re-verifies now (the player does not read editorial reviews; `check-final` reports
`editorialFinal: approved` only for a typed final review), **REVIEW DRAFT** with its open findings,
otherwise NOT RE-VERIFIED (with the refusal), FAILED, PREVIEW EXCERPTS ONLY, IN PROGRESS
or CHANGED. `list` prints the same labels as JSON, and the running server answers
`/inventory.json` with them and its per-attempt activity: page loads (each with a token the page
carries), media requests of each attempt's exact MP4 route (404s, favicon and other paths are not
recorded) and the page's own playback reports (its script POSTs `/activity` when an attempt's video
fires `loadeddata` or `playing`; admitted only from this server's origin with an issued page token and
that attempt's route). A running page re-reads an attempt's receipts whenever the
delivery, the MP4, any pinned input or a top-level project file changes identity, so a
project Studio rewrote after the page first loaded stops showing CHECKED FOR REVIEW on the next load.
This is the MP4 view only; open and record the matching Studio project with
`native_handoff.py open` (below). Copy delivered MP4s and
receipts, never hard-link them: a second link makes later verification and review
readers refuse the file (`cut preview hash input is unsafe or over budget`).

### Record each output's hand-off: exact MP4, matching project, owned views

For each delivered native attempt (final or review draft), after `review_player.py serve`
prints its URL:

```bash
./sniper python3 scripts/producer/studio/native_handoff.py open /abs/Q1/final-v1 \
  --owner batch-<id> --record /abs/Q1/HANDOFF-final-v1.json --review-player http://127.0.0.1:<port>/ \
  [--pending-findings /abs/Q1/PENDING-FINDINGS.json]
```

Before any view opens it binds the delivered MP4 (the review player's own evaluator: exact
bytes, decode receipt, CHECKED FOR REVIEW only when receipts re-verify), validates the delivery's findings and
`--pending-findings` (same schema as `--draft-findings`), reads the approved content from the
batch authority (below), and hashes, without following links, every project file the delivery
pins, the top-level authored sources and every visible `.html`/`.htm` file; a linked file or
folder is named, never hashed or walked through. A refusal here opens nothing. It then writes an
O_EXCL intent file beside the record (`<record>.intent.json`: owner, token, attempt) and opens or
reuses that project's managed Studio view with the MP4 bound. It asks the live server who it is
(`/__hyperframes_config`: the registered PID and this project directory), loads the project as
Studio's page does (the main preview and every sub-composition preview: the requests on which
Studio stamps missing `data-hf-id` values), hashes again, re-runs the receipt reader and re-reads
the view. It confirms the review player (its server pid, port and start time) lists this attempt,
serves these bytes and shows the label the hand-off computed after the load.

The record (`native-visible-handoff`, schema 1, a new file outside the attempt and project) keeps
the MP4 path/SHA-256; the project identity before open and after load; the Studio URL, PID and
process start, ownership, holders and whether it served this project; the review-player URL,
server identity and label; the draft/final label and open and pending findings; receipts before
and after; the approved content comparison; and the view's cleanup state. `status` is
`views-ready` only when every check held; otherwise `handoff-incomplete` with named `failures`
and exit 2: `STUDIO_CHANGED_PROJECT` (Studio rewrote files while serving them; the receipts
reason is recorded), `MP4_RECEIPTS_NOT_REVERIFIED_BEFORE_OPEN` / `_AFTER_LOAD`,
`PROJECT_DIFFERS_FROM_DELIVERY` (including linked files and folders), `STUDIO_NOT_OPENED`,
`STUDIO_VIEW_OWNED_ELSEWHERE`, `STUDIO_DID_NOT_SERVE_PROJECT`, `STUDIO_NOT_LIVE_AFTER_LOAD`,
`MP4_CHANGED_DURING_HANDOFF`, `REVIEW_PLAYER_NOT_VERIFIED`, `REVIEW_PLAYER_LABEL_DIFFERS`,
`APPROVAL_BINDING_MISSING`, `APPROVED_CONTENT_DIFFERS_FROM_BUILD`, or a named unreadable step. Once the intent file exists a
record carrying the token is always written, including `handoff-interrupted` when the command is
interrupted or receives SIGTERM (for example an agent tool timeout); if the process is killed
outright, the intent file itself serves `release` and `prune-holds`. The views stay open either
way. A project built before the selection-id rule fails with `STUDIO_CHANGED_PROJECT`: report it
and keep the MP4 visible. The rewritten folder is no longer the delivered project; a corrected
revision stamps its authored markup with `native-short.ts studio-ids` (NATIVE_SHORTS_WORKFLOW.md),
builds a new project and exports it.

**Views-ready is not a visible hand-off.** `open` checks servers and leaves `visibleHandoffAt`
null. The interactive coordinator opens the review page and the Studio page for the operator,
then records it:

```bash
./sniper python3 scripts/producer/studio/native_handoff.py confirm --handoff /abs/Q1/HANDOFF-final-v1.json \
  --record /abs/Q1/VISIBLE-final-v1.json --review-page <reviewPlayer.url> --studio-page <studio.url> \
  --browser Chrome --attested-by "<who opened them, e.g. the coordinator session>"
```

It accepts only a `views-ready` record with no failures and its exact verified URLs, and re-runs
every check now: the MP4 bytes and label; the same registered Studio process (pid and start
time), live, bound to that MP4 and serving this project (loaded again), then the project identity
against the post-load identity (the operator's own Studio navigation can stamp more files); the
same review-player server serving these bytes with the after-load label
(`REVIEW_PLAYER_NOT_VERIFIED_AT_CONFIRM` otherwise). For the review page the evidence is observed,
not attested: the served page must itself report that its video element started playing this exact
MP4 route, from a page load after `viewsVerifiedAt` (`REVIEW_PAGE_PLAYBACK_NOT_OBSERVED` otherwise,
so press play on the review page). An HTTP request of the MP4, from `curl` or any other client, is
recorded as `mediaRequested` and never counts. The attestation states that the review page and the
Studio page were opened for the operator, with the caller's identity. Only when all of this holds
is `visibleHandoffAt` set. What it still cannot prove: that a person watched or listened, that the
window was visible or unobscured, or that playback continued past the report; a local program that
fetches the page can imitate its report. Playback, seeking, listening and approval remain the checks
below and the review records.

**Approved content (`approved-content-production-2026-09-27`).** The batch authority bound at
batch start is the only source of each clip's approved title and script; no caller-supplied
approval is accepted. When the export request names a batch clip (`productionBudget`), the
hand-off reads that clip's approval by name (`studio.production.api.read_approval`, approval-v2)
and requires the project folder's own binding (`approval_for_project`) to exist and name the same
clip; an unbound or differently bound folder, or an unreadable named batch, is
`APPROVAL_BINDING_MISSING`. An export that names no batch clip is read by its folder; a folder no
batch binds records `not-supplied`: approval is unknown there, never "not approved". The build is
read as B1 reads a
plan: the `catalogTitle` copy, else the built-in `canvas.titleCard` copy; the canvas source asset
and the source word index and text of every kept `canvas.occurrences` row, in output order. The
approved script is the spoken words, so word texts are each occurrence's source text, which
`canvas.captionCorrections` never rewrite; accepted caption display corrections are listed as
`displayCorrections` (occurrence, source text, display text, reason; any beyond 128 are counted in
`displayCorrectionsOmitted`) and are never a mismatch. The title is exact, normalization-only (NFC
and whitespace; reported, not material) or different; the source, the ordered word indices (the
same words in another order differ), the word texts, the merged cut seconds (against the approval's
merged second ranges), the transcript (the plan's admitted manifest transcript against the
approval's) and the writer-rule occurrence timing must equal the approval's, and the clip and batch
the delivery's production budget names. A mismatch is `APPROVED_CONTENT_DIFFERS_FROM_BUILD`,
reported and never repaired by changing content. Content approval is recorded apart from
`output.executionReview`, whose `humanApprovedRenderedOutput: false` speaks only for the render's
execution.

Later navigation in Studio can load more files than the hand-off load did; `confirm` re-checks.

**Owned views and holds.** A hand-off's `--owner` tag and token are recorded on a view only when
that hand-off launched it. Every hand-off relying on a view, including one that reused the user's
or another hand-off's view of the same project, is one hold naming its token and its intent and
record files; a plain unowned `managed_preview.py open` that reuses a view adds one user hold. An
owned open never replaces a stale view of its project unless its own tag launched it and no other
token or the user still holds it: otherwise `STUDIO_VIEW_OWNED_ELSEWHERE`, and nothing is stopped.
(A plain `managed_preview.py open` by the user may still replace its project's own stale view.)
`native_handoff.py views --owner batch-<id>` lists the owner's launched views with their holds and
retained process identities and counts every other active view, for workload qualification.
`native_handoff.py release --handoff <record or intent file> [...] --record <new file>` drops those
hand-offs' holds and stops, by verified identity, only a view a hand-off launched once no hand-off
and no user hold remains; the last hand-off holder's release stops a view its launcher already let
go. A view nobody's hand-off launched is never stopped by a release; a cleanup that is not verified
stays registered and exits 2. Release is bound to tokens, so two batches reusing one tag cannot
release each other's views. A view holds at most 16 holds; a full list is refused with the holders
named. The recovery for lost holds is `native_handoff.py prune-holds --project <dir> --record <new
file>`: it keeps a hold only while its intent or record file still names its token and that
hand-off has not ended without a view to keep (a record `handoff-incomplete` or `handoff-interrupted`
holds nothing), stops nothing and reports what it dropped. A registry record written by the first hand-off version (an owner tag
without a token) reads as a legacy view that no token release stops. Views of other projects are
never stopped or reused by a hand-off.

`native_review_bundle.py open <bundle> <id>` uses the same open, served check and Studio load for
a bundle's editable fork (an unowned view, like `managed_preview.py open`), reporting
`studioChangedOnOpen` apart from the operator's edits. The fork's single dialogue node carries its
own `data-hf-id`, so a fork of a stamped build is not rewritten when opened.

### Verify the browser that receives the handoff

Server readiness and media `readyState` are not playback approval. Test the
actual delivery browser, including the in-app browser when that is where the
operator is reviewing. A Chrome result does not establish an in-app result.
At the opening, a middle scene, and the final spoken passage, verify that the
current footage/caption/graphic is visible and future or expired clips are
hidden. Seek backward as well as forward, then play continuously through cuts.

Check live audio transport separately from the encoded audio checks. Repeated
`seeking`/`waiting` events during uninterrupted playback, unexpected pauses, or
audible chopping fail live review even if decoding, sample counts and loudness
passed. Record the browser, continuous playback interval, observed failures and
whether listening actually occurred. Never label signal checks or advancing
`currentTime` as a listening pass. A user report of choppy sound reopens this
check until the affected playback path is verified.

Managed Studio must use the same qualified runtime adaptation as native export.
Its same-document element checks are needed by embedded browser playback as
well as capture; launching stock Studio can skip clip visibility and audio
scheduling. Reuse that adaptation instead of adding per-project timing masks
or changing audio synchronization tolerances to hide the failure.

Reuse the managed preview entry points below: native projects use
`managed_preview.py open`; legacy generated graphics views use
`studio_review.py open`. Opening a ready native project needs no rerender.

A native review draft (`review-draft.mp4`, status `native-short-review-draft`) may be
handed off the same way, labeled **REVIEW DRAFT - editorial review pending; not
final**. Review bundles accept it, keep its `.review-draft.mp4` name and show the label
on the local page. `managed_preview.py open` of a draft-built project reports
`reviewState: "draft"` and prints the label; the composition is not altered and
nothing is burned into the video. Keep the last checked MP4 visible beside a draft.
If a project is sealed as verification evidence, prepare a separate editable
revision with its dependencies intact and record its origin before handing it
over for edits. Preserve the checked project, MP4 and receipts.

Studio exposes the layers supported by the selected project route; the legacy
graphics view does not make baked footage editable. The checked MP4 remains the
reference for final encoded picture and mastered audio. After Studio changes,
label the MP4 as the previous render until the affected stages are rebuilt and
checked, then refresh both views to the new revision.

A headless exporter may finish technical QC without opening browser tabs; the
owning interactive task completes this handoff. If either view cannot open or
pass its checks, keep the working view available and report the missing view and
actual failure. Do not describe the two-view handoff as complete or rerender
solely to repair a preview-launch failure.

## The loop (one orchestrator: `scripts/producer/studio/studio_review.py`)

```bash
PY=.venv/bin/python3
REVIEW=scripts/producer/studio/studio_review.py

$PY $REVIEW open    <producer_dir>            # generate/refresh + serve (no browser opens; open the printed studio: URL)
# ... operator edits panels/timing in Studio (persists to project files) ...
$PY $REVIEW sync    <producer_dir>            # dry-run diff of Studio edits vs plan
$PY $REVIEW sync    <producer_dir> --apply    # fold edits into edit_plan.json (gated)
# Run applicable current-plan gates/reviews and renew any stale receipt now.
# Then run the exact assemble command printed by sync (same manifest).
$PY $REVIEW sync    <producer_dir> --apply --assemble   # only if no intervening review is required
$PY $REVIEW status  <producer_dir>            # state + the next action
$PY $REVIEW context <producer_dir> --context-fields selection,lint  # agent bridge
$PY $REVIEW stop    <producer_dir>            # shut the preview server down
```

`open` requires `<producer_dir>/edit_plan.json` + `<producer_dir>/base_final.mp4`
(the graphics-free base from `render.py --skip-graphics`; if missing, `open`
prints the exact command). It generates `<producer_dir>/studio/` via
`studio/studio_project.py`, picks a free port in **3990-3999** (bind-probe),
launches the installed preview under the shared native lifecycle (browser
auto-open OFF), records `{port, pid, url, startedAt}` in
`studio/.studio-server.json`, and prints the URL
(`http://localhost:<P>/#project/studio`). `stop` verifies the recorded pid is
and its retained descendants have exited before clearing ownership. The central
private registry (`studio/managed_preview_registry.py`) keeps one managed preview
per project, at most six across draft directories/checkouts: opening another
project never stops or switches an existing view, repeated open of the same
project reuses its exact live server (also one another checkout started from a runtime
with the same content identity), and replacing that project's own stale-runtime server
first verifies its cleanup. Beyond the bound the refusal names every running view and
stops nothing. Studio startup takes a slot of its own host-pool class, `studio`
(`native_work_pool_studio.py`: two slots, 1 GiB memory and 256 MiB disk, all provisional until a Studio startup
tree is measured), never a render slot, so a finished Short's view opens while other Shorts render; it still
waits for the memory budget and disk headroom every member shares. The slot is released once the server is
ready, when nothing was started, and when a failed start's cleanup is verified: nothing was spawned, or what was
spawned is gone, root and process group (`managed_preview_launch.settle_failed_launch`, `group_survivors`; a
descendant that left the session with `setsid` is not covered, as for every tool process). Only a failed start
whose cleanup is unverified keeps its slot quarantined (recover it with `native_work_recovery.py <nonce>`) and
its project fenced. The wait for a Studio slot holds the Studio registry lock, so other projects' `open`, `stop`
and `status` wait with it, up to the open's deadline (60 s by default). An older install (the `4a15560` engine)
reads a live Studio start as a quarantined member and refuses its own admission while one runs (it fails closed):
do not upgrade while batches of an older engine run. A startup that fails
before any child exists is recorded as stopped. An unfinished launch (an opener that was
killed or interrupted, or a server whose stop was not verified) keeps only that project's
record in `launching`, and only while a process of that launch still runs: its retained
identities, or the server it started, found by its exact command (this project, the
recorded port and the recorded runtime CLI; stock servers, other ports and other
checkouts are never taken for one, and a record from earlier code that names no port is
settled by its retained identities alone). Every `open`,
`list`, `status` and capacity check closes such a record once nothing of it runs; `open`
of that project replaces the survivor after admission, and `stop <project>` stops it.
A survivor that does not exit stays recorded and named in the error.

For an already-authored native project, use
`python scripts/producer/studio/managed_preview.py open <native-project> --port <P>`
directly. This serves its existing files without plan regeneration. Use this
managed entry point instead of raw SDK preview commands. Open the returned URL
through the app's browser control when a visible preview is wanted. The matching
`status` and `stop` actions read/check or stop the registered native project;
`list` shows every managed view. `open ... --review-mp4 <file>` records the
review MP4 the view accompanies, and `status`/`list` report whether those bytes
are unchanged; reopening with a newer MP4 rebinds it without restarting Studio.
`--wait-seconds` bounds the wait for another agent's registry operation. What Studio
writes into the project it serves is never a preview, static-preflight or source input:
its server record (`.studio-server.json` at the project root), its log (`.hyperframes/`)
and the SDK's own caches at the project root (`.thumbnails/`, `.waveform-cache/`,
`.transcode-cache/`), and likewise Finder's `.DS_Store` and AppleDouble `._*` files. So
opening or using Studio never changes reviewed preview units or fails an export running
for the same project. Every other file or folder, hidden or not, stays an input. Studio
reads the process table with C-format start times and UTF-8 text (`LC_TIME=C`,
`LC_CTYPE=UTF-8`), so a caller's locale, a non-ASCII project or checkout path, or an
unrelated process's argument bytes change nothing; a table it cannot read refuses the
command instead of settling a launch. Stopped records
are kept; the registry holds at most 4096 records, so a host that has managed more
projects than that must remove old stopped records by hand. Known limits: process
start times are read in the host's time zone, so a view registered before a time-zone
change (or from a shell with `TZ` set) no longer matches and is treated as exited; and a
project path is keyed as spelled, so one accented folder opened once as NFC and once as
NFD gets two views.

Re-render after an applied
sync: `assemble.py <base_final.mp4> <edit_plan.json> <final.mp4> --auto-base
--fingerprint <base.fingerprint.json> --manifest <asset_manifest.json>`
with observed timing from that attempt. Graphics-only edits can reuse a
fingerprint-current base; source, cut, motion, reframe, grade or tool changes
may require rebuilding it. The former ~86s observation is not a throughput
guarantee. `sync --assemble` without `--apply` is an error before any subprocess.

Manifest discovery checks beside the plan, then the established parent
`source/asset_manifest.json` layout. `--manifest` wins and an invalid explicit
path fails rather than falling back. Both sync and its rebuild (including the
printed copy/paste command) use the same resolved manifest. Prefer an explicit
path when more than one project layout is present.

## The wedge rule (why sync exists)

Studio persists operator edits by MUTATING the project files on disk.
`studio.manifest.json` records the sha256 of every generated file, so the
generator can tell operator edits from its own output:

- `studio_project.py` (and therefore `open`) **refuses to regenerate over a
  directory whose files differ from its manifest** — exit 2, findings listed.
  Unsynced Studio edits are never silently discarded. An agent must obtain
  explicit user direction before using `open --force` to discard them.
- The exits: `sync --apply` (`studio/studio_sync.py <studio_dir> --apply`)
  diffs the edits back into `edit_plan.json` (gate-checked, plan backup
  written) and **rebaselines the manifest + fingerprint**, after which
  regeneration is clean; or `open --force` discards the edits deliberately.
  Sync exit codes: 0 = report printed / applied / already clean; 1 = the
  gates rejected the updated plan (nothing written — no backup, no plan, no
  manifest); 2 = refused (blockers, load/binding failure). `--apply` prints
  a JSON summary; dry-run prints text (`--json` for the full report).
- **Gating is baseline-diff:** `--apply` blocks only on NEW gate failures
  the edit introduces. Pre-existing `plan_lint` failures are reported as
  `preexistingGateFailures` ("predates this edit — not caused by it") and do
  not block — so a legacy plan carrying doctrine violations CAN take Studio
  edits; the edit just can't add new violations. Per-entry template
  contracts on CHANGED entries stay hard. Rejected JSON =
  `{newGateFailures, preexistingGateFailures}`; the applied summary also
  carries `preexistingGateFailures`. Exit codes unchanged.
- **Exception — Studio-installed additions never sync.** Files Studio
  installed that the manifest does not track (e.g. a registry-installed
  comp) are deliberately left untracked by `sync --apply` (listed
  prominently as `unsupportedAdditions` in the report/summary), so they keep
  reading as `unexpected` and regeneration still requires `--force`. That is
  fail-closed on purpose: regeneration deletes files it does not rewrite, so
  silently adopting them would be worse. Route them through brain review
  (author the graphic in the plan), or discard them with `open --force`.
  `status` detects the additions-only state and says so instead of routing
  back to sync.
- **Pending residuals block apply.** An instance's arbitrary structure,
  script, style or text edits are not inferred into the plan. Modified tracked
  sidecars/assets also remain pending. A valid host value or timing edit cannot
  authorize unrelated index comments, scripts, styles, text or added elements.
  Apply refuses before writing the plan, backup, index, manifest or fingerprint;
  ordinary regeneration still refuses. Unknown index elements (even a new host
  pointing at an existing composition) now refuse apply rather than rebaseline
  the whole index. Untracked standalone files retain the nonfatal pending policy
  above. The operator must resolve unsupported edits, or explicitly authorize
  discarding them; sync never adds a DOM-to-plan interpretation step.
- **Supported saved forms remain supported.** Attribute order, quote/entity and
  integral-number serialization may change without changing values. Exact host
  spec/timing edits and the existing view-only class/track/z changes are allowed;
  all other index content is compared. Paired declaration defaults must still
  agree with host values. Script/style source is not treated as collapsible
  whitespace. Deleting a known host updates only the exact original generator
  `const bindings` statement after the complete residual proof, preserving other
  saved index bytes. Its resulting raw hash becomes the new manifest hash.
  Index publication creates an exclusive unique same-directory temporary file;
  an operator file at the former fixed temporary name is never consumed.
  Plan publication likewise uses the existing exclusive atomic JSON writer,
  preserving its original formatting without consuming a sibling temporary name.
  The optional strict-boolean `indexNeedsSplitText` manifest field retains the
  original head dependency through deletion of its last user. Existing views
  without that field reconstruct it from original entries; an already-deleted
  old view that cannot prove its head fails closed, with no guessed migration.
- **A save during the gate remains pending.** Apply retains the original tracked
  hashes before the real plan gate, rechecks supported residuals afterward, then
  checks the original index and tracked bytes before the first write. A late
  instance or index save refuses without a plan, history or manifest write.
  This covers the awaited gate window, not an atomic filesystem transaction
  against unrelated external editors.
- `view.fingerprint.json` binds the view to its inputs (canonicalized
  effective graphicsTrack + base file identity + generator version).

## Verified quirks (all confirmed live against 0.7.33)

- **Agent bridge needs the explicit port and the project cwd.**
  `node <cli> preview --context --json --port <P> [--context-fields
  selection|lint|...]` MUST be given `--port` (server self-discovery does not
  work in this environment) and MUST run from inside the studio project dir
  (cwd-resolved). `studio_review.py context` does both using the recorded
  port.
- **The file server refuses symlinks.** The base video is staged as a real
  copy (`assets/base.mp4`), never a symlink.
- **Composition attributes are raw JSON.** `data-variable-values` /
  `data-composition-variables` are JSON.parsed as raw attribute text —
  HTML-entity escaping (`&quot;`) is a Studio lint ERROR. The generator
  writes raw JSON; keep it that way in hand edits.
- **Automatic backups.** Studio writes backups of mutated project files under
  `<studio_dir>/.hyperframes/backup/` — that directory is ignored by the
  manifest diff.
- **One by-design lint info finding.** Session lint reports info-level
  `timed_element_missing_visibility_hidden` on the base `<video>` element.
  This is by design (the base is always visible); any gate consuming session
  lint MUST whitelist exactly this finding.
- **File-mutations API (agent-driven edits).** The bridge's context JSON
  carries selection + lint state; agent edits go through Studio's
  file-mutation endpoints against the project files (panel variable values,
  clip timing) — the same on-disk mutations the GUI makes, so they flow
  through the identical sync path. After agent edits, run `sync` like any
  operator session.
- **`.studio-server.json` is runtime bookkeeping**, not a project file: the
  orchestrator parks it around every manifest diff (generate/sync/status) so
  it never reads as an unsynced edit.

## What does NOT sync

- **View-only lane/z changes.** Track/lane and z-order in the view are
  generated layout (`lane_layout.py`); rearranging lanes in Studio does not
  change the plan.
- **Studio-added elements do not survive a re-render.** New clips/elements
  created inside Studio have no `graphicsTrack` entry; add graphics in the
  plan (brain-authored), then regenerate.
- **Structural instance-file edits need brain review.** Rewriting a
  composition instance's HTML/script structure (beyond panel variable values
  and timing) is a template change — route it through the brain + template
  contract, not sync.
- Timing shown in the view is the **effective** (exit-on-cut clamped) timing
  the renderers composite; the clamp is projected at generation time.

## Delivery governance in the manual lane

On produced/full-scope projects, `assemble.py`'s delivery wall requires the
controller-issued template-usage receipt
(`.sniper-template-usage-approved.json`) — and ANY sync-applied plan change
correctly stales it. Re-minting requires passing the CURRENT deterministic
gates, which a legacy plan may fail for pre-existing reasons. Two lanes:

- **Auto lane (default):** the controller owns graphics — keep the receipt
  flow: apply the scoped edit, rerun applicable current-plan gates and fresh
  independent reviews, issue the post-review receipt, then assemble. Do not
  use the combined sync/rebuild command immediately after an edit that stales
  the receipt; successful baseline-diff sync does not satisfy that review wall.
- **Operator lane (explicit ownership choice):** only when the user actually
  takes responsibility for supplying graphics, persist that choice as
  `lanes.graphics = "operator"` in the stored project intent. This changes the
  system-owned graphics contract; it is not a workaround for stale receipts
  or failed gates. Editing in Studio alone does not authorize changing lane
  ownership. Whole-output QC and any remaining review/approval walls still
  apply; a successful sync is not approval of the deliverable.

Pre-admission-era manifests additionally need assemble's
`--allow-legacy-unadmitted` (non-production migration flag).

## Palmier (optional legacy mirror)

Palmier Pro remains available as the optional legacy export for operators who
want a pro NLE for footage-level polish: the one-way, post-approval
exact-master mirror (`palmier/push.py`, one byte-identical clip of the
approved `final.mp4`). Studio replaces it as the default manual-control/review
surface for the graphics layer. `/produce-palmier` still routes the mirror
and the isolated experimental candidate.
