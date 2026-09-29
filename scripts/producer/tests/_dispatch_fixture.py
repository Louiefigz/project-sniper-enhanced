"""TEST scaffolding for dispatch and process tests: requests, approvals, launchers and a TEST exporter child.

No real render runs. The TEST exporter child is the real ``native_short_export.main`` (supervised
claim, acknowledgement and the real task reservation) with ``prepare`` and the pipeline replaced by
a TEST delivery. Every subprocess points the budget authority and the pool state at the test's
private root (``isolate``) before it does anything else; no real process or host is named.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

PRODUCER = Path(__file__).resolve().parents[1]
LAUNCH = ('import sys; sys.path[:0] = [sys.argv[1], sys.argv[1] + "/tests"]\n'
          'import _dispatch_fixture as fixture; fixture.enter(sys.argv[2:])\n')
EXPORTER_SCRIPT = ('import sys; sys.path[:0] = [{producer!r}, {tests!r}]\n'
                   'import _dispatch_fixture as fixture\n'
                   'fixture.test_exporter({root!r}, {testdir!r})\n')


def isolate(root: Path) -> None:
    """Point every authority, engine, capacity and pool-state reader of this process at TEST values."""
    from _budget_fixture import ENGINE
    import native_work_lease
    from studio import native_budget_binding as binding, native_budget_engine as engine
    from studio import native_budget_exporter as exporter, native_budget_forecast as forecast
    from studio import native_budget_owner as owner, native_budget_store as store
    store.default_root = lambda: root
    for module in (binding, exporter, owner):
        module.default_root = store.default_root
    binding.engine_identity = engine.engine_identity = lambda _repo: dict(ENGINE)
    forecast.heavy_lane_capacity = lambda *_seconds: 1
    native_work_lease.state_root = lambda: root.parent / 'pool-state'


def launcher(role: str, root: Path, testdir: Path) -> list[str]:
    """The command that starts a TEST-isolated ``role`` process (arguments follow)."""
    return [sys.executable, '-B', '-c', LAUNCH, str(PRODUCER), role, str(root), str(testdir)]


def enter(argv: list[str]) -> None:
    """Run one role in a fresh, isolated process: cli, dispatcher or run-media."""
    role, root, testdir, rest = argv[0], Path(argv[1]), Path(argv[2]), argv[3:]
    isolate(root)
    from studio.production import dispatch, process, process_watch
    process_watch.ACK_SECONDS = 10.0                 # the TEST exporter acknowledges within seconds
    dispatch.RUN_SELF = launcher('dispatcher', root, testdir)
    dispatch.RUN_MEDIA = [*launcher('run-media', root, testdir), 'run-media']
    dispatch.APP_ROOT, dispatch.POLL_SECONDS = testdir / 'app', 0.2
    process.EXPORTER, process.STOP_GRACE_SECONDS = testdir / 'test_exporter.py', 3.0
    process.POLL_SECONDS = 0.2
    if role == 'dispatcher':
        sys.argv = ['dispatch.py', *rest]
        dispatch.main()
    sys.argv = ['native_batch.py', *rest]
    import native_batch
    native_batch.main()


def write_exporter(root: Path, testdir: Path) -> Path:
    """The TEST exporter script the export watchdog starts in place of the real one."""
    script = testdir / 'test_exporter.py'
    script.write_text(EXPORTER_SCRIPT.format(producer=str(PRODUCER), tests=str(PRODUCER / 'tests'), root=str(root),
                                             testdir=str(testdir)))
    return script


class FakePipeline:
    """A TEST delivery in place of the native pipeline: a labeled draft MP4, its receipt and outcome."""

    testdir: Path = Path('/nonexistent')

    def __init__(self, request: dict, _environment: dict, _advisory: bool) -> None:
        """Keep the reserved request."""
        self.request = request

    def execute(self, _render_only: bool, _invocation: object) -> bool:
        """Wait while the test holds the export (bounded), then deliver and record the outcome."""
        from studio import native_budget_binding as binding
        until = time.monotonic() + 60
        while (self.testdir / 'hold').exists() and not (self.testdir / 'release').exists() and time.monotonic() < until:
            time.sleep(0.05)
        output = Path(self.request['output'])
        mp4 = output / 'review-draft.mp4'
        mp4.write_bytes(b'TEST review draft of ' + output.name.encode())
        result = {'status': 'native-short-review-draft', 'output': str(mp4),
                  'sha256': hashlib.sha256(mp4.read_bytes()).hexdigest()}
        (output / 'delivery.json').write_text(json.dumps(result))
        binding.record_request_outcome(self.request, result)
        print(json.dumps(result), flush=True)
        return True


def fake_prepare(args: object, budget: dict | None) -> tuple[dict, dict]:
    """The attempt directory and the reserved request, without runtime setup or media."""
    output = args.output.absolute()
    output.mkdir(mode=0o700)
    return {'output': str(output), 'project': str(args.project.resolve()), 'productionBudget': budget}, {}


def test_exporter(root: str, testdir: str) -> None:
    """The TEST exporter child: the real entry with a TEST preparation and pipeline."""
    isolate(Path(root))
    from studio import native_short_export as export
    FakePipeline.testdir = Path(testdir)
    export.prepare, export.NativeShortPipeline = fake_prepare, FakePipeline
    export.main()


def media_request(directory: Path, fields: dict, options: dict | None = None) -> Path:
    """A TEST ``native-media-request`` file: fields = batchId, taskId, clipId, route, project, output."""
    value = {'schemaVersion': 1, 'kind': 'native-media-request', **fields, 'options': options or {}}
    path = directory / f'{fields["taskId"]}.request.json'
    path.write_text(json.dumps(value))
    return path


def approval_row(clip: str, approval: object) -> dict:
    """A TEST approval as the operator's approval file writes it."""
    return {'clipId': clip, 'title': approval.title, 'recordedBy': approval.recorded_by,
            'script': {'sourceSha256': approval.source_sha256, 'sourceSeconds': approval.source_seconds,
                       'transcriptPath': approval.transcript_path, 'transcriptSha256': approval.transcript_sha256,
                       'transcriptWords': approval.transcript_words,
                       'wordRanges': [list(row) for row in approval.word_ranges],
                       'wordTexts': list(approval.word_texts), 'ranges': [list(row) for row in approval.ranges]}}


def approval_file(directory: Path, clip: str, approval: object) -> Path:
    """A TEST ``native-short-approval`` file for one clip."""
    path = directory / f'approval-{clip}.json'
    path.write_text(json.dumps({'schemaVersion': 1, 'kind': 'native-short-approval', **approval_row(clip, approval)}))
    return path


def tasks_file(directory: Path, name: str, tasks: list[dict]) -> Path:
    """A TEST ``native-production-tasks`` submission."""
    path = directory / f'{name}.tasks.json'
    path.write_text(json.dumps({'schemaVersion': 1, 'kind': 'native-production-tasks', 'tasks': tasks}))
    return path


def start_args(directory: Path, batch_id: str, clips: str, **extra: object) -> object:
    """``native_batch.py start`` arguments with every clip's TEST approval handed over."""
    from types import SimpleNamespace
    from _budget_fixture import approval
    pairs = [f'{clip}={approval_file(directory, clip, approval(clip))}' for clip in clips.split(',') if clip]
    values = {'batch': batch_id, 'clips': clips, 'approval': pairs, 'approvals': None, 'pool_slots': None,
              'source': [], 'ai_slots': None, 'ai_reservations': None}
    return SimpleNamespace(**{**values, **extra})


def added_approval(directory: Path, clip: str) -> Path:
    """The TEST approval file handed over with a clip added after start."""
    from _budget_fixture import approval
    return approval_file(directory, clip, approval(clip))
