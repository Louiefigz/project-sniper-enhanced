#!/usr/bin/env python3
"""Write the reference library's manifests and Markdown from rendered records.

Called by `release/reference_library_writer.py` after every beat is rendered. All
prose here was written for Project Sniper on 2026-09-18; case content comes from
`release/reference_library_spec.py`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from release import reference_library_spec as spec

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = ("Original reference written for Project Sniper and rendered from its own motion templates. "
          "Adapt the mechanism with the speaker's own words and footage; never reuse this copy or its numbers.")


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _rel(target: str, from_file: Path) -> str:
    """A link from one library document to a repository-relative path."""
    return os.path.relpath(ROOT / target, from_file.parent)


def _frames_md(frames: list[dict], doc: Path) -> str:
    return " ".join(f"![{frame['render']['time_s']:g}s]({_rel(frame['path'], doc)})" for frame in frames)


def _case_md(case: dict, doc: Path, fields: tuple[str, ...]) -> str:
    lines = [f"# {case['id']} — {case['title']}", "", ORIGIN, ""]
    lines += [f"**{name.replace('_', ' ').capitalize()}:** {case[name]}" for name in fields if case.get(name)]
    lines += ["", f"Compositions: {', '.join(case['catalog'])}", ""]
    for beat in case["beats"]:
        idea = beat.get("spoken_idea") or beat.get("message_paraphrase") or beat.get("idea", "")
        lines += [f"## {beat['id']} — {idea}", ""]
        if beat.get("visible"):
            lines += [f"Visible: {beat['visible']}", ""]
        if beat.get("why_this_picture"):
            lines += [f"Why this picture: {beat['why_this_picture']}", ""]
        lines += [_frames_md(beat["source_frames"], doc), ""]
    return "\n".join(lines)


def _entry_md(entry: dict, doc: Path) -> str:
    return "\n".join([f"# {entry['id']} — {entry['title']}", "", ORIGIN, "",
                      f"**Story job:** {entry['story_job']}", "", f"**Use when:** {entry['use_when']}", "",
                      f"**Do not use when:** {entry['do_not_use_when']}", "",
                      f"Composition: {entry['catalog'][0]}", "", _frames_md(entry["frames"], doc)])


FOUNDATIONS = """
# Format foundations

Start from what the viewer needs to see, not from a layout. For each important
beat, name the viewing need, choose the picture that meets it, decide how that
picture develops, and decide when it leaves. The cases below are original
references rendered from Project Sniper's own templates. Open their frames before
adapting a mechanism, and adapt the mechanism, never the copy or the numbers.

| Viewing need | Picture that meets it | Develops by | Leaves when | Case | Contrast |
|---|---|---|---|---|---|
| Believe a claim | the claim alone, then the measurement and its limit | adding the evidence, then its limit | the limit has been read | [SQ01](sequences/cases/SQ01.md) | [ME02](entries/ME02.md): when the evidence is a sum of items |
| Judge a comparison of two values | both measured bars, then the difference and the shared conditions | bars first, difference second, conditions last | the conditions have been read | [SQ02](sequences/cases/SQ02.md) | [SQ03](sequences/cases/SQ03.md): when there are more than two parts |
| See which part matters most | every part on one axis, then a verdict | bars on a shared axis, verdict last | the verdict has been read | [SQ03](sequences/cases/SQ03.md) | [SQ02](sequences/cases/SQ02.md): when only two values are compared |
| Follow a checklist to the end | rows that land as checks are named, then a finished state | one row per spoken check | the finished state is shown | [SQ04](sequences/cases/SQ04.md) | [DV01](expansion/cases/DV01.md): a side rail when the speaker's face must stay large |
| Keep the speaker and the points together | a rail beside the speaker | one row per spoken point | the last point has been spoken | [DV01](expansion/cases/DV01.md) | [SQ04](sequences/cases/SQ04.md): a full-frame checklist when the list is the subject |
| Follow a multi-part argument | a short deck, one page per part | turning the page on each spoken transition | the last page has been read | [DV02](expansion/cases/DV02.md) | [ME03](entries/ME03.md): a single marker when the parts need no summary |
| Remember a short rule | one typographic lockup above the speaker | nothing: one state, held | the rule has been said | [ME01](entries/ME01.md) | [SQ01](sequences/cases/SQ01.md): when the rule is a claim that needs evidence |
| Believe a total | the items, then the total they make | rows first, total bar with them | the total has been read | [ME02](entries/ME02.md) | [SQ03](sequences/cases/SQ03.md): when the parts should be ranked, not summed |
| Know a new part has begun | a section marker on the empty side of the frame | nothing: one state, held | the marker has been read | [ME03](entries/ME03.md) | [DV02](expansion/cases/DV02.md): when each part needs its own summary |
| Rejoin a long argument (16:9) | a chapter timeline with the finished chapters marked | marking a chapter done at each transition | the next chapter starts | [LG01](../longform/cases/LG01.json) | [DV02](expansion/cases/DV02.md): the portrait version for a short argument |

Rules for every case:

- One job per picture. A beat that needs two jobs needs two beats.
- Nothing appears before it is said, and everything that appears stays long enough
  to read at delivery size.
- Keep the example constant across beats so the change is visible; change one
  thing per beat.
- A landscape frame placed inside a portrait Short shrinks; check label
  legibility at phone size before reusing a landscape case.
- Reference frames illustrate a mechanism. They are not production assets, not
  qualified templates and not evidence that a finished Short works.
"""

DIRECTING_GUIDE = """
# Directing guide for sequence cases

Each sequence case records, per beat, the spoken idea, what is visible, why that
picture serves the words, and the rendered frames with the template, variables
and time that produced them.

1. Read the case's lesson and payoff, then open every frame of its opening,
   development and payoff beats.
2. Name the mechanism in one sentence, for example "one row per spoken check".
3. Open at least one contrasting case for the same viewing need
   (`../FORMAT_FOUNDATIONS.md`).
4. Rebuild the mechanism with the speaker's own words, timing and footage; never
   reuse a case's copy or numbers.
5. Record the case ID, beat IDs and your adaptation in the storyboard.
"""

README = """
# Reference library

Original reference cases for planning the visuals of Shorts and long-form videos.
Authored for Project Sniper on 2026-09-18 and rendered from Sniper's own motion
templates by `release/reference_library_writer.py` from
`release/reference_library_spec.py`. Every topic, line and number in the cases is
an illustration written for this library; no case reproduces a third-party video,
person or course. Every frame records the template, variables and time that
rendered it, so the library can be regenerated and audited.

- `shorts/FORMAT_FOUNDATIONS.md` — start here: viewing needs, cases and contrasts.
- `shorts/sequences/` — SQ cases: several beats of one idea (`manifest.json`,
  `cases/`, `frames/`, `CATALOG_MAP.md`, `DIRECTING_GUIDE.md`).
- `shorts/expansion/` — DV cases: one composition developing across beats
  (`manifest.json`, `cases/`, `frames/`, `catalog-sources.json`, `CATALOG_MAP.md`).
- `shorts/entries/` and `shorts/manifest.json` — ME entries, one mechanism each.
- `longform/` — LG cases for 16:9 work.

References show a mechanism. They are not production assets, qualified templates
or benchmarks of finished videos. Frames are re-rendered when the templates'
design changes, so their colours and type follow the current templates.
"""


def write_documents(out: Path, entries: list, sequences: list, expansion: list, longform: list) -> None:
    """Write every manifest and document of the library under `out`."""
    shorts, seq, exp, lf = out / "shorts", out / "shorts/sequences", out / "shorts/expansion", out / "longform"
    _json(shorts / "manifest.json", {"schema": "sniper-reference-library-v1", "version": spec.VERSION,
                                     "entry_count": len(entries), "entries": entries})
    for entry in entries:
        doc = shorts / "entries" / f"{entry['id']}.md"
        _md(doc, _entry_md(entry, doc))
    _md(shorts / "FORMAT_FOUNDATIONS.md", FOUNDATIONS)
    _json(seq / "manifest.json", {"schema": "sniper-reference-sequences-v1", "version": spec.VERSION,
                                  "cases": sequences})
    for case in sequences:
        _json(seq / "cases" / f"{case['id']}.json", case)
        doc = seq / "cases" / f"{case['id']}.md"
        _md(doc, _case_md(case, doc, ("lesson", "opening", "story_arc", "payoff")))
    rows = [{"id": c["id"], "title": c["title"],
             "case_path": f"resources/references/shorts/expansion/cases/{c['id']}.json"} for c in expansion]
    _json(exp / "manifest.json", {"version": spec.VERSION, "case_count": len(expansion), "cases": rows})
    for case in expansion:
        _json(exp / "cases" / f"{case['id']}.json", case)
        doc = exp / "cases" / f"{case['id']}.md"
        _md(doc, _case_md(case, doc, ("message", "arc", "execution", "avoid", "typography")))
    _json(exp / "catalog-sources.json", {"version": spec.VERSION, "source_inspection_only": True,
                                         "adaptations_render_qualified": False,
                                         "sources": sorted({c for case in expansion for c in case["catalog"]})})
    table = "\n".join(f"| {case['id']} | {case['title']} | {', '.join(case['catalog'])} |"
                      for case in sequences + expansion)
    catalog = ("# Catalog map\n\nWhich Sniper compositions each Shorts case uses or suggests. A listed "
               "composition is a starting point, not a qualified template.\n\n"
               f"| Case | Title | Compositions |\n|---|---|---|\n{table}")
    _md(seq / "CATALOG_MAP.md", catalog)
    _md(exp / "CATALOG_MAP.md", catalog)
    _md(seq / "DIRECTING_GUIDE.md", DIRECTING_GUIDE)
    _json(lf / "manifest.json", {"schema_version": 1, "scope": "original-long-form-references",
                                 "cases": [{"id": c["id"], "aspect": "16:9",
                                            "case_path": f"resources/references/longform/cases/{c['id']}.json"}
                                           for c in longform]})
    for case in longform:
        _json(lf / "cases" / f"{case['id']}.json", case)
    _md(out / "README.md", README)
