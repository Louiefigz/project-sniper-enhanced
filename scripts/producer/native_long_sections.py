"""Declare Long section assignments and expose ready review tasks in the existing production authority.

This command does not launch an AI provider or create a scheduler. The supervising
host claims and attaches the returned task ids through studio.production.api,
writes exact claim-owned results, and completes those same registered tasks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from studio.native_budget_exporter import BUDGET_ERRORS
from studio.native_long_budget import registered_parent
from studio.production.sections import enqueue_section_authors, materialize_section_reviews


def parser() -> argparse.ArgumentParser:
    """Expose only concrete existing authority transitions, never arbitrary commands."""
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='operation', required=True)
    authors = commands.add_parser('enqueue', help='Register authors from a frozen logical assignment plan')
    authors.add_argument('--plan', type=Path, required=True)
    reviews = commands.add_parser('reviews', help='Register reviews whose immutable inputs are ready')
    reviews.add_argument('--attempt', type=Path, required=True,
                         help='An existing registered native Long export directory')
    reviews.add_argument('--stage', choices=('early', 'encoded'), required=True)
    return result


def execute(args: argparse.Namespace) -> dict:
    """Use the same dependency/claim authority as the exporter and the supervising host."""
    if args.operation == 'enqueue':
        return enqueue_section_authors(args.plan.resolve(strict=True))
    request = registered_parent(args.attempt)
    return materialize_section_reviews(request, args.stage)


def main() -> None:
    """Report registered work or an explicit refusal without launching any agents or media."""
    args = parser().parse_args()
    try:
        result = execute(args)
    except (*BUDGET_ERRORS, OSError, ValueError) as error:
        print(json.dumps({'status': 'section-task-refused', 'reason': str(error),
                          'childLaunched': False}), flush=True)
        raise SystemExit(3) from error
    print(json.dumps({'status': 'section-tasks-registered', **result}), flush=True)


if __name__ == '__main__':
    main()
