# Real websites and repository scrolls in Shorts

When the speaker mentions a brand, product, website or GitHub repository, the
editing agent should consider showing the real page. The user can also ask:
“When I mention Claude Code, show its site and scroll to the relevant feature,”
or “Find that repository and show the README example as I explain it.”

This is part of the existing agent-directed workflow. The agent resolves the
entity, verifies the official URL/owner from primary sources, chooses the useful
section and matches it to retained speech. A brand name alone does not trigger a
hardcoded layout, imply an arbitrary repository is official, or justify unrelated
scrolling. Use supplied B-roll first when it already demonstrates the point.

## Establish the real subject before inventing its representation

**Standing editing preference, September 15, 2026:** preserve the requested
treatment. A deliberately simple presenter-led clip stays restrained. For
produced edits that call for proof, examples and split-screen storytelling,
search real B-roll and assets first; add illustrations for what those assets
cannot usefully show. The Restrained style specification or a module-card
study can inform the brief; neither is an automatic preset or a reason to
disregard the selected intensity.
Preserve useful existing illustrations when revising a few evidence beats.

For produced Shorts and long-form, inspect existing source/supporting assets and
prior review findings before committing to a generic illustration of an important
named entity or factual claim. Prefer a real artifact when the job is identity,
current state, proof or a demonstrated operation. Reuse a relevant captured page
before recording another. Not searching is not evidence that an asset is missing.
When a planning stage cannot acquire assets, record the specific discovery need
for its owning stage; do not quietly turn that gap into an approved metaphor.

Give the insert a visible job: establish the channel or community, then enlarge
the exact count, offer, feature or result on its spoken cue. Keep enough original
context to identify the source and enough time/space to read the detail. A logo
identifies a platform; its actual page shows what exists. Audience size supports
audience size, not revenue. Preserve the capture's date and claim limits in the
strategy notes; do not change real interface values to match historical speech.

Illustrations still help explain a proposed relationship or abstract mechanism.
Use them alongside established real context when they explain something the page
cannot. Record that reason in the existing storyboard. This preference does not
force a website insert on every noun, displace an intentional useful analogy,
override disabled lanes, or authorize browsing/capture outside the current scope.

Keep production/provenance footnotes out of the finished picture unless viewers
need the qualification to avoid a materially false impression. If `GOAL`,
`11 MEMBERS NOW`, `AT 20 MEMBERS` and unfilled slots already communicate the
distinction, adding “not yet achieved” or “outlined slots are not yet filled”
only repeats it. Correct the representation when necessary; a label cannot
turn invented evidence into real proof.

### Scouting and independent agent verification

For these produced edits, assign asset scouting and independent strategy review
to separate agents when delegation is available. The scout inspects the source,
admitted asset pool and authorized public sources. The critic checks actual
candidates/images and the speech-to-insert decisions, not only the author's
summary. Keep their evidence in the existing scene/asset-use/review records;
do not create unsupported plan fields. In a controller with no browsing tools,
the owning preparation agent scouts and admits assets before authoring; the
tool-free critic reviews embedded evidence and returns missing needs to that
owner. It cannot claim to search independently.

For native plans, put the observed candidates and decisions in the existing
`supportingSearch`, `assetUse` and scene records. For manifest-only long-form
controllers, admit the real assets before kickoff; preserve actual observations
in `manifest.broll` catalog descriptions/frames and the relevant `brollTrack`
or `graphicsDecisions` reason fields. Those plan/manifest fields reach the
hash-bound critic packet. A link to an external scout note alone is insufficient
when the critic cannot open files. Do not invent a new `scoutEvidence` field.

The critic must request revision for a missed useful real-entity/proof shot,
an unsupported “nothing available” conclusion, a whole-clip no-insert exemption,
an unexplained restriction of authorized sourcing, or redundant footer text.
Check final encoded frames and live playback for the selected real assets and
their readable attention targets; passing technical QC is not this review.
Do not force real inserts into a brief that explicitly requests a simple clip
or disables those lanes. No finite check guarantees zero future misses; record
the evidence and enforce the existing review verdict before production.

For a talk about a business's pricing, the distinct jobs are: identify the speaker
and the business with real imagery; show the actual community, offer or current
member count on the platform where it lives; focus verified audience counts on
their own platform; use an honest diagram for the proposed price trigger or value
relationship. A captured page showing today's member count and price need not
prove a stated future goal to serve as the current-state shot. The speaker's own
footage of their work can ground the business physically. Use the real marks of
named tools when those tools need identification. Verify exact profile ownership,
metric scope and capture date; do not combine cross-platform followers into a
claim of unique people or alter counts to fit the speech.

## Choose the shot before recording

1. Inspect the source/transcript and name what this insert helps the viewer see.
   Identify the exact public site or repository. Save the verification source.
2. Inspect the page at the intended viewport. Choose actual visible start/end
   elements and their exact text. Record a nearby reveal with an opening hold,
   smooth scroll and readable result hold. A long page often needs several short
   shots rather than one fast scroll through everything.
3. Preserve the original site, logo, colors and text. Do not redraw the page,
   apply a generic brand palette or recolor its mark. Check the final encoded
   frames at phone size; use a tighter view when the important text is too small.
4. Match the reveal to the spoken point. A website feature claim is page content,
   not independent proof of successful product use. A README installation command
   is documentation, not evidence that we installed or tested the software.

## Shared capture tool

Use `scripts/producer/studio/web_capture.py PLAN.json NEW_OUTPUT_DIRECTORY`.
It owns the browser/encoder through the existing NativeRun/NativeWorkLease,
memory limits, deadlines, source/tool hashes and verified process cleanup.
Public acquisition has its own HTTPS sandbox. Native Short export keeps its
existing localhost-only sandbox and reads only the frozen local footage.

An inspection plan contains:

```json
{
  "schemaVersion": 1,
  "mode": "inspect",
  "entity": "Claude Code",
  "url": "https://github.com/anthropics/claude-code",
  "verifiedBy": "https://github.com/anthropics",
  "expectedTitle": "Claude Code",
  "reason": "Show the real README and reveal its setup section",
  "allowedHosts": ["github.com", "github.githubassets.com", "raw.githubusercontent.com", "avatars.githubusercontent.com", "camo.githubusercontent.com"],
  "viewport": { "width": 540, "height": 960, "scale": 2 }
}
```

Inspect `page.png`, the heading inventory and blocked resource URLs in
`capture.json`. Admit needed public asset hosts after checking them. A loaded
page with missing graphics is not a finished capture. For recording, use a new
plan with `mode: "capture"` and add:

```json
{
  "duration": 8,
  "fps": 25,
  "holdStart": 1.25,
  "holdEnd": 2,
  "start": { "selector": "article h1", "text": "Claude Code", "top": 140 },
  "end": { "selector": "article h2", "text": "Get started", "top": 160 }
}
```

Targets above are examples observed on September 11, 2026. Re-inspect current
pages rather than assuming their DOM stays the same. The tool rejects missing
or ambiguous targets, obscured opening/result headings, visible missing images,
stationary or excessive scrolls, insufficient frame acquisition, wrong page
identity and incomplete media. It checks native source-frame dimensions,
encoded frame count and full video decode. It retains beginning/middle/end
encoded review frames plus scrolling/timing evidence.

The final recorder captures each planned scroll position from the real browser
at native resolution, then encodes those frames on the Short's clock. This avoids
dropped scroll frames on complex pages. It does not promise wall-clock playback
of embedded page animations; treat those as illustrative page content, never as
evidence of product execution speed. The receipt records both output frame time
and acquisition wall time. Browser colors/content are preserved, with normal
JPEG/H.264 encoding loss and no creative recoloring.

The browser starts without a saved login or profile. Requests are read-only
GET/HEAD to explicitly admitted public HTTPS hosts. No transcripts or private
footage are uploaded, and no model/generation provider is called. This is a
local CLI for agent-selected public sources, not an exposed URL-fetch API.
Respect the user's current browsing permissions. Do not work around a login,
CAPTCHA or access block; report the missing shot or use another verified source.
The current recorder scrolls the document; nested panels, authenticated product
operations and arbitrary click sequences need a separately inspected workflow.

## Use the recording in the Short

### Origin receipts for new and existing captures

Run inspection and recording from `PROJECT_SNIPER`, each with a new output
directory whose parent already exists:

```sh
.venv/bin/python scripts/producer/studio/web_capture.py /absolute/inspect-plan.json /absolute/new-inspection
.venv/bin/python scripts/producer/studio/web_capture.py /absolute/capture-plan.json /absolute/new-capture
```

After successful capture and supervision, the current wrapper writes
`CAPTURE-ASSET.json`, passes that binding through the shared `origin-web`
adapter, and writes `ASSET-ORIGIN.json` plus the complete `ASSET.json`. The final
object includes both the `origin` path/hash and the original `webCapture`
receipt hashes. Inspection mode does not produce this production asset.

An existing successful capture whose `ASSET.json` predates origin bindings can
use the same adapter without another browser recording:

```sh
node --import tsx scripts/producer/native-short.ts origin-web /absolute/existing-capture/ASSET.json /absolute/existing-capture/NEW-ASSET-ORIGIN.json
```

The receipt destination must be new. The command prints the complete asset
binding to use in the plan; preserve that returned object, including `origin`
and `webCapture`. An asset already carrying its origin binding can be reused
as-is. Do not strip the origin or supervision fields, and do not treat the
intermediate `CAPTURE-ASSET.json` as the complete asset if origin creation fails.

The adapter checks the successful capture and supervision evidence and records
its canonical page URL, media dimensions, frame clock and immutable bytes in
the existing `AssetRecordV1`. It preserves `public-web-capture` acquisition and
`needs-review` publication disposition, with use limited to local editorial
review. Cached footage retains its public acquisition classification and cannot
bypass a supplied-only or local-only request.

**Integration coverage:** on September 13, 2026, a fresh official Claude prompting
article recording completed the automatic capture-to-origin wrapper in
`artifacts/native-short-storytelling-2026-09-13/claude-capture-01`: 130 frames at 25fps,
5.2 seconds, 1080×1920. The owner took 11.704 seconds and verified cleanup. The
resulting complete `ASSET.json` passed new native project assembly and cold
readback. This verifies the public SDR page-scroll path for this source; final
story/export qualification is separate. The attempted OpenAI help page returned
HTTP 403 and remains a failed capture rather than substituted evidence.

Inspection optionally accepts the same bounded `start` target as recording,
without requiring a duration or end target. It scrolls to and verifies that
specific section before saving `page.png`. Heading inventory includes h1–h6;
choose a unique observed selector/text pair. This helps assess a relevant article
section instead of judging only the page's opening viewport.

### Bind the selected shot

Copy the complete bound `ASSET.json` object, or the existing-capture adapter's
returned object, into the plan's `assets` array. Record the selected range and
claim limit in `strategy.supportingSearch.candidates`, and author the required
strategy v3 `assetUse` decision with its retained speech, purpose, essential
visible region and exact output window. Use its local asset filename in a muted
native `<video class="clip">`, with the same source/output timing as the selected
supporting shot. Keep captions and title in their independent shared lanes.

The project writer and cold reader reject changed receipts, failed supervision,
substituted video bytes and ranges beyond the recording. Export also pins the
capture receipts throughout its run. Preserve the capture folder with the
project because the current source-bound reader rechecks original assets and
receipts. `ASSET.json` establishes technical admission only. Source identity,
contextual fit, faithful claims, readability and pacing still require inspection
and encoded playback review. Publication rights and approval remain separate;
a successful capture or origin receipt cannot grant them.

`shortDirectionInstructions` carries this policy into conversational, prepared
brief and native project paths. New brief packets bind their instruction text
into the request hash, so a changed workflow creates a new packet. Supporting
video off remains authoritative. The app's Prepare Short brief button still
prepares a handoff; the editing agent performs discovery, recording and assembly.
