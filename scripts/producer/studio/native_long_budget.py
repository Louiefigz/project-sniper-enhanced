"""Public Long budget reservation and explicit repair/review continuity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cut_preview_io import bound_json, real_directory
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE
from studio.native_budget_binding import bind_project
from studio.native_budget_continuation import reserve_section_review
from studio.native_budget_exporter import BUDGET_ERRORS, reserve_long_for_args
from studio.native_budget_registry import BudgetRefused, owner_binding
from studio.native_budget_store import default_root, read_any_batch
from studio.native_export_history import attempt_reservation, known_attempts, require_current_section_attempt


def registered_parent(path: Path) -> dict:
    """Read an immutable registered parent, never a caller-invented budget field."""
    parent = path.resolve(strict=True)
    real_directory(parent)
    request = bound_json(parent / 'export-request.json')
    if request.get('output') != str(parent) or request.get('adapter') != 'native-long':
        raise BudgetRefused('Budget continuity requires an original native Long attempt')
    with attempt_reservation(request):
        if parent not in known_attempts(request):
            raise BudgetRefused('Section budget parent is not registered with its original request digest')
        if request.get('revision', {}).get('mode') == 'initial-long':
            require_current_section_attempt(request)
    return request


def require_original_authority(prior: dict) -> dict | None:
    """A missing or moved original store never makes a budgeted job unbudgeted."""
    binding = prior.get('productionBudget')
    if binding is None:
        return None
    root = default_root()
    if binding.get('authority') != str(root):
        raise BudgetRefused('Original section budget authority is not this account authority')
    read_any_batch(root, binding['batchId'])
    current = owner_binding(root, Path(prior['project']))
    if not current or (current['batchId'], current['clipId']) != (binding['batchId'], binding['clipId']):
        raise BudgetRefused('Original Long budget binding is missing or was released; no fresh clock is allowed')
    return binding


def reserve_for_entry(args: argparse.Namespace) -> tuple[bool, dict | None]:
    """Reserve before prebuild work; repairs and review-only resumes retain original authorization."""
    try:
        project, output = validate_entry(args)
        repair, resume = getattr(args, 'repair_from', None), getattr(args, 'resume_from', None)
        if repair and resume:
            raise BudgetRefused('Choose either a section repair or a resume, not both')
        prior = registered_parent(repair or resume) if repair or resume else None
        if repair and prior.get('revision', {}).get('mode') != 'initial-long':
            raise BudgetRefused('A section repair requires an initial-Long section parent')
        require_preview_resume_reviews(args, prior)
        binding = require_original_authority(prior) if prior else None
        if getattr(args, 'review_only', False) and not binding:
            raise BudgetRefused('Review-only continuation requires original production-budget authority')
        if repair and binding:
            bind_repair(prior, binding, project)
        if getattr(args, 'section_id', None) or getattr(args, 'section_from', None) or (
                prior and prior.get('productionBudget', {}).get('familyId')):
            return True, reserve_section_family(args, project, output, prior)
        if resume and binding and (getattr(args, 'section_reviews', None) or getattr(args, 'review_only', False)):
            return True, reserve_section_review(prior, project, output)
        return reserve_long_for_args(args)
    except BUDGET_ERRORS as error:
        print(json.dumps({'status': 'refused-by-production-budget', 'reason': str(error),
                          'childLaunched': False}), flush=True)
        return False, None


def validate_entry(args: argparse.Namespace) -> tuple[Path, Path]:
    """Reject structural option/path mistakes before any durable launch charge or media work."""
    project, output = args.project.resolve(strict=True), args.output.absolute()
    if getattr(args, 'review_only', False) and not getattr(args, 'resume_from', None):
        raise ValueError('Review-only continuation requires an explicit resume parent')
    if getattr(args, 'section_id', None) and not getattr(args, 'section_plan', None):
        raise ValueError('--section-id requires its frozen --section-plan')
    if getattr(args, 'section_id', None) and getattr(args, 'review_only', False):
        raise ValueError('A scoped section cannot request final review-only assembly')
    if getattr(args, 'section_from', None) and (getattr(args, 'section_id', None)
            or not getattr(args, 'section_plan', None) or getattr(args, 'resume_from', None)):
        raise ValueError('--section-from requires full current --section-plan and cannot be a scoped resume')
    real_directory(project)
    real_directory(output.parent)
    from studio.native_long_chunks import validate_chunk_options
    validate_chunk_options(args, project)
    if output.exists() or output.is_symlink() or output.is_relative_to(project) or project.is_relative_to(output):
        raise ValueError('Long export requires a new output directory outside the authored project')
    if getattr(args, 'resume_from', None) and (getattr(args, 'prepared_master', None)
            or getattr(args, 'audio_donor', None) or getattr(args, 'cache', None)
            or getattr(args, 'audio_profile', NATIVE_SHORT_MASTERING_PROFILE.identity)
            != NATIVE_SHORT_MASTERING_PROFILE.identity):
        raise ValueError('Resume preserves the original audio policy, evidence and cache; omit overrides')
    return project, output


def bind_repair(prior: dict, binding: dict, project: Path) -> None:
    """Bind one immutable repair snapshot to the existing logical Long and its original clock."""
    if project == Path(prior['project']):
        raise BudgetRefused('A section repair requires a separate immutable project snapshot')
    bind_project(Path(binding['authority']), binding['batchId'], binding['clipId'], project)


def require_preview_resume_reviews(args: argparse.Namespace, prior: dict | None) -> None:
    """Unfinished assigned early reviews must not consume a counted final-export reservation."""
    if not prior or not getattr(args, 'resume_from', None) or getattr(args, 'preview_only', False):
        return
    if prior.get('sectionProduction') and prior.get('previewOnly'):
        from studio.production.sections import require_all_early_reviews
        require_all_early_reviews(prior)


def reserve_section_family(args: argparse.Namespace, project: Path, output: Path, prior: dict | None) -> dict:
    """Use one original route family for all frozen section members and later integrated joins."""
    from studio.native_budget_family import reserve_family
    from studio.native_long_scope import scope_for_args
    from studio.production.section_plan import read_plan
    scope = scope_for_args(args, project)
    plan_file = getattr(args, 'section_plan', None)
    if plan_file is None and prior:
        plan_file = Path(prior['sectionProduction']['plan']['path'])
    if plan_file is None:
        raise BudgetRefused('Scoped production requires its frozen section assignment plan')
    context = read_plan(plan_file.resolve(strict=True))
    preview = bool(getattr(args, 'preview_only', False) or (not prior and not getattr(args, 'section_from', None)
                   and not getattr(args, 'preview_reviews', None)))
    options = {'sectionId': scope['sectionId'] if scope else None, 'previewOnly': preview, 'snapshotScope': scope}
    if prior:
        options['parentAttempt'] = Path(prior['output'])
    return reserve_family(context, project, output, options)
