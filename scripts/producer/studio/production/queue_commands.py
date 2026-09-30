"""Production-queue commands of ``native_batch.py`` that Phase 1 adds (X36): registered here, never in ``cli.py``.

``cli.py`` makes one call, ``queue_commands.register(sub)``, before it adds ``--batch`` to every command, and
merges ``HANDLERS`` into its own table (MASTER-PLAN §5: an area adds commands only through its ``register``).

- ``settle-resource --task <id> --statement "<operator's words>"`` (M-043) is the one settlement command. While
  the batch is active or draining, it records the operator's statement on a task that ended holding an
  unresolved resource, or on revoked work, in the ``task-resource-settled`` event (``basis: operator-statement``)
  and in the task's reason. It releases nothing: ``unresolved``, the slot, the charge and every reservation stay
  until termination evidence resolves them (G9, X25). The rule is ``callbacks.settle_resource``; an empty
  statement is refused there by name ("Settling records the operator's statement", exit 2).

- ``director-activity --task <director> --epoch N --token T (--clip ID ... | --all) --state working|idle`` (M-045)
  records the enrolled director's own declaration for its Shorts (``director_activity``). A Short earns no
  render-queue credit while its director counts as working, which is the default until it declares ``idle``.

- ``capacity-stall --clip ID --decision cancel --reason TEXT`` (M-050) records the operator's cancel of a
  ``capacity-stalled`` Short (``queue_stall.decide``): its work is frozen and it is closed out for good. It is the
  only stall decision (X19); a Short that is not stalled is refused by name.
"""
from __future__ import annotations

import argparse

from studio import native_budget_store as store
from studio.production import api
from studio.production.claims import ClaimRef
from studio.production.director_activity import DirectorActivity
from studio.production.queue_stall import DECISIONS, StallDecision


def cmd_settle_resource(args: argparse.Namespace) -> dict:
    """Record the operator's statement on unresolved or revoked work; nothing is released (G9, X25)."""
    return api.settle_resource(store.default_root(), args.batch, args.task, args.statement)


def cmd_director_activity(args: argparse.Namespace) -> dict:
    """The enrolled director declares itself working or idle for the named Shorts, or for every open one."""
    activity = DirectorActivity(None if args.all else tuple(args.clip), args.state == 'working')
    return api.declare_director_activity(store.default_root(), args.batch,
                                         ClaimRef(args.task, args.epoch, args.token), activity)


def cmd_capacity_stall(args: argparse.Namespace) -> dict:
    """The operator's recorded cancel of a capacity-stalled Short (the only decision, X19)."""
    return api.decide_capacity_stall(store.default_root(), args.batch, args.clip,
                                     StallDecision(args.decision, args.reason))


HANDLERS = {'settle-resource': cmd_settle_resource, 'director-activity': cmd_director_activity,
            'capacity-stall': cmd_capacity_stall}


def register(sub: argparse._SubParsersAction) -> None:
    """Add this module's commands to ``native_batch.py``'s parser; ``cli.parser`` adds ``--batch`` to each."""
    settle = sub.add_parser('settle-resource', help="Record the operator's statement on unresolved or revoked "
                                                    'work; it releases nothing')
    settle.add_argument('--task', required=True)
    settle.add_argument('--statement', required=True,
                        help="The operator's own words, recorded verbatim; a statement is never evidence")
    activity = sub.add_parser('director-activity', help="The enrolled director's own declaration: working (the "
                                                        'default; its Shorts earn no queue credit) or idle')
    activity.add_argument('--task', required=True, help="The enrolled director's task id")
    activity.add_argument('--epoch', type=int, required=True)
    activity.add_argument('--token', required=True)
    clips = activity.add_mutually_exclusive_group(required=True)
    clips.add_argument('--clip', action='append', help='A Short this declaration covers; repeat')
    clips.add_argument('--all', action='store_true', help='Every Short on a v2 clock that is not handed off')
    activity.add_argument('--state', choices=('working', 'idle'), required=True)
    stall = sub.add_parser('capacity-stall', help='Cancel a capacity-stalled Short: its work is frozen and it '
                                                  'is closed out (the batch can then close)')
    stall.add_argument('--clip', required=True)
    stall.add_argument('--decision', choices=DECISIONS, required=True)
    stall.add_argument('--reason', required=True, help="The operator's reason, recorded with the decision")
