"""Manifest and checked-delivery admission for shared native review bundles."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from cut_preview_io import bound_json, real_directory
from studio.native_runtime import digest
from studio.native_stage_evidence import read_stage, read_native_capture_receipt, require, verify_pins, verify_supervised_inputs
from studio.native_short_resume import media_result
from studio.native_review_html import canvas_clock, validate_canvas

FINAL_STATUSES = {None: 'native-short-checked-for-review', 'native-long': 'native-long-checked-for-review'}


@dataclass(frozen=True)
class ReviewComposition:
    """One immutable export and its exact authored package."""

    identity: str
    title: str
    export: Path
    project: Path
    runtime: Path
    files: dict[str, str]
    pins: dict[str, str]
    plan: dict
    entry: str
    video: Path
    video_sha256: str
    native_long: bool = False


def relative_file(root: Path, name: str) -> Path:
    """Reject traversal and aliases before inspecting or copying project files."""
    require(isinstance(name, str) and bool(name) and not Path(name).is_absolute()
            and Path(name).as_posix() == name and '..' not in Path(name).parts, 'unsafe review package path')
    file = root / name
    require(file.resolve(strict=True) == file and file.is_file() and not file.is_symlink(), 'aliased or missing review input')
    return file


def project_files(project: Path, request: dict) -> dict[str, str]:
    """Admit the complete original manifest, with no unlisted copied files."""
    real_directory(project)
    if request.get('adapter') == 'native-long':
        from studio.native_preflight_inputs import inventory
        paths, _directories = inventory(project)
        files = {str(file.relative_to(project)): digest(file) for file in paths}
        require(all(request['pins'].get(str(project / name)) == sha for name, sha in files.items()),
                'long project differs from checked export')
        expected = {str(Path(file).relative_to(project)) for file in request['pins']
                    if Path(file).is_relative_to(project)}
        require(set(files) == expected, 'long project inventory differs from checked export')
        return files
    file = project / 'PROJECT-MANIFEST.json'
    manifest = bound_json(file, request['pins'][str(file)])
    rows = manifest['files']; files = {row['file']: row['sha256'] for row in rows}
    require(len(files) == len(rows) and len({name.casefold() for name in files}) == len(files), 'duplicate review project file')
    files['PROJECT-MANIFEST.json'] = request['pins'][str(file)]
    for name, sha in files.items():
        path = relative_file(project, name)
        require(request['pins'].get(str(path)) == sha and digest(path) == sha, 'project differs from checked export')
    require(not any(path.is_symlink() for path in project.rglob('*')), 'project contains symlink')
    return files


def checked_delivery(export: Path, layout: dict | None = None) -> tuple[dict, dict, dict]:
    """Require sealed media/capture and actual final verification ownership."""
    real_directory(export)
    request_file, delivery_file = export / 'export-request.json', export / 'delivery.json'
    request, delivery = bound_json(request_file), bound_json(delivery_file)
    video = export / 'review.mp4'
    require(request.get('adapter') in FINAL_STATUSES
            and delivery.get('status') == FINAL_STATUSES[request.get('adapter')]
            and delivery.get('fullAudioVideoDecodePassed') is True
            and delivery.get('output') == str(video) and delivery.get('sha256') == digest(video), 'unchecked review delivery')
    render_file = Path(request.get('verifyStage', export / 'render-stage.json'))
    render, pins = read_stage(render_file, request.get('renderInputs', request['pins']), 'render')
    media_result(render)
    require(render['artifacts']['review']['sha256'] == delivery['sha256'], 'review media differs from render seal')
    capture_file = Path(request.get('captureStage', export / 'capture-stage.json'))
    if request.get('adapter') != 'native-long' and layout and (
            layout.get('plan') != 'SHORT-PROJECT.json' or layout.get('entry') != 'index.html'):
        capture, capture_pins = read_compatible_capture(capture_file, render, {**layout, 'project': request['project'], 'renderStage': str(render_file)})
    else:
        from studio.native_short_capture_resume import read_capture
        capture, capture_pins = read_capture(capture_file, render_file)
    require(digest(export / 'native-frames.json') == capture['artifacts']['native']['sha256'], 'review capture changed')
    pins.update(capture_pins)
    stages = delivery.get('stages', [])
    require(len({row['phase'] for row in stages}) == len(stages), 'duplicate review owner phase')
    rows = [row for row in stages if row['phase'] == 'verification']
    require(len(rows) == 1, 'missing final review verification owner')
    row = rows[0]; owner_file = export / 'verification.render.json'
    owner = bound_json(owner_file, row['sha256'])
    verify_supervised_inputs(Path(request['project']), request_file, request, owner)
    require(row['receipt'] == str(owner_file) and owner.get('status') == row['status'] == delivery['status']
            and type(owner.get('exitCode')) is int and owner['exitCode'] == 0 and not owner.get('abortReason')
            and not owner.get('receiptOwnershipFailed') and owner.get('output') == str(export / 'checks.json'), 'final review owner incomplete')
    checks = bound_json(export / 'checks.json')
    require(checks.get('status') == 'checks-passed-awaiting-owned-cleanup' and checks.get('sha256') == delivery['sha256']
            and checks.get('fullAudioVideoDecodePassed') is True
            and checks.get('pictureFramesChecked') == delivery.get('pictureFramesChecked'), 'final review checks differ')
    pins.update(owner['additionalFilePinsBefore'])
    pins.update({str(file): digest(file) for file in (request_file, delivery_file, video, owner_file, export / 'checks.json')})
    verify_pins(pins)
    return delivery, request, pins


def read_composition(row: dict) -> ReviewComposition:
    """Resolve a named native Short or compatible long-form checked composition."""
    require(set(row) <= {'id', 'title', 'export', 'plan', 'entry'} and {'id', 'title', 'export'} <= set(row), 'invalid composition manifest')
    identity, title = row['id'], row['title']
    require(isinstance(identity, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', identity) is not None, 'unsafe composition id')
    require(isinstance(title, str) and 0 < len(title.strip()) <= 200, 'invalid composition title')
    export = Path(row['export'])
    require(export.is_absolute() and export.resolve(strict=True) == export, 'export path must be canonical and absolute')
    layout = {'plan': row.get('plan', 'SHORT-PROJECT.json'), 'entry': row.get('entry', 'index.html')}
    delivery, request, pins = checked_delivery(export, layout)
    project = Path(request['project']); files = project_files(project, request)
    default_plan = 'LONG-PROJECT.json' if request.get('adapter') == 'native-long' else 'SHORT-PROJECT.json'
    plan_name, entry = row.get('plan', default_plan), row.get('entry', 'index.html')
    if request.get('adapter') == 'native-long':
        require(plan_name == default_plan and entry == 'index.html', 'long review layout differs from its export contract')
    require(plan_name in files and entry in files and entry.endswith('.html'), 'review plan/entry missing from manifest')
    plan = bound_json(relative_file(project, plan_name), files[plan_name])
    if request.get('adapter') == 'native-long':
        from studio.native_long_contract import long_audio_canvas
        plan = {**plan, 'canvas': long_audio_canvas(plan)}
    canvas_clock(plan['canvas'])
    return ReviewComposition(identity, title, export, project, Path(request['runtime']), files, pins,
                             plan, entry, Path(delivery['output']), delivery['sha256'],
                             request.get('adapter') == 'native-long')


def read_manifest(file: Path) -> list[ReviewComposition]:
    """Keep ordered arbitrary names, rejecting collisions before creating outputs."""
    manifest = bound_json(file)
    require(set(manifest) == {'schemaVersion', 'compositions'} and type(manifest['schemaVersion']) is int
            and manifest['schemaVersion'] == 1, 'invalid native review manifest schema')
    rows = manifest['compositions']
    require(type(rows) is list and 1 <= len(rows) <= 32, 'review bundle needs one to 32 compositions')
    require(all(type(row) is dict for row in rows), 'invalid composition row')
    ids = [row.get('id') for row in rows]
    require(all(isinstance(identity, str) for identity in ids) and len({identity.casefold() for identity in ids}) == len(ids),
            'duplicate review composition id')
    result = [read_composition(row) for row in rows]
    require(len({str(row.runtime) for row in result}) == 1, 'review bundle requires one qualified Studio runtime')
    return result


def read_compatible_capture(receipt: Path, render: dict, composition: dict) -> tuple[dict, dict]:
    """Use generic StageEvidence ownership and exact recorded JPEG bindings."""
    request = bound_json(receipt.parent / 'export-request.json')
    record, pins = read_stage(receipt, request['pins'], 'capture')
    require(record['project'] == render['project'] == composition['project']
            and record['successStatus'] == 'native-reference-capture-complete', 'capture project/status differs')
    if request.get('verifyStage'):
        require(request.get('renderInputs') == render['inputs'] and request.get('renderResult') == render['artifacts']['media']['path']
                and request['verifyStage'] == composition['renderStage'], 'capture belongs to another render')
    else:
        require(record['request'] == render['request'], 'capture and render have different original requests')
    native_ref = record['artifacts']['native']
    native = read_native_capture_receipt(Path(native_ref['path']), native_ref['sha256'])
    project = Path(composition['project'])
    plan = bound_json(project / composition['plan'])
    _nodes, root, _clock, _duration = validate_canvas((project / composition['entry']).read_text(), plan['canvas'])
    require(native.get('project') == str(project) and native.get('status') == 'native-references-and-seek-states-pass'
            and native.get('fromEncodedOutput') is False and native.get('failedSceneStates') == []
            and native.get('frameRate') == plan['canvas']['frameRate'], 'native capture checks failed or changed')
    require(native.get('width') == int(root.attrs['data-width']) and native.get('height') == int(root.attrs['data-height'])
            and native.get('sourceHtmlSha256') == digest(project / composition['entry'])
            and native.get('runtimeLibrarySha256') == digest(Path(request['runtime']) / 'dist/native-capture-library.mjs'),
            'native capture canvas or runtime differs')
    rows = native['frames']
    require(bool(rows) and [row['frame'] for row in rows] == native.get('expectedCapturePoints'), 'capture point inventory differs')
    images = {row['path']: row['sha256'] for row in rows}
    artifacts = {row['path']: row['sha256'] for key, row in record['artifacts'].items() if key != 'native'}
    require(len(images) == len(rows) and images == artifacts, 'capture seal omitted or changed a JPEG')
    require(any(row.get('repeat') is True for row in rows) and any(row.get('repeat') is False for row in rows), 'missing reverse/forward proof')
    return record, pins
