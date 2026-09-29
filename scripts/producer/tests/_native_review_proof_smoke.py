"""Explicit real-owner smoke, not an automatic test or production qualification.

Run only through the launcher with a new output directory and stable engine
sources. Uses the existing live qualification session without writing any rate
or capacity profile. A tiny generated fixture is technical test input only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cut_preview_io import bound_json, write_new
from native_proof_io import COLLECTOR
from native_review_calibration import tool_records, run_proof_read
from native_review_calibration_media import pin
from native_review_calibration_worker import WORKER
from native_review_proof_calibration import PLAN_KIND, read_proof_inspection
from native_work_session import open_session
from native_work_workload import engine_record
from studio.native_stage_evidence import require
from studio.owned_inspection import read_inspection, run_inspection


def setup(root: Path) -> tuple[dict, Path]:
    """Create generated-only input intent and actual current tool/engine provenance."""
    root.mkdir(mode=0o700)
    project, attempts = root / 'project', root / 'attempts'
    project.mkdir()
    attempts.mkdir()
    spec = {'canvas': {'width': 64, 'height': 36, 'frameRate': '25/1', 'totalFrames': 25},
            'frameRange': [0, 25], 'pattern': 'motion'}
    write_new(project / 'technical-project.json', {'kind': 'measurement-only', 'spec': spec})
    provenance = {'engine': engine_record(), 'tools': tool_records(root),
                  'harness': pin(WORKER.with_name('native_review_calibration.py'))}
    return {'project': str(project), 'spec': spec, 'provenance': provenance}, attempts


def run_smoke(root: Path) -> dict:
    """Exercise real preparation, owner-captured proof output and cold parent reader."""
    request, attempts = setup(root)
    session = open_session({'heavySlots': 2, 'audioSlots': 1},
                           [{'project': request['project'], 'attempt': str(attempts)}], 600)
    try:
        request['session'] = session.value
        preparation = run_inspection(WORKER, attempts / 'prepare',
                                     request | {'operation': 'prepare', 'output': str(attempts / 'prepare')})
        prepared = read_inspection(preparation, require_owner_digest=True)
        plan = {'schemaVersion': 1, 'kind': PLAN_KIND, 'collector': COLLECTOR,
                'reads': [prepared['fixture'], prepared['fixture']]}
        request.update(preparation=preparation, proofPlan=plan)
        experiment = run_proof_read(attempts / 'proof-read', request, 'owned-tiny-proof-read')
        value = bound_json(Path(experiment['path']), experiment['sha256'])
        checked = read_proof_inspection(value['inspection'], request['provenance'])
        require(engine_record() == request['provenance']['engine'], 'Engine changed during owned smoke')
        result = {'kind': 'technical-proof-read-owned-smoke', 'experiment': experiment,
                  'observationStatus': checked['result']['rawObservation']['status'],
                  'logicalReadBytes': checked['logicalReadBytes'],
                  'taskDiskReadBytes': checked['taskDiskReadBytes'], 'rateAdopted': False,
                  'unsupportedOperations': checked['result']['unsupportedOperations']}
        write_new(root / 'smoke-summary.json', result)
        return result
    finally:
        session.close()


def main() -> None:
    """Require an explicit new retained output root for this opt-in smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(run_smoke(args.output.absolute()), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
