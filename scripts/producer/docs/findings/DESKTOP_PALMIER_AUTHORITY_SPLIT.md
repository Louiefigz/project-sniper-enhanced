# Desktop Palmier needs staged authority, not an on/off bypass

## Finding

Claude Code Desktop was given two contradictory contracts:

1. `.claude/skills/producer/SKILL.md` said to converge a complete plan before a
   frame was produced and never hand-drive Palmier.
2. `.claude/hooks/palmier_guard.py` denied every mutating Palmier MCP tool.
3. The only escape hatch, `.sniper-palmier-livedrive`, disabled that protection
   for **every** mutation in the project.

That is why the workflow alternated between long stalls and fast but visibly
under-governed edits. The global marker carried no project id, timeline id,
plan hash, lane scope, operation ancestry, expiry, or readback receipt.

## What outperformed the obvious approach

Use a staged candidate-scoped authority:

| Stage | Cheap proof required | Mutations unlocked |
|---|---|---|
| cut | transcript-cut previsual gate | cut/source operations only |
| visual | plan, hook, and claims gates + rendered asset worklist | graphics, motion, b-roll, captions, color, audio |
| repair | exact failed-candidate evidence | scoped cut + visual repair |

Each mutation is a compare-and-swap transaction:

1. PreToolUse fresh-reads the active project/timeline.
2. It requires the candidate id and fingerprint to equal the last verified
   state, verifies all bound files by SHA-256, validates tool/lane scope, and
   reserves the operation.
3. PostToolUse fresh-reads again, requires an observable structural/content
   delta (except library-only imports), appends an fsynced receipt, updates the
   candidate fingerprint, and only then unlocks the next mutation.
4. If Desktop or the hook stops between steps 2 and 3, `reconcile` may adopt
   only that reserved operation. It never guesses from chat history.

This lets the cut appear early without letting downstream visual work bypass
its checks. The durable JSONL journal also means a 90-minute edit can resume
without rebuilding or replaying verified work.

## Reference mechanics that changed the quality target

The Module reference (`J_jswzXhYJA`, 5:23) is not smooth because it uses a
large number of stock transitions. The study found:

- 20 distinct card forms across 23 graphic windows;
- graphics visible for roughly 93% of the timeline after 13.5 seconds;
- only 7 hard cuts (about 1.3/minute);
- a roughly 136-second screen-share chapter kept alive by persistent PIP,
  cursor movement, and scrolling rather than repeated scene transitions.

The transferable rule is: **tokens repeat; layouts do not**. Smoothness comes
from progressive module builds, word-locked entrances, a stable face bridge,
earned seam punctuation, and clear visual hierarchy. “Use more transitions”
without those mechanics creates noise, not polish.

## Implementation

- `palmier/desktop_cli.py` — begin/advance/status/reconcile/qc/approve.
- `palmier/desktop_authority.py` — candidate lease and durable lifecycle.
- `palmier/desktop_gates.py` — staged deterministic gates.
- `palmier/desktop_manifest.py` — rendered catalog assets plus native lane
  worklist and quality contract.
- `palmier/desktop_hook.py` — pre/post mutation CAS and receipts.
- `.claude/hooks/palmier_guard.py` — ignores the global marker and requires
  the staged lease.

## When not to use it

Do not use direct Desktop mutation for an approved flat-master mirror or when a
requested lane has no measured Palmier representation. Use the in-house render
or explicitly surface the limitation. Do not map a named color grade by guess;
use exact Palmier knobs/a real LUT, then inspect the exported candidate.

## Remaining proof

Unit tests prove authority, replay, stage-scope, readback, reconciliation, and
transition-preview contracts offline. The prior smoke proves a retained Claude
session can call Palmier text and motion tools. A later first-60 run exercised
more transport and mutation mechanics, but failed product-quality review after
56m48s: QC remained pending, seven captions lost karaoke timing, and the wrong
3840×2160 canvas was accepted. Representative connected short/long evidence,
complete readback/export, audio-route authority, and failure/manual-edit
preservation are still required before the Desktop path is P5-qualified.
