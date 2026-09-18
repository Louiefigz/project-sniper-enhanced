# Connecting a Claude client to Palmier Pro (interactive live editing)

Palmier Pro (the AI-native macOS NLE) exposes a **local MCP server at
`http://127.0.0.1:19789/mcp` while the app is open**. A Claude client can connect
to it and **drive Palmier directly** — placing clips, text, keyframes, color, and
exporting — conversationally, so you watch each edit land in the timeline in real
time.

> **What this is vs. the GUI pipeline (read this first).** This is the
> **interactive live-drive** path: a human asks a Claude client to build/adjust a
> timeline in Palmier by hand over MCP. It is **fast, hands-on, and ungated**, and
> it is **distinct from the GUI PRODUCER pipeline**, which authors a gated
> `edit_plan.json` and mirrors an *approved master* into Palmier one-way (see
> [`PIPELINE.md`](../PIPELINE.md)). The live-drive is a **manual workflow, not an
> automated pipeline stage** — there is no agent-driven live pipeline built into
> the app today (the proposal to fold it in is [`PALMIER_LIVE_BUILD_SPEC.md`](PALMIER_LIVE_BUILD_SPEC.md)).

## Prerequisite

**Palmier Pro must be installed and OPEN** — the MCP only serves while the app is
running. Sanity check:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:19789/mcp \
  -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
# 200 = Palmier is up and serving MCP
```

## Claude Code — recommended

The repo ships a project-scoped **`.mcp.json`** at its root declaring the
`palmier-pro` server. Open Claude Code in this repo and it will **discover the
server and prompt you to approve it** (project-scoped MCP servers require one
approval per project). Approve it, then verify:

> "List my Palmier projects."

The `mcp__palmier-pro__*` tools become available.

**Why Claude Code is the best client for this:** unlike Claude Desktop it *also*
has your repo files (the producer editing doctrine at
`.claude/skills/producer/SKILL.md`, the comp catalog, HyperFrames), **bash** (to
run the deterministic proposers), and the **filesystem** (to read footage +
transcripts) — all in one place. So it drives Palmier **with your studied editing
doctrine**, not just generic video knowledge.

## Claude Desktop — works, but with a caveat

Claude Desktop's **Connectors UI rejects a plain-`http` localhost URL** with
`URL must start with 'https'`. Palmier serves plain HTTP on `127.0.0.1`, so the
Connectors UI cannot add it. Use the **config-file + `mcp-remote` bridge** instead
(`mcp-remote` allows localhost HTTP). Edit
`~/Library/Application Support/Claude/claude_desktop_config.json` and merge in:

```json
{
  "mcpServers": {
    "palmier-pro": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:19789/mcp"]
    }
  }
}
```

Then **fully quit** Claude Desktop (`Cmd+Q`, not just close the window) and reopen
it; verify with "List my Palmier projects."

> **Caveat:** Claude Desktop is sandboxed. It can *drive* Palmier, but it cannot
> read your footage/transcripts, run the proposers, or load the producer doctrine
> — so it edits with **generic** video knowledge. For a doctrine-driven edit, use
> Claude Code.

## Giving Claude the footage (works from Desktop too)

**Yes — you give Claude the file path.** You paste the **absolute local path**
(e.g. `~/Downloads/C0679.MP4`) and Claude calls Palmier's `import_media`
with it. This works *even from sandboxed Claude Desktop* because **Claude Desktop
never reads the file** — it tells the **local Palmier app** to import that path,
and Palmier (running on your machine) reads it from disk itself. The footage bytes
never pass through Claude / Anthropic.

- Use the **full absolute path**, not a relative one — Palmier resolves it on your
  machine. Say e.g. *"Import `~/Downloads/C0679.MP4` into the project."*
- Large files take time — Palmier waits up to ~5 min for the import/transcode.
- **The transcript: you don't need to paste it either.** After import, ask Claude
  to call Palmier's `get_transcript` — Palmier transcribes the media itself and
  returns word-level timing. So footage *and* transcript are both covered by
  Palmier's own tools; Desktop needs no local file access for either. (What Desktop
  still can't do is run *your repo's* proposers or load the doctrine — that's the
  Claude Code advantage.)

## The live-drive workflow (what to ask Claude to do)

1. Open Palmier Pro (create or open the target project).
2. In **Claude Code**, load the producer editing doctrine so Claude follows your
   studied styles + graphics catalog: invoke the `producer` skill (or point it at
   `.claude/skills/producer/SKILL.md`).
3. Point Claude at the footage + transcript.
4. Ask it to **build the edit live** — cuts first (they land in seconds), then
   graphics from the catalog, then motion/keyframes — each element placed via MCP
   so you watch the timeline populate.
5. Steer conversationally ("tighten that cut", "add a zoom here"); **export from
   Palmier** when done.

## Palmier MCP tools (reference)

Call `get_projects` / `get_timeline` first; IDs are short prefixes — pass them
back exactly. Timeline positions are **project frames**; source positions are
**seconds** (the tools convert — never multiply by fps yourself).

`open_project` · `new_project` · `get_projects` · `set_active_timeline` ·
`create_timeline` · `get_timeline` · `get_media` · `import_media` · `search_media`
· `add_clips` · `insert_clips` · `move_clips` · `remove_clips` · `split_clips` ·
`ripple_delete_ranges` · `set_clip_properties` · `set_keyframes` · `sync_clips` ·
`add_texts` · `update_text` · `add_captions` · `apply_color` · `apply_effect` ·
`apply_layout` · `manage_tracks` · `remove_silence` · `remove_words` ·
`denoise_audio` · `detect_beats` · `generate_image` · `generate_video` ·
`generate_audio` · `export_project` · `undo`.
