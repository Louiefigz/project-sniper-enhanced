"""Serialize section task authority and export history at every publication boundary.

Lock order is always batch then project history. The caller keeps both held until
the exact checked artifact is atomically published; a prior unlocked task read
cannot protect against concurrent supersession. Unbudgeted legacy requests retain
their history-only boundary and gain no production task approval.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from studio.native_budget_binding import advance_clock
from studio.native_budget_policy import clip_record, phase_refusal
from studio.native_budget_store import locked_batch
from studio.native_export_history import attempt_reservation
from studio.native_stage_evidence import require


def publication_binding(request: dict) -> dict | None:
    """Require the section task graph to share the exact export's original authority."""
    production = request.get('sectionProduction') or request.get('productionBudget')
    if production is None:
        return None
    budget = request.get('productionBudget')
    require(isinstance(production, dict) and isinstance(budget, dict),
            'assigned section publication requires its production budget')
    for key in ('authority', 'batchId', 'clipId'):
        require(production.get(key) == budget.get(key) and production.get(key) is not None,
                'section task and export authority differ')
    return production


def require_publishable(record: dict, binding: dict) -> None:
    """Check the live output and its original clock without minting new authorization."""
    require(record['batchId'] == binding['batchId'], 'section publication batch differs')
    elapsed = advance_clock(record)
    refusal = phase_refusal(record, clip_record(record, binding['clipId']), elapsed)
    require(refusal is None, refusal or 'section production authority refused publication')


def recheck_publication(request: dict, record: dict | None) -> None:
    """Recheck the clock after potentially expensive media hashing, immediately before promotion."""
    binding = publication_binding(request)
    if binding is not None:
        require(record is not None, 'publication lost its locked task authority')
        require_publishable(record, binding)
        if request.get('productionBudget', {}).get('familyId'):
            from studio.native_budget_family_state import verify_family_request
            verify_family_request(record, request, 'verify')


@contextmanager
def section_publication(request: dict, outcome: dict | None = None) -> Iterator[dict | None]:
    """Hold current production tasks and history stable through the caller's promotion."""
    binding = publication_binding(request)
    if binding is None:
        with attempt_reservation(request):
            yield None
        return
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        require_publishable(record, binding)
        if request.get('productionBudget', {}).get('continuationOf'):
            from studio.native_budget_continuation import refuse_delivered
            refuse_delivered(clip_record(record, binding['clipId']), request['productionBudget']['continuationOf'])
        with attempt_reservation(request):
            yield record
            commit_publication(session, record, request, outcome)


def commit_publication(session: object, record: dict, request: dict, outcome: dict | None) -> None:
    """Settle checked delivery before releasing the same locks that protected its file."""
    if not outcome or outcome.get('status') != 'native-long-checked-for-review':
        return
    budget = request.get('productionBudget', {})
    if budget.get('familyId'):
        from studio.native_budget_family import apply_family_outcome as apply
    elif budget.get('continuationOf'):
        from studio.native_budget_continuation import apply_review_outcome as apply
    else:
        return
    event = apply(record, request, outcome, advance_clock(record))
    if event:
        session.commit(record, event)


def publish_delivery(request: dict, result: dict) -> None:
    """Publish success only while both currentness authorities remain locked."""
    from cut_preview_io import bound_json, write_new
    from studio.native_segments.reviews import assembly_snapshot
    root = Path(request['output'])
    if request.get('revision', {}).get('mode') != 'initial-long' or result['status'] != 'native-long-checked-for-review':
        write_new(root / 'delivery.json', result)
        return
    try:
        with section_publication(request, result) as production_record:
            assembled = bound_json(root / 'revision-picture.json')['sectionSnapshot']
            require(assembly_snapshot(request, production_record) == assembled,
                    'section QC changed before delivery')
            recheck_publication(request, production_record)
            write_new(root / 'delivery.json', result)
    except (OSError, RuntimeError, ValueError) as error:
        result.update(status='failed', failureCategory='section-publication-stale', error=str(error))
        if (root / 'delivery.json').exists():
            result.update(failureCategory='budget-authority-commit',
                          checkedDeliveryStatus='native-long-checked-for-review')
            return  # Preserve the immutable checked artifact; authority reconciliation is still required.
        write_new(root / 'delivery.json', result)
