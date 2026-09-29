"""Historical recorded judgments, never revived claims or current task approval.

Only an explicit author repair edge permits inspection of its superseded
reviewer's already-recorded progress. Original claim namespaces and receipts
remain unchanged; current author and media authority are checked separately.
"""
from __future__ import annotations

from studio.production.section_results import SCOPE, read_document, require, task_of


def repair_authors(record: dict, request: dict, row: dict) -> tuple[dict, dict, dict]:
    """Prove one exact registered author replacement and both immutable authored outputs."""
    from studio.native_segments.compatibility import validate_repair
    from studio.production.section_assignment_repair import replacement_problem
    from studio.production.section_plan import require_context, revalidate_context
    from studio.production.sections import integrated_author
    original = validate_repair(request)
    context = revalidate_context(request)
    require_context(record, context)
    require(row in context['assignments'], 'chunk carry assignment is not current')
    old_context = original['sectionProduction']
    require(all(context[key] == old_context[key] for key in ('authority', 'batchId', 'clipId', 'sharedPlan')),
            'chunk carry changed production or shared creative authority')
    require(context.get('parentPlan') == old_context['plan'], 'chunk carry skips its exact parent assignment plan')
    previous = next(item for item in old_context['assignments'] if item['sectionId'] == row['sectionId'])
    author, prior = task_of(record, row['authorTaskId']), task_of(record, previous['authorTaskId'])
    require(author['kind'] == 'repairCycle' and author['replaces'] == prior['id']
            and prior['supersededBy'] == author['id'], 'chunk carry needs an explicit current author replacement')
    require(replacement_problem(author, record['production']['tasks']) is None, 'chunk carry author lineage differs')
    require(prior['sectionBinding'] == previous['authorBinding'], 'chunk carry prior author differs from parent')
    integrated_author(request, row, record)
    read_document(prior, prior['receipts'][0])
    return original, author, prior


def historical_reviewers(record: dict, authors: tuple[dict, dict]) -> list[dict]:
    """Find original encoded reviewers without treating superseded tasks as current prerequisites."""
    current, prior = authors
    rows = [task for task in record['production']['tasks'].values()
            if task.get('sectionBinding', {}).get('authorTaskId') == prior['id']
            and task['sectionBinding']['role'] == 'encoded-review' and task['sectionBinding'].get('chunkPlan')
            and task.get('sectionProgress')]
    require(len(rows) <= 1, 'chunk carry has ambiguous original reviewers')
    for task in rows:
        valid_carry_withdrawal(task)
    return [historical_reviewer(record, task['id'], (current, prior)) for task in rows
            if 'sectionCarryWithdrawal' not in task]


def historical_reviewer(record: dict, task_id: str, authors: tuple[dict, dict]) -> dict:
    """Preserve original approval provenance and independence from both author generations."""
    from studio.production.dependencies import stale_inputs
    task = task_of(record, task_id)
    current, prior = authors
    binding = task['sectionBinding']
    valid_carry_withdrawal(task)
    require('sectionCarryWithdrawal' not in task, 'chunk carry judgment was explicitly withdrawn')
    require(task['state'] in ('completed', 'superseded') and not task.get('supersededBy')
            and not task.get('cancelRequested') and not task.get('failure')
            and not task.get('approvalStale') and stale_inputs(record).get(task_id) is None,
            'chunk carry reviewer was cancelled, failed or materially stale')
    require(task['state'] == 'superseded' and task['revoked']
            and task['terminalElapsed'] == prior['terminalElapsed'] == current['enqueuedElapsed']
            and task['reason'] in {f"input {prior['id']} was superseded (was {state})"
                                   for state in ('completed', 'running')},
            'chunk carry reviewer was not superseded by this author replacement')
    require(prior['id'] in task['prerequisites'] and prior['receipts'][0] in binding['inputs']
            and task['clipId'] == prior['clipId'] == current['clipId']
            and all(binding[key] == prior['sectionBinding'][key] for key in SCOPE),
            'chunk carry reviewer differs from its original author')
    reviewer = task['handle']['host'], task['handle']['thread']
    require(all(reviewer != (author['handle']['host'], author['handle']['thread']) for author in authors),
            'chunk carry reviewer is an original or current author')
    return task


def valid_carry_withdrawal(task: dict) -> bool:
    """Validate an optional bounded explicit revocation marker without reading artifacts."""
    from studio.production.host_contract import clip_text, finite_seconds
    if 'sectionCarryWithdrawal' not in task:
        return True
    value, binding = task['sectionCarryWithdrawal'], task.get('sectionBinding', {})
    require(binding.get('role') == 'encoded-review' and binding.get('chunkPlan') is not None
            and task.get('revoked') is True, 'only revoked chunk reviewers carry withdrawal markers')
    require(type(value) is dict and set(value) == {'elapsed', 'reason'} and finite_seconds(value['elapsed'])
            and type(value['reason']) is str and bool(value['reason'].strip())
            and clip_text(value['reason']) == value['reason'], 'invalid chunk carry withdrawal')
    return True


def withdraw_chunk_carry(task: dict, elapsed: float, reason: str) -> bool:
    """Record the first explicit withdrawal; dependency supersession never calls this helper."""
    from studio.production.host_contract import clip_text
    binding = task.get('sectionBinding', {})
    if binding.get('role') != 'encoded-review' or binding.get('chunkPlan') is None:
        return False
    if 'sectionCarryWithdrawal' in task:
        valid_carry_withdrawal(task)
        return False
    task['sectionCarryWithdrawal'] = {'elapsed': elapsed, 'reason': clip_text(reason)}
    valid_carry_withdrawal(task)
    return True
