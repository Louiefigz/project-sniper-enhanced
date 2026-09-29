"""Non-decodable TEST packages exercising real source, owner and immutable receipt readers.

All media and technical outcomes here are synthetic. No playback, codec or
editorial qualification is established by this fixture.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cut_preview_io import bound_json, write_new
from studio.native_export_history import attempt_reservation, register_attempt
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity
from studio.native_segments.review_media import STATUS, source_state
from studio.native_segments.review_package import read_package, receipt_pin, retained_package, seal_package, source_pins
from studio.native_segments.review_scopes import package_scopes, phase_for


def prepare_test_master(host: object) -> None:
    """Keep one unchanged fictional whole master across exact immutable fixture attempts."""
    root = host.budget.base
    master = root / 'TEST-prepared-master.wav'
    receipt = root / 'TEST-prepared-master.json'
    if not master.exists():
        master.write_bytes(b'TEST non-decodable whole-program master')
        write_new(receipt, {'output': str(master), 'masterSha256': digest(master)})
    target = Path(host.request['output']) / 'prepared-audio.json'
    if not target.exists():
        write_new(target, {'reference': str(master), 'referenceSha256': digest(master),
                           'masterReceipt': str(receipt), 'masterReceiptSha256': digest(receipt)})


def install_test_packages(test: object, host: object) -> None:
    """Extend synthetic window production before sealing, without patching cold validators."""
    original_phase, original_seal = host.fixture.write_phase, host.seal

    def write_phase(label: str, root: Path) -> None:
        """Include the production PCM digest in the non-decodable section fixture."""
        original_phase(label, root)
        if label.startswith('segment-picture-'):
            file = root / f'{label}.json'
            value = bound_json(file)
            value['audio']['pcmSha256'] = value['audio']['sha256']
            file.unlink()
            write_new(file, value)

    def seal(index: int) -> None:
        """Expose packages only when their complete window inventory is already sealed."""
        original_seal(index)
        prepare_test_master(host)
        with attempt_reservation(host.request):
            register_attempt(host.request)
        root = Path(host.request['output'])
        for scope in package_scopes(host.request):
            if all((root / f"segment-picture-{row['index']}-stage.json").exists()
                   or f"segment-picture-{row['index']}" in host.request['revision'].get('windowDonors', {})
                   for row in scope['windows']):
                seal_test_package(host, scope)

    test.enterContext(patch.object(host.fixture, 'write_phase', side_effect=write_phase))
    test.enterContext(patch.object(host, 'seal', side_effect=seal))
    prepare_test_master(host)


def media_file(directory: Path, name: str) -> dict:
    """Name digest-bound fictional media unmistakably as TEST evidence."""
    file = directory / name
    file.write_bytes(f'TEST non-decodable {name}'.encode())
    return {'path': str(file), 'sha256': digest(file)}


def seal_test_package(host: object, scope: dict) -> dict:
    """Create an explicitly fictional outcome, then run the actual package seal and cold reader."""
    request = host.request
    phase, root = phase_for(scope['id']), Path(request['output'])
    retained = retained_package(request, scope['id'])
    if retained:
        return retained
    file = root / f'{phase}.json'
    if file.exists():
        return receipt_pin(file)
    directory = root / f'{phase}-TEST'
    directory.mkdir()
    snapshot = source_state(request, scope)[0]
    picture, audio = media_file(directory, 'picture.mp4'), media_file(directory, 'audio.wav')
    mux, media = media_file(directory, 'mux.mp4'), media_file(directory, 'review.mp4')
    samples = (scope['frameRange'][1] - scope['frameRange'][0]) * 48000
    audio['samples'] = samples
    media.update(startFrame=scope['frameRange'][0], endFrameExclusive=scope['frameRange'][1],
                 audiblePathAacEncodes=1, fullAudioVideoDecodePassed=True,
                 color={'aacPacketsIdentical': True}, audioClock={'presentedSamples': samples})
    value = {'schemaVersion': 1, 'kind': 'native-long-review-package', 'status': STATUS, 'scope': scope,
             'inputIdentity': identity(snapshot), 'sources': snapshot,
             'request': str(root / 'export-request.json'), 'requestSha256': digest(root / 'export-request.json'),
             'picture': picture, 'assembly': {'piecePayloadsIdentical': True}, 'audio': audio, 'mux': mux,
             'media': media, 'additionalPictureEncodes': 0, 'audioCategory': 'derived-review-only', 'humanApproved': False}
    write_new(file, value)
    pins = {**request['pins'], **source_pins(request, scope), str(root / 'export-request.json'): value['requestSha256']}
    owner = host.fixture.owner_record(request, pins, STATUS, str(file))
    write_new(root / f'{phase}.render.json', owner)
    seal_package(SimpleNamespace(request=request, root=root, evidence={}), phase, phase)
    read_package(request, scope['id'], receipt_pin(file))
    return receipt_pin(file)
