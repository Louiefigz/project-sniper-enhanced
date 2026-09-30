"""Production-queue commands of ``native_batch.py`` that Phase 1 adds (X36): registered here, never in ``cli.py``.

``cli.py`` makes one call, ``queue_commands.register(sub)``, before it adds ``--batch`` to every command, and
merges ``HANDLERS`` into its own table (MASTER-PLAN §5: an area adds commands only through its ``register``).

- ``settle-resource --task <id> --statement "<operator's words>"`` (M-043) is the one settlement command. While
  the batch is active or draining, it records the operator's statement on a task that ended holding an
  unresolved resource, or on revoked work, in the ``task-resource-settled`` event (``basis: operator-statement``)
  and in the task's reason. It releases nothing: ``unresolved``, the slot, the charge and every reservation stay
  until termination evidence resolves them (G9, X25). The rule is ``callbacks.settle_resource``; an empty
  statement is refused there by name ("Settling records the operator's statement", exit 2).

M-045 adds ``director-activity`` here.
"""
from __future__ import annotations

import argparse

from studio import native_budget_store as store
from studio.production import api


def cmd_settle_resource(args: argparse.Namespace) -> dict:
    """Record the operator's statement on unresolved or revoked work; nothing is released (G9, X25)."""
    return api.settle_resource(store.default_root(), args.batch, args.task, args.statement)


HANDLERS = {'settle-resource': cmd_settle_resource}


def register(sub: argparse._SubParsersAction) -> None:
    """Add this module's commands to ``native_batch.py``'s parser; ``cli.parser`` adds ``--batch`` to each."""
    settle = sub.add_parser('settle-resource', help="Record the operator's statement on unresolved or revoked "
                                                    'work; it releases nothing')
    settle.add_argument('--task', required=True)
    settle.add_argument('--statement', required=True,
                        help="The operator's own words, recorded verbatim; a statement is never evidence")
