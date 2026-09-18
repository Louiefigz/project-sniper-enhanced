"""Manifests and readable documents for the packaged reference library.

Called by `release.reference_library_writer`. The loaders read the manifests; the
agent reads the Markdown. Both are generated from the same records, so they agree.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from release import reference_library_spec as spec

ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _rel(target: str, from_file: Path) -> str:
    """Markdown link from a document to a repo-relative frame path."""
    return os.path.relpath(ROOT / target, from_file.parent)


def _frames_md(frames: list[dict], doc: Path) -> str:
    return " ".join(f"![{frame['render']['time_s']:g}s]({_rel(frame['path'], doc)})" for frame in frames)


def _case_md(case: dict, doc: Path, fields: tuple[str, ...]) -> str:
    lines = [f"# {case['id']} · {case['title']}", "",
             "Original reference rendered from Project Sniper's own templates. The copy in "
             "the pictures is illustrative; a real edit uses the speaker's words.", ""]
    lines += [f"**{name.replace('_', ' ').capitalize()}:** {case[name]}" for name in fields if case.get(name)]
    lines += ["", f"**Catalog:** {', '.join(case['catalog'])}", ""]
    for beat in case["beats"]:
        idea = beat.get("spoken_idea") or beat.get("message_paraphrase") or beat.get("idea", "")
        lines += [f"## {beat['id']} — {idea}", ""]
        if beat.get("visible"):
            lines += [f"**On screen:** {beat['visible']}", ""]
        if beat.get("why_this_picture"):
            lines += [f"**Why:** {beat['why_this_picture']}", ""]
        lines += [_frames_md(beat["source_frames"], doc), ""]
    return "\n".join(lines)


def _entry_md(entry: dict, doc: Path) -> str:
    return "\n".join([f"# {entry['id']} · {entry['title']}", "",
                      f"**Story job:** {entry['story_job']}", "",
                      f"**Use when:** {entry['use_when']}", "",
                      f"**Do not use when:** {entry['do_not_use_when']}", "",
                      f"**Composition:** {entry['catalog'][0]}", "",
                      _frames_md(entry["frames"], doc)])


FOUNDATIONS = """
# Format foundations — choose by what the viewer needs to see

Pick a picture for what the viewer needs at that moment, not for variety.

| The viewer needs to… | Use | Reference |
|---|---|---|
| count along with parallel points | a list that builds as it is spoken | A01 |
| see a change | before and after in one frame | A02 |
| hold one thesis | one statement with one emphasis | A03 |
| compare ways to reach one goal | a fixed destination with changing routes | N26 |
| see a rate, not just a total | the amount and the time together | N27 |
| notice the word that carries the point | emphasis drawn after reading | N10 |
| find one part of a busy screen | a push-in on that control | N04 |
| hold a whole argument | one diagram that develops node by node | CR07 |
| see a belief corrected | the same page with the line replaced | LM06 |
| follow a long section in order | the whole path, then one step lit at a time | LF01 |

**Always:** return to the speaker when the picture has done its job; hold anything with
text long enough to read; keep the copy in the speaker's words.

**Never:** show a picture the words do not need, or leave one up after the speaker has
moved on.
"""


def write_documents(out: Path, entries: list, sequences: list, expansion: list, longform: list) -> None:
    """Write every manifest and document for the library."""
    shorts, seq, exp, lf = out / "shorts", out / "shorts/sequences", out / "shorts/expansion", out / "longform"
    _json(shorts / "manifest.json", {"schema": "sniper-reference-library-v1", "version": spec.VERSION,
                                     "entry_count": len(entries), "entries": entries})
    for entry in entries:
        _md(shorts / "entries" / f"{entry['id']}.md", _entry_md(entry, shorts / "entries" / f"{entry['id']}.md"))
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
    catalog = "\n".join(f"| {case['id']} | {case['title']} | {', '.join(case['catalog'])} |"
                        for case in sequences + expansion)
    table = f"| Case | Mechanism | Compositions |\n|---|---|---|\n{catalog}"
    _md(seq / "CATALOG_MAP.md", f"# Sequence catalog map\n\n{table}")
    _md(exp / "CATALOG_MAP.md", f"# Expansion catalog map\n\n{table}")
    _md(seq / "DIRECTING_GUIDE.md", "# Directing guide\n\nRead each case's lesson, then its beats "
        "in order. Every beat names the composition that renders it and three frames showing the "
        "mechanism develop. Adapt the mechanism to the speaker's words; never reuse the copy.")
    _json(lf / "manifest.json", {"schema_version": 1, "scope": "original-long-form-references",
                                 "cases": [{"id": c["id"], "aspect": "16:9",
                                            "case_path": f"resources/references/longform/cases/{c['id']}.json"}
                                           for c in longform]})
    for case in longform:
        _json(lf / "cases" / f"{case['id']}.json", case)
    _md(out / "README.md", README)


README = """
# Reference library (packaged, original)

Worked examples of editing mechanisms — how a list builds, how a comparison holds a fixed
goal, how emphasis lands after reading — each illustrated by frames rendered from Project
Sniper's own motion templates.

**Provenance.** Written and rendered for Project Sniper on 2026-09-17 by
`release/reference_library_writer.py` from `release/reference_library_spec.py`. Every frame
records the composition, the variables and the time that produced it. No third-party
footage, screenshot, brand, likeness or creator name appears anywhere in this library.
Earlier development builds used a research library built from other creators' videos;
that library is not part of this product.

**Scope.** These are references, not qualified templates or benchmarks. A reference shows a
mechanism working with illustrative copy; it does not show that a finished Short using it
performs well.
"""
