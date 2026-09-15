# A playing video can still look like a broken button

During IMG_7138 shortlist review on 2026-09-14, the user clicked an assembled
selection and saw nothing happen. The video was playing: source time was
1091.62 seconds, `paused` was false, and `readyState` was 4. At the actual
766 × 807 browser-panel size, however, the video occupied vertical coordinates
−804 through −409 pixels. The entire player was above the viewport.

The layout stacks the player above the cards below 850 pixels wide. A previous
test checked playback and range transitions, but not whether the player was
visible after clicking a lower card.

The shared `templates/clip-review/review.mjs` now calls
`player.scrollIntoView({behavior: 'instant', block: 'start'})` and focuses the
player after an explicit selection click. It also shows playback state, the
active passage, and a resume action. It does not scroll on automatic passage
transitions, which would interrupt someone reading the notes.

Use this for explicit play-from-list actions when the target player is elsewhere
in the layout. Do not automatically scroll a person merely because a background
media event occurred. Test at the actual panel width: a successful `play()`
promise alone does not prove the user can see the result.

Regression checks cover nonchronological playback, stopping at the final range,
cold metadata, a blocked play request, stale promise rejection, pause, and seek.
Browser review additionally covers player visibility and the controls. These
tests qualify the review UI; they do not certify editorial cut accuracy.

## Follow-up: visible player, black picture

The user subsequently reported a different failure: the player was in view but
black at about 24:29, even though the clock advanced. A frame decoded from the
proxy at that time contained the expected presenter and whiteboard. The review
proxy was H.264 High with two B-frames; an isolated Constrained Baseline sample
displayed picture in the embedded browser. The local review was switched to a
Constrained Baseline/no-B-frame proxy with the same 1904.269-second duration.
This mitigates compatibility; it does not establish the browser's internal
failure mechanism. The shared template also gained decoder reload/reseek and
an optional source poster. Verify changing picture across passage boundaries,
not just a poster, playback time, or resolved play promise.

## September 15: same-file replay needs its own check

The rebuilt 56.24-second Short later displayed black while paused at 1.430142
seconds, with `readyState: 4`, 1080×1920 dimensions and no media error. Reloading
the media restored picture. The exact MP4 had already passed full decode and
encoded-picture checks. This supports a stale playback-surface problem, but does
not prove a browser-engine cause or a codec defect.

`SelectionPlayback.start()` now calls `media.load()` for an explicit media URL,
including the same URL, preserves the requested seek until metadata arrives,
and calls `play()` within the click gesture. Natural completion reloads exhausted
media into a paused state at zero for native replay. The manual reload control
continues to preserve the selected passage position.

Live browser verification showed the opening at 0.20 seconds, changing picture
at 26.70 seconds, and a same-file restart with visible opening at 0.45 seconds.
After completion, the media was paused at zero with the poster visible. Native
replay displayed picture at 0.23 seconds and continued to 24.25 seconds. Source
comparison opened at 1465.87 seconds and advanced to selected passages 2 and 4,
with visible original footage. These are sampled visual observations, not a
claim of continuous listening or proof that every browser is reliable.

That check also caught a stale “Selection finished” label during native replay:
the selection ranges were cleared, so native media events were ignored. The
controller now tracks native playback separately, reports playing/paused/ended,
and clears that tracking before stop/reload so delayed pause/waiting events
cannot overwrite the final status. Eleven focused tests pass, including the
original nine and native replay status/stop/reload regressions.

After reloading the final module, the browser showed the ending scene at 50.97
seconds, reset to paused zero on completion, and replayed through the native
control with visible opening at 0.16 seconds and the correct “Playing” label.
Native pause at 7.06 seconds retained visible picture and reported “Paused”.

Use this reset for explicit review selections affected by stale replay. Do not
reload on every time update or internal passage transition: that would interrupt
normal playback and discard buffering. A player repair does not justify
re-encoding a verified deliverable without evidence that the encoded file fails.
