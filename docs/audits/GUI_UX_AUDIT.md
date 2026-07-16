# GUI UX audit

**Audited:** 2026-07-12  
**Scope:** every user-visible App Router page, every normal workflow state, global navigation, recovery screens, and the controls that hand work to local/AI/Palmier processes.

## Product contract

Project Sniper now presents one primary workflow and three optional specialist tools:

1. **Producer — Create / Edit:** the planner, deterministic gate, render/QC,
   and project-control workflow. Palmier is the primary viewing/editing surface;
   Producer records progress, requests governed AI revisions, and preserves the
   last approved delivery separately from the working Palmier revision.
2. **Segmenter — Split footage:** finds standalone clips in a long recording and exports MP4 clips. It is not a required first step.
3. **Clipper — Precision cut:** removes spoken words and exports an FCPXML timeline for Final Cut Pro. It does not render an MP4 or synchronize recordings.
4. **Text Check:** scans selected still frames from a local MP4 and reports possible on-screen text problems. It does not change the video.

The old “Part One / Part Two / Part Three” mental model was incorrect because the tools are alternatives, not a mandatory sequence.

## The Palmier revision answer

**Open in Palmier** is the primary project-card action as soon as media and
format exist. It opens an existing managed timeline or creates a clearly
unapproved source working view. Opening never transfers ownership or pauses a
background job. **Take control in Palmier** is a separate, disabled-until-safe
manual handoff action.

Palmier's visible managed timeline is the editable source of truth; the last
QC-approved revision is a separate delivery checkpoint. Sniper fingerprints
the complete MCP-readable timeline. A manual change advances the working
revision and invalidates approval. AI work must copy that exact revision,
apply only a governed scoped delta, run deterministic gates and independent
critics, then compare-and-swap the candidate after QC. The native delta adapter
is not complete yet, so a manual Palmier baseline currently blocks the legacy
plan writer rather than being overwritten.

## Expectation-versus-result matrix

### Global and home

| Control | Reasonable user expectation | Verified contract |
|---|---|---|
| Project Sniper logo | Return home | Links to `/`. |
| Create / Edit | Make a finished video or revise a project | Opens Producer. |
| Split Footage | Turn a long recording into separate clips | Opens Segmenter. |
| Precision Cut | Make word-level dialogue cuts | Opens Clipper; the UI states that output is FCPXML, not MP4. |
| Text Check | Find visible text problems | Opens the local-MP4 text checker. |
| Ready / Setup Needed | Understand whether local dependencies work | Focusable disclosure shows editor/transcription state and failure detail; it is no longer a hover-only tooltip. |
| Producer primary card | Start the normal video workflow | Opens Producer and previews all four user steps. |
| Specialist tool cards | Know input, output, and whether the tool is required | Each card states “you provide,” “you get,” and a task-specific action. |
| Privacy disclosure | Understand what leaves the Mac | States the local/full-video boundary and which derived data may reach configured providers. |

### Producer: starting and resuming

| Control | Reasonable user expectation | Verified contract |
|---|---|---|
| Project folder | Start from multiple clips/assets | Opens the native folder picker. Plain copy explains the normal case; folder conventions are under Advanced. |
| Single media file | Start from one existing video/audio file | Opens the native file picker and creates a new Producer project from it. |
| Describe the video you want | Give creative direction before generation | The 1–1200 character brief is validated, stored in `project.json`, forwarded to auto-edit, and included in the authoring prompt as untrusted editorial direction. |
| Format buttons | Choose vertical or horizontal output | Uses explicit Vertical short (9:16) / Horizontal video (16:9) pressed states. |
| Editing-style buttons | Choose a recognizable editing level/style | Friendly names and one-sentence summaries replace raw scope IDs; exact inclusions are optional details. |
| Add background music | Opt in to a project music track | Music remains off unless explicitly selected; required dialogue ducking stays enforced. |
| Prepare media | Continue toward video creation | Builds the media record and transcripts, then opens “Your media is ready.” The incompatible skip-transcription shortcut was removed from the normal flow. |
| Continue a project | Resume without reconstructing files | Shows three recent projects by default; Show more/fewer works without burying new-video intake. |
| Open in Palmier | Use the primary working/viewing surface | Opens the managed timeline without changing ownership; prepares a source working view when no approved edit exists. |
| Review saved timeline | Diagnose or review Sniper state | Opens the built-in editor as a secondary progress/recovery surface. |
| Take control in Palmier | Manually own an approved revision | Enabled only after approval and while idle; explicit handoff never hides an active job. |
| Show Final Cut timeline | Use a Clipper-only saved project | Reveals its saved FCPXML file instead of leaving a dead recent-project card. |
| Rename | Change the display name | Inline Save/Cancel with visible failure state. |
| View details | Inspect technical stage/file state | Expands technical stage checks and paths; they no longer dominate every card. |
| Create/Render/Prepare project actions | Advance an incomplete project | Every action calls its matching route and now requires the expected terminal stream event before reporting success. |
| Optional reference | Apply editing mechanics from an example | Closed by default. Copy states that words, branding, assets, and music are not copied. |

### Producer: media-ready and editor states

| Control | Reasonable user expectation | Verified contract |
|---|---|---|
| Create your video | Produce a playable finished video | Authors, validates, renders, and quality-checks the video. A quiet/early stream close is an error, not success. |
| Advanced edit-plan JSON | Expert-only manual path | Closed by default. A changed plan invalidates the old check, and manual render stays disabled until the current JSON passes validation. |
| Projects | Leave the editor | Returns to projects; unsaved timeline changes require confirmation. |
| Undo / Redo | Reverse timeline changes | Operates on in-memory plan history with truthful disabled states. |
| Save timeline | Persist direct timeline changes | Writes the plan and snapshots the prior version. Errors remain visible. |
| Render updated video | Make timeline/revision changes visible in the video | Runs the same saved-plan planning/QC controller as Auto Edit and exposes output only after current approval. Editing is visibly locked while AI or rendering owns the plan. |
| Show final video | Find the deliverable | Reveals the full-resolution final video in Finder. |
| Update Palmier mirror | Bootstrap an approved fidelity reference | Creates an unclobberable exact-master shadow only when it cannot overwrite a newer Palmier authority. |
| Sniper version / Palmier version | Compare a proven delivery artifact | Enabled only for matching approval/readback/publication proof; it is not the live-edit authority selector. |
| Palmier controls report | Understand what can be changed natively | Hidden by default; exact/limited/flattened/no-native-control labels never masquerade as visual omissions. |
| Reclaim Sniper mirror | Resume GUI-driven mirroring after Palmier work | Leaves the Palmier-owned timeline untouched, invalidates prior proof, and forces a new shadow. |
| Tell the editor what to change | Revise the watched video in plain language | Multiline input accepts natural language/time ranges. **Apply edit** updates and reloads the timeline; copy then instructs the user to render. |
| Transcript / word controls | Cut or restore speech | Mutates the plan; loading, empty, missing-sidecar, and read-error states are distinct and retryable. |
| Audio / Elements / Layout | Change the selected aspect of the edit | Controls mutate the plan; audio labels and validation are plain-language. Motion/Transitions are marked “view only” where no edit control exists. |
| Timeline controls | Seek, select ranges, split, move, and trim | Controls are wired to plan mutations. Fine arrow nudges are described truthfully as ±0.04s rather than falsely claiming one frame at every frame rate. |

### Segmenter

| Control | Reasonable user expectation | Verified contract |
|---|---|---|
| Progress steps | Know where the user is | Add files → Review clips → Choose output is always visible. |
| Add all files / individual rows | Assign one main video and optional synchronized media | Native pickers with correct required/optional names and separate accessible remove controls. |
| Topic changes | Get a safe general-purpose starting instruction | Recommended for interviews, podcasts, lessons, and talking heads. |
| Coaching conversations | Use the former show-specific recipe intentionally | Explicit opt-in template; it is no longer the silent default. |
| Custom | Write original boundaries | Clears the template and requires instructions before continuing. |
| What clips should we find? | Tell the model where clips start/end and what to omit | The edited text is sent to segmentation. |
| Change files / Back to review / Start over | Navigate without surprise data loss | Normal edit/export navigation preserves state; only Start over resets and asks for confirmation. |
| Download selected MP4 clips | Receive playable clips | Exports selected single-camera clips. |
| Download synchronized camera/audio bundle | Receive optional multicam material | Available only with extra sources; non-OK HTTP responses now surface an error before stream parsing. |
| Save for editing in Producer | Continue to a finished-video workflow | Saves clips to a workspace project and provides a direct Open Producer link. |

### Clipper

| Control | Reasonable user expectation | Verified contract |
|---|---|---|
| Host camera / optional media | Choose the dialogue scene | Copy clearly requires every extra camera/mic to already be synchronized and compatible; Clipper does not sync or conform media. |
| Continue | Transcribe and move toward a first cut | Transcription failures are visible in both single- and dual-track modes. |
| How should this clip be edited? | Control the AI cut | A visible, persisted instruction field replaces the hidden call-in-show recipe. The generic default removes filler/repetition without inventing words. |
| Create / Regenerate AI edit | Apply the current instruction | Posts the actual edited request; regenerating warns that it replaces the current generated decisions. |
| Word editor | Fine-tune which spoken words remain | Removal/restoration and seeking remain wired; export is blocked when nothing remains. |
| Download FCPXML timeline | Receive the advertised output | Downloads a Final Cut Pro timeline and repeatedly states that no MP4 is rendered. |
| Save FCPXML to workspace | Keep the timeline in the workspace | Validates the response and creates an actionable recent project with Show Final Cut timeline. |
| Back / Start over | Return without accidental loss | Destination-specific labels; destructive reset is explicit and confirmed. |

### Text Check

| Control | Reasonable user expectation | Verified contract |
|---|---|---|
| Choose a local MP4 | Select the video to inspect | Native picker; copy states the tool reports suggestions and does not apply fixes. |
| Video type | Pick a sensible scan strategy | Plain-language main choice; recommended default is identified. |
| Advanced settings | Tune sampling/model/cost details | Closed by default; pHash/Hamming/OCR/API caps no longer block ordinary users. |
| Scan for text errors | Start analysis | Extracts/deduplicates frames, requests confirmation above the safety threshold, and analyzes only after approval. |
| Retry scan | Recover from a failed run | Clears stale results/progress and starts a fresh run. |
| Possible text errors / filters | Inspect likely issues | Findings seek the video; visible/total confidence behavior is explicit. |
| Diagnostics | Inspect technical execution | Closed by default under Advanced. |

The success state is now strict: **“No text errors found” appears only after the run reaches `done`**. Waiting for confirmation and error states can no longer masquerade as a clean scan.

## Recovery and accessibility

- Unknown URLs show a task-oriented recovery screen with Home and Producer links.
- Unexpected screen errors use the app error boundary with Try again and Home; workflow errors remain inline beside the failed action.
- Loading states explain what is loading instead of rendering a blank page.
- Global navigation is task-named and horizontally reachable on narrow screens.
- A skip link targets the tool content.
- Pressed controls expose `aria-pressed`; key fields have programmatic labels; major progress/errors use status/alert semantics.
- Invalid nested file-row controls were replaced in Segmenter and Clipper.
- Runtime dependency failures are keyboard/touch accessible.

## Verification method

The audit combined:

- real in-app browser navigation of `/`, `/producer`, a finished Producer editor, `/segmenter`, `/clipper`, `/frameio-review`, and the not-found screen;
- safe interaction checks for navigation, runtime details, project list expansion/details, Segmenter template changes, and editor disclosures;
- source-level tracing from every mutating control to its handler/API route;
- TypeScript, ESLint, unit/contract tests, production build, and diff-whitespace checks;
- focused regression tests for creative-brief validation/forwarding, required SSE terminal events, Clipper prompt/media contracts, Segmenter templates, transcript response states, and Frame Review state handling.
- a live recovery test on C0679: Resume Edit reused the saved plan, Next was
  terminated during the real ffmpeg render, the supervisor restarted it in
  813 ms, the worker continued, Producer reconnected to the current phase, and
  the finished editor exposed its caption cues plus natural-language revision
  field in a non-collapsed workspace at the narrow in-app viewport.

Native file choosers, paid model jobs, and user-project renders were not
triggered merely to prove labels. Palmier itself was tested with an isolated,
disposable project: full-copy semantic equality, candidate-only mutation,
unchanged parent, composited inspection metadata, explicit-timeline export,
prior-project restoration, and cleanup all passed.

## Intentional limitations (now stated in the GUI)

- Segmenter creates clips, not a finished program.
- Clipper exports FCPXML and requires already-synchronized auxiliary media.
- Text Check reports problems but does not edit the video.
- Manual Palmier revisions are canonical immediately but require fresh QC before delivery approval.
- Palmier-native governed AI deltas are not connected end-to-end yet; the old plan-only writer fails closed on a manual baseline.
- Sniper never silently clobbers or translates a human Palmier timeline through a stale `edit_plan.json`.

These are product boundaries, not hidden surprises.
