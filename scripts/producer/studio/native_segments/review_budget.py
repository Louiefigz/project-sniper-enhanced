"""Bounded derived review AAC membership in the existing section-owner history.

Packages are one deterministic member per frozen family scope. A completed
member must reuse its sealed bytes, including across export invocation tokens.
They never spend or evade a final-delivery AAC candidate: no final output can
consume this review-only receipt. Failed members retain the shared retry rules.
"""
from __future__ import annotations

from studio.native_budget_registry import BudgetRefused
from studio.native_segments.long_plan import identity
from studio.native_segments.review_scopes import owner_phase, package_phase, phase_scope


def package_identity(request: dict, phase: str) -> str:
    """Bind the actual current scope, master and sealed media before owner admission."""
    from studio.native_segments.review_media import source_state
    scope = phase_scope(request, phase)
    return identity(source_state(request, scope)[0])


def previous_owner(rows: list[dict], owner: dict) -> dict | None:
    """Enforce one package per family member without adding a new accounting store."""
    package = owner_phase(owner['phase'])
    if package is None:
        return next((row for row in reversed(rows) if row['phase'] == owner['phase']
                     and row['inputIdentity'] == owner['inputIdentity']), None)
    matching = [row for row in rows if row['attemptId'] == owner['attemptId']
                and owner_phase(row['phase']) == package]
    if any(row['status'] == 'running' for row in matching):
        raise BudgetRefused('This review package family member already has a live owner')
    if any(row['status'] == 'succeeded' for row in matching):
        raise BudgetRefused('Completed review package must reuse its sealed bytes; no second AAC encode')
    previous = matching[-1] if matching else None
    if previous and previous['inputIdentity'] != owner['inputIdentity']:
        raise BudgetRefused('Frozen review package member changed within its original family')
    return previous


def require_package_family(request: dict, phase: str) -> None:
    """Packages only execute beneath an existing final-family invocation."""
    if not package_phase(phase):
        return
    binding = request.get('productionBudget', {})
    if not binding.get('familyInvocation') or binding.get('route') != 'final':
        raise BudgetRefused('Review package requires its original final section family')
    if not binding.get('familyId') or binding.get('familyId') != binding.get('attemptId'):
        raise BudgetRefused('Review package family differs from its counted attempt')
    if request.get('adapter') != 'native-long' or not request.get('sectionChunks'):
        raise BudgetRefused('Review package requires current admitted Long chunks')
    phase_scope(request, phase)
