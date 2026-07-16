# Palmier visual-mirror handoff

**Status: implemented in the current tree; offline contract tests pass.**

Read `docs/PIPELINE.md` for the whole Producer flow and
`docs/palmier/PALMIER_PARITY_CONTRACT.md` for the product invariants. This file is the
implementation map for the Sniper→Palmier bootstrap/fidelity mirror. It is a
compatibility layer beneath the Palmier-canonical product model in
`docs/palmier/PALMIER_CANONICAL_WORKFLOW.md`, not the final edit-authority direction.

## Product model

1. Before a managed Palmier timeline exists, Sniper's reviewed plan and
   approved visual/audio master are the bootstrap authority.
2. A valid, current, QC-approved Sniper master may seed Palmier even when some
   plan concepts are not natively editable there.
3. The bootstrap mirror is exact: one visible clip of approved `final.mp4`.
4. Capability findings remain honest: exact, approximate, baked, unsupported.
5. Once the managed Palmier timeline exists, its visible working revision is
   canonical. Opening it changes nothing; a manual edit advances the working
   head and invalidates older approval at the next reconciliation boundary.
6. AI work snapshots the complete current Palmier readback, copies that exact
   timeline with `create_timeline(from:)`, and edits the copy. It never replays
   a stale Sniper plan over the working head.
7. The candidate remains separate until deterministic/rendered QC plus an
   unchanged-parent compare-and-swap succeeds.
8. The legacy `ownership` sidecar field is only a compatibility mirror-writer
   lease. It is not the product's edit-authority switch, and the UI has no
   "Reclaim Sniper" path.
9. Component preservation stays honest: the exact master guarantees fidelity;
   imported component assets do not claim native reconstruction.

The exact mirror remains useful for bootstrapping and A/B fidelity proof. It is
not allowed to replace a newer canonical Palmier revision. Editing authority
uses direct Palmier readback and candidate forks; there is no lossy two-way
translation through `edit_plan.json`.

## Code map

- `palmier/master.py` — resolves the current approved visual master and its
  canvas/FPS/duration/hash authority.
- `palmier/parity.py` — native-editability findings plus the separate
  `mirrorReady` safety verdict. Unknown/malformed plan state blocks.
- `palmier/preflight.py` — pure mirror-safety/translation verdict.
- `palmier/translate.py` — emits one visual-master placement and non-visible
  component-import inventory.
- `palmier/media.py` — content-addressed Palmier library reuse/adoption/import.
- `palmier/mirror.py` — exact-master publication, component preservation, and
  atomic `sniper|palmier` ownership transitions.
- `palmier/executor.py` — places the one visible mirror clip.
- `palmier/verify.py` — readback proof for project/timeline/media identity,
  exact range, canvas, FPS, duration, and frame count.
- `palmier/shadow.py` — unclobberable shadow lifecycle and human-timeline
  restoration.
- `palmier/sync.py` — no-op detection and the verified shadow transaction.
- `palmier/sync_lock.py` — per-project lock, latest-wins queue, global Palmier
  serialization, and active-assemble deferral.
- `palmier/timeline_authority.py` — full MCP-readable snapshots, canonical and
  candidate fingerprints, copy verification, and QC/CAS promotion.
- `palmier/ownership.py` — offline lock-compatible handoff/reclaim CLI.
- `palmier/push.py` — CLI, preflight, authority gate, queue loop, and NDJSON.
- `src/app/api/producer/palmier/` — status, preflight, push, ownership, and open
  routes.
- `palmier-bar.tsx` — default-hidden capability report, current/stale A/B gate,
  and state-aware open/update actions.

## Persistent contracts

### `palmier.sync.json` schema v4

Representative shape:

```json
{
  "schemaVersion": 4,
  "ownership": "sniper",
  "mirrorMode": "visual-master",
  "projectId": "…",
  "projectName": "…",
  "projectPath": "/…/project.palmier",
  "lastPushPlanHash": "…",
  "latestTimelineId": "…",
  "mediaMap": {},
  "componentStatus": [],
  "laneFp": {"visual": "…", "components": "…"},
  "parity": {
    "schemaVersion": 1,
    "fullyEditable": false,
    "mirrorReady": true,
    "mirrorMode": "visual-master",
    "findings": [],
    "capability": {
      "visibleTimeline": "single-approved-master-clip",
      "visualAndAudioFidelity": "byte-identical-master",
      "componentAssets": "best-effort-non-visible-library-imports",
      "componentTimelineEditability": false
    }
  },
  "verification": {
    "ok": true,
    "planHash": "…",
    "timelineId": "…",
    "visualMaster": {"masterHash": "…"}
  },
  "timelineIds": []
}
```

Legacy sidecars default to Sniper ownership only for reading; new ownership
actions require a canonical schema-v4 visual-master sidecar.

### `final.palmier.meta.json`

Publication is an atomic byte copy of the approved master, then hash-verified:

```json
{
  "planHash": "…",
  "authorityHash": "…",
  "visualMasterHash": "…",
  "publishedHash": "…",
  "mirrorMode": "visual-master",
  "proof": "byte-identical-approved-master",
  "exportVerified": true,
  "visualVerified": true,
  "audioVerified": true,
  "audioProof": "byte-identical-approved-master"
}
```

For managed projects, `master.py` and the TS route both require the durable
quality-policy marker, schema-v2 approval, full authority digest, assembly
proof, deterministic audit evidence, clean planning reviews, both rendered
review lenses, frame hashes, and final bytes. Legacy behavior requires an
explicit legacy marker; missing/corrupt files never imply legacy.

## Sync transaction

1. Resolve the canonical producer dir, disk plan, manifest, and stored intent.
2. Require the current schema-v2 QC approval and recomputed authority digest.
3. Run `plan_lint` and pure parity preflight. Known capability limits may
   mirror; malformed/unknown state may not.
4. Refuse sync when `ownership == "palmier"`.
5. Probe approved `final.mp4`; bind exact path/hash/canvas/FPS/duration.
6. Reuse/import the master and component assets without placing components on
   the visible timeline.
7. Create a fresh shadow and place exactly one master clip.
8. Read it back and prove media identity, placement, duration, canvas, FPS, and
   frame count. Failure restores the prior human timeline and quarantines the
   partial shadow.
9. Publish `final.palmier.mp4` from exact master bytes and verify its hash.
10. Activate the verified shadow and atomically checkpoint schema v4.

An unchanged current hash reactivates the verified shadow without mutation.
There is no `--force`; changed mirrors always create a new fork.

## Component preservation

The component inventory includes, when declared and resolvable:

- original source media and transcripts;
- selected b-roll;
- selected music/audio beds;
- rendered graphics/animation overlays;
- caption/title artifacts;
- SFX artifacts.

Each is imported independently as best-effort non-visible library media. A
failure records its reason and does not compromise the exact visible mirror.
These assets are raw materials for manual Palmier work, not a claim that the
Sniper timeline was reconstructed into separate native controls.

## UI state machine

| State | UI behavior |
|---|---|
| Current verified mirror | Green verified chip; A/B enabled; **Open approved Palmier edit** available |
| Saved plan changed or preview stale | Palmier toggle disabled; **Update Palmier mirror** after new approval |
| Known editability limits | Mirror remains allowed; collapsed report labels native/flattened/no-control concepts |
| Newer manual Palmier head | Old A/B disabled; **Open current Palmier edit**; later AI work rebases from this head |
| Pending AI candidate | Parent stays preserved; **Review Palmier candidate**; approval remains pending |
| Malformed/unknown/unapproved | Red blocker; no MCP mutation |

The capability report is hidden by default so the editor opens on the video,
not a wall of diagnostic rows.

## Legacy ownership commands

These low-level compatibility commands remain for older mirror sidecars and
tests. They are not the current product workflow and must not be surfaced as a
"take control / reclaim" ceremony:

```bash
PYTHONPATH=scripts/producer .venv/bin/python3 \
  scripts/producer/palmier/ownership.py <producer-dir> --handoff

PYTHONPATH=scripts/producer .venv/bin/python3 \
  scripts/producer/palmier/ownership.py <producer-dir> --reclaim
```

`--reclaim` clears prior compatibility mirror proof. Canonical AI work still
must reconcile the live Palmier working head and may never clobber it.

## Verification

Offline:

```bash
cd scripts/producer/tests
../../../.venv/bin/python -m unittest test_palmier_*.py

npm run type-check
npm test
npm run lint
npm run build
```

Live verification is separate and must be intentional because it mutates the
open Palmier project. No live MCP call or user-project render is implied by the
offline test evidence in this document.

## MCP constraints and future native editability

Palmier currently exposes media clips, native text, trim/speed/transforms, and
some keyframes, but not a complete shared graph for HyperFrames groups, shapes,
icons, internal animations, captions, every transition, reframe grammar, audio
finish, and other Sniper concepts. Those remain capability findings.

Native adapters can be added incrementally, but they must include deterministic
validation, stable returned ids, full readback, rollback tests, and honest UI
copy. The exact visual-master mirror remains the reference even after native
controls improve.
