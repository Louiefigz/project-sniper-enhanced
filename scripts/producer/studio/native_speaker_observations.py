#!/usr/bin/env python3
"""Speaker observations measured once by code for one source, bound to its approved scripts (P2-06).

This module measures and never attributes. It records three things:
- per retained word, the speech-band (120-3400 Hz) left and right levels over the word's exact sample span;
- per sampled source frame, every face found at or above the FACE_TRACK score threshold, in source pixels;
- contact sheets of face crops, labelled with source seconds.

Who speaks, and how sure, is decided later in shared evidence (P2-07), with a recorded ``certainty`` and
``basis``. That vocabulary is defined once there (X53) and never here.

``observe`` runs ``worker`` once under ``owned_inspection.run_inspection``. The worker writes the record as
the inspection's owner-captured ``result.json``. ``observe`` then publishes the completed inspection
reference as ``<output>/SPEAKER-OBSERVATIONS.json``. P2-07 binds that reference and reads the record with
``read_inspection``. It compares ``source.sourceSha256`` with the manifest source, and ``scripts`` with its
coverage clips.

Sibling modules:
- ``native_speaker_inputs``: input freezing and script binding;
- ``native_speaker_sampling``: the pure frame plan and clock;
- ``native_speaker_media``: the ffprobe and audio-decode subprocesses;
- ``native_speaker_stereo``: audio levels;
- ``native_speaker_faces``: the picture pass and contact sheets.

CLI: native_speaker_observations.py --manifest M --transcript T (--batch B | --scripts F) --output DIR
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audit.dialogue_consistency import SAMPLE_RATE
from cut_preview_io import write_new
from studio.native_runtime import digest as file_digest
from studio.native_speaker_faces import DETECTION_WIDTH, face_rows, measure_frames
from studio.native_speaker_inputs import batch_scripts, current_inputs, file_scripts, inspection_request
from studio.native_speaker_media import decode_audio, probe_streams, stream_clock
from studio.native_speaker_sampling import clipped_limits, frame_plan, observation_plan, retained_words, source_clock
from studio.native_speaker_stereo import stereo_cue, stereo_limits, stereo_rows
from studio.native_stage_evidence import require
from studio.owned_inspection import read_inspection, require_worker, run_inspection

__all__ = ['ObservationRequest', 'face_rows', 'observation_plan', 'observe', 'stereo_cue', 'stereo_limits',
           'stereo_rows', 'worker']

KIND = 'sniper-speaker-observations'
REFERENCE_NAME = 'SPEAKER-OBSERVATIONS.json'
DETECTOR = 'yunet-2023mar'
WORKER = Path(__file__).resolve()
CUE_LIMIT = ('Measurements are cues, not attribution; stills do not establish lip synchronization; '
             'nothing here is listening.')
LEVEL_LIMIT = ("Word levels are 120-3400 Hz signal energy over each word's sample span, not voice activity: they "
               "include any speech-band music or noise, and the louder channel need not be the speaker's side; a "
               "channel level below -120 dBFS (digital silence) is recorded as null.")
FACE_LIMIT = (f'Faces are YuNet detections at or above the FACE_TRACK score threshold on frames scaled to at most '
              f'{DETECTION_WIDTH} px wide, mapped to source pixels; only sampled frames were measured, and a '
              'missed detection is not an absence.')


@dataclass(frozen=True)
class ObservationRequest:
    """One source's measurement request.

    Attributes:
        manifest: The admitted source manifest; it lists exactly one source.
        transcript: That source's utterance transcript, in the approvals' word index space.
        scripts: ``{clipId, scriptIdentity, wordRanges}`` rows (batch approvals, or a file in tests).
        output: A new directory for the inspection and the published reference.
    """

    manifest: Path
    transcript: Path
    scripts: tuple[dict, ...]
    output: Path


def _pinned_decoders(tools: dict) -> None:
    """Refuse unless ``ffmpeg``/``ffprobe`` on PATH are the pinned tools (the shared frame reader runs those).

    Args:
        tools: The inspection's resolved tools.

    Raises:
        ValueError: Either PATH tool is missing or resolves elsewhere.
    """
    for name in ('ffmpeg', 'ffprobe'):
        found = shutil.which(name)
        require(found is not None and Path(found).resolve() == Path(tools[name]).resolve(),
                f'The frame reader would run another {name} than the pinned {tools[name]}')


def build_record(request: dict, source: dict, rate: Fraction, measured: dict) -> dict:
    """The sealed measurement record, with exactly the P2-06 record keys.

    Args:
        request: The inspection request (``transcript``, ``scripts``, ``model``, ``tools``, ``scoreThreshold``).
        source: The manifest source row.
        rate: The source frame rate.
        measured: ``words``, ``faces``, ``sampling``, ``sheets``, ``stereoLimits`` and ``frameLimits``.

    Returns:
        The record. P2-07 binds ``source.sourceSha256``, ``source.transcriptSha256`` and ``scripts``.
    """
    limits = [CUE_LIMIT, LEVEL_LIMIT, FACE_LIMIT, *measured['stereoLimits'], *measured['frameLimits']]
    return {'schemaVersion': 1, 'kind': KIND,
            'source': {'id': source['id'], 'sourceSha256': source['sourceSha256'],
                       'transcriptSha256': request['transcript']['sha256']},
            'scripts': request['scripts'], 'rate': f'{rate.numerator}/{rate.denominator}',
            'words': measured['words'], 'faces': measured['faces'], 'sampling': measured['sampling'],
            'sheets': measured['sheets'],
            'tools': {'ffmpegSha256': file_digest(Path(request['tools']['ffmpeg'])),
                      'modelSha256': request['model']['sha256'], 'detector': DETECTOR,
                      'scoreThreshold': request['scoreThreshold']},
            'limits': limits}


def _progress(phase: str) -> None:
    """One advancing line for the inspection owner's idle watchdog (``native_workload.ProgressWatch``)."""
    print(f'SNIPER_PROGRESS {phase} 1', flush=True)


def _same_source(source: dict, when: str) -> None:
    """Re-hash the source media; its bytes must still be ``sourceSha256``."""
    require(file_digest(Path(source['path'])) == source['sourceSha256'], f'Speaker observation source bytes changed {when}')
    _progress(f'speaker-source-{when}')


def _measure(request: dict, inputs: dict, root: Path) -> dict:
    """Read the packet clock, decode the audio and the sampled frames once each, then build the record."""
    source, words = inputs['source'], inputs['words']
    rate = source_clock(source)
    _pinned_decoders(request['tools'])
    _same_source(source, 'before')
    frame_clock, clock = stream_clock(probe_streams(source['path'], request['tools']['ffprobe']), rate)
    samples = decode_audio(source, request['tools']['ffmpeg'])
    rows = stereo_rows(samples, retained_words(request['scripts'], words), SAMPLE_RATE)
    measured = {'words': rows, 'stereoLimits': stereo_limits(samples, rows, SAMPLE_RATE)}
    audio = {'sampleRate': SAMPLE_RATE, 'channels': int(samples.shape[1])}
    _progress('speaker-audio')
    planned = ObservationRequest(Path(request['manifest']['path']), Path(request['transcript']['path']),
                                 tuple(request['scripts']), root)
    plan = frame_plan(planned, words, frame_clock)
    sampling = {**plan, 'clock': clock}
    measured['frameLimits'] = clipped_limits(plan, frame_clock)
    faces, sheets, decode = measure_frames(request, source, sampling, root)
    _same_source(source, 'after')
    measured.update(faces=faces, sheets=sheets, sampling={**sampling, 'audio': audio, 'decode': decode})
    return build_record(request, source, rate, measured)


def worker(file: Path) -> None:
    """Measure only under the live inspection owner; a detached or changed request is refused first.

    Args:
        file: The owner's ``request.json``; the record is written beside it as ``result.json``.
    """
    request = require_worker(file, WORKER)
    inputs = current_inputs(request)
    record = _measure(request, inputs, file.parent)
    require(current_inputs(request) == inputs, 'Speaker observation inputs changed during measurement')
    require_worker(file, WORKER)
    write_new(file.parent / 'result.json', record)


def observe(request: ObservationRequest) -> dict:
    """Measure once under ``run_inspection`` and publish the reference as ``SPEAKER-OBSERVATIONS.json``.

    Args:
        request: The manifest, transcript, approved scripts and a new output directory.

    Returns:
        The completed inspection reference ``{path, sha256, owner, ownerSha256}``.

    Raises:
        ValueError: An input is refused before the owner starts, or the record does not describe the request.
        FileExistsError: ``request.output`` already exists.
    """
    body = inspection_request(request)
    output = request.output.parent.resolve(strict=True) / request.output.name
    output.mkdir(mode=0o700)
    reference = run_inspection(WORKER, output / 'inspection', body)
    record = read_inspection(reference, require_owner_digest=True)
    source = {'id': body['source']['id'], 'sourceSha256': body['source']['sourceSha256'],
              'transcriptSha256': body['transcript']['sha256']}
    require(record.get('kind') == KIND and record.get('source') == source and record.get('scripts') == body['scripts'],
            'Speaker observation record does not describe the requested source and scripts')
    write_new(output / REFERENCE_NAME, reference)
    return reference


def _parser() -> argparse.ArgumentParser:
    """The CLI's arguments; ``--worker`` is the owner's internal entry."""
    parser = argparse.ArgumentParser(description='Measure speaker observations once for one source.')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--transcript', type=Path)
    scripts = parser.add_mutually_exclusive_group()
    scripts.add_argument('--batch', help="read every clip's current approved script from this batch")
    scripts.add_argument('--scripts', type=Path,
                         help='a JSON file {"sourceSha256", "transcriptSha256", '
                              '"scripts": [{clipId, scriptIdentity, wordRanges}]}')
    parser.add_argument('--output', type=Path, help='a new directory')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the worker, or measure one source and print the published reference as one JSON line.

    Args:
        argv: The arguments (``sys.argv[1:]`` when None).

    Returns:
        0 on success; argument errors exit 2 through argparse.
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if args.worker:
        worker(args.worker)
        return 0
    if not (args.manifest and args.transcript and args.output and (args.batch or args.scripts)):
        parser.error('--manifest, --transcript, --output and one of --batch or --scripts are required')
    scripts = batch_scripts(args.batch, args.manifest, args.transcript) if args.batch \
        else file_scripts(args.scripts, args.manifest, args.transcript)
    reference = observe(ObservationRequest(args.manifest, args.transcript, scripts, args.output.absolute()))
    print(json.dumps(reference, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
