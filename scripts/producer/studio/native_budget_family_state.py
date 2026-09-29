"""Logical family liveness and exact child admission in the existing budget transaction."""
from __future__ import annotations

from pathlib import Path
import re

from cut_preview_io import bound_json
from native_render_processes import ProcessIdentity, identity_matches
from studio.native_budget_launch import _process_table, find_attempt
from studio.native_budget_policy import clip_record, phase_refusal
from studio.native_budget_registry import BudgetRefused
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity


def require(condition: bool, message: str) -> None:
    """Use the existing public budget refusal rather than a fallback admission."""
    if not condition:
        raise BudgetRefused(message)


def family_of(clip: dict, family_id: str) -> dict:
    """Resolve one durable logical launch, never inventing one from request fields."""
    rows = [row for row in clip.get('sectionFamilies', []) if row['id'] == family_id]
    require(len(rows) == 1, 'Unknown section family')
    return rows[0]


def invocation_of(family: dict, token: str) -> dict:
    """An exact reserved child token owns one immutable project/output pair."""
    rows = [row for row in family['invocations'] if row['id'] == token]
    require(len(rows) == 1, 'Unknown section family invocation')
    return rows[0]


def terminal_failure(row: dict, elapsed: float, category: str) -> None:
    """Keep a bounded charged outcome when a child is proven gone or its grant ends."""
    row.update(status='abandoned', completedElapsed=elapsed,
               failure={'category': category, 'phase': None, 'errorType': None, 'signature': category})


def reconcile_family(record: dict, clip: dict, family: dict, elapsed: float | tuple) -> None:
    """Observe actual child processes; awaiting a future author is not process liveness."""
    elapsed, table = elapsed if isinstance(elapsed, tuple) else (elapsed, None)
    attempt = next(row for row in clip['attempts'] if row['id'] == family['id'])
    if attempt['status'] != 'running':
        return
    live = [row for row in family['invocations'] if row['status'] == 'running']
    table = (_process_table() if live else {}) if table is None else table
    for row in live:
        if not identity_matches(table, ProcessIdentity(**row['supervisor'])):
            terminal_failure(row, elapsed, 'abandoned')
    expired = elapsed >= attempt['admittedElapsed'] + attempt['grantedSeconds']
    stopped = record['status'] != 'active' or clip['state'] == 'handed-off'
    if expired or stopped:
        family['state'] = 'failed'
        terminal_failure(attempt, elapsed, 'budget-exhausted' if expired else 'cancelled')


def active_family_attempts(record: dict, elapsed: float, table: dict | None = None) -> set[str]:
    """Reconcile logical launches before the legacy process-only launch reconciler runs."""
    pairs = [(clip, family) for clip in record['clips'].values()
             for family in clip.get('sectionFamilies', [])]
    for clip, family in pairs:
        reconcile_family(record, clip, family, (elapsed, table))
    return {family['id'] for _clip, family in pairs
            if family['state'] in ('awaiting-sections', 'finalizing')}


def verify_family_request(record: dict, request: dict, phase: str) -> tuple[dict, dict]:
    """Bind a worker's exact frozen request before Popen, under the existing batch lock."""
    binding = request['productionBudget']
    require(record['batchId'] == binding['batchId'], 'Section family belongs to another batch')
    clip = clip_record(record, binding['clipId'])
    family = family_of(clip, binding['familyId'])
    require(family['id'] == binding['attemptId'], 'Section family attempt differs')
    attempt = find_attempt(record, binding['clipId'], family['id'])
    require(attempt['route'] == binding['route'] and attempt['status'] == 'running',
            'Section family launch route or state differs')
    row = invocation_of(family, binding['familyInvocation'])
    elapsed = record['clock']['elapsed']
    require(elapsed < attempt['admittedElapsed'] + attempt['grantedSeconds'], 'Section family grant expired')
    refusal = phase_refusal(record, clip, elapsed)
    require(not refusal, refusal or 'Section family is no longer active')
    require(family['state'] in ('awaiting-sections', 'finalizing') and row['status'] == 'running',
            'Section family invocation has settled or was fenced')
    require((row['project'], row['output']) == (request['project'], request['output']),
            'Section family invocation project/output differs')
    require(request.get('sectionProduction', {}).get('plan') == family['plan'], 'Section family plan changed')
    from studio.production.section_plan import require_context, revalidate_context
    require_context(record, revalidate_context(request))
    file = Path(row['output']) / 'export-request.json'
    require(bound_json(file) == request, 'Section family worker request differs from its published bytes')
    sha = digest(file)
    require(row['requestSha256'] in (None, sha), 'Section family request changed after its first owner')
    require(request['pins'].get(str(Path(row['project']) / 'LONG-PROJECT.json')) == row['planSha256'],
            'Section family project plan changed after reservation')
    scope = request.get('sectionScope')
    require((identity(scope) if scope is not None else None) == row['scopeSha256'], 'Section scope changed')
    require_phase(family, row, request, phase.removeprefix(f"family-{row['id']}-"))
    row['requestSha256'] = sha
    return family, row


def require_phase(family: dict, row: dict, request: dict, phase: str) -> None:
    """A scoped child cannot join; a final integration cannot silently generate missing pictures."""
    from studio.native_segments.owners import segment_phase
    index = segment_phase(phase)
    if index is None:
        require_support_phase(family, row, request, phase)
        return
    require(request['productionBudget']['route'] == 'final', 'Preview family cannot render final section pictures')
    windows = request.get('revision', {}).get('renderWindows', [])
    require(index < len(windows), 'Section owner is outside frozen window inventory')
    if row['sectionId'] is None:
        require(phase in request['revision'].get('windowDonors', {}), 'Final integration cannot render missing section media')
        return
    assignment = next(item for item in family['assignments'] if item['sectionId'] == row['sectionId'])
    window = windows[index]
    require(assignment['frameRange'][0] <= window['startFrame'] < window['endFrame'] <= assignment['frameRange'][1],
            'Section family child escaped its owned frame range')


def require_support_phase(family: dict, row: dict, request: dict, phase: str) -> None:
    """Only preview children can launch the exact frozen moving-preview inventory."""
    route = request['productionBudget']['route']
    from studio.native_segments.review_scopes import package_phase, phase_scope
    if package_phase(phase):
        require(route == 'final', 'review package cannot consume a preview family')
        scope = phase_scope(request, phase)
        require(row['sectionId'] is None or scope['sectionIds'] == [row['sectionId']],
                'review package escaped its owned creative assignment')
        return
    allowed = ('capture', 'preview')
    if route == 'final' and row['sectionId'] is None:
        allowed += ('picture', 'render', 'verify')
    if phase in allowed:
        return
    match = re.fullmatch(r'preview-(?:picture|package)-(0|[1-9][0-9]{0,2})', phase)
    require(route == 'preview' and match is not None, 'Section family does not admit this worker phase')
    inventory = next((item for item in family['previewInventory'] if item['sectionId'] == row['sectionId']), None)
    require(inventory is not None and int(match[1]) < len(inventory['windows']),
            'Preview owner is outside frozen window inventory')
    from studio.native_review_regions import region_packet
    from studio.native_long_scope import request_preview_windows
    windows = request_preview_windows(request, region_packet(request))
    require([[item['startFrame'], item['endFrame']] for item in windows] == inventory['windows'],
            'Preview request differs from the frozen family windows')
