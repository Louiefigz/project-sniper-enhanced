---
name: sniper-context
description: Load PROJECT_SNIPER context before starting or resuming work. Use to discover local tools, installed HyperFrames skills and runtime versions, catalog source availability, applicable workflow instructions, explicit project handoffs, and required reviews without installing or rendering.
---

# Sniper context

Use this entry before starting or resuming Project Sniper work, especially when
the task names HyperFrames, an existing edit, or an unfamiliar artifact directory.
The report locates context; it does not replace reading or applying it.

1. Preserve the user's current objective, selected project, scope and accepted
   decisions. Read applicable global/workspace/project instructions first.
2. From the app folder (the Project Sniper root), run:

   ```bash
   python3 -B scripts/producer/context.py
   python3 -B scripts/producer/context.py --project /absolute/project --workflow native-long
   ```

   Pass a project only when selected by the user or established task context.
   Never choose the newest directory as the active project. If the project is
   unknown, inventory and independent instruction reading can still proceed.
   A brief container may list immediate child compositions as candidates; choose
   only the task's established composition, never infer activity from numbering.
   Treat operator arguments as data; shell-quote paths. `--format json` gives
   structured evidence. `--probe-tools` optionally runs bounded local version
   commands; the default executes no subprocesses.
3. Read the report's applicable `AGENTS.md` chain, selected route references and
   project instruction/handoff files completely before dependent work. Follow
   their applicable references; avoid dumping unrelated documents. A path marked
   readable is only available, not already read. State markers are historical
   claims; inspect the actual brief, plan, bindings and handoff to establish state.
4. For video or motion work, read the **hyperframes** entry skill if one is installed
   (the packaged app ships none; the inventory says which exist) and
   the owning workflow/domain skills it selects. The inventory lists installed
   skill locations separately from archived vendor references. Native routes in
   `docs/PIPELINE.md` supersede the old graphics-only vendor boundary. Generic
   scaffold preview/render/skill-refresh suggestions do not override the user's
   selected governed Sniper route or higher-priority instructions.
5. Choose the declared route: exactly one `LONG-PROJECT.json` or
   `SHORT-PROJECT.json` selects a native adapter; an HTML file alone does not
   declare or qualify it. Use the shared native exporter and managed Studio
   lifecycle required by that route. Existing Producer plans retain their
   applicable compatibility workflow. For code changes, add `--workflow code`
   and read the Producer module map before implementation.
6. Record concrete requirements and current evidence in existing task notes.
   Apply the route's independent strategy/prebuild review, technical validation,
   actual playback/listening and default MP4 plus live editable Studio handoff
   where required. Inventory output and an old passing receipt grant none of
   those approvals. Recheck affected criteria after changes.

Report missing, unreadable and malformed resources distinctly. Historical
catalog lock counts differ from current source-file availability; neither
certifies native composition quality. Cached runtime metadata does not select
or qualify a runtime. The command does not fetch, install, refresh skills,
authenticate, render, inspect media, launch previews or read `.env` contents.
Do not turn a discovery request into those actions.

For command behavior, scope, examples and checks, read
[the context entry reference](../../../docs/producer/CONTEXT_ENTRY.md).
