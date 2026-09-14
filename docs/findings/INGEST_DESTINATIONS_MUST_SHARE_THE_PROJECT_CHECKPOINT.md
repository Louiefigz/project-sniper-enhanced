# Ingest destinations must share the actual project checkpoint

The supporting-media HTTP audit found that target selection and lease selection
used different precedence rules. A request naming both `projectRoot: A` and
`outDir: B` could lock A while preparing B. Supplying only B's `source/` directory
also checked for a journal inside `source/`, although the managed project's
checkpoint lived in `producer/`. A deeper destination could escape the old
one-parent project lookup entirely.

The fix makes the destination one explicit choice and derives its physical
project owner before acquiring a lease. The source, producer and project-root
output paths all consult the same producer checkpoint. Nested managed output
paths, redirected source/producer directories, malformed project markers and
ambiguous nested project ownership are rejected. A standalone legacy output
folder continues to own its existing standalone lease and journal.

The route retains that selected root and producer directory together with the
actual live lease guard. Before starting Python and before reading its result,
it checks both the held lease identity and the current destination ownership.
A directory that becomes part of a managed project during preparation cannot
silently switch which checkpoint controls the request.

Input paths matter too. Folder ingest writes `broll_catalog.json` into the input
B-roll folder. A referenced directory in another managed project is therefore
not a read-only source. The route checks the actual prepared input before Python
runs. A fresh copied folder belongs to the new project; a referenced foreign
project folder is rejected. Individual media-file imports remain available.

Seven focused regressions cover conflicting/malformed selectors, managed
source/root/producer checkpoint parity, nested paths, redirected directories,
untagged layouts, foreign catalog protection and ownership drift. Alongside
existing mutation, intake and placement checks, 50 checks pass. These are
control/file tests; live HTTP/media qualification is recorded separately.

This does not establish global filesystem isolation or a new project registry.
It closes the specific routing mismatch while reusing the existing checkpoint,
lease, stable file-reading and media admission mechanisms. Use normal speech
preparation for changed recordings; supporting-media rescan continues to retain
only verified unchanged transcripts.
