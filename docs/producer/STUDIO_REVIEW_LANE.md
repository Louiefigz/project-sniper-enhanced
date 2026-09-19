# STUDIO REVIEW LANE — manual control over the graphics layer

The default manual-control/review surface after a Producer render. HyperFrames
Studio (shipped by the pinned `hyperframes@0.7.33` —
`templates/motion/node_modules/hyperframes/dist/cli.js`) opens a generated
review project as a full timeline editor: the graphics-free base footage on
track 0, every `graphicsTrack` entry as a timed, panel-editable clip above it.
The operator (or an agent through the bridge) adjusts graphics there; the
edits are diffed back into `edit_plan.json`; `assemble.py` recomposites.

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

Use the operator's requested browser or established browser preference. Keep
both views available in separate tabs; preserve an active review position until
the next candidate is ready. Start a newly presented candidate at the beginning.
Include both labeled live URLs in the handoff and record which candidate/project
they show plus the checks actually performed in the existing review notes.

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
private registry holds one current preview across draft directories/checkouts;
repeated open reuses it and replacement first verifies prior cleanup. Startup
must pass host resource admission and acquire the shared heavy-job lease.

For an already-authored native project, use
`python scripts/producer/studio/managed_preview.py open <native-project> --port <P>`
directly. This serves its existing files without plan regeneration. Use this
managed entry point instead of raw SDK preview commands. Open the returned URL
through the app's browser control when a visible preview is wanted. The matching
`status` and `stop` actions read/check or stop the registered native project.

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
