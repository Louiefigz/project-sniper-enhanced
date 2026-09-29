"""Bind a sealed audio stage to a native Short export and import its exact bytes.

The exporter selects a stage by audio-input identity among bounded sibling
directories (standalone stages and stages prepared inside earlier attempts) and
the project's immutable attempt history, or by an explicit ``--audio-stage``. With none, the export prepares its own stage
inside the attempt before capture. Import copies the sealed premaster into the
attempt and reuses the sealed float master through the existing prepared-master
reader, so the 'inside the attempt' rule, preview excerpts and every final
AAC/AV gate stay unchanged. No cleanup or mastering DSP runs again; bounded AAC
true-peak correction during final delivery remains available.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from audio.mastering_profile import resolve_mastering_profile
from audio.native_master_preparation import NativeMasterPreparation, prepare_native_master
from cut_preview_io import bound_json, write_new
from studio.native_audio_contract import audio_input_contract, audio_input_identity
from studio.native_audio_seal import SEAL_NAME, discover_stage, read_sealed_stage
from studio.native_export_history import known_attempts, lineage_attempts
from studio.native_runtime import digest
from studio.native_short_dialogue import clock
from studio.native_short_picture_reuse import copy_picture
from studio.native_stage_evidence import require

IMPORT_DIRECTORY = 'audio-stage-import'


def audio_stage_options(parser: argparse.ArgumentParser) -> None:
    """Expose explicit stage selection; discovery by identity is the default."""
    parser.add_argument('--audio-stage', type=Path,
                        help='Import this sealed audio stage directory; its audio-input identity must match')


def current_identity(request: dict) -> str:
    """Recompute the project's audio-input identity with the request's tools and profile."""
    contract = audio_input_contract(Path(request['project']), request['audioProfile'], request['tools'])
    return audio_input_identity(contract)


def explicit_stage(directory: Path, identity: str) -> tuple[Path, dict]:
    """Admit an operator-selected stage only when it matches exactly and is current."""
    seal = directory.resolve(strict=True) / SEAL_NAME
    return seal, read_sealed_stage(seal, identity)


def bind_audio_stage(request: dict, explicit: Path | None) -> dict:
    """Record which sealed audio this attempt imports, before its request is published.

    Args:
        request: The unpublished native Short export request.
        explicit: Operator-selected stage directory, or None to discover by identity.

    Returns:
        The request with an ``audioStage`` binding, unchanged for recovered audio.
    """
    reused = request.get('verifyStage') or request.get('audioDonor') or request.get('preparedMaster')
    if request.get('adapter') == 'native-long' or reused:
        require(explicit is None, '--audio-stage cannot replace resumed, donor or recovered audio')
        return request
    identity = current_identity(request)
    found = explicit_stage(explicit, identity) if explicit else discover_stage(
        Path(request['output']).parent, identity, tuple(set(known_attempts(request)) | set(lineage_attempts(request))))
    if found is None:
        seal = Path(request['output']) / 'audio-stage' / SEAL_NAME
        request['audioStage'] = {'mode': 'attempt', 'audioInputSha256': identity,
                                 'seal': str(seal), 'sealSha256': None}
        return request
    seal, record = found
    request['audioStage'] = {'mode': 'explicit' if explicit else 'discovered', 'audioInputSha256': identity,
                             'seal': str(seal), 'sealSha256': digest(seal)}
    request['pins'].update({str(seal): digest(seal),
                            record['masterReceipt']['path']: record['masterReceipt']['sha256']})
    return request


def bound_stage(request: dict) -> dict:
    """Re-verify the bound seal against the attempt's current audio inputs."""
    binding = request['audioStage']
    identity = current_identity(request)
    require(identity == binding['audioInputSha256'], 'audio inputs changed after the export bound its audio stage')
    seal = Path(binding['seal'])
    require(binding['sealSha256'] in (None, digest(seal)), 'bound audio stage seal changed')
    return read_sealed_stage(seal, identity)


def import_stage_audio(request: dict, canvas: dict, audio_finishing: object) -> dict:
    """Copy the sealed premaster and reuse the sealed float master inside this attempt.

    Args:
        request: The published export request carrying ``audioStage``.
        canvas: The project's canvas (clock and review sections).
        audio_finishing: The project's authored finishing object.

    Returns:
        The ``prepared-audio.json`` value consumed by previews and final delivery.
    """
    record = bound_stage(request)
    require(record['audioInput']['audioFinishing'] == audio_finishing, 'sealed audio finishing differs')
    root = Path(request['output'])
    directory = root / IMPORT_DIRECTORY
    directory.mkdir()
    premaster = directory / 'premaster.wav'
    copy_picture(Path(record['premaster']['path']), premaster, record['premaster']['sha256'])
    receipt = (Path(record['masterReceipt']['path']), record['masterReceipt']['sha256'])
    master = NativeMasterPreparation(premaster, record['premaster']['sha256'],
        clock(canvas).sample_at_frame(canvas['totalFrames']), root / 'audio-preparation',
        resolve_mastering_profile(request['audioProfile']), tuple(record['audioInput']['reviewSections']),
        prepared_master=receipt)
    path, sha = prepare_native_master(master, (request['tools']['ffmpeg'], request['tools']['ffprobe']))
    imported = bound_json(path, sha)
    require(imported.get('masterSha256') == record['master']['sha256']
            and imported.get('preparedMasterReceiptSha256') == receipt[1], 'imported master differs from its seal')
    evidence = {'mode': request['audioStage']['mode'], 'seal': request['audioStage']['seal'],
                'sealSha256': digest(Path(request['audioStage']['seal'])),
                'audioInputSha256': record['audioInputSha256'], 'premasterSha256': record['premaster']['sha256'],
                'masterSha256': record['master']['sha256'], 'importedMasterReceipt': str(path),
                'importedMasterReceiptSha256': sha, 'cleanupPassesRun': 0, 'masteringPassesRun': 0}
    write_new(directory / 'import.json', evidence)
    return {'kind': 'master', 'reference': str(premaster), 'referenceSha256': record['premaster']['sha256'],
            'masterReceipt': str(path), 'masterReceiptSha256': sha, 'audioFinishing': audio_finishing,
            'audioStage': evidence}
