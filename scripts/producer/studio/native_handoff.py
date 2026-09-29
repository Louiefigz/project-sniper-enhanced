#!/usr/bin/env python3
"""Hand-off of one delivered output: its exact MP4 and its matching editable Studio project.

  native_handoff.py open ATTEMPT --owner TAG --record NEW.json [--review-player URL] [--pending-findings F]
  native_handoff.py confirm --handoff REC --record NEW.json --review-page URL --studio-page URL
                    --browser NAME --attested-by WHO
  native_handoff.py views --owner TAG
  native_handoff.py release --handoff REC [--handoff REC ...] --record NEW.json
  native_handoff.py prune-holds --project DIR --record NEW.json

``open`` (``native_handoff_open``) mints a token, binds the delivered MP4, the project identity and
the approved content the batch authority holds, opens (or reuses and holds) that project's managed
Studio view, verifies and loads it, re-measures, and writes ``views-ready`` or ``handoff-incomplete``
(exit 2); ``visibleHandoffAt`` stays null. ``confirm`` (``native_handoff_confirm``) re-runs every
view check, requires the review player to have observed a browser load of this exact MP4 after the
views were verified, records the coordinator's attestation for the Studio page, and alone sets
``visibleHandoffAt``. ``views`` counts TAG's views for qualification. ``release`` drops the named
hand-offs' holds (a record or its intent file) and stops only views they launched that nobody else
holds. ``prune-holds`` drops holds whose evidence file no longer names their token. SIGTERM (a
tool timeout) is turned into an exception so an interrupted hand-off still writes its record.
Nothing here plays, listens to or approves the video.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import signal
import sys
from pathlib import Path
from typing import Callable, Iterator

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from cut_preview_io import write_new
from studio import managed_preview as managed
from studio import managed_preview_owned as owned
from studio import native_handoff_checks as checks
from studio import native_handoff_evidence as evidence
from studio.native_handoff_confirm import Confirmation, confirm, handoff_owner
from studio.native_handoff_open import HandoffRequest, hand_off  # noqa: F401 (the public entry points)

INCOMPLETE_EXIT = 2


class HandoffTerminated(BaseException):
    """SIGTERM reached a running hand-off command (for example, an agent tool timeout)."""


@contextlib.contextmanager
def sigterm_raises() -> Iterator[None]:
    """Deliver SIGTERM as an exception, so the command's own cleanup writes its record; restore afterwards."""
    def raise_terminated(signum: int, _frame: object) -> None:
        """Turn the signal into an exception at the current bytecode of the main thread."""
        raise HandoffTerminated(f'signal {signum} (SIGTERM) stopped the hand-off command')
    previous = signal.signal(signal.SIGTERM, raise_terminated)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def release(handoffs: list[Path], record: Path, wait_seconds: float) -> dict:
    """Release the named hand-offs' holds and stop only what they launched; keep a new cleanup record."""
    record = evidence.admit_record(record, ())
    claims = [handoff_owner(file) for file in handoffs]
    result = {'schemaVersion': 1, 'kind': 'native-handoff-release',
              'handoffs': [claim['binding'] for claim in claims],
              **owned.release_views([claim['owner'] for claim in claims], wait_seconds)}
    write_new(record, result)
    return result


def prune(project: Path, record: Path, wait_seconds: float) -> dict:
    """The lost-hold recovery: drop holds whose evidence no longer names them; keep a new record."""
    record = evidence.admit_record(record, ())
    result = {'schemaVersion': 1, 'kind': 'native-handoff-prune-holds', **owned.prune_holds(str(project), wait_seconds)}
    write_new(record, result)
    return result


def parser() -> argparse.ArgumentParser:
    """The sub-commands and their typed arguments."""
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest='action', required=True)
    show, check, views, stop, prunes = (sub.add_parser(name) for name in
                                        ('open', 'confirm', 'views', 'release', 'prune-holds'))
    show.add_argument('attempt', type=Path)
    show.add_argument('--owner', required=True)
    show.add_argument('--review-player', help='The URL review_player.py serve printed for this batch')
    show.add_argument('--pending-findings', type=Path, help='{"schemaVersion":1,"findings":[...]} still open')
    show.add_argument('--load-seconds', type=float, default=checks.DEFAULT_LOAD_SECONDS)
    check.add_argument('--handoff', type=Path, required=True)
    for name in ('review-page', 'studio-page', 'browser', 'attested-by'):
        check.add_argument(f'--{name}', required=True)
    views.add_argument('--owner', required=True)
    stop.add_argument('--handoff', type=Path, action='append', required=True)
    prunes.add_argument('--project', type=Path, required=True)
    for command in (show, check, views, stop, prunes):
        command.add_argument('--wait-seconds', type=float, default=managed.DEFAULT_WAIT_SECONDS)
    for command in (show, check, stop, prunes):
        command.add_argument('--record', type=Path, required=True)
    return root


def _status(result: dict, ok: str) -> tuple[dict, bool]:
    """A result and whether its status is the successful one."""
    return result, result['status'] == ok


ACTIONS: dict[str, Callable[[argparse.Namespace], tuple[dict, bool]]] = {
    'open': lambda args: _status(hand_off(HandoffRequest(
        args.attempt, args.record, args.owner, args.review_player, args.pending_findings, args.load_seconds,
        args.wait_seconds)), 'views-ready'),
    'confirm': lambda args: _status(confirm(Confirmation(
        args.handoff, args.record, (args.review_page, args.studio_page, args.browser, args.attested_by),
        args.wait_seconds)), 'visible-handoff'),
    'release': lambda args: _status(release(args.handoff, args.record, args.wait_seconds), 'released'),
    'prune-holds': lambda args: (prune(args.project, args.record, args.wait_seconds), True),
    'views': lambda args: (owned.owned_views(args.owner, args.wait_seconds), True)}


def main() -> int:
    """Run one sub-command; exit 2 when a hand-off, confirmation or release is incomplete."""
    args = parser().parse_args()
    with sigterm_raises():
        result, ok = ACTIONS[args.action](args)
    print(json.dumps(result))
    return 0 if ok else INCOMPLETE_EXIT


if __name__ == '__main__':
    sys.exit(main())
