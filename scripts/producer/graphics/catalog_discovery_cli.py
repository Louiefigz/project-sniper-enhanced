#!/usr/bin/env python3
"""Search the recorded HyperFrames catalog or inspect one exact item.

CLI (run with the project venv, from anywhere)::

    catalog_discovery_cli.py search "<words>" [--type block|component|local]
        [--declared-aspect 16:9|9:16] [--status <status>] [--tag <tag>]
        [--limit N] [--format json|text]
    catalog_discovery_cli.py lookup <name|mirror:name|local:kind> [--format ...]

Read-only: never executes catalog HTML, renders, fetches or writes. Exit 0 on
an answer (an empty search IS an answer), 1 when a lookup finds nothing, 2 on
a usage/loader error. JSON is the contract; text is the concise reading form.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from graphics.catalog_discovery import (  # noqa: E402
    ASPECTS, DEFAULT_LIMIT, STATUSES, TYPES, SearchFilters, load_catalog,
    lookup_item, search_catalog,
)

_TEXT_WIDTH = 110


def _parser() -> argparse.ArgumentParser:
    """Build the closed search and lookup argument surface."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--format", choices=("json", "text"), default="json")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="keyword search, bounded + ranked")
    search.add_argument("query", nargs="+")
    search.add_argument("--type", choices=TYPES)
    search.add_argument("--declared-aspect", choices=ASPECTS)
    search.add_argument("--status", choices=STATUSES)
    search.add_argument("--tag")
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    lookup = commands.add_parser("lookup", help="exact item by name or ref")
    lookup.add_argument("name")
    return parser


def _clip(text: str, width: int = _TEXT_WIDTH) -> str:
    """Normalize whitespace and bound a displayed text field."""
    text = " ".join(text.split())
    return text if len(text) <= width else text[:width - 1] + "…"


def _declared_line(record: dict) -> str:
    """Display declared facts separately from measured capability."""
    declared = record["declared"]
    dims = declared["dimensions"]
    parts = [f"declared {dims[0]}x{dims[1]}" if dims else "declared canvas: none",
             f"aspects {declared['aspects'] or '?'} ({declared['aspectSource'] or 'unknown'})"]
    if record.get("duration"):
        parts.append(f"{record['duration']}s")
    measured = record["integration"]["measured"]
    if measured:
        parts.append(f"MEASURED {measured['canvas'][0]}x{measured['canvas'][1]} "
                     f"{measured['aspect']} {measured['fadeClass']}")
    return " · ".join(parts)


def _record_lines(record: dict, position: int | None) -> list[str]:
    """Format one result with its provenance and adaptation notes."""
    head = f"{position}. " if position else ""
    integration = record["integration"]
    lines = [f"{head}{record['ref']}  [{record['type']} · {integration['status']} · "
             f"{record['provenance']}]"]
    if record.get("match"):
        match = record["match"]
        why = "; ".join(f"{term}→{','.join(fields)}"
                        for term, fields in match["matchedTerms"].items())
        lines.append(f"   match: score {match['score']} · {why}"
                     + (f" · unmatched {match['unmatchedTerms']}"
                        if match["unmatchedTerms"] else ""))
    lines.append(f"   {_clip(record['title'] + ' — ' + record['description'])}")
    if record.get("templateVariables"):
        lines.append(f"   template variables: {', '.join(sorted(record['templateVariables']))}")
    upstream = record.get("upstream")
    if upstream:
        reference = upstream["reference"]
        lines.append(f"   source: {reference['path']} "
                     f"({'present' if reference['exists'] else 'MISSING'})")
    lines.append(f"   {_declared_line(record)}")
    study = record.get("study")
    if study:
        lines.append(f"   study: fit={_clip(str(study['fit']), 40)} · "
                     f"port={_clip(str(study['port']), 40)} · "
                     f"scrubSafe={study['scrubSafe']} · aspectFlex={study['aspectFlex']}")
    lines.extend(f"   note: {_clip(note)}" for note in record["adaptationNotes"])
    lines.extend(f"   DISAGREEMENT: {_clip(item)}" for item in record["disagreements"])
    return lines


def _provenance_lines(provenance: dict) -> list[str]:
    """Display loaded source facts and reported disagreements."""
    mirror, capability = provenance["mirror"], provenance["capability"]
    lines = [f"mirror: {mirror['source']} CLI {mirror['cliVersion']} mirrored "
             f"{mirror['mirroredAt']} · lock {mirror['itemsListed']} listed / "
             f"{mirror['itemsInstalled']} installed · index {mirror['indexRecords']} · "
             f"sources present {mirror['referenceSourcesPresent']} · "
             f"known missing {mirror['knownMissing']}",
             f"study: {provenance['study']['records']} records — {provenance['study']['note']}",
             f"capability: {'FRESH' if capability['fresh'] else 'UNAVAILABLE: ' + capability['error']}"
             f" · {capability['releaseReadyKinds']} release-ready of "
             f"{capability['integratedKinds']} integrated kinds · ported {sorted(provenance['ported'])}"]
    lines.extend(f"ISSUE: {item}" for item in provenance["issues"])
    lines.extend(f"DISAGREEMENT: {item}" for item in provenance["disagreements"])
    return lines


def render_text(result: dict) -> str:
    """Concise human-readable form of a search or lookup result."""
    lines = _provenance_lines(result["provenance"]) + [f"scope: {result['scope']}"]
    if "results" in result:
        lines.append(f"search {result['query']!r} → {result['total']} match(es), "
                     f"showing {result['returned']}"
                     + (f" · ignored short terms {result['ignoredTerms']}"
                        if result["ignoredTerms"] else "")
                     + (" (LIMITED — raise --limit or narrow the query)"
                        if result["limited"] else "")
                     + (f" · exact matches excluded by filters: "
                        f"{result['excludedExactMatches']}"
                        if result["excludedExactMatches"] else ""))
        for position, record in enumerate(result["results"], start=1):
            lines.extend(_record_lines(record, position))
        return "\n".join(lines)
    lines.append(f"lookup {result['name']!r} → "
                 f"{'found' if result['found'] else 'NOT FOUND'} "
                 f"({len(result['matches'])} record(s))")
    for record in result["matches"]:
        lines.extend(_record_lines(record, None))
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> tuple[dict, int]:
    """Execute one parsed command; return (result, exit code)."""
    catalog = load_catalog()
    if args.command == "lookup":
        result = lookup_item(catalog, args.name)
        return result, 0 if result["found"] else 1
    filters = SearchFilters(type=args.type, declared_aspect=args.declared_aspect,
                            status=args.status, tag=args.tag, limit=args.limit)
    return search_catalog(catalog, " ".join(args.query), filters), 0


def main(argv: list[str] | None = None) -> int:
    """Print JSON (default) or text; loader/usage errors exit 2."""
    args = _parser().parse_args(argv)
    try:
        result, code = execute(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"schemaVersion": 1, "ok": False,
                          "error": f"{type(exc).__name__}: {exc}"}))
        return 2
    for issue in result["provenance"]["issues"]:
        print(f"issue: {issue}", file=sys.stderr)
    print(render_text(result) if args.format == "text"
          else json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
