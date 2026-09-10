# Hold the returned caption projection; do not render it again

`render._explicit_caption_stage` calls `project_render_captions` before it
defers caption burn for `skip_graphics`. Therefore the actual returned
`RenderCtx.caption_projection` already contains the full compilation, artifact
authority, cue alpha shards, and existing 30-second lossless alpha pages.
An opening/body bridge can reuse that actual generation rather than compile
or materialize a second caption generation.

The new `guided_caption_projection.py` helper captures that returned object
under separately held plan, manifest, timeline, transcript/dependency and
execution-input bindings. Readback checks the same complete local/external
inventory, including later-body cues/pages, font/fontconfig bytes, tools and
compiler/page code. It never calls a materializer, cache `_current`, decoder,
provider, or approval operation. Guarded identity projections exactly match
the existing compiler/page digest domains.

`stage_caption_dependencies` creates a private new directory and copies only
the existing caption artifacts needed by Audit B. It preserves original
source-manifest resolution; source manifests, fonts, tools and alpha pages
are not moved. Files use descriptor-relative exclusive creation, not hardlinks
or replacement. Failed partial directories are retained and cannot be reused.

## Actual evidence, 2026-09-07

Final command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts:scripts/producer:scripts/producer/tests \
  .venv/bin/python -m unittest test_guided_caption_projection test_guided_caption_projection_media -v
```

16/16 passed in 14.499 seconds suite / 14.93 seconds wall. Retained output:
`/private/tmp/sniper-held-caption-media-n1wtktil`; full log:
`/private/tmp/sniper-held-caption-helper-final-20260907.log`.

Measured phases: synthetic inputs 1,662 ms; actual ordinary 1080p NTSC base
and returned caption projection 11,526 ms; capture 61 ms; read 30 ms; new
Audit B dependency staging 65 ms. Two actual caption cues and their alpha
page passed existing shard/page validators. The entire original renderer
output/work inventory and admitted synthetic source bytes remained unchanged.

Fourteen metadata/file tests additionally cover changed source-facing
documents, transcript/font/tool/media/receipt drift, omitted later assets,
identity-domain parity, malformed JSON, symlink/FIFO/hardlink rejection,
mid-read deadline, retained partial staging, actual parent rename/symlink
confinement, and growth exactly at descriptor-open (zero bytes read).

The first media cohort also passed 15/15 in 15.36 seconds before the final
preflight-open hardening; retain it separately at
`/private/tmp/sniper-held-caption-media-fyvxjqvv`.

## Limits and remaining integration

The helper is not wired into opening/body execution. Its in-memory type,
supplied binding, or saved hashes **do not authenticate an invocation**. The
owning service still must hold the actual successful renderer return,
source/pipeline authority, original deadline, cleanup and approval lineage.
This test uses synthetic admission metadata and makes no creator-source,
guided-worker, final QC, audiovisual listening, or delivery approval claim.

Bounds: nonempty regular single-link files ≤2 GiB, held inventory ≤4,096
files/16 GiB, JSON ≤16 MiB, cues ≤1,024 and pages ≤256. External font refs
are bounded and observed locally; nothing is downloaded. The caller's guard
is used before/after work and between bounded chunks, never replaced with a
fresh allowance. These are helper workload bounds, not quality limits.

The shared picture graph still needs explicit caption-tail ordering and
integer frame gates, so original page-local frame zero is shifted by its
absolute page start. The retained final picture must be captured **after**
this combined graph; the later legacy caption burn must not re-encode it.
Existing full-master selection, one AAC delivery, packet-copy checks, whole
QC and prefix proof remain independent requirements.

Pages reduce cue decoder fanout, but do not waive the existing pre-encode
oracle's 64 Mi native input-pixel aggregate admission. Never drop captions,
downscale, or increase the cap silently. This helper does not claim fixed
native FFmpeg RSS or general long-form caption workload qualification.
