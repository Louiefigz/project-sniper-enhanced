"""Seal reusable native work only after its original owner completed cleanly.

These records preserve completed work for new verification; they never qualify
delivery, repair old attempts, or execute media. Short and long adapters provide
their own exact input closure, artifact inventory, and stage success status.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import MAX_JSON, bound_json, file_hash, real_directory, write_new
from studio.native_run_config import source_hashes

MAX_NATIVE_FILE_BYTES = 1024 ** 4  # Stream large originals without the preview's 2 GiB cap.
MAX_NATIVE_CAPTURE_JSON_BYTES = 256 * 1024 * 1024
STABLE_FIELDS = ('sourceStable', 'sdkStable', 'sandboxStable', 'additionalFilesStable',
                 'leaseCleanupVerified')
RECORD_KEYS = {'schemaVersion', 'stage', 'project', 'root', 'request', 'supervisor',
               'inputs', 'artifacts', 'successStatus', 'supervisorPins'}


@dataclass(frozen=True)
class StageEvidence:
    """One caller-selected completed stage and every file required to reuse it."""

    stage: str
    project: Path
    root: Path
    request: Path
    supervisor: Path
    inputs: dict[str, str]
    artifacts: dict[str, Path]
    success_status: str


def require(value: bool, message: str) -> None:
    """Reject incomplete shared native evidence without optimizable assertions."""
    if not value:
        raise ValueError(f'Native stage evidence: {message}')


def read_native_capture_receipt(path: Path, expected: str | None = None) -> dict:
    """Read detailed frame proof; small requests and stage seals keep their 16 MiB limit."""
    return bound_json(path, expected, maximum=MAX_NATIVE_CAPTURE_JSON_BYTES)


def _hash(file: Path) -> str:
    """Hash regular canonical bytes with an explicit large-original limit."""
    return file_hash(file, maximum=MAX_NATIVE_FILE_BYTES)


def _pin_map(value: object) -> dict[str, str]:
    """Validate identities before treating a record as an input dependency map."""
    require(type(value) is dict and bool(value), 'missing input pins')
    for filename, expected in value.items():
        require(isinstance(filename, str) and Path(filename).is_absolute()
                and Path(filename).as_posix() == filename, 'input pin path is not absolute/canonical')
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected) is not None,
                f'missing SHA256 pin: {filename}')
    return value


def verify_pins(pins: dict[str, str]) -> None:
    """Rehash all retained dependencies, checking symlink and inode stability."""
    for filename, expected in _pin_map(pins).items():
        require(_hash(Path(filename)) == expected, f'changed input: {filename}')


def verify_supervised_inputs(project: Path, request_path: Path, request: dict, pipeline: dict) -> None:
    """Check shared supervision independently of each adapter's success policy."""
    require(request.get('project') == str(project) and pipeline.get('project') == str(project),
            'donor belongs to a different project')
    require(request.get('output') == str(request_path.parent), 'donor request output differs')
    for key in STABLE_FIELDS:
        require(pipeline.get(key) is True, f'donor supervision did not verify {key}')
    cleanup = pipeline.get('cleanup')
    require(type(cleanup) is dict and cleanup.get('verified') is True
            and cleanup.get('survivors') == [], 'donor owned cleanup is incomplete')
    before = _pin_map(pipeline.get('additionalFilePinsBefore'))
    require(before == pipeline.get('additionalFilePinsAfter'), 'donor additional before/after pins disagree')
    require(all(before.get(key) == value for key, value in _pin_map(request.get('pins')).items()),
            'donor request pins were not supervised')
    require(before.get(str(request_path)) == _hash(request_path), 'donor request changed after supervision')
    sources = pipeline.get('sourceHashesBefore')
    require(type(sources) is dict and bool(sources)
            and sources == pipeline.get('sourceHashesAfter') == source_hashes(project),
            'current authored project differs from supervised sources')
    require(all(_hash(project / name) == value for name, value in sources.items()),
            'supervised authored project bytes changed')


def _owned_completion(pipeline: dict, status: str) -> None:
    """Reject aborted, unlaunched, incomplete, or ambiguously owned attempts."""
    require(isinstance(status, str) and 0 < len(status) <= 128
            and status not in {'failed', 'preparing', 'running'}, 'invalid stage success status')
    require(pipeline.get('status') == status and type(pipeline.get('exitCode')) is int
            and pipeline['exitCode'] == 0, 'stage owner did not complete successfully')
    require(not pipeline.get('abortReason') and not pipeline.get('receiptOwnershipFailed'),
            'stage owner failed or lost receipt ownership')
    owners, pid = pipeline.get('ownerIdentities'), pipeline.get('pid')
    require(type(pid) is int and pid > 0 and type(owners) is list and bool(owners),
            'stage owner identity is missing')
    for row in owners:
        require(type(row) is dict and all(type(row.get(key)) is int and row[key] > 0
                for key in ('pid', 'pgid', 'parent_pid'))
                and isinstance(row.get('started'), str) and bool(row['started'].strip()),
                'stage owner identity is partial')
    require(len({row['pid'] for row in owners}) == len(owners)
            and any(row['pid'] == row['pgid'] == pid for row in owners),
            'stage root owner identity is incomplete')


def _inside(file: Path, root: Path) -> None:
    """Keep receipts and outputs within the same canonical original attempt."""
    require(file.is_absolute() and file != root and file.is_relative_to(root)
            and file.resolve(strict=True) == file, f'escaping or linked stage path: {file}')
    real_directory(file.parent)


def _validate_spec(spec: StageEvidence) -> None:
    """Validate the stage namespace and disjoint inputs, outputs, and receipts."""
    require(isinstance(spec.stage, str) and re.fullmatch('[a-z][a-z0-9-]{0,63}', spec.stage) is not None,
            'invalid stage name')
    real_directory(spec.project)
    real_directory(spec.root)
    require(spec.root != spec.project and not spec.root.is_relative_to(spec.project),
            'stage output must be outside the authored project')
    require(type(spec.artifacts) is dict and bool(spec.artifacts), 'missing stage artifacts')
    for name in spec.artifacts:
        require(isinstance(name, str) and re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}', name) is not None,
                'invalid artifact name')
    paths = [spec.request, spec.supervisor, *spec.artifacts.values()]
    require(all(isinstance(path, Path) for path in paths), 'stage paths must be Path values')
    require(len(set(paths)) == len(paths), 'stage receipt and artifact paths overlap')
    for file in paths:
        _inside(file, spec.root)
    require(spec.root / f'{spec.stage}-stage.json' not in paths, 'stage cannot seal itself')
    require(not set(map(str, paths)).intersection(_pin_map(spec.inputs)),
            'stage inputs overlap generated artifacts or receipts')


def _binding(file: Path, maximum: int = MAX_NATIVE_FILE_BYTES) -> dict[str, str]:
    """Retain the exact path and bytes of an artifact or supervision receipt."""
    return {'path': str(file), 'sha256': file_hash(file, maximum=maximum)}


def _build_record(spec: StageEvidence) -> tuple[dict, dict[str, str]]:
    """Validate original completion and collect a new immutable stage record."""
    _validate_spec(spec)
    request_ref, supervisor_ref = _binding(spec.request, MAX_JSON), _binding(spec.supervisor, MAX_JSON)
    request = bound_json(spec.request, request_ref['sha256'])
    pipeline = bound_json(spec.supervisor, supervisor_ref['sha256'])
    require(spec.inputs == request.get('pins'), 'stage inputs differ from original request')
    verify_supervised_inputs(spec.project, spec.request, request, pipeline)
    _owned_completion(pipeline, spec.success_status)
    artifacts = {name: _binding(file) for name, file in spec.artifacts.items()}
    require(pipeline.get('output') in {row['path'] for row in artifacts.values()},
            'supervised output is missing from stage artifacts')
    record = {'schemaVersion': 1, 'stage': spec.stage, 'project': str(spec.project),
              'root': str(spec.root), 'request': request_ref, 'supervisor': supervisor_ref,
              'inputs': dict(spec.inputs), 'artifacts': artifacts,
              'successStatus': spec.success_status, 'supervisorPins': pipeline['additionalFilePinsBefore']}
    pins = {row['path']: row['sha256'] for row in [request_ref, supervisor_ref, *artifacts.values()]}
    pins.update(pipeline['additionalFilePinsBefore'])
    pins.update({str(spec.project / name): value for name, value in pipeline['sourceHashesBefore'].items()})
    verify_pins(pins)
    return record, pins


def seal_stage(spec: StageEvidence) -> dict:
    """Exclusively seal completed work; a failed owner never receives a new seal."""
    record, pins = _build_record(spec)
    path = spec.root / f'{spec.stage}-stage.json'
    require(len(canonical_compact_json(record).encode()) + 1 <= MAX_JSON, 'stage receipt exceeds JSON limit')
    write_new(path, record)
    verify_pins(pins)
    return record


def _record_spec(record: dict) -> StageEvidence:
    """Reconstruct only a closed versioned schema, without defaulting missing proof."""
    require(set(record) == RECORD_KEYS and type(record['schemaVersion']) is int
            and record['schemaVersion'] == 1, 'invalid stage record schema')
    require(type(record['artifacts']) is dict, 'invalid stage artifact inventory')
    refs = [record['request'], record['supervisor'], *record['artifacts'].values()]
    for ref in refs:
        require(type(ref) is dict and set(ref) == {'path', 'sha256'}, 'invalid stage file binding')
        require(isinstance(ref['path'], str), 'stage binding path must be a string')
        _pin_map({ref['path']: ref['sha256']})
    require(all(isinstance(record[key], str) for key in ('project', 'root')), 'invalid stage root/project')
    return StageEvidence(record['stage'], Path(record['project']), Path(record['root']),
                         Path(record['request']['path']), Path(record['supervisor']['path']),
                         _pin_map(record['inputs']),
                         {key: Path(row['path']) for key, row in record['artifacts'].items()},
                         record['successStatus'])


def read_stage(receipt_path: Path, current_inputs: dict[str, str], expected_stage: str) -> tuple[dict, dict[str, str]]:
    """Revalidate every current byte and return the record plus pins for a new owner."""
    receipt_hash = file_hash(receipt_path, maximum=MAX_JSON)
    record = bound_json(receipt_path, receipt_hash)
    spec = _record_spec(record)
    require(spec.stage == expected_stage and receipt_path == spec.root / f'{spec.stage}-stage.json',
            'stage receipt belongs to another stage or root')
    require(spec.inputs == _pin_map(current_inputs), 'current stage input dependencies differ')
    rebuilt, pins = _build_record(spec)
    require(rebuilt == record, 'stage evidence changed after sealing')
    pins[str(receipt_path)] = receipt_hash
    verify_pins(pins)
    return record, pins
