"""Retain serial technical package measurements under the existing live pool session.

This harness writes measurements only. It never adopts a rate or qualifies
capacity. Unmeasured production operations remain explicit admission blockers.
"""
from __future__ import annotations

import argparse
import resource
import time
from pathlib import Path
from uuid import uuid4

from cut_preview_io import bound_json, write_new
from native_review_calibration_media import pin, run, validate_spec
from native_review_calibration_worker import WORKER
from native_review_proof_calibration import run_proof_read
from native_work_pool_policy import host_identity, policy_identity
from native_work_service_runs import FACTS
from native_work_service_cache import observation_facts
from native_work_session import open_session
from native_work_workload import engine_record
from studio.native_run_config import local_environment
from studio.native_stage_evidence import require
from studio.owned_inspection import read_inspection, run_inspection


def tool_records(root: Path) -> dict:
    """Pin actual tools and retain their reported versions without media processing."""
    tools, _environment = local_environment()
    records = {}
    for name in ('ffmpeg', 'ffprobe'):
        file = root / f'{name}-version.txt'
        file.write_bytes(run([tools[name], '-version']))
        records[name] = {'executable': pin(Path(tools[name])), 'version': pin(file)}
    return records


def recheck_pins(rows: list[dict]) -> None:
    """Cold-hash the actual frozen input/output inventory outside the child timer."""
    require(all(pin(Path(row['path'])) == row for row in rows), 'Calibration artifact changed')


def raw_usage() -> dict:
    """Observe actual reaped-child counters; block counts are not physical bytes."""
    own, children = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return {'parentCpuSeconds': own.ru_utime + own.ru_stime,
            'reapedChildCpuSeconds': children.ru_utime + children.ru_stime,
            'parentInputBlocks': own.ru_inblock, 'reapedChildInputBlocks': children.ru_inblock,
            'parentOutputBlocks': own.ru_oublock, 'reapedChildOutputBlocks': children.ru_oublock}


def cache_evidence(root: Path, facts: dict, owner: dict) -> dict:
    """Record unknown cache honestly; absent physical IO observation cannot become zero."""
    observations = observation_facts(facts['cacheObservation'], facts['inputPins'], owner['ownerIdentities'])
    observed = root / 'cache-observations.json'
    write_new(observed, observations)
    value = {key: observations[key] for key in ('method', 'regime', 'filesystem')}
    value.update(schemaVersion=1, kind='native-service-cache-evidence', observations=pin(observed))
    file = root / 'cache-evidence.json'
    write_new(file, value)
    return pin(file)


def measure_once(root: Path, request: dict, run_id: str) -> dict:
    """Enclose real preparation proofs, owner wait/work/cleanup and cold output readback."""
    started, monotonic = time.time(), time.monotonic()
    before = raw_usage()
    prepared = read_inspection(request['preparation'], require_owner_digest=True)
    recheck_pins(prepared['outputPins'])
    reference = run_inspection(WORKER, root, {**request, 'measurementId': run_id})
    result = read_inspection(reference, require_owner_digest=True)
    recheck_pins(result['inputPins'] + result['outputPins'])
    owner = bound_json(Path(reference['owner']), reference['ownerSha256'])
    finished, elapsed = time.time(), time.monotonic() - monotonic
    gross, queue = finished - started, owner['queue']['queueSeconds']
    require(abs(gross - elapsed) < .01 and gross >= queue, 'Measurement clock changed')
    timing = {'startedEpoch': started, 'finishedEpoch': finished, 'grossSeconds': gross,
              'queueSeconds': queue, 'serviceSeconds': gross - queue}
    value = {'schemaVersion': 1, 'kind': 'native-long-review-package-service-run', 'id': run_id,
             **{key: result[key] for key in FACTS}, 'preparation': request['preparation'],
             'inspection': reference, 'timing': timing,
             'cacheEvidence': cache_evidence(root, result, owner)}
    write_new(root / 'observed-resources.json', {'before': before, 'after': raw_usage(),
        'owner': reference, 'monotonicSeconds': elapsed, 'physicalReadBytes': None,
        'notes': 'Raw resource counters retained; no conversion of block counts to physical read bytes.'})
    file = root / 'measurement.json'
    write_new(file, value)
    return {'id': run_id, 'role': 'training', 'referenceId': request.get('referenceId'), 'measurement': pin(file)}


def serial_runs(root: Path, request: dict, count: int, rows: list[dict]) -> None:
    """Run one measured owner at a time and compare subsequent output to the first."""
    baseline = None
    for index in range(count):
        row = measure_once(root / f'measure-{index:02d}', {**request, 'operation': 'measure',
            'reference': baseline, 'referenceId': None if baseline is None else 'serial-00'}, f'serial-{index:02d}')
        rows.append(row)
        if baseline is None:
            baseline = bound_json(Path(row['measurement']['path']))['inspection']


def record_failure(root: Path, error: Exception) -> dict:
    """Retain failed ownership/diagnostics; never count failure as a measured success."""
    identifier = f'failure-{uuid4().hex}'
    diagnostic = root / f'{identifier}.json'
    write_new(diagnostic, {'kind': 'native-long-review-package-measurement-failure',
                           'type': type(error).__name__, 'message': str(error)})
    owners = sorted(root.rglob('inspection.render.json'), key=lambda path: path.stat().st_mtime_ns)
    latest = owners[-1] if owners else None
    owner = bound_json(latest) if latest else None
    terminal = owner and owner.get('completedAt') and owner.get('status') == 'failed'
    return {'id': identifier, 'owner': pin(latest) if terminal else None, 'diagnostic': pin(diagnostic)}


def finish_session(session: object, root: Path, manifest: dict) -> None:
    """Retain the complete manifest even if closing the existing session fails."""
    try:
        if session is not None:
            session.close()
    except Exception as error:
        manifest['failures'].append(record_failure(root, error))
        raise
    finally:
        write_new(root / 'measurements.json', manifest)


def calibrate(root: Path, spec: dict, count: int) -> dict:
    """Use one exact declared project/attempt session; adopt no host rate or capacity."""
    validate_spec(spec)
    require(type(count) is int and 1 <= count <= 8, 'Serial run count must be1..8')
    require(root.is_absolute() and root.parent.resolve(strict=True) == root.parent, 'Noncanonical calibration root')
    root.mkdir(mode=0o700)
    project, attempts = root / 'project', root / 'attempts'
    project.mkdir()
    attempts.mkdir()
    write_new(project / 'technical-project.json', {'kind': 'measurement-only', 'spec': spec})
    manifest = {'schemaVersion': 1, 'kind': 'native-long-review-package-measurements',
                'host': host_identity(), 'policy': policy_identity(), 'engine': engine_record(),
                'tools': tool_records(root), 'harness': pin(Path(__file__).resolve()), 'runs': [], 'failures': []}
    session = None
    try:
        session = open_session({'heavySlots': 2, 'audioSlots': 1},
                               [{'project': str(project), 'attempt': str(attempts)}], 7200)
        request = {'project': str(project), 'session': session.value, 'operation': 'prepare', 'spec': spec,
                   'provenance': {key: manifest[key] for key in ('engine', 'tools', 'harness')}}
        preparation = run_inspection(WORKER, attempts / 'prepare', request)
        serial_runs(attempts, {**request, 'preparation': preparation}, count, manifest['runs'])
        require(engine_record() == manifest['engine'], 'Engine changed during calibration')
    except Exception as error:
        manifest['failures'].append(record_failure(root, error))
        raise
    finally:
        finish_session(session, root, manifest)
    return manifest


def main() -> int:
    """Run explicitly bounded serial technical fixtures and retain all evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--runs', type=int, default=2)
    args = parser.parse_args()
    result = calibrate(args.output, bound_json(args.spec.resolve(strict=True)), args.runs)
    print(f"Retained {len(result['runs'])} serial technical measurements; no rate or capacity adopted.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
