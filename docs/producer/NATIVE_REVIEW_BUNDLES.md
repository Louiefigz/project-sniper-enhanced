# Shared native local and Studio review preparation

`native_review_bundle.py` replaces artifact-specific Studio preparation imports.
It accepts an ordered manifest of named checked exports. It creates a fresh
bundle, preserves original projects, copies the exact checked MP4s, and prepares
independent editable Studio projects with `media.autoProxy: false`.

```json
{
  "schemaVersion": 1,
  "compositions": [
    {
      "id": "customer-story",
      "title": "Customer story",
      "export": "/absolute/path/to/checked-export",
      "plan": "SHORT-PROJECT.json",
      "entry": "index.html"
    }
  ]
}
```

`plan` and `entry` default to the values shown. IDs must be unique, including
case-insensitive matches, and contain letters, digits, underscores or hyphens.
Each export must have the original render seal, successful capture seal, complete
final verification owner and unchanged checked MP4. All project files must be
present in the original manifest with their admitted hashes.

```bash
.venv/bin/python scripts/producer/studio/native_review_bundle.py prepare /absolute/review-manifest.json /absolute/new-review-bundle
.venv/bin/python scripts/producer/studio/native_review_bundle.py open /absolute/new-review-bundle customer-story
```

The bundle's `index.html` embeds the pinned shared
`templates/clip-review/playback.mjs` controller, including its decoder reset at
the end and on replay. Play/replay, resume and reload controls work on local file
pages without requiring an external JavaScript module request.

Each `studio/<id>/` contains an independent editable project. The `open` command
opens actual HyperFrames Studio through the existing managed-preview lifecycle
and checks the qualified runtime. Opening raw project HTML is not the Studio
handoff. Preparing files or starting Studio does **not** claim successful live
browser playback or listening; both still require observation.

`NATIVE-REVIEW-BUNDLE.json` records the prepared surfaces and keeps those approvals
false. On opening, `localVideoStatus` verifies the checked MP4 bytes separately
from `studioState`, which reports changed, missing and added editable files.
Intentional Studio edits remain allowed. They do not update or qualify the MP4:
`exportConsistencyVerified` remains false, and edits require a new export and
verification before delivery. Automatic Studio proxies must remain disabled.

## Shared behavior and compatibility

- The checked AAC is packet-copied, then its complete packet and presentation
  clocks are compared with the final MP4. No additional audio or video encode is
  used for the Studio dialogue track.
- Exact source audio spans become one continuous checked AAC track. Other HTML
  bytes remain unchanged except separately recorded media-wrapper display sets.
  Source or cut changes require rebuilding that audio and renewing verification.
- The canvas supplies duration, dimensions, frame rate and frame/sample mapping.
  Checkpoint extraction selects frame indices in one decode, including rational
  rates such as `30000/1001`; it does not infer time from rounded frame seeks.
- Packaging supports named portrait/landscape canvases and long durations under
  the same native HTML/segment contract. Pure fixtures exercise those cases.
  **Checked export admission currently recognizes the existing native Short
  delivery protocol only.** This repository has no corresponding native
  long-form delivery adapter; generic packaging does not invent one or accept an
  unverified MP4. Add that producer's real receipt adapter before CLI long-form
  handoff is described as qualified.
- Fresh destinations are mandatory. Failed or partially published attempts are
  retained. Existing editable projects are never overwritten by a new prepare.

## Optional raw recognition diagnostic

Recognition runs separately from review preparation. It retains the raw local
Whisper JSON once and reports recognized text independently from the existing
word-timing quality policy. Bad timestamps remain failed; even a passing policy
is not acoustic alignment or human listening approval.

```bash
.venv/bin/python scripts/producer/studio/native_review_recognition.py /absolute/final-audio.m4a /absolute/new-recognition-attempt
.venv/bin/python scripts/producer/studio/native_review_recognition.py /absolute/final-audio.m4a --reuse /absolute/prior-attempt/RECOGNITION-RECEIPT.json
```

The reuse command verifies source, raw-result and owner bindings and launches no
recognition. Model/tool inputs are pinned during the original supervised local
run. Recognition uses existing local models only and never downloads or calls a
paid provider. `timingApproved`, `wordSyncApproved` and `humanListeningApproved`
remain false in diagnostic results.
