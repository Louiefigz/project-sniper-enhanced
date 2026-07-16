#!/usr/bin/env python3
"""ledger_lessons — machine interface to docs/findings/FAILURE_LEDGER.md.

The FAILURE LEDGER is the learning loop's memory: every defect a QC panel or
the operator catches becomes (a) a ledger table row naming its encoding and
(b), where the fix is judgment rather than code, a ``LESSON-id`` line in the
"## Brain lessons" section that the authoring prompts are contractually bound
to obey (auto-edit ``authoring.ts`` + SKILL.md step 4).

This module parses both halves — pure string ops, format only (deterministic
code owns WHERE; the lessons' meaning is the brain's) — and regenerates the
"known past failure modes" section of ``QC_CHECKLIST.md`` from the rows so
future QC panels start from every past miss. Fails loudly on a missing file,
a missing section, or a malformed lesson line: a ledger the loop cannot read
is a defect, not a fallback case.

CLI:
    ledger_lessons.py lessons            # JSON list of {id, text}
    ledger_lessons.py rows               # JSON list of ledger rows
    ledger_lessons.py sync-checklist     # rewrite QC_CHECKLIST derived block
"""

from __future__ import annotations

import json
import os
import sys

_FINDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "docs", "findings")
LEDGER_PATH = os.path.join(_FINDINGS_DIR, "FAILURE_LEDGER.md")
CHECKLIST_PATH = os.path.join(_FINDINGS_DIR, "QC_CHECKLIST.md")

LESSONS_HEADING = "## Brain lessons"
_DERIVED_BEGIN = "<!-- LEDGER-DERIVED:BEGIN (ledger_lessons.py sync-checklist) -->"
_DERIVED_END = "<!-- LEDGER-DERIVED:END -->"


def _section(text: str, heading: str) -> str:
    """The body of one ``## heading`` section (to the next ## or EOF)."""
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines)
                     if ln.strip() == heading)
    except StopIteration:
        raise ValueError(f"FAILURE_LEDGER has no {heading!r} section")
    body: list[str] = []
    for ln in lines[start + 1:]:
        if ln.startswith("## "):
            break
        body.append(ln)
    return "\n".join(body)


def parse_lessons(path: str = LEDGER_PATH) -> list[dict]:
    """The Brain lessons: ``[{"id": "LESSON-001", "text": "..."}]``.

    Every non-empty line in the section must be a ``- LESSON-<n>: text``
    bullet — anything else raises (fail loudly; the section is a contract
    the authoring prompts obey line-by-line, so silent skips are corruption).
    """
    with open(path, encoding="utf-8") as f:
        body = _section(f.read(), LESSONS_HEADING)
    lessons: list[dict] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.lstrip("-*").strip()
        head, sep, text = line.partition(":")
        if not sep or not head.startswith("LESSON-") \
                or not head[len("LESSON-"):].isdigit() or not text.strip():
            raise ValueError(
                f"malformed Brain lessons line {raw!r} — every line must be "
                "'- LESSON-<n>: imperative sentence'")
        lessons.append({"id": head, "text": text.strip()})
    if not lessons:
        raise ValueError("Brain lessons section is empty — the learning loop "
                         "has no contract to enforce")
    return lessons


def parse_rows(path: str = LEDGER_PATH) -> list[dict]:
    """The ledger table rows as dicts keyed by the header cells."""
    with open(path, encoding="utf-8") as f:
        body = _section(f.read(), "## Ledger")
    table = [ln.strip() for ln in body.splitlines()
             if ln.strip().startswith("|")]
    if len(table) < 3:
        raise ValueError("Ledger table needs a header, a separator and at "
                         "least one row")
    header = [c.strip() for c in table[0].strip("|").split("|")]
    rows: list[dict] = []
    for ln in table[2:]:                       # [1] is the |---| separator
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) != len(header):
            raise ValueError(f"ledger row has {len(cells)} cells, header has "
                             f"{len(header)}: {ln!r}")
        rows.append(dict(zip(header, cells)))
    return rows


def failure_modes_md(rows: list[dict]) -> str:
    """The derived 'known past failure modes' bullets for QC_CHECKLIST.md."""
    out = []
    for r in rows:
        out.append(f"- **{r['id']}** ({r['caught-by']}): {r['defect']} — "
                   f"encoded as {r['encoded-as']} [{r['status']}]")
    return "\n".join(out)


def sync_checklist(ledger: str = LEDGER_PATH,
                   checklist: str = CHECKLIST_PATH) -> None:
    """Regenerate the checklist block between the LEDGER-DERIVED markers."""
    with open(checklist, encoding="utf-8") as f:
        text = f.read()
    if _DERIVED_BEGIN not in text or _DERIVED_END not in text:
        raise ValueError(f"{checklist} is missing the LEDGER-DERIVED markers")
    head, rest = text.split(_DERIVED_BEGIN, 1)
    _, tail = rest.split(_DERIVED_END, 1)
    block = failure_modes_md(parse_rows(ledger))
    with open(checklist, "w", encoding="utf-8") as f:
        f.write(f"{head}{_DERIVED_BEGIN}\n{block}\n{_DERIVED_END}{tail}")


def _cli() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lessons"
    if cmd == "lessons":
        print(json.dumps(parse_lessons(), indent=2))
    elif cmd == "rows":
        print(json.dumps(parse_rows(), indent=2))
    elif cmd == "sync-checklist":
        sync_checklist()
        print(json.dumps({"ok": True, "checklist": CHECKLIST_PATH}))
    else:
        print(json.dumps({"ok": False, "errors": [
            f"unknown command {cmd!r} (lessons | rows | sync-checklist)"]}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
