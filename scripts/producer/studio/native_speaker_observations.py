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
from cut_preview_io import bound_json, write_new
from producer_config import FACE_TRACK
from studio.native_runtime import digest as file_digest
from studio.native_speaker_faces import DETECTION_WIDTH, face_rows, measure_frames
from studio.native_speaker_sampling import (checked_scripts, decode_audio, observation_plan, retained_words,
                                            source_clock, source_words)
from studio.native_speaker_stereo import stereo_cue, stereo_rows
from studio.native_stage_evidence import require
from studio.owned_inspection import read_inspection, require_worker, run_inspection

__all__ = ['ObservationRequest', 'face_rows', 'observation_plan', 'observe', 'stereo_cue', 'stereo_rows', 'worker']

KIND = 'sniper-speaker-observations'
REQUEST_KIND = 'sniper-speaker-observations-request'
REFERENCE_NAME = 'SPEAKER-OBSERVATIONS.json'
DETECTOR = 'yunet-2023mar'
WORKER = Path(__file__).resolve()
SOURCE_KEYS = ('id', 'path', 'sourceSha256', 'duration', 'frameRate', 'vfr', 'resolution', 'rotation', 'audio')
CUE_LIMIT = ('Measurements are cues, not attribution; stills do not establish lip synchronization; '
             'nothing here is listening.')
LEVEL_LIMIT = ("Word levels are 120-3400 Hz signal energy over each word's sample span, not voice activity: they "
               "include any speech-band music or noise, and the louder channel need not be the speaker's side.")
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


def single_source(manifest: dict, where: Path) -> dict:
    """The manifest's one admitted source (its SOURCE_KEYS), with its media path made absolute."""
    sources = manifest.get('sources')
    if type(sources) is not list or len(sources) != 1 or not isinstance(sources[0], dict):
        raise ValueError(f'Speaker observations measure one source; {where} must list exactly one admitted source')
    row = sources[0]
    missing = [key for key in SOURCE_KEYS if key not in row]
    if missing or type(row['path']) is not str or type(row['sourceSha256']) is not str \
            or type(row['duration']) not in (int, float) or not row['duration'] > 0:
        raise ValueError(f'{where} source needs {list(SOURCE_KEYS)} with a path, a sourceSha256 and a positive duration')
    return {**{key: row[key] for key in SOURCE_KEYS}, 'path': str(where.parent / row['path'])}


def inspection_request(request: ObservationRequest) -> dict:
    """Validate every input and freeze the worker's request; no media is opened.

    Raises:
        ValueError: Not one source, a refused transcript or script, or sampling over its cap (E-S6).
    """
    manifest, transcript = request.manifest.resolve(strict=True), request.transcript.resolve(strict=True)
    source = single_source(bound_json(manifest), manifest)
    transcript_sha = file_digest(transcript)
    words = source_words(transcript, transcript_sha, source['duration'])
    scripts = checked_scripts(request.scripts, len(words))
    observation_plan(request, words, source_clock(source))
    model = Path(FACE_TRACK['yunet_model_path']).resolve(strict=True)
    return {'kind': REQUEST_KIND, 'project': str(manifest.parent), 'source': source, 'scripts': scripts,
            'manifest': {'path': str(manifest), 'sha256': file_digest(manifest)},
            'transcript': {'path': str(transcript), 'sha256': transcript_sha},
            'model': {'path': str(model), 'sha256': file_digest(model)},
            'scoreThreshold': float(FACE_TRACK['yunet_score_threshold'])}


def current_inputs(request: dict) -> dict:
    """Re-observe the manifest, transcript and model the request froze; returns ``{source, words}``."""
    for key in ('manifest', 'transcript', 'model'):
        require(file_digest(Path(request[key]['path'])) == request[key]['sha256'], f'Speaker observation {key} changed')
    require(Path(request['model']['path']) == Path(FACE_TRACK['yunet_model_path']).resolve(strict=True),
            'Speaker observation model is not the FACE_TRACK model')
    manifest = Path(request['manifest']['path'])
    source = single_source(bound_json(manifest), manifest)
    require(source == request['source'], 'Speaker observation source row changed')
    words = source_words(Path(request['transcript']['path']), request['transcript']['sha256'], source['duration'])
    require(checked_scripts(request['scripts'], len(words)) == request['scripts'], 'Speaker observation scripts changed')
    return {'source': source, 'words': words}


def _pinned_decoders(tools: dict) -> None:
    """The shared frame reader runs ``ffmpeg``/``ffprobe`` from PATH; they must be the pinned tools."""
    for name in ('ffmpeg', 'ffprobe'):
        found = shutil.which(name)
        require(found is not None and Path(found).resolve() == Path(tools[name]).resolve(),
                f'The frame reader would run another {name} than the pinned {tools[name]}')


def build_record(request: dict, source: dict, rate: Fraction, measured: dict) -> dict:
    """The sealed measurement record (P2-06 record keys; P2-07 reads ``source`` and ``scripts``)."""
    limits = [CUE_LIMIT, LEVEL_LIMIT, FACE_LIMIT] + ([measured['stereoLimit']] if measured['stereoLimit'] else [])
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


def _measure(request: dict, inputs: dict, root: Path) -> dict:
    """Decode the audio and the sampled frames once each, then build the record."""
    source, words = inputs['source'], inputs['words']
    rate = source_clock(source)
    _pinned_decoders(request['tools'])
    require(file_digest(Path(source['path'])) == source['sourceSha256'], 'Speaker observation source bytes changed')
    _progress('speaker-source')
    samples = decode_audio(source, request['tools']['ffmpeg'])
    measured = {'words': stereo_rows(samples, retained_words(request['scripts'], words), SAMPLE_RATE),
                'stereoLimit': stereo_cue(samples, SAMPLE_RATE)}
    audio = {'sampleRate': SAMPLE_RATE, 'channels': int(samples.shape[1])}
    _progress('speaker-audio')
    planned = ObservationRequest(Path(request['manifest']['path']), Path(request['transcript']['path']),
                                 tuple(request['scripts']), root)
    sampling = observation_plan(planned, words, rate)
    faces, sheets, decode = measure_frames(request, source, sampling, root)
    _progress('speaker-sheets')
    measured.update(faces=faces, sheets=sheets, sampling={**sampling, 'audio': audio, 'decode': decode})
    return build_record(request, source, rate, measured)


def worker(file: Path) -> None:
    """Measure only under the live inspection owner; a detached or changed request is refused first."""
    request = require_worker(file, WORKER)
    inputs = current_inputs(request)
    record = _measure(request, inputs, file.parent)
    require(current_inputs(request) == inputs, 'Speaker observation inputs changed during measurement')
    require_worker(file, WORKER)
    write_new(file.parent / 'result.json', record)


def observe(request: ObservationRequest) -> dict:
    """Measure once under ``run_inspection`` and publish the reference as ``SPEAKER-OBSERVATIONS.json``.

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


def batch_scripts(batch: str, manifest: Path, transcript: Path) -> tuple[dict, ...]:
    """Every clip's current approved script in a batch; each must be on this source and transcript."""
    from studio import native_budget_store
    from studio.production.approvals import read_approval
    from studio.production.session import read_now
    native_budget_store.require_batch_id(batch)
    source = single_source(bound_json(manifest.resolve(strict=True)), manifest.resolve(strict=True))
    identity = {'source': source['sourceSha256'], 'transcript': file_digest(transcript.resolve(strict=True))}
    root = native_budget_store.default_root()
    record, _elapsed = read_now(root, batch)
    rows = []
    for clip in sorted(record['clips']):
        current = read_approval(root, batch, clip)['current']
        require(current is not None and all(current.get(key) == value for key, value in identity.items()),
                f'Clip {clip} of batch {batch} has no approved script on this source and transcript')
        rows.append({'clipId': clip, 'scriptIdentity': current['script'], 'wordRanges': current['wordRanges']})
    return tuple(rows)


def file_scripts(path: Path) -> tuple[dict, ...]:
    """Scripts from a ``{"scripts": [...]}`` file (tests and replays); rows are checked by the request."""
    value = bound_json(path.resolve(strict=True))
    require(set(value) == {'scripts'} and type(value['scripts']) is list,
            f'{path} must be {{"scripts": [{{clipId, scriptIdentity, wordRanges}}, ...]}}')
    return tuple(value['scripts'])


def _parser() -> argparse.ArgumentParser:
    """The CLI's arguments; ``--worker`` is the owner's internal entry."""
    parser = argparse.ArgumentParser(description='Measure speaker observations once for one source.')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--transcript', type=Path)
    scripts = parser.add_mutually_exclusive_group()
    scripts.add_argument('--batch', help="read every clip's current approved script from this batch")
    scripts.add_argument('--scripts', type=Path, help='a JSON file {"scripts": [{clipId, scriptIdentity, wordRanges}]}')
    parser.add_argument('--output', type=Path, help='a new directory')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the worker, or measure one source and print the published reference as one JSON line."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.worker:
        worker(args.worker)
        return 0
    if not (args.manifest and args.transcript and args.output and (args.batch or args.scripts)):
        parser.error('--manifest, --transcript, --output and one of --batch or --scripts are required')
    scripts = batch_scripts(args.batch, args.manifest, args.transcript) if args.batch else file_scripts(args.scripts)
    reference = observe(ObservationRequest(args.manifest, args.transcript, scripts, args.output.absolute()))
    print(json.dumps(reference, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
