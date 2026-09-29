"""Export an assembled native Short locally, with source, audio and picture QC.

``main`` never exports in the process that parsed the command: it runs the export as the supervised
child of the outer watchdog (``production.process_watch.supervise_export``), which bounds the whole
lifetime (runtime setup, locks, hashing, publication and pipeline) by the production deadline. The
child proves it is that child with an exact claim (``production.process.supervised_claim``), never a
flag, and alone reserves and is charged; a claimed media task's child first acknowledges its claim.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import MASTERING_PROFILE_IDENTITIES, NATIVE_SHORT_MASTERING_PROFILE
from cut_preview_io import real_directory, write_new
from studio.native_run_config import local_environment
from studio.native_runtime import BUILD_WAIT_SECONDS, REPO, digest, install_runtime
from studio.native_short_delivery import clock
from studio.native_short_pipeline import NativeShortPipeline
from studio.native_source_store import hold_source_store_owner
from studio.native_short_resume import prepare_reverification, render_stage_for_attempt
from studio.native_reference_reuse import bind_reference_map, reference_snapshot
from studio.native_run import utc
from studio.native_export_history import attempt_reservation, register_attempt
from studio.native_short_autoresume import recover_automatically
from studio.native_short_draft_export import draft_options, draft_selection, project_admission, validate_draft_options
from studio.native_visual_plan import visual_plan_reuse_identity
from studio.native_short_export_pins import (  # noqa: F401  (re-exported for callers and patches)
    assert_admitted_pins, input_pins, prebuild_review_pins, request_input_paths, style_application_pins,
    visual_plan_pins, require_readable_request,
)
from studio.native_budget_clock import stage_allowance
from studio.native_budget_owner import short_disk_projection
from studio.native_budget_exporter import (
    bind_current_budget, close_unpublished_launch, refuse_if_budgeted, reserve_for_args, reserve_for_task,
)
from studio.production.process import (
    ExportLaunch, SupervisionRefused, interrupt_on_termination, publish_grant, supervised_claim,
)


def prepare(args: argparse.Namespace, budget: dict | None = None) -> tuple[dict, dict]:
    """Require the same shared project reader used by local assembly before heavy work."""
    cache_mode = source_cache_mode(args)
    project, output = args.project.resolve(strict=True), args.output.absolute()
    validate_options(args, project, output)
    if budget is None:
        refuse_if_budgeted(project)
    bounded = {'productionBudget': budget} if budget else {}
    reference_map = getattr(args, 'reference_map', None)
    reference_map = reference_map.absolute() if reference_map else None
    reference_snapshot(project, reference_map, 'short')
    tools, environment = local_environment()
    admission = project_admission(args, project, (tools, environment), stage_allowance(bounded, 60))  # else {}
    if not admission:
        subprocess.run([tools['node'], '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'),
                        'check-export', str(project)], cwd=REPO, env=environment, check=True,
                       timeout=stage_allowance(bounded, 60))
    plan = json.loads((project / 'SHORT-PROJECT.json').read_text())
    canvas = plan['canvas']
    rate = clock(canvas).fps.fraction
    if not 1 <= rate <= 60 or not 0 < canvas['totalFrames'] / rate <= 180:
        raise ValueError('Native Short export supports explicit 1–60 fps timelines up to 180 seconds')
    runtime = install_runtime(build_wait=stage_allowance(bounded, BUILD_WAIT_SECONDS))  # cold setup, bounded
    cache = args.cache.resolve() if args.cache else runtime.parent / 'frame-cache'
    cache.mkdir(parents=True, exist_ok=True)
    pins = input_pins(project, runtime, tools)
    reuse = visual_plan_reuse_identity(plan, args.audio_profile)
    request = {'schemaVersion': 1, 'project': str(project), 'output': str(output),
               'runtime': str(runtime), 'cache': str(cache), 'tools': tools,
               'captureMode': 'sdk-streaming' if getattr(args, 'sdk_streaming', False) else 'cached-native-batches',
               'sourceCacheMode': cache_mode, 'diskProjection': short_disk_projection(canvas),
               'audioProfile': args.audio_profile,
               'pictureDonor': None, 'pins': pins, 'audioDonor': None, 'preparedMaster': None, **admission}
    if reuse:
        request['visualPlanReuse'] = reuse
    if budget:
        request['productionBudget'] = budget
    with attempt_reservation(request):
        request = select_and_publish(args, request, reference_map)
    return request, environment


def select_and_publish(args: argparse.Namespace, request: dict, reference_map: Path | None) -> dict:
    """Reserve discovery and immutable publication before another invocation can start."""
    budget = request.get('productionBudget')
    resume = getattr(args, 'resume_from', None)
    if (drafted := draft_selection(args, request, reference_map)) is not None:  # review draft / promotion
        request = drafted
    elif resume:
        attempt = resume.absolute()
        request = prepare_reverification(request, render_stage_for_attempt(attempt), attempt)
    elif getattr(args, 'verify_from', None):
        request = prepare_reverification(request, args.verify_from.absolute())
    else:
        add_donors(args, request)
        request = bind_reference_map(request, reference_map)
        if not args.audio_donor and not args.picture_donor and not getattr(args, "preview_only", False) and getattr(args, "preview_reviews", None):
            request = recover_automatically(request)
    if not request.get('promoteDraft'):  # a promotion copies the draft's encoded audio; it binds no stage
        from studio.native_audio_import import bind_audio_stage  # sealed whole-program audio by identity
        request = bind_audio_stage(request, getattr(args, 'audio_stage', None))
    from studio.native_motion_previews import bind_preview_options
    if not request.get('reviewDraft'):  # A review draft renders no previews, binds no reviews, captures nothing.
        request = bind_preview_options(request, args)
        from studio.native_capture_reuse import bind_capture_reuse
        request = bind_capture_reuse(request)
    from studio.native_short_revision_reuse import bind_picture_revision
    request = bind_picture_revision(request)
    # Invocation-scoped (never copied from a donor): reader leases stay valid while this process lives.
    request['sourceStoreOwner'] = hold_source_store_owner(Path(request['cache']))
    request = bind_current_budget(request, budget)
    require_readable_request(request)
    output = Path(request['output'])
    output.mkdir(mode=0o700)
    write_new(output / 'export-request.json', request)
    register_attempt(request)
    return request


def validate_options(args: argparse.Namespace, project: Path, output: Path) -> None:
    """Reject incompatible recovery options and unsafe destinations before expensive work."""
    real_directory(output.parent)
    if output.exists() or output.is_symlink() or output.is_relative_to(project) \
            or project.is_relative_to(output):
        raise ValueError('Export needs a new directory outside the authored project')
    recovering = getattr(args, 'verify_from', None) or getattr(args, 'resume_from', None)
    if getattr(args, 'verify_from', None) and getattr(args, 'resume_from', None):
        raise ValueError('Use only one of --verify-from and --resume-from')
    if recovering and any((args.cache, args.audio_donor,
            args.picture_donor, args.cached_native_batches, getattr(args, 'sdk_streaming', False), args.acquire_source_cache,
            args.audio_profile != NATIVE_SHORT_MASTERING_PROFILE.identity,
            getattr(args, 'render_only', False))):
        raise ValueError('--verify-from/--resume-from preserves the sealed route, cache and audio policy; omit render options')
    if recovering and getattr(args, 'reference_map', None):
        raise ValueError('--verify-from/--resume-from preserves the original reference map; omit --reference-map')
    validate_draft_options(args)
    if getattr(args, 'preview_reviews', None):
        from studio.native_motion_review import require_typed_short_reviews
        require_typed_short_reviews(args.preview_reviews, project)


def add_donors(args: argparse.Namespace, request: dict) -> None:
    """Reuse the existing independently qualified picture and AAC donor contracts."""
    if args.audio_donor:
        donor = args.audio_donor.resolve(strict=True)
        request['audioDonor'] = str(donor)
        request['pins'][str(donor)] = digest(donor)
    if args.picture_donor:
        from studio.native_short_picture_reuse import picture_reuse_pins, read_record
        donor = args.picture_donor.resolve(strict=True)
        if read_record(donor / 'export-request.json').get('captureMode') != request['captureMode']:
            raise ValueError('Picture donor requires its original explicit capture route')
        request['pictureDonor'] = str(donor)
        request['pins'].update(picture_reuse_pins(Path(request['project']), donor))


def source_cache_mode(args: argparse.Namespace) -> str:
    """Use content-bound decoded frames, retaining the explicit sequential SDR option."""
    if not getattr(args, 'acquire_source_cache', False):
        return 'acquire-content-store'
    if getattr(args, 'sdk_streaming', False):
        raise ValueError('Sequential source-cache acquisition cannot use --sdk-streaming')
    return 'acquire-content-store-sequential-sdr'


def execute(args: argparse.Namespace, task: object | None = None) -> bool:
    """Reserve the budgeted launch before any preparation, then run the owned stages.

    ``task`` is the claimed media task this process acknowledged (``production.media.task_execution``);
    its one launch is reserved against that claim instead of as a free-standing launch.
    """
    invocation = (time.monotonic(), utc())
    validate_options(args, args.project.resolve(strict=True), args.output.absolute())
    admitted, budget = reserve_for_args(args) if task is None else reserve_for_task(args, task)
    if not admitted:
        return False
    publish_grant(budget)  # the outer watchdog now bounds the rest by this launch's grant
    try:
        request, environment = prepare(args, budget)
    except BaseException as error:
        close_unpublished_launch(budget, error)
        raise
    pipeline = NativeShortPipeline(request, environment, args.unused_ram_advisory)
    return pipeline.execute(args.render_only, invocation)


def run_supervised(args: argparse.Namespace, task: object | None) -> bool:
    """The supervised child's whole export; a claimed task is acknowledged first (the watchdog settles it)."""
    from studio.production.media import task_execution
    with interrupt_on_termination():
        if task is None:
            return execute(args)
        with task_execution(task) as proceed:
            return proceed and execute(args, task)


def parser() -> argparse.ArgumentParser:
    """The exporter's closed options (``run-media`` derives a request's route with the same parser)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--reference-map', type=Path,
                        help='Bind checked planning decisions for an explicit reference-shot/style request')
    stage = parser.add_mutually_exclusive_group()
    stage.add_argument('--render-only', action='store_true',
                       help='Seal completed media for later verification; does not qualify delivery')
    stage.add_argument('--verify-from', type=Path,
                       help='Reuse sealed media and compatible completed capture; run all remaining QC')
    stage.add_argument('--resume-from', type=Path,
                       help='Resume an explicit attempt, including a later compatible capture, into a fresh directory')
    draft_options(parser, stage)
    parser.add_argument('--audio-donor', type=Path)
    parser.add_argument('--audio-profile', choices=MASTERING_PROFILE_IDENTITIES, default=NATIVE_SHORT_MASTERING_PROFILE.identity,
                        help='Explicit delivery profile; audio reuse also requires the current recorded AAC encoding policy')
    parser.add_argument('--picture-donor', type=Path,
                        help='Reuse an admitted completed SDK or batch picture; all final audio/picture QC still runs')
    capture = parser.add_mutually_exclusive_group()
    capture.add_argument('--cached-native-batches', action='store_true',
                         help='Retain picture frames for bounded revision repair (the default Short route)')
    capture.add_argument('--sdk-streaming', action='store_true',
                         help='Use the legacy streaming route without retained picture frames for local repair')
    parser.add_argument('--acquire-source-cache', action='store_true',
                        help='With cached batches, acquire exact original-size SDR source PNGs sequentially through the pinned SDK')
    parser.add_argument('--unused-ram-advisory', action='store_true',
                        help='Compatibility flag for explicit fixed policies; adaptive defaults already treat unused RAM as advisory')
    from studio.native_motion_previews import preview_options
    preview_options(parser)
    from studio.native_audio_import import audio_stage_options
    audio_stage_options(parser)
    return parser


def main() -> None:
    """One explicit output attempt, always as the supervised child of the outer export watchdog.

    Failed directories are preserved for diagnosis. The parsing process only supervises; the
    child it starts runs the export (and a forged or reused claim is refused, exit 2).
    """
    args = parser().parse_args()
    try:
        supervision = supervised_claim()
    except SupervisionRefused as error:
        print(json.dumps({'status': 'refused-supervision', 'reason': str(error), 'childLaunched': False}), flush=True)
        raise SystemExit(2) from error
    if supervision is None:
        from studio.production.process_watch import supervise_export
        raise SystemExit(supervise_export(ExportLaunch(tuple(sys.argv[1:]), args.project)))
    raise SystemExit(0 if run_supervised(args, supervision.task) else 1)


if __name__ == '__main__':
    main()
