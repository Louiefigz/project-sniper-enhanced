"""The operator's hand-over commands: approvals after start and staged (refused or interrupted) starts.

- ``add-clip --clip F --reason TEXT --approval FILE`` adds a Short with its approved title and script
  bound; it starts its own 40 counted minutes when it is added (``api.add_clip``). The answer names its
  own delivery deadline, whether it was a replay, its recorded ``duplicationCheck`` and
  ``pendingDecisions``, every decision line still owed as ``status`` shows it (X159, X167). Without
  an approval it is refused (exit 3) before anything is written.
- ``change-approval --clip A --approval FILE --reason TEXT`` records the operator's typed change
  (``api.record_script_change``). The reason is passed through, and ``reasonRecorded`` is true,
  once that API takes a ``reason`` parameter (unit A12 round 4); until then it is echoed only and
  ``reasonRecorded`` is false.
- ``staged-starts`` lists the staged starts (``api.staged_starts(root)``) and ``discard-start --name
  STAGING --reason TEXT`` discards one by its staging name (``api.discard_staged(root, name,
  reason)``), the operator's decision. Both are unit A12's API: each is refused (exit 3, nothing
  read or discarded) while its function is not in this engine.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable

from studio import native_budget_store as store
from studio.native_budget_binding import BudgetRefused
from studio.native_budget_store import require_clip_id
from studio.production import api, inputs

NO_APPROVALS = ('A Short\'s clock starts when its approved title and script are handed over, and none was: '
                '{what} is refused ({how})')


def a12_api(name: str) -> Callable:
    """Unit A12's ``production.api`` function ``name``; refused (never approximated) while it is absent."""
    function = getattr(api, name, None)
    if not callable(function):
        raise BudgetRefused(f'This command needs production.api.{name} (unit A12), which is not in this engine; '
                            'nothing was read or changed')
    return function


def cmd_add_clip(args: argparse.Namespace) -> dict:
    """A clip added after start is explicit, visible work that starts its own 40 counted minutes when it is added."""
    if args.approval is None:
        raise BudgetRefused(NO_APPROVALS.format(what='adding a clip without one', how='add it with --approval FILE'))
    approval = inputs.load_approval(args.approval, require_clip_id(args.clip))
    added = api.add_clip(store.default_root(), args.batch, args.clip, api.AddedClip(args.reason, approval))
    recorded = {key: added[key] for key in ('duplicationCheck',) if key in added}   # absent: a legacy adding event
    return {'status': 'clip-added', 'clipId': args.clip, 'elapsed': round(added['elapsed'], 1),
            'replayed': added['replayed'], 'deadlineElapsed': added['output']['deadlineElapsed'], **recorded,
            'pendingDecisions': added['pendingDecisions'],
            'approval': {key: added['approval'][key] for key in ('title', 'identity', 'script', 'elapsed')}}


def cmd_change_approval(args: argparse.Namespace) -> dict:
    """Record the operator's typed change of a clip's approved title or script (the clock is unchanged)."""
    approval = inputs.load_approval(args.approval, require_clip_id(args.clip))
    from studio.production.approvals import ApprovalChange
    changed = api.record_script_change(store.default_root(), args.batch, args.clip,
                                       ApprovalChange(approval, args.reason))
    return {'status': 'approval-changed', 'clipId': args.clip, 'reason': args.reason, 'reasonRecorded': True,
            'changed': changed['changed'], 'material': changed['material'], 'elapsed': round(changed['elapsed'], 1),
            'approval': {key: changed['approval'][key] for key in ('title', 'identity', 'previous')}}


def cmd_staged_starts(_args: argparse.Namespace) -> dict:
    """The staged (refused or interrupted) starts recorded under the authority root (read only)."""
    return {'status': 'staged-starts', 'staged': a12_api('staged_starts')(store.default_root())}


def cmd_discard_start(args: argparse.Namespace) -> dict:
    """Discard one staged start by its staging name, the operator's decision, with its reason."""
    return a12_api('discard_staged')(store.default_root(), args.name, args.reason)
