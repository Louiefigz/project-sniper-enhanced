# Clip review layout

Reusable local review page for a recording's proposed Shorts. The user approved
this layout during IMG_7138 review on 2026-09-14: green editorial cards, priority
filters, source-time buttons, expanded reasoning, and a source player that plays
noncontiguous ranges in the chosen output order.

Keep the player visible when any card starts playback. On narrow panels the
player sits above the list; a play action scrolls and focuses it immediately.
The player reports loading, playing, paused, finished, and failed states and
offers an explicit resume button. Source audio and approximate selection timing
must not be described as a finished render or an audio master.

For embedded-browser reviews, prefer H.264 Constrained Baseline, `yuv420p`, no
B-frames (`-profile:v baseline -bf 0`), dense keyframes, AAC, and MP4 faststart.
The IMG_7138 High-profile proxy intermittently displayed black while its clock
advanced; a Baseline sample displayed real frames. This is compatibility
mitigation, not proof of a particular decoder defect. The Reload video control
resets the media resource and retains the active passage position. A configured
`review.posterUrl` provides a real source thumbnail before playback starts.

## Reuse

Copy `index.html`, `review.css`, `review.mjs`, and `playback.mjs` into a recording's
local review folder. Add `candidates.json`, an H.264/AAC `review-proxy.mp4`,
`SHORTLIST.md`, and `transcript-timed.txt`. Serve that folder with a localhost
HTTP server supporting byte-range requests (HTTP 206); do not open `index.html`
as a file URL. The folder should remain local and generated footage/transcripts
should stay out of Git. Update these canonical template files first for future
layout fixes, then copy them into active review folders.

The JSON is editorial data, not HTML. The page inserts all prose using
`textContent`. Each candidate has an `id`, `title`, `priority` (`A` or `B`),
`kind`, `target` (e.g. `35–45s`), `tags` (`rant` and/or `conversation` for those
filters), `why`, `caution`, `visual`, and ordered `ranges`:

```json
{
  "summary": "Two source-grounded ideas from this conversation.",
  "sourceDurationSeconds": 600,
  "review": {
    "title": "Recording · Shorts shortlist",
    "heading": "The Shorts inside this conversation",
    "mediaUrl": "review-proxy.mp4",
    "speakerNote": "Explain microphone mapping and any review limitations here."
  },
  "candidates": [{
    "id": "first-idea",
    "title": "Proposed editorial hook",
    "priority": "A",
    "kind": "Assembled founder story",
    "target": "15–20s",
    "tags": [],
    "why": "Why this moment earns a Short.",
    "caution": "Context that the final edit must preserve.",
    "visual": "How the footage supports the story.",
    "ranges": [
      {"start": 120, "end": 130, "role": "Hook", "speaker": "Presenter", "quote": "Recorded words."},
      {"start": 40, "end": 50, "role": "Payoff", "speaker": "Presenter", "quote": "Recorded words."}
    ]
  }]
}
```

Ranges use original-source seconds, and array order is output order (including
backward jumps). The page validates positive, bounded spans. It uses browser
seeking and `timeupdate`, so selections are review previews, not frame-exact
exports. Before handoff, test a multi-range selection through its last passage
in the actual narrow panel, then test replay, pause/resume, and a source-time
button. Playback controller regressions run without media downloads:

```sh
node --test scripts/tests/clip_review_playback.test.mjs
```

## Finished edits alongside originals

An optional candidate `edited` object accepts `mediaUrl`, `duration` in seconds and `posterUrl`. Its primary action is **Play edited Short**; **Compare original passages** and source-time buttons restore the original file. `review.notesUrl` and `review.transcriptUrl` can point to shared notes. The player always labels whether the edited video or original footage is loaded, and switches the actual media resource before seeking. Keep all review files local.
