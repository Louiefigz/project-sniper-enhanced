# Project context entry

Start or resume a Sniper task with `/sniper-context` in Claude Code or
`$sniper-context` in Codex. The adapters share the canonical
[context skill](../../.claude/skills/sniper-context/SKILL.md).

The local command runs from any directory when given its absolute script path.
From the Project Sniper Git root:

```bash
python3 -B scripts/producer/context.py
python3 -B scripts/producer/context.py --project /absolute/project --workflow native-long
python3 -B scripts/producer/context.py --project /absolute/project --format json
python3 -B scripts/producer/context.py --workflow code --probe-tools
```

The default is read-only, offline and subprocess-free. It reads bounded package
and project JSON metadata, locates instructions, uses the existing local catalog
loader, and checks source readability. It does not run setup, the runtime
installer, managed preview status, skill refresh, catalog installation, render,
media probes, authentication or network calls. Optional fixed `--probe-tools`
version commands each have a three-second timeout; their output is reduced to a
numeric version and never printed verbatim. No `.env` or credential contents
are read. Local CLI behavior beyond its version invocation is not certified.

Without `--project`, no active project is selected. With it, that exact directory
and known state markers are inspected; the command never chooses the newest
project, export or receipt. If a selected brief container lacks a native
declaration, up to 64 immediate entries are inspected for child compositions.
Matching children are listed as unselected candidates, with a truncation flag;
there is no recursion or directory-symlink traversal. Use `--project` with the
chosen declared composition for its actual project state and route reads.
Scoped ancestor `AGENTS.md` paths and selected
project `CLAUDE.md`/handoff markers are exposed. Paths are available context, not
proof the agent has read them. The owning agent must read applicable files and
follow their references before dependent work. Generic scaffold instructions
cannot override a selected governed route or higher-priority user instructions.

Auto-routing reuses the native exporter's declaration selector. A single Short
or Long manifest reports its declared route, while missing, conflicting,
unreadable or malformed manifests remain explicit. This is discovery, not
schema validation or render admission. Pass `--workflow` to request a planned
route's reads even before its manifest exists; the report keeps the observed
project route separate. For editing implementation, select `code` to include
the module map. More specialized instructions are followed progressively.

Tool paths and installed package versions are current local observations.
Adapted runtime cache entries are metadata only: no runtime is selected or
qualified. Installed HyperFrames domain skills are distinguished from archived
vendor copies. The current native direction in [PIPELINE](../PIPELINE.md) owns
the route; old vendor mirror prose is provenance, not present workflow policy.

Catalog output separates the historical mirror lock from current source files.
Merged catalog entries include local integrations and upstream mirror entries;
the separate mirror count covers upstream sources even for a merged local port.
Missing, broken-link, non-file and unreadable states remain distinct. Inventory
does not refresh upstream or certify templates for the requested composition.

Project JSON may contribute only a closed set of recorded status labels.
Arbitrary text, commands, secrets and review narratives are not echoed. A
recorded `pass` or `completed` is explicitly historical and cannot certify
current hashes, strategy, speech fidelity, motion or listening. Default video
handoff still requires checked local playback and matching live editable Studio
under [the review handoff rule](STUDIO_REVIEW_LANE.md#required-review-handoff-local-playback-and-studio).

Exit code 2 means the explicitly selected directory was unavailable or invalid;
the error reports its class without echoing exception contents. Optional tool
and catalog gaps remain reported inventory with exit code 0. The inventory is
limited to supported Sniper/HyperFrames tools and known project markers, not an
exhaustive machine, MCP, plugin or recursive artifact audit.

## Requirements and evidence

| Requirement and source | Action | Evidence/status |
|---|---|---|
| User: stop overlooking installed HyperFrames | Read installed runtime/package metadata and domain skill paths | Live command sample and focused tests below |
| Standing agreement: applicable instructions before work | Emit ancestor chain, route reads and explicit project markers; adapters require full applicable reading | Route/scoped-instruction tests; reading itself remains the agent's duty |
| User: clear context command for both agents | Canonical skill, Claude command and Codex adapter | Skill surface and skill validation checks |
| Preserve native governance | Reuse native selector and reference shared exporter/review lane | Manifest conflict/symlink tests; no renderer or gate changes |
| Honest state, no active/latest assumption | Explicit selection, known markers and bounded unselected child candidates | No-selection, decoy-directory, candidate-bound and historical-status tests |
| Local discovery, no secrets/install side effects | Default executes no subprocess; safe metadata fields and error classes | No-execution and secret-redaction tests |
| Current sources versus old lock | Existing catalog loader plus per-source readability | Historical/current-count test and observed sample |

## Checked sample: September 17, 2026

Running the absolute script path from `/private/tmp` against the SamCart proof
container reported the following current observations:

```text
HyperFrames package / SDK: 0.8.31 / 0.8.31
Adapted runtime metadata: 8 entries; none selected or qualified
Merged catalog: 418 entries; 416 source files readable, 2 missing
Historical mirror lock (2026-08-28): 371 installed / 372 listed
Mirror source files now: 370 readable / 372 indexed, 2 missing
Missing mirror entries: lt-neon-border, texture-mask-text
Selected outer container: native-undeclared
Immediate declared candidates: prepared-project-03, source-project
Candidate scan: 22 entries inspected, not truncated; neither selected
```

The lock records an upstream add error for `lt-neon-border`.
`texture-mask-text` is already recorded absent in the mechanism study but omitted
from the lock's missing list; the underlying installation cause is unknown.
No files were fetched to repair either. Counts and candidates above are a dated
observation, not pinned capability claims or active-project selection.

Optional version probes returned Node `23.10.0`, FFmpeg/FFprobe `8.0`, Codex
`0.144.1` and Claude `2.1.247`. Whisper's path was found without a version probe.
The full command reports absolute executable/package/skill paths and source
statuses; JSON includes both installed skill roots and adapted runtime entries.

Verification completed:

- `.venv/bin/python -B -m unittest discover -s scripts/producer/tests -p test_context_entry.py -v`:
  16 bounded tests passed, including live catalog loading with subprocesses
  disabled, explicit selection, redaction, configured `CODEX_HOME`, and child scan.
- `node scripts/tests/skill_surface.test.mjs`: passed for both agent adapters
  and Claude command/README discovery.
- Skill creator `quick_validate.py`: both canonical skill and Codex adapter
  passed using the existing sibling `youtube-automation/venv` Python with
  PyYAML. Sniper's own venv lacks PyYAML; nothing was installed.
- Mechanical checks: logic files under 300 lines, functions under 50 lines,
  at most four parameters/two nested control levels, docstrings/type hints, and
  tracked diff whitespace checked. No broader build or media checks were needed.
- Independent semantic review passed after fixing consistent `CODEX_HOME`
  instruction/skill lookup; the bounded candidate-discovery addition also
  passed a separate re-review. These reviews concern this context tool, not the
  video project's production, playback or listening approval.
