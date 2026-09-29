"""Public logical Long family admission using the existing locked budget authority."""
from __future__ import annotations

from pathlib import Path
from contextlib import nullcontext

from cut_preview_io import real_directory
from studio.native_budget_binding import REPO, advance_clock, bind_project
from studio.native_budget_engine import engine_identity
from studio.native_budget_family_state import require, verify_family_request
from studio.native_budget_registry import owner_binding, project_identity
from studio.native_budget_store import locked_batch
from studio.production.outputs import long_launch_binding
from studio.production.section_plan import read_plan
from studio.production.section_scope import selected_assignments


def reserve_family(context: dict, project: Path, output: Path, options: dict) -> dict:
    """Reserve an exact child of one counted preview/final launch without renewing its clock."""
    settings = family_settings(context, project, output, options)
    root = Path(context['authority'])
    with locked_batch(root, context['batchId']) as session:
        record = session.read()
        from studio.native_segments.review_service_binding import prepare_admission
        prepare_admission(session, record, settings)
        from studio.native_budget_family_preparation import prepare_invocation
        prepare_invocation(record, settings)
        elapsed = advance_clock(record)
        from studio.native_budget_family_reservation import reserve_invocation
        grant = reserve_invocation(record, settings, elapsed)
        session.commit(record, {'event': 'launch-admitted', 'kind': 'section-family-invocation',
            'clipId': context['clipId'], 'attemptId': grant['attemptId'],
            'invocationId': grant['familyInvocation'], 'output': str(output), 'elapsed': elapsed})
    return grant


def family_settings(context: dict, project: Path, output: Path, options: dict) -> dict:
    """Validate immutable scope and same-lineage ownership before taking the batch admission lock."""
    require(read_plan(Path(context['plan']['path'])) == context, 'Section family plan changed')
    require(type(options) is dict and set(options) - {'parentAttempt'} == {'sectionId', 'previewOnly', 'snapshotScope'}
            and type(options['previewOnly']) is bool, 'Invalid family reservation options')
    require(project.is_absolute() and project.resolve(strict=True) == project, 'Family project must be canonical')
    require(output.is_absolute() and output.resolve() == output and not output.exists(), 'Family output must be new')
    real_directory(project)
    real_directory(output.parent)
    require(not output.is_relative_to(project) and not project.is_relative_to(output), 'Family output overlaps project')
    scope = options['snapshotScope']
    require((scope is None) == (options['sectionId'] is None), 'Family scope and selected section differ')
    selected = selected_assignments({'project': str(project), 'sectionScope': scope}, context)
    require(scope is None or selected[0]['sectionId'] == options['sectionId'], 'Family selected assignment differs')
    root = Path(context['authority'])
    from studio.production.section_plan import require_context
    engine = engine_identity(REPO)
    with locked_batch(root, context['batchId']) as session:
        record = session.read()
        require_context(record, context)
        require(record['engine'] is not None and record['engine']['identity'] == engine['identity'],
                'Section family requires this batch frozen engine')
    bind_project(root, context['batchId'], context['clipId'], project)
    found = owner_binding(root, project)
    require(found is not None and all(found[key] == context[key] for key in ('batchId', 'clipId')),
            'Family project belongs to another production authority')
    from studio.native_long_contract import family_preview_inventory
    from studio.native_segments.review_forecast import project_work
    from studio.native_segments.review_service_binding import planned_binding
    options = {**options, **({'parentAttempt': str(Path(options['parentAttempt']).resolve(strict=True))}
                            if options.get('parentAttempt') is not None else {})}
    return {'context': context, 'project': str(project), 'output': str(output), 'options': options,
            'route': 'preview' if options['previewOnly'] else 'final', 'engine': engine,
            'projectIdentity': project_identity(project),
            'longOutput': long_launch_binding(root, found, project_identity(project)),
            'previewInventory': family_preview_inventory(project, context), 'reviewWork': project_work(project, context),
            'plannedService': planned_binding(project, context)}


def record_family_outcome(request: dict, result: dict) -> None:
    """Settle a child; a final family closes only with its checked complete-program delivery."""
    binding = request['productionBudget']
    with locked_batch(Path(binding['authority']), binding['batchId']) as session:
        record = session.read()
        from studio.native_export_history import attempt_reservation
        history = attempt_reservation(request) if result.get('status') == 'native-long-checked-for-review' else nullcontext()
        with history:
            settle_locked(session, record, request, result)


def apply_family_outcome(record: dict, request: dict, result: dict, elapsed: float) -> dict | None:
    """Apply under held batch authority; checked delivery also requires the caller's held history lock."""
    from studio.native_budget_family_outcome import apply_family_outcome as apply
    return apply(record, request, result, elapsed)


def settle_locked(session: object, record: dict, request: dict, result: dict) -> None:
    """Commit only the bounded event while the wrapper retains its required publication locks."""
    event = apply_family_outcome(record, request, result, advance_clock(record))
    if event is not None:
        session.commit(record, event)
