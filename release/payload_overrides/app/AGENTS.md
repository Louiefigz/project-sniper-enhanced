# Project Sniper — working instructions

These are the instructions for whichever agent is driving this editor: Codex reads
this file, Claude Code reads `CLAUDE.md` beside it. Both are complete on their own.
**This package is self-contained** — nothing here refers to a parent repository, a
sibling checkout or a developer machine.

## Apply the instructions before presenting work

For each task, identify the applicable requirements and verify them against the actual
result before handing it back. Reading an instruction is not proof that the result
satisfies it. Preserve the operator's decisions and the remaining requirements across
revisions and across context handoffs.

## Where the doctrine lives

| Read this | For |
|---|---|
| `docs/PIPELINE.md` | The canonical route. It wins every contradiction. |
| `.claude/skills/producer/SKILL.md` | The editing doctrine: how a plan is authored and gated. Codex adapters are in `.agents/skills/`. |
| `docs/producer/command-driven-editing/12_SHORT_LONG_EXECUTABLE_MATRIX.md` | Current route behaviour and its explicit blockers. |
| `scripts/producer/CLAUDE.md` | The Python engine's module map. Read before adding or duplicating engine functionality. |
| `docs/producer/STUDIO_REVIEW_LANE.md` | The required review handoff: local playback **and** the editable Studio project. |
| `docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md` | Selection and paper-edit rules before showing the operator candidates. |

## Producer work

- Read the Producer skill for editorial work and the pipeline direction for the
  applicable route. Follow the required domain instructions before their steps.
- For selection and paper edits, read the assembled speech as a new viewer would: who
  and what is this about, why does it matter, and does the ending answer the opening?
  A title is not spoken context. Cut repetition before context. Mark source excerpts
  separately from proposed final speech and keep the exact source selections for any
  proposed deletion.
- At video handoff, give the operator both the encoded video and the matching editable
  Studio project, and keep both current after an adjustment.
- Honour the requested destination and scope. A trim-only request must not gain
  graphics, motion, music or any other treatment nobody asked for.
- Run the applicable gates and QC before claiming anything is complete.

## What this install can and cannot do

- **The provider CLI is pinned.** `src/app/api/_lib/subscription-policy.ts` admits exactly
  one version string per provider and one authentication shape. Do not relax it, and do
  not change a global CLI to make a check pass. The pinned copies live in this package's
  `../runtime/cli/`.
- **Subscription only.** There is no paid-API path, and none may be added. Local
  processing plus the operator's own subscription is the whole model.
- **Never route video off the machine.** Transcript and plan text and the rendered
  still frames used for visual review go to the selected provider; the video does not.
- **Optional integrations are not configured here.** Palmier Pro, the `separate` audio
  preset and Frame Review are gated in this package. Do not advertise them as available,
  and do not route work through them.
- **The Shorts reference library is not included in this package** for provenance
  reasons. Do not tell the operator to consult it, and do not claim reference-matched
  execution. See `../PENDING-OWNER-DECISIONS.txt`.

## Checks

```bash
npm run type-check
npm run lint
npm test
cd scripts/producer && PYTHONPATH=.:tests ../../.venv/bin/python3 selftest.py
```

The Python suite is stdlib `unittest`, not pytest. Both suites must stay green. If a
change cannot be verified this way, say so explicitly rather than claiming success.
