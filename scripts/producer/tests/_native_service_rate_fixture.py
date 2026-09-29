"""TEST-only structural rate evidence with retained real cold-reader inputs.

Owner receipts and IO numbers are synthetic. They test validators and never
constitute measured performance, actual process execution or host qualification.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from native_work_pool_policy import policy_identity
from native_work_service_pins import identity
from native_work_service_schema import BOUND_DIMENSIONS
from native_work_service_provenance import WORKER, HARNESS
from native_work_service_cache import observation_facts, unobserved_cache
from studio.native_stage_evidence import STABLE_FIELDS

HOST = {'fixture': 'TEST-host'}
ENGINE = {'identity': 'e' * 64, 'files': 1}


def saved(root: Path, name: str, value: object) -> dict:
    """Write exact TEST bytes and return a current immutable pin."""
    file = root / name
    file.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True).encode()
    file.write_bytes(data)
    return {'path': str(file), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def owned(root: Path, name: str, result: dict, binding: tuple) -> dict:
    """Construct explicitly synthetic completed inspection proof consumed by real readers."""
    directory = root / name
    provenance, preparation, reference_id, reference = binding
    files = [WORKER, HARNESS, Path(sys.executable).resolve()]
    files.extend(Path(value['executable']['path']) for value in provenance['tools'].values())
    code = {str(file): hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    value = {'kind': 'TEST-ONLY', 'provenance': provenance, 'pins': code,
             'tools': {key: row['executable']['path'] for key, row in provenance['tools'].items()},
             'operation': 'prepare' if preparation is None else 'measure', 'preparation': preparation,
             'measurementId': None if preparation is None else name.split('/')[0],
             'referenceId': reference_id, 'reference': reference}
    request = saved(directory, 'request.json', value)
    output = saved(directory, 'result.json', {'status': 'ordinary-preview-inspection-complete', **result})
    pins = {**code, request['path']: request['sha256']}
    owner = {'args': [sys.executable, '-B', str(WORKER), '--worker', request['path']],
             'status': 'ordinary-preview-inspection-complete', 'exitCode': 0, 'pid': 100,
             'ownerIdentities': [{'pid': 100, 'pgid': 100, 'parent_pid': 99, 'started': 'TEST-only'}],
             'cleanup': {'verified': True, 'survivors': []}, 'output': output['path'], 'completedOutput': output,
             'additionalFilePinsBefore': pins, 'additionalFilePinsAfter': pins,
             'startedAt': '2026-01-01T00:00:00+00:00', 'nativeLaunchedAt': '2026-01-01T00:00:01+00:00',
             'completedAt': '2026-01-01T00:00:08+00:00', 'elapsedSeconds': 8.,
             'queue': {'queueSeconds': 1.}, **{key: True for key in STABLE_FIELDS}}
    proof = saved(directory, 'inspection.render.json', owner)
    return {'path': output['path'], 'sha256': output['sha256'],
            'owner': proof['path'], 'ownerSha256': proof['sha256']}


def contract() -> dict:
    """A serial TEST descriptor with explicit unknown-cache method, never a real claim."""
    return {'format': 'long', 'stage': 'review-package',
            'canvas': {'width': 1920, 'height': 1080, 'frameRate': '25/1'},
            'encoderContractSha256': 'a' * 64,
            'audio': {'sampleRate': 48000, 'channels': 2, 'sampleFormat': 'pcm_f32le'},
            'filesystem': {'type': 'TEST', 'volumeIdentity': 'TEST-volume'}, 'cacheRegime': 'unknown',
            'execution': {'ownedConcurrency': 1}, 'proofPlanVersion': 'TEST-read-plan-v1'}


def cache_pin(root: Path, value: dict, inputs: list[dict]) -> tuple[dict, dict]:
    """Retain TEST IO assertions so changed observation bytes are detected."""
    observation = unobserved_cache(inputs, value['filesystem'], HOST)
    process = {'pid': 100, 'pgid': 100, 'parent_pid': 99, 'started': 'TEST-only'}
    observation['readPasses'] = [{'logicalReads': [{'input': row, 'returnedBytes': row['bytes']} for row in inputs],
        'kernelSamples': [{'method': 'proc_pid_rusage-v2', 'identity': process,
            'before': {'processStart': 1, 'absoluteTime': 10, 'diskReadBytes': 100},
            'after': {'processStart': 1, 'absoluteTime': 20, 'diskReadBytes': 1000}}]}]
    observation['notes'] = 'TEST ONLY synthetic observations; not measured IO'
    facts = observation_facts(observation, inputs, [process])
    observations = saved(root, 'cache-observations.json', facts)
    evidence = saved(root, 'cache.json', {'schemaVersion': 1, 'kind': 'native-service-cache-evidence',
                 'method': facts['method'], 'regime': facts['regime'], 'filesystem': facts['filesystem'],
                 'observations': observations})
    return evidence, observation


def measured(root: Path, spec: tuple, facts: tuple) -> dict:
    """Retain one parent-written TEST interval around its completed synthetic owner."""
    name, role, reference, seconds = spec
    conditions, dimensions, cache, inputs, preparation, provenance = facts
    cache, observation = cache_pin(root / name, conditions, inputs)
    output = saved(root, f'{name}/media.bin', name.encode())
    common = {'unit': 'build-and-seal', 'contract': conditions, 'dimensions': dimensions,
              'inputPins': inputs, 'outputPins': [output], 'referenceMatched': reference is not None,
              'unsupportedOperations': []}
    compared = json.loads((root / reference / 'measurement.json').read_text())['inspection'] if reference else None
    owner = owned(root, f'{name}/owner', {'kind': 'native-long-review-package-technical-result',
                  **common, 'cacheObservation': observation, 'measurementId': name},
                  (provenance, preparation, reference, compared))
    start = 1767225600.
    value = {'schemaVersion': 1, 'kind': 'native-long-review-package-service-run', 'id': name,
             **common, 'preparation': preparation, 'inspection': owner, 'cacheEvidence': cache,
             'timing': {'startedEpoch': start, 'finishedEpoch': start + seconds + 1,
                        'grossSeconds': seconds + 1, 'queueSeconds': 1., 'serviceSeconds': seconds}}
    return {'id': name, 'role': role, 'referenceId': reference,
            'measurement': saved(root, f'{name}/measurement.json', value)}


def fixture(root: Path, held_bytes: bytes = b'TEST held-out') -> tuple[dict, tuple]:
    """Build a closed TEST record with independently varied held-out media."""
    tools = {name: {'executable': saved(root, name, f'TEST {name}'.encode()),
                    'version': saved(root, f'{name}.version', b'TEST version')} for name in ('ffmpeg', 'ffprobe')}
    harness = {'path': str(HARNESS), 'bytes': HARNESS.stat().st_size,
               'sha256': hashlib.sha256(HARNESS.read_bytes()).hexdigest()}
    provenance = {'engine': ENGINE, 'tools': tools, 'harness': harness}
    conditions = contract()
    dims = {key: 100 for key in BOUND_DIMENSIONS.values()}
    dims.update(frames=1500, windows=6)
    cache = None
    common = saved(root, 'shared-master.bin', b'TEST common audio')
    inputs = [saved(root, 'training.bin', b'TEST training'), common]
    held = [saved(root, 'held.bin', held_bytes), common]
    prep = owned(root, 'training-prep', {'kind': 'native-long-review-package-technical-preparation',
                 'outputPins': inputs, 'picturePins': inputs[:1]}, (provenance, None, None, None))
    held_prep = owned(root, 'held-prep', {'kind': 'native-long-review-package-technical-preparation',
                      'outputPins': held, 'picturePins': held[:1]}, (provenance, None, None, None))
    runs = [measured(root, ('training', 'training', None, 10.), (conditions, dims, cache, inputs, prep, provenance)),
            measured(root, ('held-reference', 'held-out', None, 9.), (conditions, dims, cache, held, held_prep, provenance)),
            measured(root, ('held', 'held-out', 'held-reference', 9.), (conditions, dims, cache, held, held_prep, provenance))]
    manifest = saved(root, 'manifest.json', {'schemaVersion': 1, 'kind': 'native-long-review-package-measurements',
                    'host': HOST, 'policy': policy_identity(), 'engine': ENGINE, 'tools': tools, 'harness': harness,
                    'runs': runs, 'failures': []})
    bounds = {name: dims[key] for name, key in BOUND_DIMENSIONS.items()}
    cell = {'id': 'TEST-cell', 'unit': 'build-and-seal', 'contract': conditions,
            'bounds': {**bounds, 'minFrames': 1500}, 'runIds': ['training'], 'heldOutRunIds': ['held'],
            'marginFactor': 1.25, 'ceilingSeconds': 12.5}
    row = {'id': 'TEST-rate', 'kind': 'native-long-review-package-service-v1', 'engine': ENGINE,
           'tools': tools, 'harness': harness, 'cells': [cell], 'measurement': {'manifest': manifest}, 'writtenAt': 'TEST'}
    caches = [json.loads(Path(row['measurement']['path']).read_text())['cacheEvidence'] for row in (runs[0], runs[2])]
    validation = saved(root, 'validation.json', {'schemaVersion': 1, 'kind': 'native-long-review-package-service-validation',
        'measurement': manifest, 'rateIdentity': identity({key: value for key, value in row.items() if key != 'writtenAt'}),
        'heldOutRunIds': ['held'], 'validator': {'recordedBy': 'TEST independent',
        'implementation': saved(root, 'validator.py', b'TEST different validator')}, 'cacheEvidence': caches,
        'failureIds': [], 'passed': True})
    row['adoption'] = {'validation': validation, 'recordedBy': 'TEST independent', 'recordedAt': 'TEST'}
    record = {'schemaVersion': 1, 'kind': 'sniper-native-service-rates', 'host': HOST, 'policy': policy_identity(),
              'serviceRates': [row], 'writtenAt': 'TEST'}
    return record, (ENGINE, {name: value['executable']['path'] for name, value in tools.items()})
