"""Cold binding of service measurements to actual technical owner execution."""
from __future__ import annotations

import sys
from pathlib import Path

from native_work_service_pins import document, pin, require

WORKER = Path(__file__).with_name('native_review_calibration_worker.py').resolve()
HARNESS = WORKER.with_name('native_review_calibration.py')


def owner_request(reference: dict, owner: dict, provenance: dict, operation: str) -> dict:
    """Reject repackaged old owners even when the new manifest claims current code."""
    file = Path(reference['path']).parent / 'request.json'
    before = owner['additionalFilePinsBefore']
    request = document({'path': str(file), 'bytes': file.stat().st_size, 'sha256': before[str(file)]})
    require(request.get('provenance') == provenance and request.get('operation') == operation,
            'Owner request provenance or operation differs from service row')
    require(owner.get('args') == [sys.executable, '-B', str(WORKER), '--worker', str(file)],
            'Service measurement used another worker command')
    require(pin(provenance['harness']) == HARNESS, 'Service measurement used another harness')
    validate_pins(request, owner, provenance)
    return request


def validate_pins(request: dict, owner: dict, provenance: dict) -> None:
    """Require current declared implementation and exact required launch/tool pins."""
    pins = request.get('pins')
    require(type(pins) is dict and 0 < len(pins) <= 16384, 'Missing bounded owner implementation pins')
    required = {str(WORKER), str(HARNESS), str(Path(sys.executable).resolve(strict=True))}
    for name, value in provenance['tools'].items():
        executable = pin(value['executable'])
        pin(value['version'])
        require(request.get('tools', {}).get(name) == str(executable), 'Owner executable differs from service row')
        required.add(str(executable))
    require(required <= set(pins), 'Owner omitted required service implementation pins')
    before, after = owner['additionalFilePinsBefore'], owner['additionalFilePinsAfter']
    for filename, sha in pins.items():
        require(before.get(filename) == sha and after.get(filename) == sha, 'Owner implementation pin differs')
        file = Path(filename)
        pin({'path': filename, 'bytes': file.stat().st_size, 'sha256': sha})


def picture_identity(prepared: dict, measured: dict) -> tuple:
    """Compare generated picture content independently of filenames or shared audio."""
    pictures = prepared.get('picturePins')
    require(type(pictures) is list and 0 < len(pictures) <= 128, 'Preparation lacks generated picture inventory')
    require(all(item in prepared['outputPins'] and item in measured['inputPins'] for item in pictures),
            'Generated picture inventory differs from measured prepared inputs')
    require(len({item['path'] for item in pictures}) == len(pictures), 'Duplicate generated picture pin')
    for item in pictures:
        pin(item)
    return tuple(sorted((item['sha256'], item['bytes']) for item in pictures))
