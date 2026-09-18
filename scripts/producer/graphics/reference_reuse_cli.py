"""Prepare and check reusable shot decisions for an explicit reference-match request.

Uses the recorded shared catalog, without downloads, installation or rendering.
Preparing candidates leaves visual inspection and selection pending. Checking a
completed map verifies planning evidence, never style or execution qualification.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, file_hash, write_new
from graphics.catalog_discovery import load_catalog
from graphics.reference_reuse_map import prepare_map, read_checked_map
from graphics.reference_study_bindings import export_study_bindings, read_study_bindings


def parser() -> argparse.ArgumentParser:
    """Expose separate preparation and checking with exclusive output files."""
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Search and freeze candidates for requested shots')
    prepare.add_argument('request', type=Path)
    prepare.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('check', help='Recheck evidence and completed reuse/custom decisions')
    check.add_argument('map', type=Path)
    check.add_argument('--output', type=Path)
    save = commands.add_parser('save-study', help='Save completed matches for reuse in other projects')
    save.add_argument('map', type=Path)
    save.add_argument('--output', type=Path, required=True)
    study = commands.add_parser('check-study', help='Verify saved matches without repeating discovery')
    study.add_argument('map', type=Path)
    return cli


def execute(args: argparse.Namespace) -> tuple[dict, int]:
    """Use the shared catalog exactly once; write only an explicit new output."""
    catalog = load_catalog()
    if args.command == 'save-study':
        record = export_study_bindings(args.map.absolute(), catalog)
        write_new(args.output.absolute(), record)
        return {'status': 'study-bindings-saved', 'path': str(args.output.absolute()),
                'matchCount': len(record['matches']), 'renderApproved': False}, 0
    if args.command == 'check-study':
        checked = read_study_bindings(args.map.absolute(), catalog)
        return {'status': 'study-bindings-current', 'path': checked['path'],
                'sha256': checked['sha256'], 'inputPins': checked['inputPins'],
                'blockedMatches': checked['blockedMatches'],
                'matchCount': len(checked['bindings']['matches']), 'renderApproved': False}, 0
    if args.command == 'prepare':
        file = args.request.absolute()
        hashed = file_hash(file)
        request = bound_json(file, hashed)
        if 'request' in request:
            raise ValueError('The request file cannot contain its own evidence binding')
        record = prepare_map({**request, 'request': {'path': str(file), 'sha256': hashed}}, catalog)
        write_new(args.output.absolute(), record)
        return {'status': 'reference-reuse-draft', 'map': str(args.output.absolute()),
                'inspectionAndSelectionRequired': True, 'renderApproved': False}, 0
    snapshot = read_checked_map(args.map.absolute(), catalog)
    report = {**snapshot['report'], 'map': {'path': snapshot['path'], 'sha256': snapshot['sha256']}}
    if args.output:
        write_new(args.output.absolute(), report)
    return report, 0 if report['ready'] is True else 1


def main() -> None:
    """Report failed or blocked checks without publishing a successful receipt."""
    args = parser().parse_args()
    try:
        report, code = execute(args)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        report, code = {'status': 'failed', 'error': str(error), 'renderApproved': False}, 2
    print(json.dumps(report, indent=2))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
