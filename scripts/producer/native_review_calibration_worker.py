"""Owned technical workers for generated Long review-package measurements.

No entry here authors production approvals, publishes segment seals, adopts
forecast rates, or changes runtime capacity. All media work requires inspection.
"""
from __future__ import annotations

import argparse
import math
import time
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json, write_new
from native_review_calibration_media import pin, prepare_fixture, read_fixture
from native_review_proof_calibration import proof_read
from native_work_pool_disk import filesystem
from native_work_pool_policy import host_identity
from native_work_pool_storage import read_statfs
from native_work_qualification import session_member
from native_work_service_cache import unobserved_cache
from native_work_workload import engine_record
from studio.native_export import active_owner_snapshot
from studio.native_segments.review_media import derive_media
from studio.native_stage_evidence import require
from studio.owned_inspection import STATUS, read_inspection, require_worker

WORKER = Path(__file__).resolve()
UNSUPPORTED = ['production-source-authority-traversal', 'production-stage-seal-publication',
               'recurring-coordinator-proof-entrypoints', 'physical-read-byte-observation']


def require_provenance(request: dict) -> None:
    """Bind measured execution to actual current code/tools, not parent metadata alone."""
    value = request['provenance']
    require(set(value) == {'engine', 'tools', 'harness'} and value['engine'] == engine_record(),
            'Calibration engine provenance changed')
    require(value['harness'] == pin(WORKER.with_name('native_review_calibration.py')),
            'Calibration harness provenance changed')
    require(set(value['tools']) == {'ffmpeg', 'ffprobe'}, 'Calibration tool inventory changed')
    for name, record in value['tools'].items():
        require(set(record) == {'executable', 'version'}
                and record['executable'] == pin(Path(request['tools'][name]))
                and record['version'] == pin(Path(record['version']['path'])),
                'Calibration executable provenance changed')


def require_session(request: dict, file: Path) -> None:
    """Reject a worker not launched under this declared, unexpired pool session."""
    import native_work_pool_state as state
    from native_work_pool_mix import session_of
    from native_work_pool_observe import observe
    session = request['session']
    host = host_identity()
    with state.ledger(time.monotonic() + state.LEDGER_WAIT_SECONDS) as namespace:
        live = session_of(observe(namespace), host)
        require(live is not None and live['value'] == session, 'Calibration session is no longer live')
    require(session_member(session, request['project'], str(file.parent)), 'Undeclared calibration job')
    owner = active_owner_snapshot(file.parent / 'inspection.render.json')
    pool = owner.get('pool', {})
    require(pool.get('mode') == 'qualification-session'
            and pool.get('modeRecord', {}).get('session') == session['nonce'],
            'Calibration requires its real candidate-session owner')


def retained_pins(root: Path) -> list[dict]:
    """Name every generated media/proof file, excluding mutable owner diagnostics."""
    value = bound_json(root / 'technical-inputs.json')
    rows = [pin(root / 'technical-inputs.json')]
    rows.extend(row['pin'] for row in value['windows'])
    rows.extend(value['audio'][name] for name in ('master', 'reference', 'receipt'))
    return rows


def prepare(request: dict, root: Path) -> dict:
    """Prepare generated inputs under one actual owner, independently of timing runs."""
    prepare_fixture(request['spec'], request['tools'], root)
    read_fixture(root / 'technical-inputs.json', request['tools'])
    return {'status': STATUS, 'kind': 'native-long-review-package-technical-preparation',
            'outputPins': retained_pins(root), 'fixture': pin(root / 'technical-inputs.json'),
            'picturePins': [row['pin'] for row in bound_json(root / 'technical-inputs.json')['windows']],
            'productionAuthority': False}


def contract_for(value: dict, root: Path) -> dict:
    """Derive actual geometry, encoder and output filesystem; cache remains unknown."""
    canvas = value['spec']['canvas']
    disk, stat = filesystem(str(root)), read_statfs(str(root))
    encoders = {row['encoding']['encoderContractSha256'] for row in value['windows']}
    require(len(encoders) == 1, 'Generated windows use different encoder contracts')
    return {'format': 'long', 'stage': 'review-package',
            'canvas': {key: canvas[key] for key in ('width', 'height', 'frameRate')},
            'encoderContractSha256': encoders.pop(),
            'audio': {'sampleRate': 48000, 'channels': 2, 'sampleFormat': 'pcm_f32le'},
            'filesystem': {'type': stat.f_fstypename.decode(),
                           'volumeIdentity': f'{disk.device}:{list(stat.f_fsid)}:{stat.f_mntfromname.decode()}'},
            'cacheRegime': 'unknown', 'execution': {'ownedConcurrency': 1},
            'proofPlanVersion': 'technical-media-only-v1'}


def dimensions_for(value: dict, pins: list[dict]) -> dict:
    """Report actual bytes; bitrate is a coarse file-size upper bound, not observed peak."""
    sizes = [row['pin']['bytes'] for row in value['windows']]
    start, end = value['spec']['frameRange']
    rate = Fraction(value['spec']['canvas']['frameRate'])
    return {'frames': end - start, 'windows': len(sizes), 'pictureBytes': sum(sizes),
            'peakBitrate': math.ceil(max(sizes) * 8 * rate),
            'masterBytes': value['audio']['master']['bytes'],
            'referenceBytes': value['audio']['reference']['bytes'],
            'pinnedInputBytes': sum(row['bytes'] for row in pins), 'proofFiles': len(pins)}


def match_reference(reference: dict | None, inputs: list[dict], result: dict) -> bool:
    """Compare actual same-input final bytes to a cold original serial observation."""
    if reference is None:
        return False
    original = read_inspection(reference, require_owner_digest=True)
    require(original.get('kind') == 'native-long-review-package-technical-result'
            and original['inputPins'] == inputs, 'Calibration reference inputs differ')
    before = original['mediaProof']
    require(pin(Path(before['media']['path']))['sha256'] == before['media']['sha256'],
            'Calibration reference output changed')
    require(before['media']['sha256'] == result['media']['sha256']
            and before['audio']['pcmSha256'] == result['audio']['pcmSha256']
            and before['media']['audioClock'] == result['media']['audioClock'],
            'Generated package differs from serial reference')
    return True


def measure(request: dict, root: Path) -> dict:
    """Measure shared media work honestly; unsupported production work remains listed."""
    require(type(request.get('measurementId')) is str and 0 < len(request['measurementId']) <= 96,
            'Calibration measurement lacks a bounded original run identity')
    prepared = read_inspection(request['preparation'], require_owner_digest=True)
    require(prepared.get('kind') == 'native-long-review-package-technical-preparation',
            'Calibration inputs lack real preparation owner')
    fixture = prepared['fixture']
    require(pin(Path(fixture['path'])) == fixture, 'Technical fixture changed after preparation')
    file = Path(fixture['path'])
    inputs = read_fixture(file, request['tools'])
    original = retained_pins(file.parent)
    require(original == prepared['outputPins'], 'Prepared media changed before measurement')
    directory = root / 'package'
    directory.mkdir()
    result = derive_media(inputs, directory)
    matched = match_reference(request.get('reference'), original, result)
    require(retained_pins(file.parent) == original, 'Technical inputs changed during measurement')
    value = bound_json(file)
    outputs = [pin(path) for path in sorted(directory.iterdir()) if path.is_file()]
    contract = contract_for(value, root)
    return {'status': STATUS, 'kind': 'native-long-review-package-technical-result', 'measurementId': request['measurementId'],
            'unit': 'build-and-seal', 'contract': contract,
            'dimensions': dimensions_for(value, original), 'inputPins': original, 'outputPins': outputs,
            'referenceMatched': matched, 'unsupportedOperations': list(UNSUPPORTED), 'mediaProof': result,
            'productionAuthority': False,
            'cacheObservation': unobserved_cache(original, contract['filesystem'], request['session']['host'])}


def execute(file: Path) -> None:
    """Require the existing live owner and session before any media or output writes."""
    request = require_worker(file, WORKER)
    require_session(request, file)
    require_provenance(request)
    operation = request.get('operation')
    require(operation in ('prepare', 'measure', 'proof-read'), 'Unknown technical calibration operation')
    result = (proof_read(request) if operation == 'proof-read' else
              prepare(request, file.parent) if operation == 'prepare' else measure(request, file.parent))
    require_session(request, file)
    require_provenance(request)
    write_new(file.parent / 'result.json', result)


def main() -> int:
    """Worker-only CLI: direct invocation without live binding always refuses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', required=True, type=Path)
    args = parser.parse_args()
    execute(args.worker)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
