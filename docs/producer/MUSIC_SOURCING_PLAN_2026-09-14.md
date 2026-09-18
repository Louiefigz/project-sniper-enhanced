# Shared music sourcing and mixing plan

Status: researched plan, 2026-09-14. Provider connection, purchases, generation,
and native Shorts music support are not completed by this document.

## Current sample and implementation

The offer audio comparison served at `http://127.0.0.1:4001/` has no separately
added music bed. Its prepared request has `music: false`. The cleaned export
uses source-derived dialogue, RNNoise cleanup, and mastering. Its receipts do
not name a downloaded or generated music asset. Music audible in this specific
source-derived soundtrack would therefore be embedded in the supplied footage;
these records do not identify that music or establish its license. This finding
does not identify music in every earlier review example.

Evidence:

- `artifacts/shared-audio-2026-09-14/review-manifest.json`
- `artifacts/shorts-qualification-2026-09-14/project-offer-control-corrected-01/SHORT-PROJECT.json`
- The prepared request referenced by that project's `requestPacket.path`
- `artifacts/shared-audio-2026-09-14/evaluation-01/voice-rnn/receipt.json`
- `artifacts/shared-audio-2026-09-14/review-02/audio/receipt.json`

The existing long-form route accepts a music asset and mixes it under speech.
`src/lib/server/native-short-project.ts:assertNativeShortIntent` currently
rejects requested music because the native Shorts route cannot deliver it yet.
Shared voice cleanup working in both formats does not imply shared music
sourcing and mixing are complete.

## Recommended sourcing policy

Start with a small internal library of licensed instrumental beds, then add AI
generation as an optional source when no approved track fits. Reuse downloaded
bytes only when their license permits the intended new use. The objective is
permission for monetized videos across the user's publishing platforms, not a
claim that every track is copyright-free.

| Option | Fit and constraint | Connection approach |
| --- | --- | --- |
| Pixabay | Free commercial video use under its license. Some tracks trigger Content ID; save download evidence and certificates where available. | Curated official downloads imported into the internal asset library. No music API assumed. |
| Eleven Music | AI generation with an official API. Current Starter pricing is $6/month for eligible individuals; company use requires checking plan eligibility. Existing output retains its applicable rights after cancellation. | Optional provider adapter; account entitlement and a spending limit must be established before paid calls. |
| Epidemic Sound Pro | Stock music for online commercial/client videos and ads. Videos published while subscribed remain cleared; new publications after cancellation need appropriate coverage. | Start with licensed downloads. Its separate commercial developer API has custom pricing; a consumer subscription is not proof of API entitlement. |

Provider facts checked against official sources:
[Pixabay FAQ](https://pixabay.com/service/faq/),
[Pixabay license](https://pixabay.com/service/license-summary/),
[ElevenLabs pricing](https://elevenlabs.io/pricing/api),
[Eleven Music model terms](https://elevenlabs.io/eleven-music-model-specific-terms),
[Eleven Music API](https://elevenlabs.io/docs/api-reference/music/compose),
[Epidemic Pro coverage](https://www.epidemicsoundhelp.com/hc/en-us/articles/26247236323858-Pro-Plan),
[Epidemic developer plans](https://developers.epidemicsound.com/).

AI generation does not guarantee unique output or freedom from infringement
claims. Eleven Music also restricts artist/song-name prompts. Describe mood,
instrumentation, tempo, and structure instead. Its individual plans must not be
assumed to cover an organizational account. Keep any internal track cache for
the permitted production use; do not turn it into a music redistribution
service. See [Music Terms](https://elevenlabs.io/music-terms) and the model terms.

## Build order and reuse

1. **Source and rights admission.** Extend the existing `AssetRecordV1` and
   source admission workflow, rather than inventing a separate music catalog.
   Bind track/provider identity, original URL, exact file hash, acquisition
   date, and license evidence. Include account/plan eligibility, permitted
   platforms, monetized/advertising/client uses, attribution, and whether a
   new publication requires an active subscription. Retain evidence in a
   versioned receipt linked to the asset. A file's presence is not permission;
   `guided_proposal_music.py` already distinguishes admission from rights.
2. **Music direction before assembly.** Add music intent to the same strategy
   that plans speech and visual beats: role, energy, tempo range, instruments,
   vocal preference, cue windows, transitions, and ending. Match perceived
   energy to speaking pace and narrative shifts; do not impose one BPM on all
   fast Shorts. Allow silence for explanation, emotion, and emphasis. Rank
   existing permitted tracks before retrieving or generating candidates.
3. **Provider adapter.** Resolve local approved assets first. Implement an
   official API adapter only for the chosen service and entitled account.
   Store provider/model, prompt hash, request receipt, cost, and output hash.
   Cache successful results so a rerender does not generate/bill again. A
   timeout must not blindly repeat a potentially billed request. Respect the
   user's local-work preference; generation can use a minimal generic music
   brief and does not require uploading footage, speech, or a transcript.
4. **One shared mix path.** Reuse `audio/music_stage.py:resolve_music_track`,
   `audio/program_mix_bus.py`, and the existing bed preparation, ducking, and
   mastering helpers. Adapt the native Shorts route to the shared float-audio
   path before its final encoding. Bind the music selection and timing to the
   native request/export identity and cache. Preserve music-disabled behavior.
   Add cue timing through a common contract when needed, rather than writing
   a separate Shorts mixer. Source audio containing music requires an explicit
   keep/replace decision so two beds are not layered accidentally.
5. **Review and delivery.** Show the actual track title, creator/provider,
   origin, and license status beside clearly labeled with-music and
   without-added-music previews. The latter may still contain music embedded
   in source footage and must say so. Check speech intelligibility, ducking
   recovery, stereo balance, loudness, peaks, edit joins, loops, and tail fades
   on the encoded deliverable. Attach the music evidence to the delivery
   report and recheck publication-dependent permissions before publishing.

## Completion evidence

- Render a fast Short, a slower teaching Short, and a multi-section long video
  through the same music helpers. Review actual encoded audio and measure cost
  and end-to-end time, including candidate selection and any generation.
- Exercise mono/stereo music, short beds that need fitting, silent tracks,
  abrupt endings, source-embedded music, quiet speech, and music-disabled runs.
- Test missing rights evidence, expired publication coverage, attribution,
  paid ads versus organic scope, changed files, provider failures, and reuse
  after cancellation according to the particular license.
- Run rights checks without publishing. Any later platform claim check uses
  the authorized publishing workflow; local analysis cannot promise that a
  platform will never issue a claim. Preserve evidence to resolve claims.
- Confirm no provider calls occur on cached rerenders and no private source
  media is transmitted by the music adapter.
- Mark ready only after actual renders and listening review, with any provider
  eligibility or unresolved licensing limits visible in the report.

No production code, provider credentials, subscription, or paid generation was
changed as part of preparing this plan.
