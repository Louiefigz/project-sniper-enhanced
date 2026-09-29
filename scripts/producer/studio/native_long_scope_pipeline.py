"""Execute one explicitly admitted immutable section without joining a partial project."""
from __future__ import annotations

import json
import time

from cut_preview_io import write_new
from studio.native_long_scope import require_scope_request, selected_windows
from studio.native_run import utc
from studio.native_runtime import digest
from studio.native_stage_evidence import require

SAVED = 'native-long-section-sealed-awaiting-integration'
PREVIEWED = 'native-motion-previews-complete'


def execute_scope(pipeline: object, invocation: tuple[float, str] | None = None) -> bool:
    """Run normal capture, preview and section owners; every final-project path remains closed."""
    started, began = invocation or (time.monotonic(), utc())
    request = pipeline.request
    result = {'status': 'failed', 'startedAt': began, 'sectionScope': request['sectionScope'],
              'output': str(pipeline.root / 'section-result.json'), 'humanApproved': False,
              'fullProjectAdmission': False, 'finalAssembly': False}
    try:
        require_scope_request(request)
        require(request.get('productionBudget', {}).get('familyInvocation'),
                'scoped section requires its original durable logical export family')
        pipeline.capture()
        result['previews'] = pipeline.preview()
        if request.get('previewOnly'):
            result.update(status=PREVIEWED, editorialReview='pending')
        else:
            result['sections'] = render_scope(pipeline)
            result.update(status=SAVED, editorialReview='pending-or-registered')
    except (Exception, KeyboardInterrupt) as error:
        result.update(status='failed', errorType=type(error).__name__, error=str(error),
                      failureCategory='cancelled' if isinstance(error, KeyboardInterrupt)
                      else getattr(error, 'category', 'renderer-failure'),
                      failedPhase=getattr(error, 'phase', None))
    return complete_scope(pipeline, result, started)


def render_scope(pipeline: object) -> list[dict]:
    """Retain every verified technical seal and expose selected review readiness immediately."""
    from studio.native_motion_previews import require_motion_previews
    from studio.native_segments.supervision import run_sections
    from studio.native_segments.owners import current_window
    require_motion_previews(pipeline.request)
    run_sections(pipeline)
    rows = []
    for window in selected_windows(pipeline.request):
        phase = f"segment-picture-{window['index']}"
        receipt = current_window(pipeline.request, phase)
        rows.append({'phase': phase, 'inputIdentity': window['inputIdentity'],
                     'generation': window['generation'], 'receipt': receipt})
    return rows


def complete_scope(pipeline: object, result: dict, started: float) -> bool:
    """Settle only this invocation; the original family retains waiting sections and its clock."""
    from studio.native_budget_family import record_family_outcome
    result.update(completedAt=utc(), elapsedSeconds=time.monotonic() - started, stages=pipeline.stages)
    file = pipeline.root / 'section-result.json'
    write_new(file, result)
    reported = dict(result)
    try:
        record_family_outcome(pipeline.request, {**result, 'receiptSha256': digest(file)})
    except (ValueError, RuntimeError) as error:
        reported.update(status='failed', failureCategory='budget-authority', error=str(error))
    print(json.dumps(reported), flush=True)
    return reported['status'] in {SAVED, PREVIEWED}
