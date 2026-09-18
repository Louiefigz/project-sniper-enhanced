# PROJECT_SNIPER working instructions

Read and follow the shared workspace instructions in [../AGENTS.md](../AGENTS.md).
This file is at the actual Git root so a task started directly in PROJECT_SNIPER
can discover the shared instructions as well.

## Apply instructions before presenting work

For each task, identify the applicable requirements and verify them against the
actual result before handoff. Keep a compact requirement/source/evidence record
for substantive work in its existing notes; simple answers need no new files.
Reading an instruction is not proof that the result satisfies it. Preserve user
decisions and remaining requirements across revisions and context handoffs.

## Producer work

- Start or resume with the [context entry skill](.claude/skills/sniper-context/SKILL.md)
  (`$sniper-context` in Codex, `/sniper-context` in Claude Code), or run
  `python3 -B scripts/producer/context.py --project /absolute/selected-project`.
  It locates installed HyperFrames tools/skills, current catalog sources, scoped
  instructions and handoff files. Read the applicable files it identifies;
  discovery alone neither reads the instructions nor completes a review.
- Read the [Producer skill](.claude/skills/producer/SKILL.md) for editorial work
  and the [pipeline direction](docs/PIPELINE.md) for the applicable route. Follow
  required domain skills and referenced workflow instructions before their steps.
- For script selection and paper edits, apply the
  [context and trimming playbook](docs/producer/SHORTS_JOURNEY_SELECTION_PLAYBOOK.md)
  before showing candidates to the user. Read the assembled speech as a new
  viewer: who/what is this about, why does it matter, and does the ending answer
  the opening? Titles and editorial notes do not replace missing spoken context.
  Preserve enough source-backed development within the accepted duration; cut
  repetition before context. Mark source excerpts separately from proposed final
  speech, and keep exact source selections for proposed deletions.
- At video handoff, follow the shared
  [local playback and Studio requirement](docs/producer/STUDIO_REVIEW_LANE.md#required-review-handoff-local-playback-and-studio).
- For Producer implementation changes, read
  [the module map](scripts/producer/CLAUDE.md) and relevant architecture before
  adding or duplicating functionality. Preserve unrelated work and use the
  checks appropriate to the change.
