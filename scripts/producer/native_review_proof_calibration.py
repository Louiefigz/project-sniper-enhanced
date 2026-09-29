"""Owned bounded proof-read experiments, separate from package service adoption.

Only ordered reads in the frozen plan are measured. Preparation validation,
owner launch/cleanup, parent readback and provenance hashing remain outside that
kernel interval. No row produced here is an adoptable package service-rate run.
"""
from __future__ import annotations

import time
from pathlib import Path

from cut_preview_io import digest, write_new
from native_proof_io import COLLECTOR, cache_pass, measure_read_pass, validate_inputs
from native_review_calibration_media import pin
from native_work_service_cache import logical_bytes, physical_bytes
from native_work_service_provenance import owner_request
from native_work_service_runs import inspection, validate_timing
from studio.native_stage_evidence import require
from studio.owned_inspection import STATUS, read_inspection, run_inspection

PLAN_KIND = 'native-technical-proof-read-plan'
RESULT_KIND = 'native-long-review-package-technical-proof-read-result'
UNSUPPORTED = ['production-source-authority-traversal', 'production-stage-seal-publication',
               'recurring-coordinator-proof-entrypoints', 'whole-worker-physical-read-observation',
               'ffmpeg-process-tree-physical-read-observation']


def validate_plan(plan: dict, prepared: dict) -> list[dict]:
    """Bind ordered, possibly repeated reads to exact owned preparation outputs."""
    require(type(plan) is dict and set(plan) == {'schemaVersion', 'kind', 'collector', 'reads'}
            and type(plan['schemaVersion']) is int and plan['schemaVersion'] == 1
            and plan['kind'] == PLAN_KIND and plan['collector'] == COLLECTOR,
            'Unknown technical proof-read plan')
    validate_inputs(plan['reads'])
    require(prepared.get('kind') == 'native-long-review-package-technical-preparation'
            and prepared.get('productionAuthority') is False, 'Proof reads lack actual technical preparation')
    outputs = prepared.get('outputPins')
    require(type(outputs) is list and 0 < len(outputs) <= 128
            and all(row in outputs for row in plan['reads']), 'Proof read escaped prepared output inventory')
    return list({row['path']: row for row in plan['reads']}.values())


def proof_read(request: dict) -> dict:
    """Run one no-child pass after preparation admission; retain unavailable raw facts."""
    identifier = request.get('measurementId')
    require(type(identifier) is str and 0 < len(identifier) <= 96, 'Proof measurement ID missing')
    prepared = read_inspection(request['preparation'], require_owner_digest=True)
    inputs = validate_plan(request['proofPlan'], prepared)
    observed = measure_read_pass(request['proofPlan']['reads'])
    return {'status': STATUS, 'kind': RESULT_KIND, 'measurementId': identifier,
            'preparation': request['preparation'], 'proofPlan': request['proofPlan'],
            'proofPlanSha256': digest(request['proofPlan']), 'inputPins': inputs,
            'rawObservation': observed, 'productionAuthority': False,
            'unsupportedOperations': list(UNSUPPORTED),
            'measurementScope': 'ordered-bounded-read-pass-only'}


def require_result(result: dict, request: dict) -> None:
    """Refuse relabeled results or omitted scope limitations before reading counters."""
    fields = {'status', 'kind', 'measurementId', 'preparation', 'proofPlan', 'proofPlanSha256',
              'inputPins', 'rawObservation', 'productionAuthority', 'unsupportedOperations', 'measurementScope'}
    require(set(result) == fields and result['status'] == STATUS and result['kind'] == RESULT_KIND
            and result['productionAuthority'] is False
            and result['unsupportedOperations'] == UNSUPPORTED
            and result['measurementScope'] == 'ordered-bounded-read-pass-only', 'Invalid technical proof result')
    require(result['measurementId'] == request.get('measurementId')
            and result['preparation'] == request.get('preparation')
            and result['proofPlan'] == request.get('proofPlan')
            and result['proofPlanSha256'] == digest(request['proofPlan']),
            'Proof result differs from original owner request')


def raw_pass(result: dict, owner: dict) -> dict:
    """Bind the measured interval to its sole real owned worker, never a process tree."""
    identities = owner.get('ownerIdentities')
    require(type(identities) is list and len(identities) == 1, 'Proof owner must have one exact process identity')
    raw = result['rawObservation']
    require(type(raw) is dict and raw.get('status') in {'measured', 'unavailable'},
            'Proof read failed; raw diagnostic cannot support successful observations')
    rows = raw.get('logicalReads')
    expected = result['proofPlan']['reads']
    if rows:
        require(type(rows) is list and len(rows) == len(expected), 'Proof read plan is incomplete')
        require(all(row == {'input': wanted, 'returnedBytes': wanted['bytes']}
                    for row, wanted in zip(rows, expected)), 'Measured reads differ from ordered plan')
    else:
        require(raw['status'] == 'unavailable', 'Measured pass omitted its actual reads')
    return owned_pass(raw, identities[0])


def owned_pass(raw: dict, identity: dict) -> dict:
    """Bridge the full existing owner row without dropping its recorded parent PID."""
    require(type(identity) is dict and set(identity) == {'pid', 'parent_pid', 'pgid', 'started'},
            'Proof owner identity has another shape')
    registry = {key: identity[key] for key in ('pid', 'pgid', 'started')}
    if raw['status'] == 'measured':
        require(all(raw[side].get('parentPid') == identity['parent_pid']
                    for side in ('identityBefore', 'identityAfter')), 'Measured worker parent differs from owner')
    observed = cache_pass(raw, registry)
    for sample in observed['kernelSamples'] or []:
        sample['identity'] = dict(identity)
    return observed


def read_proof_inspection(reference: dict, provenance: dict) -> dict:
    """Cold-check actual captured output, original request, preparation and pass arithmetic."""
    result, owner = inspection(reference)
    request = owner_request(reference, owner, provenance, 'proof-read')
    require_result(result, request)
    prepared, preparing_owner = inspection(request['preparation'])
    owner_request(request['preparation'], preparing_owner, provenance, 'prepare')
    inputs = validate_plan(request['proofPlan'], prepared)
    require(inputs == result['inputPins'], 'Proof working-set identity changed')
    require(all(pin(Path(row['path'])) == row for row in inputs), 'Proof input changed after measurement')
    observed = raw_pass(result, owner)
    return {'result': result, 'owner': owner, 'pass': observed,
            'logicalReadBytes': logical_bytes(observed['logicalReads'], inputs),
            'taskDiskReadBytes': physical_bytes(observed['kernelSamples'], owner['ownerIdentities'])}


def run_proof_read(root: Path, request: dict, run_id: str) -> dict:
    """Use the unchanged inspection owner; retain outer timing separately from kernel IO."""
    from native_review_calibration_worker import WORKER
    started, monotonic = time.time(), time.monotonic()
    prepared = read_inspection(request['preparation'], require_owner_digest=True)
    validate_plan(request['proofPlan'], prepared)
    reference = run_inspection(WORKER, root, {**request, 'output': str(root),
                                'operation': 'proof-read', 'measurementId': run_id})
    checked = read_proof_inspection(reference, request['provenance'])
    finished, elapsed = time.time(), time.monotonic() - monotonic
    gross, queue = finished - started, checked['owner']['queue']['queueSeconds']
    require(abs(gross - elapsed) < .01 and gross >= queue, 'Proof experiment clock changed')
    timing = {'startedEpoch': started, 'finishedEpoch': finished, 'grossSeconds': gross,
              'queueSeconds': queue, 'serviceSeconds': gross - queue}
    validate_timing(timing, checked['owner'])
    value = {'schemaVersion': 1, 'kind': 'native-technical-proof-read-experiment', 'id': run_id,
             'inspection': reference, 'preparation': request['preparation'],
             'proofPlanSha256': digest(request['proofPlan']), 'outerTiming': timing,
             'logicalReadBytes': checked['logicalReadBytes'], 'taskDiskReadBytes': checked['taskDiskReadBytes'],
             'unsupportedOperations': list(UNSUPPORTED), 'rateAdoptable': False,
             'timingScope': 'outer-validation-owner-cleanup-readback-not-the-kernel-read-interval'}
    file = root / 'proof-read-experiment.json'
    write_new(file, value)
    return pin(file)
