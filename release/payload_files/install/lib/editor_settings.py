"""Settings for Sniper's interactive Claude editor window (install/editor.command).

    python3 -B install/lib/editor_settings.py <app-dir>

Prints the JSON passed to ``claude --settings``: a subscription login only, and
every CLAUDE.md-style instruction file in the folders ABOVE the app excluded, so a
package inside the home folder does not load the buyer's ~/CLAUDE.md or
~/.claude/CLAUDE.md into Sniper's editor. The app's own CLAUDE.md (which imports
AGENTS.md) and CLAUDE.local.md still load.
"""
import json
import os
import sys

_NAMES = ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md"), os.path.join(".claude", "rules", "**"))


def ancestor_instruction_files(app_dir: str) -> list:
    """Instruction-file patterns in every folder above ``app_dir``, nearest first.

    Both the path as given (what the CLI walks from its working folder) and its
    resolved spelling are covered, so a package under a symlinked folder is too.
    """
    excluded = []
    for start in dict.fromkeys((os.path.abspath(app_dir), os.path.realpath(app_dir))):
        folder = os.path.dirname(start)
        while True:
            excluded.extend(p for p in (os.path.join(folder, n) for n in _NAMES) if p not in excluded)
            if folder == os.path.dirname(folder):
                break
            folder = os.path.dirname(folder)
    return excluded


def main() -> int:
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.stderr.write("usage: editor_settings.py <app-dir>\n")
        return 64
    print(json.dumps({"forceLoginMethod": "claudeai", "claudeMdExcludes": ancestor_instruction_files(sys.argv[1])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
