#!/usr/bin/env python3
"""Convert a saved project's legacy identifiers to the neutral names.

    python3 -m release.normalize_project <project-dir> [--check]

Maintainer tooling, not shipped. The distributed runtime accepts only the neutral
identifiers, so a project saved before the rename has to be converted before it
is opened by a release build. Run it on a **copy**: it rewrites
`project.json`, `producer/edit_plan.json` and `producer/reference.json` in place,
and writes a `.pre-rename` backup of each file it changes.

The legacy table is imported from `release.migrate_names`, so the source rename
and the saved-data conversion can never disagree.

`--check` reports what would change and exits 1 when anything still needs it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from release.migrate_names import convert

FILES = ("project.json", "producer/edit_plan.json", "producer/reference.json")


def _changed(path: Path) -> tuple[str, str] | None:
    """Original and converted text for a file that needs conversion."""
    if not path.is_file():
        return None
    original = path.read_text(encoding="utf-8")
    converted = convert(original)
    if converted == original:
        return None
    json.loads(converted)  # a conversion that breaks JSON is a bug; fail loudly
    return original, converted


def normalize(project: Path, check: bool) -> list[str]:
    """Convert one project; return the files that needed it.

    Args:
        project: Project directory (a copy — originals are never the target).
        check: Report only.
    """
    touched: list[str] = []
    for name in FILES:
        path = project / name
        result = _changed(path)
        if result is None:
            continue
        touched.append(name)
        if check:
            continue
        backup = path.with_name(path.name + ".pre-rename")
        if not backup.exists():
            shutil.copyfile(path, backup)
        path.write_text(result[1], encoding="utf-8")
    return touched


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not (args.project / "project.json").is_file():
        print(f"not a project directory: {args.project}", file=sys.stderr)
        return 2
    touched = normalize(args.project, args.check)
    verb = "needs conversion" if args.check else "converted"
    for name in touched:
        print(f"{verb}: {name}")
    if not touched:
        print("already neutral")
    return 1 if (args.check and touched) else 0


if __name__ == "__main__":
    raise SystemExit(main())
