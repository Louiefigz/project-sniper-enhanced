"""Export a declared native long project with reusable stages and early seam checks."""
from __future__ import annotations

import argparse
import json
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import MASTERING_PROFILE_IDENTITIES, NATIVE_SHORT_MASTERING_PROFILE
from cut_preview_io import bound_json, real_directory, write_new
from studio.native_long_options import section_options, section_boundaries, bind_task_options
from studio.native_long_scope import scope_for_args
from studio.native_long_contract import disk_projection, read_long_plan, sample_frame_count
from studio.native_preflight_inputs import inventory
from studio.native_run import utc
from studio.native_run_config import local_environment
from studio.native_runtime import REPO, digest, install_runtime
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_long_autoresume import recover_automatically, resume_request
from studio.native_long_prebuild import require_long_prebuild, review_implementation_files
from studio.native_export import export_adapter
from studio.native_export_history import register_attempt, attempt_reservation
from studio.native_visual_plan import visual_plan_reuse_identity
from studio.native_visual_usage_registration import usage_implementation_files


def implementation_pins(project: Path, runtime: Path, tools: dict) -> dict:
    """Bind the existing shared owners, audio/QC modules and native runtime closure."""
    files, _directories = inventory(project)
    producer = REPO / 'scripts/producer'
    files += [file for file in producer.rglob('*.py') if 'tests' not in file.parts]
    files += list((producer / 'studio').glob('*.mjs'))
    files += list((producer / 'studio/native_segments').glob('*.mjs'))
    files += list((producer / 'studio/runtime').glob('*.mjs'))
    files.append(producer / 'studio/runtime/patches.json')
    files += [runtime / 'dist' / name for name in ('cli.js', 'native-capture-library.mjs',
              'hyperframe.runtime.iife.js', 'hyperframe.manifest.json', 'frame-source-transport.mjs',
              'native-render-sdk.mjs', 'native-export-guard.mjs')]
    files += [Path(value).resolve(strict=True) for value in tools.values()]
    files += [Path(sys.executable).resolve(strict=True), producer / 'studio/native_localhost_only.sb']
    files += review_implementation_files()
    files += usage_implementation_files()
    from graphics.visual_source_project import source_implementation_files
    files += source_implementation_files()
    from graphics.graphics_render import GSAP_CORE
    files.append(Path(GSAP_CORE).resolve(strict=True))
    return {str(file): digest(file) for file in set(files) if file.is_file()}


def prepare(args: argparse.Namespace, production_budget: dict | None = None) -> tuple[dict, dict]:
    """Reject incompatible options and unsafe paths before output or media work."""
    from studio.native_long_budget import validate_entry
    project, output = validate_entry(args)
    if production_budget is None:
        from studio.native_budget_exporter import refuse_if_budgeted
        refuse_if_budgeted(project)
    section_scope = scope_for_args(args, project)
    plan = read_long_plan(project, section_scope=section_scope)
    if export_adapter(project) != 'native-long':
        raise ValueError('Expected the native long export contract')
    tools, environment = local_environment()
    reviewed = require_long_prebuild(project, tools, environment, section_scope)
    runtime = install_runtime()
    cache = args.cache.resolve() if args.cache else runtime.parent / 'long-frame-cache'
    cache.mkdir(parents=True, exist_ok=True)
    real_directory(cache)
    request = {'schemaVersion': 1, 'adapter': 'native-long', 'project': str(project), 'output': str(output),
        'runtime': str(runtime), 'cache': str(cache), 'tools': tools, 'captureMode': 'sdk-streaming',
        'sourceCacheMode': 'native-long', 'audioProfile': args.audio_profile, 'audioDonor': None,
        'pictureDonor': None, 'preparedMaster': None, 'pins': implementation_pins(project, runtime, tools),
        'budget': plan['budget'], 'sampleCount': sample_frame_count(plan, section_scope), 'diskProjection': disk_projection(plan)}
    if section_scope:
        request['sectionScope'] = section_scope
    if section_options(args):
        request['sectionImplementationPins'] = {
            file: sha for file, sha in request['pins'].items() if not Path(file).is_relative_to(project)}
    reuse = visual_plan_reuse_identity(plan, args.audio_profile)
    if reuse:
        request['visualPlanReuse'] = reuse
    for file, sha in reviewed['pins'].items():
        if file in request['pins'] and request['pins'][file] != sha:
            raise ValueError('Reviewed long project changed before export pinning')
    request['pins'].update(reviewed['pins'])
    request['prebuildReview'] = {key: value for key, value in reviewed.items() if key != 'pins'}
    if reviewed.get('referenceMap'):
        request['referenceMap'] = reviewed['referenceMap']
    prepare_sections(args, request, plan)
    request = select_and_publish(args, request, production_budget)
    return request, environment


def prepare_sections(args: argparse.Namespace, request: dict, plan: dict) -> None:
    """Bind technical windows and the complete non-project implementation partition."""
    if not section_options(args):
        return
    from studio.native_segments.plan import initial_long_plan
    identity = hashlib.sha256(json.dumps(request['pins'], sort_keys=True).encode()).hexdigest()
    request['revision'] = initial_long_plan(plan['canvas'], identity, section_boundaries(args, plan['canvas']))
    parent = getattr(args, 'repair_from', None)
    if parent:
        from studio.native_segments.compatibility import prepare_long_repair
        request.update(prepare_long_repair(request, parent.resolve(strict=True)))
    from studio.native_long_scope import selected_windows
    frames = sum(row['endFrame'] - row['startFrame'] for row in selected_windows(request))
    request['diskProjection'] = disk_projection(plan, frames)


def select_and_publish(args: argparse.Namespace, request: dict, production_budget: dict | None = None) -> dict:
    """Choose compatible stages and register a new attempt under the project reservation."""
    sectioned = request.get('revision', {}).get('mode') == 'initial-long'
    projection = request['diskProjection']
    if args.resume_from and not sectioned:
        attempt = args.resume_from.resolve(strict=True)
        request = resume_request(request, attempt)
    else:
        add_audio_reuse(args, request)
        if not sectioned and not args.prepared_master and not args.audio_donor and not getattr(args, "preview_only", False) and getattr(args, "preview_reviews", None):
            request = recover_automatically(request)
    preview_args = args
    if args.resume_from and sectioned:
        from studio.native_long_recovery import prepare_section_recovery
        request = prepare_section_recovery(request, args.resume_from.resolve(strict=True))
        preview_args = inherited_section_previews(args, request)
    from studio.native_long_scope import bind_family_preview_windows
    bind_family_preview_windows(request, production_budget, getattr(args, 'section_plan', None))
    from studio.native_motion_previews import bind_preview_options
    if request.get('sectionPreviewWindows') is not None:
        from studio.production.section_plan import read_plan
        request['sectionProduction'] = request.get('sectionProduction') or read_plan(args.section_plan.resolve(strict=True))
        request['productionBudget'] = production_budget
    request = bind_preview_options({**request, 'diskProjection': projection}, preview_args)
    from studio.native_budget_exporter import bind_long_budget
    request = bind_long_budget(request, production_budget)
    request = bind_task_options(args, request)
    if getattr(args, 'section_from', None):
        from studio.native_long_integration import prepare_section_integrations
        request = prepare_section_integrations(request, [path.resolve(strict=True) for path in args.section_from])
    from studio.native_long_chunks import bind_chunk_request
    request = bind_chunk_request(request)
    apply_family_mode(request)
    # Budget/task authority is consulted before history; never acquire a batch lock inside history.
    with attempt_reservation(request):
        return publish_request(args, request)


def apply_family_mode(request: dict) -> None:
    """A family route controls preview/final mode; initial final work still requires current early reviews."""
    budget = request.get('productionBudget', {})
    if not budget.get('familyId'):
        return
    request['previewOnly'] = budget['route'] == 'preview'
    if not request['previewOnly']:
        from studio.production.sections import require_all_early_reviews
        require_all_early_reviews(request)


def publish_request(args: argparse.Namespace, request: dict) -> dict:
    """Publish an immutable launch while the caller holds the project history reservation."""
    if request.get('revision', {}).get('mode') == 'initial-long':
        from studio.native_export_history import section_attempt_sequence
        request['sectionAttemptSequence'] = section_attempt_sequence(request)
        from studio.native_segments.owners import bind_window_recovery
        attempts = [args.resume_from.resolve(strict=True)] if args.resume_from else None
        request = bind_window_recovery(request, attempts)
        if getattr(args, 'section_reviews', None):
            from studio.native_segments.reviews import review_pins
            file = args.section_reviews.resolve(strict=True)
            request['sectionReviews'] = str(file)
            request['pins'].update(review_pins(file))
    output = Path(request['output'])
    from studio.native_source_store import hold_source_store_owner
    request['sourceStoreOwner'] = hold_source_store_owner(Path(request['cache']))
    output.mkdir(mode=0o700)
    from studio.native_segments.frame_capture import bind_frame_reuse
    bind_frame_reuse(request)
    from studio.native_segments.frame_metadata import require_retained_metadata_capacity
    require_retained_metadata_capacity(request)
    write_new(output / 'export-request.json', request)
    register_attempt(request)
    return request


def inherited_section_previews(args: argparse.Namespace, request: dict) -> argparse.Namespace:
    """Bind the preserved original preview policy through its normal validator; reject overrides."""
    from studio.native_stage_evidence import require
    values = dict(vars(args))
    for option, field in (('preview_reviews', 'previewReviews'), ('preview_from', 'previewFrom')):
        supplied = getattr(args, option, None)
        retained = request.get(field)
        require(supplied is None or str(supplied.resolve(strict=True)) == retained,
                'section resume cannot change its admitted preview evidence')
        values[option] = Path(retained) if retained else None
    require(not getattr(args, 'preview_only', False) or request.get('previewOnly') is True,
            'section resume cannot change its admitted preview mode')
    values.update(preview_only=request.get('previewOnly', False), resume_from=None)
    return argparse.Namespace(**values)


def add_audio_reuse(args: argparse.Namespace, request: dict) -> None:
    """Keep explicit audio-only reuse available even after a failed picture attempt."""
    for key, value in (('preparedMaster', args.prepared_master), ('audioDonor', args.audio_donor)):
        if value is None:
            continue
        receipt = value.resolve(strict=True)
        request[key] = str(receipt)
        files = [receipt, receipt.parent / 'program-master.wav']
        if key == 'audioDonor':
            files.append(receipt.parent / 'candidate.mp4')
        request['pins'].update({str(file): digest(file) for file in files})


def main() -> None:
    """One invocation, truthful durable status, preserved failed attempts and no providers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--cache', type=Path)
    recovery = parser.add_mutually_exclusive_group()
    recovery.add_argument('--resume-from', type=Path)
    recovery.add_argument('--repair-from', type=Path,
                          help='Repair a preserved Long snapshot, reusing only compatible verified picture sections')
    parser.add_argument('--sections', action='store_true',
                        help='Render and save initial Long sections; independent section QC is required before joining')
    parser.add_argument('--chunks', action='store_true',
                        help='Require authored Long chunk/transition admission under the existing creative assignments')
    parser.add_argument('--section-reviews', type=Path,
                        help='Pinned independent QC of the saved initial Long sections')
    parser.add_argument('--section-plan', type=Path,
                        help='Frozen shared creative plan and registered logical author/reviewer assignments')
    parser.add_argument('--section-from', type=Path, action='append',
                        help='Integrate an immutable current sealed section; repeat once per logical assignment')
    parser.add_argument('--section-id', help='Admit one immutable ready section; full integration remains separately gated')
    parser.add_argument('--review-only', action='store_true',
                        help='Resume completely sealed sections for registered QC and assembly on the original budget')
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument('--prepared-master', type=Path, help='Reuse a checked float master after a picture-only change/failure')
    reuse.add_argument('--audio-donor', type=Path, help='Reuse checked AAC; all final audio and picture checks still run')
    parser.add_argument('--audio-profile', choices=MASTERING_PROFILE_IDENTITIES,
                        default=NATIVE_SHORT_MASTERING_PROFILE.identity)
    from studio.native_motion_previews import preview_options
    preview_options(parser)
    args = parser.parse_args()
    began = time.monotonic(), utc()
    from studio.native_long_budget import reserve_for_entry
    from studio.native_budget_exporter import close_unpublished_launch
    allowed, production_budget = reserve_for_entry(args)
    if not allowed:
        raise SystemExit(3)
    try:
        request, environment = prepare(args, production_budget)
    except BaseException as error:
        close_unpublished_launch(production_budget, error)
        raise
    print(json.dumps({'status': 'prepared-awaiting-resource-admission', 'budget': request['budget']}), flush=True)
    success = NativeShortPipeline(request, environment).execute(invocation=began)
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()
