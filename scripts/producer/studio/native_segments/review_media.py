"""Continuous derived playback from exact sealed Long picture and mastered audio.

No picture is rendered or re-encoded. Absolute program origins remain in the
receipt while the review container starts at zero. Technical checks do not grant
an editorial continuity judgment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_runtime import digest
from studio.native_segments.long_plan import identity
from studio.native_segments.manifest import Tools, check_bytes, check_compatible, check_coverage
from studio.native_segments.owners import current_window
from studio.native_stage_evidence import require, verify_pins

STATUS = 'native-long-review-package-complete'


@dataclass(frozen=True)
class PackageMediaInputs:
    """Verified media inputs; this value grants no production or owner authority."""

    request: dict
    scope: dict
    windows: list[dict]
    prepared_audio: dict


def source_state(request: dict, scope: dict) -> tuple[dict, list[dict], dict]:
    """Reopen every original window seal and the exact whole-program prepared master."""
    from studio.native_long_worker import read_long_audio
    verify_pins(request['pins'])
    values = [current_window(request, f"segment-picture-{row['index']}") for row in scope['windows']]
    prepared = read_long_audio(request)
    master = bound_json(Path(prepared['masterReceipt']), prepared['masterReceiptSha256'])
    require(digest(Path(master['output'])) == master['masterSha256'], 'review package master changed')
    rows = [{'frameRange': [value['window']['startFrame'], value['window']['endFrame']],
             'pictureSha256': value['piece']['sha256'],
             'pcmSha256': value['audio']['pcmSha256']} for value in values]
    assignments = [row for row in request['sectionChunks']['assignments'] if row['sectionId'] in scope['sectionIds']]
    ownership = [{key: row[key] for key in ('sectionId', 'generation', 'inputIdentity')}
                 for row in request['sectionProduction']['assignments'] if row['sectionId'] in scope['sectionIds']]
    signature = {'scope': {key: scope[key] for key in ('id', 'kind', 'frameRange', 'sectionIds')},
                 'assignments': ownership, 'canvas': request['revision']['canvas'], 'windows': rows,
                 'masterSha256': master['masterSha256'], 'referenceSha256': prepared['referenceSha256'],
                 'implementation': request.get('sectionImplementationPins'),
                 'audioProfile': request['audioProfile'],
                 'admissionIdentities': [row['admissionIdentity'] for row in assignments]}
    return signature, values, prepared


def local_pieces(values: list[dict], scope: dict) -> list[dict]:
    """Rebase verification metadata only; all sealed source bytes stay untouched."""
    start, end = scope['frameRange']
    pieces = [{**row['piece'], 'startFrame': row['piece']['startFrame'] - start,
               'endFrameExclusive': row['piece']['endFrameExclusive'] - start} for row in values]
    check_coverage(pieces, end - start)
    check_compatible(pieces, pieces[0]['stream'])
    check_bytes(pieces)
    return pieces


def package_picture(request: dict, scope: dict, values: list[dict], directory: Path) -> tuple[dict, dict]:
    """Join exact packets and prove compatible timestamps, complete decoding and payloads."""
    from guided_opening_picture import observe_picture
    from studio.native_segments.assemble import concat
    from studio.native_segments.verify import verify_assembly
    pieces = local_pieces(values, scope)
    path = directory / 'picture.mp4'
    tools = Tools.of(request)
    concat(pieces, path, tools, request['revision']['grid']['timescale'])
    check_bytes(pieces)
    proof = verify_assembly(path, pieces, tools, pieces[0]['stream'])
    canvas = request['revision']['canvas']
    actual = observe_picture(path, (canvas['frameRate'], scope['frameRange'][1] - scope['frameRange'][0],
                                   (canvas['width'], canvas['height'])),
                             {key: {'path': value} for key, value in request['tools'].items()})
    return actual, proof


def derive_media(inputs: PackageMediaInputs, directory: Path) -> dict:
    """Process verified media without manufacturing production or editorial evidence.

    Callers supply their own authority: production retains source_state, while
    technical calibration must validate generated inputs under a real owner.
    This helper never publishes a production candidate or a successful seal.
    """
    from guided_opening_mux import mux_ranges
    from studio.native_motion_previews import audio_excerpt
    from studio.native_short_delivery import correct_native_srgb, full_decode
    request, scope = inputs.request, inputs.scope
    picture, assembly = package_picture(request, scope, inputs.windows, directory)
    start, end = scope['frameRange']
    pcm = audio_excerpt(request, inputs.prepared_audio, {'startFrame': start, 'endFrame': end,
                        'canvas': request['revision']['canvas']}, directory / 'audio.wav')
    tools = {key: {'path': value} for key, value in request['tools'].items()}
    mux = mux_ranges(directory, {'ranges': {'core': picture, 'review': picture}},
                       {'core': pcm, 'review': pcm}, tools)['review']
    color = correct_native_srgb(Path(mux['path']), directory / 'review.mp4', pcm['samples'])
    full_decode(Path(color['output']))
    media = {**mux, 'path': color['output'], 'sha256': color['sha256'],
             'sizeBytes': Path(color['output']).stat().st_size, 'color': color,
             'fullAudioVideoDecodePassed': True}
    return {'picture': picture, 'assembly': assembly, 'audio': pcm, 'mux': mux, 'media': media}


def build_package(request: dict, scope: dict, directory: Path) -> dict:
    """Derive one continuous review-only AAC package under its existing admitted owner."""
    snapshot, values, prepared = source_state(request, scope)
    result = derive_media(PackageMediaInputs(request, scope, values, prepared), directory)
    require(source_state(request, scope)[0] == snapshot, 'review package inputs changed during derivation')
    return {'schemaVersion': 1, 'kind': 'native-long-review-package', 'status': STATUS,
            'scope': scope, 'inputIdentity': identity(snapshot), 'sources': snapshot,
            'request': str(Path(request['output']) / 'export-request.json'),
            'requestSha256': digest(Path(request['output']) / 'export-request.json'),
            **result,
            'additionalPictureEncodes': 0, 'audioCategory': 'derived-review-only',
            'humanApproved': False}


def execute_package(request: dict, phase: str) -> None:
    """Keep partial failed artifacts private; only the owner-bound result names a candidate."""
    import uuid
    from studio.native_segments.review_scopes import phase_scope
    scope = phase_scope(request, phase)
    root = Path(request['output'])
    require(not (root / f'{phase}.json').exists(), 'review package candidate already exists; retain its owner outcome')
    directory = root / f'{phase}-work-{uuid.uuid4().hex}'
    directory.mkdir()
    write_new(root / f'{phase}.json', build_package(request, scope, directory))
