"""TEST harness: run ``context.py`` with the calling test's private budget-authority and work-lease roots.

A child process cannot inherit a test's in-process patches of ``native_budget_store.default_root`` and
``native_work_lease.state_root``, so the TypeScript gates' engine given check (``context.py --given-check``)
would otherwise read the user's real authority. ``_isolated_review.ts`` runs the real review commands with
their given check pointed here. Test-only: nothing in the product runs or reads this file.

    python3 -B _isolated_context.py <budget-root> <lease-root> <context.py arguments...>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

import native_work_lease  # noqa: E402
from studio import native_budget_store  # noqa: E402


def main() -> int:
    """Patch both roots to the given TEST folders, then run the real context.py entry."""
    budgets, lease, *arguments = sys.argv[1:]
    native_budget_store.default_root = lambda: Path(budgets)
    native_work_lease.state_root = lambda: Path(lease)
    import context
    return context.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
