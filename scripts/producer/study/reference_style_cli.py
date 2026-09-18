#!/usr/bin/env python3
"""Prepare and compile meticulous reference-editing style packs."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.reference_review import (build_worklist, canonical_hash,
                                    load_object)  # noqa: E402
from study.reference_review_media import extract_review_media  # noqa: E402
from study.reference_style_pack import (PackInputs, compile_style_pack,
                                        template_registry_skeleton)  # noqa: E402


def _atomic_json(path: str, value: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)


def _prepare(args: argparse.Namespace) -> dict:
    worklist = build_worklist(args.video, args.deep_study)
    worklist = extract_review_media(worklist, args.output_dir)
    path = os.path.join(args.output_dir, "reference_review_worklist.json")
    _atomic_json(path, worklist)
    return {"status": "review-ready", "worklist": os.path.abspath(path),
            "items": len(worklist["items"]),
            "sourceFrames": worklist["coverage"]["sourceFrames"],
            "contactSheets": sum(len(row.get("contactSheets", []))
                                 for row in worklist["items"])}


def _compile(args: argparse.Namespace) -> dict:
    inputs = PackInputs(args.worklist, args.mechanics_review,
                        args.editorial_review, args.templates,
                        args.deep_study, args.adjudication)
    pack = compile_style_pack(inputs)
    _atomic_json(args.output, pack)
    return {"status": "style-pack-ready", "path": os.path.abspath(args.output),
            "releaseClass": pack["releaseClass"],
            "windows": len(pack["grammar"]["windows"]),
            "templates": sum(1 for row in pack["grammar"]["windows"]
                             if row.get("template"))}


def _review_template(args: argparse.Namespace) -> dict:
    worklist = load_object(args.worklist)
    blank = {"kind": "", "informationForm": "", "layoutFamily": "",
             "transitionFamily": "", "animationFamily": ""}
    value = {
        "schemaVersion": 1, "lens": args.lens,
        "worklistHash": canonical_hash(worklist),
        "sourceHash": worklist.get("source", {}).get("sha256"),
        "items": [{"itemId": row["id"], "verdict": "pending",
                   "materialIssues": [], "confidence": 0.0,
                   "classification": dict(blank), "observations": {}}
                  for row in worklist.get("items") or []],
    }
    _atomic_json(args.output, value)
    return {"status": "review-template-ready", "lens": args.lens,
            "path": os.path.abspath(args.output), "items": len(value["items"])}


def _template_skeleton(args: argparse.Namespace) -> dict:
    value = template_registry_skeleton(
        args.worklist, args.mechanics_review, args.editorial_review,
        args.adjudication)
    _atomic_json(args.output, value)
    return {"status": "template-registry-ready", "path": os.path.abspath(args.output),
            "bindings": len(value["bindings"])}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("video"); prepare.add_argument("deep_study")
    prepare.add_argument("output_dir")
    compile_cmd = commands.add_parser("compile")
    compile_cmd.add_argument("worklist"); compile_cmd.add_argument("mechanics_review")
    compile_cmd.add_argument("editorial_review"); compile_cmd.add_argument("templates")
    compile_cmd.add_argument("deep_study"); compile_cmd.add_argument("output")
    compile_cmd.add_argument("--adjudication")
    review = commands.add_parser("init-review")
    review.add_argument("worklist")
    review.add_argument("lens", choices=("mechanics", "editorial", "adjudication"))
    review.add_argument("output")
    templates = commands.add_parser("init-templates")
    templates.add_argument("worklist"); templates.add_argument("mechanics_review")
    templates.add_argument("editorial_review"); templates.add_argument("output")
    templates.add_argument("--adjudication")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "prepare":
            result = _prepare(args)
        elif args.command == "init-review":
            result = _review_template(args)
        elif args.command == "init-templates":
            result = _template_skeleton(args)
        else:
            result = _compile(args)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
