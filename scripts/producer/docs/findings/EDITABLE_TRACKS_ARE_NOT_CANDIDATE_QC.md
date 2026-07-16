# Editable tracks are not candidate QC

## The defect

A busy NLE timeline can look persuasive while the delivery frame is blank,
clipped, illegible, mistimed, or editorially incoherent. Successful imports,
text insertion, keyframes, and track readback prove that editing operations
landed. They do not prove that the viewer receives a good video.

The July 13 Palmier evidence made the distinction visible: the timeline held a
speaker track, audio, graphics, and multiple full-frame visual clips while the
viewer at roughly 33 seconds showed an apparently white frame. At the same
time, a terminal described a deep product audit that explicitly was not
reviewing that specific edit. Neither the populated timeline nor the unrelated
audit could approve the candidate on screen.

## The evidence ladder

Keep four proofs separate:

1. **Execution proof** — the skilled session invoked the expected MCP tool and
   received a successful result.
2. **Editability proof** — fresh Palmier readback shows the actual text, clip,
   transform, or keyframes. The disposable smoke measured 25.522 seconds for
   its first text turn and 16.592 seconds for a resumed keyframe turn.
3. **Candidate proof** — the retained candidate has a fresh semantic
   fingerprint, remains bound to the unchanged parent, and its operation
   journal is hash-bound to the approved plan.
4. **Delivery proof** — export that exact candidate once, run deterministic
   graph/render/audio/frame checks, then run independent composition and
   editorial critics against the same export hash and evidence.

Only the fourth proof can authorize promotion. A count of tracks, clips, MCP
calls, or readback rows must never substitute for it.

## The repair rule

When delivery QC fails, preserve the editable candidate and the retained
session. Feed the exact failed lens, material issues, rejected fingerprint,
and cited export/frame evidence back to that session. Repair only the failed
operation IDs or lane, export the newly fingerprinted candidate, and rerun the
complete delivery gate.

Do not create a wholesale replacement for a full-plan live build. Replacement
throws away approved work, increases wall time, and can silently exchange the
candidate the critic saw for a different timeline.

## Speed without weaker review

The mutation turn should be deliberately cheap: retain the planning session,
use low execution effort, batch independent same-tool rows, and read back only
after risky or dependency-producing batches. The expensive independent
composition and editorial critics can run in parallel because both read the
same immutable export authority.

This shortens the critical path without moving QC earlier than the rendered
artifact it must judge.

## When not to use the full gate

A transport smoke that only asks whether one editable element can be created
does not need production editorial approval; label it as a smoke and remove
its disposable project. Likewise, a read-only diagnostic can stop at Palmier
readback. Any candidate offered for promotion, publishing, or operator signoff
requires exact-export delivery proof.
