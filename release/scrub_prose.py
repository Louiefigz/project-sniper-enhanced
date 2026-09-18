#!/usr/bin/env python3
"""Second migration stage: remove creator, course and client identities from prose.

    python3 -m release.scrub_prose [--dry-run]

`release.migrate_names` renamed the identifiers. What remained were people and
organisations named in comments, docs and skills: reference creators, course
authors and — more seriously — a client and the people in a client's recording.
The distributed product must carry none of them. Maintainer tooling, not shipped.

Line-level rules come first: some lines exist only to identify someone or to link
into a sibling repository's paid material, and are removed or rewritten whole.
Phrase rules follow, then single names. Run the suites afterwards, and read the
changed lines: a phrase list does not certify the result.
"""
from __future__ import annotations

import argparse
import re

from release.migrate_names import ROOT, candidates

# Whole lines that identify a person or link into a sibling repository's corpus.
DROP_LINE = (
    re.compile(r"\*\*Creator:\*\*.*\(Punch Young"),
    re.compile(r"\]\(\.\./\.\./\.\./youtube-automation/"),
    re.compile(r"Creator doctrine \(taught, not measured\): \[`adrian-per/`\]"),
)
# Ordered phrase rules (case-sensitive; longest first).
PHRASES: tuple[tuple[str, str], ...] = (
    ("Trevor / World Pet Health's", "a client's"),
    ("World Pet Health", "a client"), ("WorldPet Health", "a client"), ("WorldPet", "a client"),
    ("Trevor Odom's", "a reviewer's"), ("Trevor Odom", "a reviewer"),
    ("Restrained Ralston", "Restrained"), ("Ralston's payoff criteria", "the payoff criteria"),
    ("Restrained/Lewis", "expansion"), ("Lewis Mudrich", "a second reference creator"),
    ("Hormozi 121 swipe file", "the packaged Director hook library"),
    ("Hormozi's 121-hook swipe file", "the packaged Director hook library"),
    ("QUEST archetypes + Hormozi 121", "the packaged Director hook library"),
    ("the RAG hook stack", "the packaged Director library (resources/director)"),
    ("Hormozi-bot", "coaching-bot"), ("Hormozi hooks", "hook swipe files"),
    ("Kallaway-kinetic", "kinetic"), ("Kallaway-grade", "kinetic-grade"),
    ("Kallaway-style", "kinetic-style"), ("Kallaway-ized", "kinetic"),
    ("full Kallaway", "full kinetic"), ("Kallaway screenshots", "kinetic reference screenshots"),
    ("The Kallaway grammar", "The kinetic grammar"), ("the Kallaway reference", "the kinetic reference"),
    ("Kallaway intro style", "kinetic intro style"), ("Kallaway is maximalist", "Kinetic is maximalist"),
    ("the iampunch shorts grammar", "the punch shorts grammar"),
    ("_references/iampunch/", "_references/punch/"), ("iampunch", "the punch reference"),
    ("@personalbrandlaunch", "a reference account"), ("personalbrandlaunch", "a reference account"),
    ("Nate-style", "module-style"), ("nate-offer", "module-offer"), ("nate-native", "module-native"),
    ("Nate's", "the module reference's"), ("NATE_", "MODULE_"),
)
# Remaining single names, whole-word, in order.
NAMES: tuple[tuple[str, str], ...] = (
    (r"\bTrevor's\b", "the client's"), (r"\bTrevor\b", "the client"),
    (r"\bLewis\b", "a second reference creator"), (r"\bRalston\b", "the reference creator"),
    (r"\bKallaway\b", "kinetic"), (r"\bHormozi\b", "a published hook bank"),
    (r"\bNate\b", "module"), (r"\bnate\b", "module"),
)
TEXT = frozenset({".md", ".ts", ".tsx", ".py", ".mjs", ".cjs", ".js", ".json", ".html",
                  ".css", ".txt", ".yaml", ".yml"})


def scrub(text: str) -> str:
    """Apply the line, phrase and name rules to one text."""
    kept = [line for line in text.split("\n") if not any(rule.search(line) for rule in DROP_LINE)]
    text = "\n".join(kept)
    for old, new in PHRASES:
        text = text.replace(old, new)
    for pattern, new in NAMES:
        text = re.sub(pattern, new, text)
    return text


def main(argv: list[str] | None = None) -> int:
    """Scrub every shipped-surface text file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    changed = 0
    for path in candidates():
        if path.suffix.lower() not in TEXT:
            continue
        try:
            before = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        after = scrub(before)
        if after != before:
            changed += 1
            print(f"{'would change' if args.dry_run else 'changed'} {path.relative_to(ROOT)}")
            if not args.dry_run:
                path.write_text(after, encoding="utf-8")
    print(f"{changed} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
