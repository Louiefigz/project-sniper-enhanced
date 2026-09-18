# Final-project storage requirement

Aaron's September 9 requirement: keep intermediate work while editing when it
makes revisions faster; after he accepts a final edit, reclaim disposable media
so projects do not consume unnecessary disk. Preserve the original recording,
the final edited video and the ability to reopen the edit in HyperFrames Studio.
This requirement does not authorize deleting current files before final acceptance.

## Observed current behavior

- Existing caption/audio/graphics caches support reuse during editing. Removing
  them during a live revision would defeat the work already done to avoid renders.
- Existing worker/claim cleanup handles execution resources; the coordinator's
  code/command search found no complete final-project storage cleanup workflow.
- `scripts/producer/studio/project_assets.py::stage_base_video` makes a real copy
  of the graphics-free base inside `studio/assets/`. The preview server rejected
  symlinks in the retained implementation check.
- `studio/studio_review.py` opens a project using its edit plan and
  `base_final.mp4`. The generated Studio view also retains composition files,
  assets and a view manifest. The final MP4 alone is not the editable project.

Therefore “keep only two video files” and “Studio opens immediately with all
editable graphics intact” are not both guaranteed by the current code. A compact
archive would need explicit support to rebuild any intentionally discarded
working base from retained source/plan before reopening. Do not silently delete
the current Studio base or replace it with an already composited final video.

## Required finish-and-cleanup behavior

1. While a project is active, retain current reusable media and in-flight or
   unsynced Studio work. Show storage usage by original/source, required project
   media, final exports, reusable intermediates and obsolete temporary outputs.
2. Bind finalization to the exact user-accepted export and project version. Final
   playback, decode and required delivery checks remain prerequisites; accepting
   an earlier draft does not finalize a later file.
3. Produce a project-scoped cleanup preview listing exact files, reasons, retained
   dependencies and reclaimable disk bytes. Distinguish actual reclaimable blocks
   from apparent size for shared/hardlinked/cloned data. Unknown ownership or
   references are blockers, not permission to delete by filename or age.
4. Retain original media, the accepted final export, edit plan, transcript and
   source mapping, required Studio compositions/assets, original resource/approval
   records and compact provenance needed to reopen/rebuild. Protect shared media,
   templates, fonts and caches still used by another active project.
5. Delete only verified project-owned disposable intermediates: superseded draft
   exports, obsolete temporary cut copies, regenerable audio/graphics/caption
   renders and duplicate working media whose retained replacement and consumers
   are established. Do not sweep Downloads, /private/tmp, or a global cache.
6. Refuse cleanup during rendering, unresolved publication/recovery, unsynced
   Studio edits or a changed final/dependency set. Recheck the exact planned files
   before deletion; do not follow a substituted symlink or broaden a stale plan.
7. Verify retained originals/final bytes and Studio reopenability after cleanup.
   A future revision can regenerate discarded caches, with its resulting time
   cost made clear. Record freed space and any failed deletions accurately.

## Storage tradeoff to implement explicitly

The requested long-term target is original media + final export + a small project
archive and genuinely necessary assets. The current Studio base may still be a
large required file. Before deleting it, implement and verify rehydration/rebinding
from retained originals and the saved plan, or retain it and show its cost. Do not
describe a project as small or fully reopenable merely because its JSON is small.

Any reversible quarantine or Trash option must report that bytes are still on
disk until actually removed; it must not claim reclaimed capacity prematurely.

## Scope and timing

No footage, draft, evidence, cache or project asset was deleted while recording
this requirement. Keep the current revised real-video draft as the immediate
priority. Storage finalization is a separate bounded feature for the implementation
owner, with read-only inventory first and actual deletion tested on disposable
fixtures before use on a completed creator project. This document is a requirement
and observed implementation gap, not a shipped cleanup feature or permission to
execute deletion against the current unfinished edit.
