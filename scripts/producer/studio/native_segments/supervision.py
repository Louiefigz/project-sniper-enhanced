"""Dispatch section owners under the existing qualified pool; no independent resource grants."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cut_preview_io import bound_json, write_new
from native_work_pool_policy import class_capacity, host_identity
from native_work_qualification import committed
from native_work_workload import current_engine, describe
from studio.native_runtime import digest
from studio.native_segments.owners import restore_window, revision_windows, seal_window, supervise_window


def section_capacity(request: dict) -> int:
    """Read qualified capacity for this exact Long workload; missing evidence means one."""
    import native_work_pool_state as state
    from native_work_pool_mix import request_mode, session_of
    from native_work_pool_observe import observe
    host = host_identity()
    record = committed(host)
    workload = describe(request['project'], str(Path(request['output']) / 'segment-picture-0.render.json'), 'heavy')
    if record.needs_engine:
        workload['engine'] = current_engine()
    row = {'project': request['project'], 'root': request['output'], 'class': 'heavy', 'workload': workload}
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        session = session_of(observe(namespace), host)
        mode, _incompatible = request_mode(session, record, row)
    return class_capacity(mode, 'heavy')


class SectionProcesses:
    """Track only child supervisors launched here and request their normal owned cleanup."""

    def __init__(self, pipeline: object) -> None:
        """Retain the parent pipeline and synchronized direct-child inventory."""
        self.pipeline = pipeline
        self.children: set[subprocess.Popen] = set()
        self.lock = threading.Lock()
        self.cancelled = False

    def launch(self, phase: str) -> dict:
        """Each supervisor owns signals on its main thread and seals immediately on completion."""
        root = self.pipeline.root
        command = [sys.executable, str(Path(__file__).resolve()),
                   str(root / 'export-request.json'), phase]
        with self.lock:
            if self.cancelled:
                raise RuntimeError('Section dispatch cancelled before launch')
            child = subprocess.Popen(command, env=self.pipeline.environment)
            self.children.add(child)
        try:
            code = child.wait()
        finally:
            with self.lock:
                self.children.remove(child)
        result = bound_json(root / f'{phase}-supervisor.json')
        if code != 0 or result['status'] != 'sealed':
            from studio.native_short_pipeline import NativeStageFailure
            raise NativeStageFailure(phase, {'failureCategory': result.get('failureCategory'),
                                            'abortReason': result.get('error')})
        return result

    def cancel(self) -> None:
        """Bound cancellation of direct supervisors; unproved descendants retain their pool quarantine."""
        with self.lock:
            self.cancelled = True
            children = list(self.children)
        for child in children:
            if child.poll() is None:
                child.terminate()
        until = time.monotonic() + 30
        for child in children:
            stop_supervisor(child, until)


def stop_supervisor(child: subprocess.Popen, until: float) -> None:
    """Wait for normal cleanup, then stop only this direct child; never fabricate cleanup proof."""
    try:
        child.wait(timeout=max(.01, until - time.monotonic()))
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=5)


def run_sections(pipeline: object) -> None:
    """Save ready results immediately; wait for every launched owner before surfacing failure."""
    phases = []
    from studio.native_long_scope import selected_windows
    for window in selected_windows(pipeline.request):
        phase = f"segment-picture-{window['index']}"
        if not restore_window(pipeline, phase):
            phases.append(phase)
    from studio.native_budget_continuation import require_review_only
    require_review_only(pipeline.request, phases)
    publish_ready_reviews(pipeline)
    if not phases:
        return
    from studio.native_budget_clock import stage_allowance
    allowance = stage_allowance(pipeline.request, pipeline.request['budget']['ownerSeconds'])
    context = {'deadline': time.monotonic() + allowance, 'evidence': dict(pipeline.evidence)}
    write_new(pipeline.root / 'section-owner-context.json', context)
    processes = SectionProcesses(pipeline)
    with ThreadPoolExecutor(max_workers=min(len(phases), section_capacity(pipeline.request))) as executor:
        futures = [executor.submit(processes.launch, phase) for phase in phases]
        try:
            failure = collect_sections(pipeline, futures)
        except BaseException:
            processes.cancel()
            cancel_pending(futures)
            raise
    if failure:
        raise failure


def cancel_pending(futures: list) -> None:
    """Withdraw queued dispatches while live child supervisors perform owned cleanup."""
    for future in futures:
        future.cancel()


def collect_sections(pipeline: object, futures: list) -> Exception | None:
    """Collect every result and preserve first failure without discarding other completed seals."""
    failure = None
    for future in as_completed(futures):
        try:
            result = future.result()
            pipeline.stages.extend(result['stages'])
            pipeline.evidence.update(result['evidence'])
            publish_ready_reviews(pipeline)
        except Exception as error:
            failure = failure or error
    return failure


def publish_ready_reviews(pipeline: object) -> None:
    """Expose each complete logical group's review without waiting for unrelated children."""
    request = pipeline.request
    if request.get('sectionProduction'):
        from studio.production.section_chunk_presentation import package_ready_scopes
        package_ready_scopes(pipeline)
        from studio.production.sections import materialize_section_reviews
        result = materialize_section_reviews(request, 'encoded')
        if result['enqueued'] or result.get('readyChunks'):
            print(json.dumps({'status': 'section-review-ready', **result}), flush=True)


def supervise_section(file: Path, phase: str) -> None:
    """Child main thread delegates all process/media authority to the shared pipeline owner."""
    from studio.native_run_config import local_environment
    from studio.native_short_pipeline import NativeShortPipeline
    request = bound_json(file)
    root = Path(request['output'])
    context_file = root / 'section-owner-context.json'
    context = bound_json(context_file)
    _tools, environment = local_environment()
    pipeline = NativeShortPipeline(request, environment, owner_deadline=context['deadline'])
    pipeline.evidence.update(context['evidence'])
    pipeline.evidence[str(context_file)] = digest(context_file)
    result = {'status': 'failed'}
    try:
        if request.get('sectionProduction'):
            from studio.production.sections import require_early_review
            require_early_review(request, phase)
        label = supervise_window(pipeline, phase, [0])
        seal_window(pipeline, phase, label)
        result['status'] = 'sealed'
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
        result['failureCategory'] = getattr(error, 'category', 'renderer-failure')
    result.update(stages=pipeline.stages, evidence=pipeline.evidence)
    write_new(root / f'{phase}-supervisor.json', result)
    print(json.dumps({'section': phase, 'status': result['status']}), flush=True)
    raise SystemExit(0 if result['status'] == 'sealed' else 1)


if __name__ == '__main__':
    supervise_section(Path(sys.argv[1]), sys.argv[2])
