"""Long logical section tasks through the existing enrolled-director production authority.

This adapter declares work and validates current results; it never creates agents,
a second scheduler, or approval from a technical render. A host must claim and
attach each real author/reviewer execution through the existing production API.
"""
from __future__ import annotations

from pathlib import Path

from studio.native_segments.long_plan import identity
from studio.native_segments.owners import segment_phase
from studio.production.api import enqueue_tasks
from studio.production.claims import Outcome
from studio.production.section_plan import (
    pin_file, read_plan, require_context, revalidate_context, task_spec, unique_pins,
)
from studio.production.section_results import claim_directory, read_completed_result, require, validate_binding
from studio.production.section_review_inputs import (
    early_inputs, encoded_ready, media_manifest, require_early_coverage, section_windows,
)
from studio.production.session import read_now, transact
from studio.production.section_scope import selected_assignments, require_full_scope, join_pairs


def enqueue_section_authors(planfile: Path) -> dict:
    """Enqueue up to three private section authors before project integration exists."""
    context = read_plan(planfile)
    root = Path(context['authority'])
    record, _elapsed = read_now(root, context['batchId'])
    require_context(record, context)
    specs = tuple(task_spec(context, row, row['authorBinding']) for row in context['assignments'])
    return {**enqueue_tasks(root, context['batchId'], specs), 'sectionProduction': context}


def integrated_author(request: dict, row: dict, record: dict) -> dict:
    """Recheck the registered author and exact copied files in the immutable current project."""
    value = read_completed_result(record, row['authorTaskId'], row['authorBinding'])
    task = record['production']['tasks'][row['authorTaskId']]
    directory = claim_directory(task)
    artifacts = {pin['path']: pin for pin in value['artifacts']}
    project = Path(request['project'])
    for name, relative in row['projectFiles'].items():
        source = artifacts.get(str(directory / name))
        require(source is not None, 'author result omits its assigned project artifact')
        target = pin_file(project / relative)
        require(target['sha256'] == source['sha256'] and target['bytes'] == source['bytes']
                and request['pins'].get(target['path']) == target['sha256'],
                'integrated project differs from its assigned author output')
    return task['receipts'][0]


def bind_section_tasks(request: dict, planfile: Path) -> dict:
    """Pin the frozen assignments and completed authors before immutable export publication."""
    context = enqueue_section_authors(planfile)['sectionProduction']
    require(request.get('adapter') == 'native-long' and request.get('revision', {}).get('mode') == 'initial-long',
            'section assignments require the initial Long section route')
    require(context['assignments'][-1]['frameRange'][1] == request['revision']['canvas']['totalFrames'],
            'logical assignments do not cover the complete Long')
    record, _elapsed = read_now(Path(context['authority']), context['batchId'])
    retained = [context['plan'], context['sharedPlan']]
    for row in selected_assignments(request, context):
        section_windows(request, row)
        receipt = integrated_author(request, row, record)
        retained.extend([*row['authorBinding']['inputs'], receipt])
    request['sectionProduction'] = context
    retained.extend(pin for row in context['assignments'] for pin in row['authorBinding']['inputs'])
    from studio.production.section_recovery import add_pin
    for pin in retained:
        add_pin(request, pin)
    return request


def review_binding(request: dict, row: dict, record: dict) -> tuple[dict, list[dict]]:
    """Bind one early reviewer to completed authors and every required current sample."""
    receipt = integrated_author(request, row, record)
    pins, expected = early_inputs(request, row)
    binding = {**row['authorBinding'], 'role': 'early-review', 'authorTaskId': row['authorTaskId'],
               'inputs': unique_pins([*row['authorBinding']['inputs'], receipt, *pins])}
    from studio.production.section_review_scope import bind_scope
    binding = bind_scope(request, row, binding)
    validate_binding(binding)
    return binding, expected


def review_task(context: dict, row: dict, binding: dict) -> object:
    """Give exact media inputs their own task identity, never another generation's approval."""
    role = binding['role']
    field = 'earlyTaskId' if role == 'early-review' else 'encodedTaskId'
    selected = {**row, field: row[field] + '-' + identity(binding)[:12]}
    return task_spec(context, selected, binding)


def early_result(request: dict, row: dict, record: dict) -> tuple[dict, object]:
    """Require current independent early judgments of the integrated authored project."""
    from studio.production.section_review_reuse import retained_early
    retained = retained_early(request, row, record)
    if retained is not None:
        return retained
    binding, expected = review_binding(request, row, record)
    spec = review_task(request['sectionProduction'], row, binding)
    document = read_completed_result(record, spec.task_id, binding)
    require_early_coverage(document, expected)
    return record['production']['tasks'][spec.task_id]['receipts'][0], spec


def encoded_spec(request: dict, row: dict, record: dict) -> object:
    """Freeze an independent encoded-review task after the full logical group is sealed."""
    if request.get('sectionChunks'):
        from studio.production.section_chunk_dispatch import chunk_spec
        return chunk_spec(request, row, record)
    early_receipt, early = early_result(request, row, record)
    author = integrated_author(request, row, record)
    manifest = media_manifest(request, row)
    binding = {**row['authorBinding'], 'role': 'encoded-review', 'authorTaskId': row['authorTaskId'],
               'mediaManifest': manifest,
               'inputs': unique_pins([*row['authorBinding']['inputs'], author, early_receipt, manifest])}
    from studio.production.section_review_scope import bind_scope
    binding = bind_scope(request, row, binding)
    validate_binding(binding)
    from studio.production.section_media import read_media_manifest
    read_media_manifest(binding)
    return review_task(request['sectionProduction'], {**row, 'earlyTaskId': early.task_id}, binding)


def materialize_section_reviews(request: dict, stage: str = 'early') -> dict:
    """Enqueue ready logical reviews; missing encoded windows defer only their own group."""
    require(stage in ('early', 'encoded'), 'invalid section review stage')
    context = revalidate_context(request)

    def operation(record: dict, elapsed: float) -> Outcome:
        """Create immutable tasks under the same lock used for their dependencies."""
        from studio.production.section_review_materialize import materialize_locked
        return materialize_locked(record, request, context, stage)

    return transact(Path(context['authority']), context['batchId'], operation)


def review_ready(request: dict, row: dict) -> bool:
    """Interior-only reviewers run early; a join reviewer waits only for its actual edge media."""
    if not encoded_ready(request, row):
        return False
    pairs = join_pairs(request['sectionProduction'], row)
    if request.get('sectionScope') and pairs:
        return False
    return all(encoded_ready(request, side) for pair in pairs for side in pair)


def _review_spec(request: dict, row: dict, state: tuple[dict, str]) -> object:
    """Select current early inputs or a complete sealed encoded manifest."""
    record, stage = state
    if stage == 'encoded':
        return encoded_spec(request, row, record)
    binding, _expected = review_binding(request, row, record)
    return review_task(request['sectionProduction'], row, binding)


def require_early_review(request: dict, phase: str) -> dict:
    """Refuse heavy work until its assigned author and independent early reviewer are current."""
    context = revalidate_context(request)
    index = segment_phase(phase)
    windows = request['revision']['renderWindows']
    require(index is not None and index < len(windows), 'invalid early-review section phase')
    window = windows[index]
    rows = [row for row in selected_assignments(request, context) if row['frameRange'][0] <= window['startFrame']
            and window['endFrame'] <= row['frameRange'][1]]
    require(len(rows) == 1, 'technical section has no unique logical assignment')
    record, _elapsed = read_now(Path(context['authority']), context['batchId'])
    receipt, _spec = early_result(request, rows[0], record)
    return receipt


def require_all_early_reviews(request: dict) -> list[dict]:
    """Require current completed independent judgments for every logical assignment."""
    context = revalidate_context(request)
    record, _elapsed = read_now(Path(context['authority']), context['batchId'])
    return [early_result(request, row, record)[0] for row in selected_assignments(request, context)]


def assembly_task_snapshot(request: dict, record: dict | None = None) -> dict:
    """Rehash every current required logical result before assembly and delivery publication."""
    require_full_scope(request)
    context = revalidate_context(request)
    if record is None:
        from studio.native_budget_store import locked_batch
        with locked_batch(Path(context['authority']), context['batchId']) as session:
            return assembly_task_snapshot(request, session.read())
    require(record['batchId'] == context['batchId'], 'assembly received another production authority')
    results = assignment_snapshots(request, context, record)
    from studio.production.section_join_barrier import join_snapshot
    joins = join_snapshot(request, record, results)
    return {'plan': context['plan'], 'assignments': results, 'joins': joins,
            'identity': identity({'assignments': results, 'joins': joins})}


def assignment_snapshots(request: dict, context: dict, record: dict) -> list[dict]:
    """Defer only absent/active encoded judgment; verify every other current section before reporting pending."""
    from studio.native_segments.reviews import SectionReviewPending
    result, pending = [], []
    for row in context['assignments']:
        try:
            result.append(_assignment_snapshot(request, row, record))
        except SectionReviewPending:
            pending.append(row['sectionId'])
    if pending:
        raise SectionReviewPending(f'Current sealed sections await encoded review: {", ".join(pending)}')
    return result


def require_encoded_task(record: dict, spec: object) -> None:
    """A known revoked/stale review is a hard refusal, never a cheap pending continuation."""
    from studio.native_segments.reviews import SectionReviewPending
    from studio.production.dependencies import stale_inputs
    task = record['production']['tasks'].get(spec.task_id)
    if task is None:
        raise SectionReviewPending('Current sealed section has no registered encoded review yet')
    require(task.get('sectionBinding') == spec.section_binding and not task.get('supersededBy')
            and not task.get('approvalStale') and not task.get('revoked')
            and not task.get('cancelRequested') and not (task.get('unresolved') and task.get('state') != 'completed')
            and stale_inputs(record).get(spec.task_id) is None, 'Encoded review is stale or fenced')
    if task['state'] in ('blocked', 'ready', 'claimed', 'running'):
        raise SectionReviewPending('Current sealed section encoded review is still pending')


def _assignment_snapshot(request: dict, row: dict, record: dict) -> dict:
    """Read one complete logical dependency chain and exact current encoded evidence."""
    author = integrated_author(request, row, record)
    from studio.production.section_review_reuse import retained_snapshot
    retained = retained_snapshot(request, row, record)
    if retained is not None:
        return {**retained, 'author': author}
    early, _early_spec = early_result(request, row, record)
    spec = encoded_spec(request, row, record)
    require_encoded_task(record, spec)
    read_completed_result(record, spec.task_id, spec.section_binding)
    task = record['production']['tasks'][spec.task_id]
    from studio.production.section_chunk_dispatch import chunk_snapshot
    media = chunk_snapshot(task, request) if spec.section_binding.get('chunkPlan') else {
        'mediaManifest': spec.section_binding['mediaManifest']}
    return {'sectionId': row['sectionId'], 'generation': row['generation'], 'inputIdentity': row['inputIdentity'],
            'author': author, 'earlyReview': early,
            'encodedReview': task['receipts'][0], **media}
