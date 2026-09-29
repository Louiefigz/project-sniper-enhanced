"""Standalone native Short reference-capture seals, reused by a later export of the same content.

A capture depends on the authored project bytes, the adapted runtime, the tools,
the invoked code and its capture policy, not on preview reviews, preview donors or
audio/picture donors. A completed capture is sealed immediately after its owner,
before any preview or render, and a later export (normally the first final after
the preview-only run) adopts it when that capture-dependency identity is equal.
Every seal byte, the donor owner's cleanup and every JPEG are re-verified on use;
the output-bound encoded-picture comparisons and full decode still run afresh.
"""
from __future__ import annotations

import sys
from pathlib import Path

from cut_preview_io import bound_json, digest
from studio.native_export_history import candidate_attempts
from studio.native_runtime import REPO
from studio.native_stage_evidence import StageEvidence, read_stage, require, seal_stage

CAPTURE_STATUS = 'native-reference-capture-complete'
CAPTURE_POLICY = ('adapter', 'project', 'runtime', 'tools', 'cache', 'captureMode', 'sourceCacheMode')


def capture_dependencies(request: dict, pins: dict[str, str]) -> dict[str, str]:
    """Pins a capture can read: project bytes, runtime, tools, interpreter and repository code."""
    roots = [Path(request['project']), Path(request['runtime']), REPO / 'scripts', REPO / 'src', REPO / 'schemas']
    executables = {*request['tools'].values(), str(Path(sys.executable).resolve())}
    return {name: sha for name, sha in pins.items()
            if name in executables or any(Path(name).is_relative_to(root) for root in roots)}


def capture_identity(request: dict, pins: dict[str, str]) -> str:
    """Exact capture-dependency identity; any project, runtime, tool, code or policy change differs."""
    return digest({'policy': {key: request.get(key) for key in CAPTURE_POLICY},
                   'dependencies': capture_dependencies(request, pins)})


def seal_standalone_capture(root: Path, request: dict) -> dict[str, str]:
    """Seal the just-completed owner's capture with no render dependency; return its pins."""
    from studio.native_short_capture_resume import capture_artifacts
    spec = StageEvidence('capture', Path(request['project']), root, root / 'export-request.json',
                         root / 'capture.render.json', request['pins'], capture_artifacts(root, request),
                         CAPTURE_STATUS)
    seal_stage(spec)
    _record, pins = read_stage(root / 'capture-stage.json', request['pins'], 'capture')
    return pins


def read_standalone_capture(seal: Path, request: dict) -> tuple[dict, dict[str, str]]:
    """Revalidate a donor seal and require its capture identity to equal the current request's."""
    from studio.native_short_capture_resume import capture_artifacts
    require(seal.name == 'capture-stage.json' and seal.is_absolute(), 'expected a canonical capture-stage.json seal')
    recorded = bound_json(seal)
    donor = bound_json(Path(recorded['request']['path']), recorded['request']['sha256'])
    record, pins = read_stage(seal, recorded['inputs'], 'capture')
    require(record['successStatus'] == CAPTURE_STATUS and record['project'] == request['project']
            and capture_identity(donor, record['inputs']) == capture_identity(request, request['pins']),
            'capture seal belongs to other project content, runtime, tools, code or capture policy')
    root = Path(record['root'])
    artifacts = capture_artifacts(root, {**donor, 'project': request['project'], 'runtime': request['runtime']})
    require({name: row['path'] for name, row in record['artifacts'].items()}
            == {name: str(file) for name, file in artifacts.items()}, 'sealed capture inventory differs')
    return record, pins


def capture_for_render(receipt: Path, render_stage: Path) -> tuple[dict, dict[str, str]]:
    """Capture evidence a sealed render consumed: its own attempt's seal or an adopted donor seal."""
    sealed = bound_json(render_stage)
    original = bound_json(Path(sealed['request']['path']), sealed['request']['sha256'])
    if original.get('captureDependencySha256') and original.get('captureStage') == str(receipt):
        record, pins = read_standalone_capture(receipt, original)
        require(original['captureDependencySha256'] == capture_identity(original, original['pins']),
                'adopted capture identity changed')
        return record, pins
    from studio.native_short_capture_resume import read_capture
    return read_capture(receipt, render_stage)


def _compatible(attempt: Path, request: dict, identity: str) -> tuple[str, str] | None:
    """Cheap filter before full validation: same project, completed invocation, equal identity."""
    seal, delivery = attempt / 'capture-stage.json', attempt / 'delivery.json'
    if not seal.is_file() or not delivery.is_file() or Path(request['output']) == attempt:
        return None
    record = bound_json(seal)
    if record.get('project') != request['project'] or record.get('successStatus') != CAPTURE_STATUS:
        return None
    donor = bound_json(Path(record['request']['path']))
    if donor.get('captureDependencySha256') or capture_identity(donor, record['inputs']) != identity:
        return None
    completed = bound_json(delivery).get('completedAt')
    return (completed, str(seal)) if isinstance(completed, str) else None


def bind_capture_reuse(request: dict) -> dict:
    """Before publication, adopt the latest compatible sealed capture instead of repeating it."""
    if request.get('adapter', 'native-short') != 'native-short' or request.get('verifyStage') \
            or request.get('captureStage'):
        return request
    identity = capture_identity(request, request['pins'])
    candidates = [row for row in (_compatible(attempt, request, identity)
                                  for attempt in candidate_attempts(request)) if row]
    if not candidates:
        return request
    seal = Path(max(candidates)[1])
    _record, pins = read_standalone_capture(seal, request)
    require(all(request['pins'].get(name, sha) == sha for name, sha in pins.items()),
            'capture donor evidence conflicts with current pins')
    return {**request, 'captureStage': str(seal), 'captureDependencySha256': identity,
            'pins': {**request['pins'], **pins}}
