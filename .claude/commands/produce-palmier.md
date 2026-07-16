---
description: Produce incrementally from Claude Code Desktop into editable Palmier
argument-hint: <producer-dir-or-source-request>
---

Invoke the `producer` skill and use its **Claude Code Desktop → Palmier** branch.

If the request includes a reference URL/file or asks to mimic an edit, invoke
the `reference-editor` skill first. Do not reduce a meticulous reference job to
the aggregate `style_profile.json`; require its release-ready style pack.

The operator's request is: $ARGUMENTS

Non-negotiable execution contract:

1. Read Palmier with `get_projects` and `get_timeline`; never navigate or mutate
   an unbound project.
2. Ingest/transcribe, author and gate the cut-only previsual, then start the
   candidate-scoped lease with `.venv/bin/python3
   scripts/producer/palmier/desktop_cli.py begin`.
   Land the cut before planning the entire visual treatment.
3. Continue in this retained session. Build the full plan from the template
   catalog, graphics proposal, reference mechanics, and Failure Ledger. Run all
   deterministic gates and required review rounds.
4. Unlock the visual stage with `desktop_cli.py advance`, read the exact
   content-addressed operations path it returns, and execute it directly through
   Palmier MCP. Use returned IDs only. Read back after risky/dependent batches.
5. If interrupted, run `desktop_cli.py status`; use `reconcile` only for the one
   reserved operation whose mutation landed before its receipt. Never rebuild or
   replay verified work.
6. For text/style changes inside an existing card, preserve its id, kind,
   anchor, and timing; update its spec and run `desktop_cli.py advance ...
   --stage repair`. Execute only the returned import + `replace-overlay` work.
   Do not regenerate the base, unrelated cards, or a flattened master.
7. Do not claim completion until `desktop_cli.py qc` passes and both exact-export
   composition/editorial frame reviews pass `desktop_cli.py approve`.
