"""Owned, jailed synthetic source-clock diagnostic; never Long qualification.

Run through ./sniper with an unused directory under the configured workspace.
The real SDK decoder writes independent full and sparse caches for comparison.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import write_new
from studio.native_runtime import digest, install_runtime
from studio.owned_inspection import SANDBOX, require_worker, run_inspection

WORKER = Path(__file__).resolve()
HELPER = WORKER.with_suffix('.mjs')


def verify_files(pins: dict[str, str]) -> None:
    """Require unchanged diagnostic and runtime inputs before and after decoding."""
    for filename, expected in pins.items():
        if digest(Path(filename)) != expected:
            raise ValueError(f'Diagnostic input changed: {filename}')


def worker(file: Path) -> None:
    """Require the existing live owner and retain Sniper's media jail."""
    request = require_worker(file, WORKER)
    verify_files(request['diagnosticPins'])
    command = ['/usr/bin/sandbox-exec', '-f', str(SANDBOX), request['tools']['node'],
               str(HELPER), str(file)]
    subprocess.run(command, check=True, timeout=300)
    verify_files(request['diagnosticPins'])
    require_worker(file, WORKER)


def inspect(root: Path) -> None:
    """Admit one bounded technical experiment without editorial or delivery status."""
    root.mkdir(mode=0o700)
    project = root / 'project'
    project.mkdir()
    write_new(project / 'DIAGNOSTIC.json', {'synthetic': True, 'productionQualification': False})
    runtime = install_runtime()
    source = WORKER.parent.parent / 'studio'
    files = [HELPER, *source.rglob('*.mjs'), *runtime.joinpath('dist').glob('*')]
    pins = {str(path): digest(path) for path in files if path.is_file()}
    request = {'project': str(project), 'runtime': str(runtime), 'diagnosticPins': pins,
               'kind': 'synthetic-cfr-source-grid', 'productionQualification': False}
    reference = run_inspection(WORKER, root / 'inspection', request)
    write_new(root / 'diagnostic-reference.json', reference)
    print(json.dumps(reference))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(Path(sys.argv[2]).resolve(strict=True))
    elif len(sys.argv) == 2:
        inspect(Path(sys.argv[1]).resolve())
    else:
        raise SystemExit('usage: native_sparse_media_diagnostic.py UNUSED_WORKSPACE_DIRECTORY')
