"""The inputs speaker observations are measured from: frozen before the owner starts, re-observed by the worker.

The inputs are one admitted source per manifest, its utterance transcript, and the approved scripts. Scripts
come from one of two places:
- the batch's approvals (``--batch``);
- a file that names the same source and transcript identities (``--scripts``).

On either path, a script bound to another source or transcript is refused. Its word indexes would select
another transcript's times, and the sealed record would still carry the approved identities (REVIEW M2).
The model path comes from ``FACE_TRACK['yunet_model_path']`` only, and is re-checked by the worker.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from cut_preview_io import bound_json
from producer_config import FACE_TRACK
from studio.native_runtime import digest as file_digest
from studio.native_speaker_sampling import checked_scripts, observation_plan, source_clock, source_words
from studio.native_stage_evidence import require

if TYPE_CHECKING:
    from studio.native_speaker_observations import ObservationRequest

REQUEST_KIND = 'sniper-speaker-observations-request'
SOURCE_KEYS = ('id', 'path', 'sourceSha256', 'duration', 'frameRate', 'vfr', 'resolution', 'rotation', 'audio')
FILE_KEYS = frozenset({'sourceSha256', 'transcriptSha256', 'scripts'})


def single_source(manifest: dict, where: Path) -> dict:
    """The manifest's one admitted source, with its media path made absolute.

    Args:
        manifest: The parsed manifest.
        where: The manifest file; relative media paths resolve from its folder.

    Returns:
        The source row reduced to SOURCE_KEYS.

    Raises:
        ValueError: Not exactly one source, or a source without a path, sourceSha256 or positive duration.
    """
    sources = manifest.get('sources')
    if type(sources) is not list or len(sources) != 1 or not isinstance(sources[0], dict):
        raise ValueError(f'Speaker observations measure one source; {where} must list exactly one admitted source')
    row = sources[0]
    missing = [key for key in SOURCE_KEYS if key not in row]
    if missing or type(row['path']) is not str or type(row['sourceSha256']) is not str \
            or type(row['duration']) not in (int, float) or not row['duration'] > 0:
        raise ValueError(f'{where} source needs {list(SOURCE_KEYS)} with a path, a sourceSha256 and a positive duration')
    return {**{key: row[key] for key in SOURCE_KEYS}, 'path': str(where.parent / row['path'])}


def source_identity(manifest: Path, transcript: Path) -> dict:
    """``{source, transcript}``: the manifest source's sourceSha256 and the SHA-256 of the transcript bytes.

    Args:
        manifest: The admitted source manifest.
        transcript: The utterance transcript.

    Returns:
        The two identities an approved script is bound to (``approval_row``'s ``source`` and ``transcript``).
    """
    manifest = manifest.resolve(strict=True)
    return {'source': single_source(bound_json(manifest), manifest)['sourceSha256'],
            'transcript': file_digest(transcript.resolve(strict=True))}


def batch_scripts(batch: str, manifest: Path, transcript: Path) -> tuple[dict, ...]:
    """Every clip's current approved script in a batch, read from the live budget authority.

    Args:
        batch: The batch id.
        manifest: The admitted source manifest.
        transcript: The utterance transcript.

    Returns:
        ``{clipId, scriptIdentity, wordRanges}`` rows sorted by clip.

    Raises:
        ValueError: A clip without a current approval, or one on another source or transcript.
    """
    from studio import native_budget_store
    from studio.production.approvals import read_approval
    from studio.production.session import read_now
    native_budget_store.require_batch_id(batch)
    identity = source_identity(manifest, transcript)
    root = native_budget_store.default_root()
    record, _elapsed = read_now(root, batch)
    rows = []
    for clip in sorted(record['clips']):
        current = read_approval(root, batch, clip)['current']
        require(current is not None and all(current.get(key) == value for key, value in identity.items()),
                f'Clip {clip} of batch {batch} has no approved script on this source and transcript')
        rows.append({'clipId': clip, 'scriptIdentity': current['script'], 'wordRanges': current['wordRanges']})
    return tuple(rows)


def file_scripts(path: Path, manifest: Path, transcript: Path) -> tuple[dict, ...]:
    """Scripts from a ``{sourceSha256, transcriptSha256, scripts}`` file (tests and replays).

    Args:
        path: The scripts file.
        manifest: The admitted source manifest the scripts must be on.
        transcript: The transcript the scripts must be on.

    Returns:
        The file's script rows; ``checked_scripts`` validates them with the request.

    Raises:
        ValueError: Another shape, or a sourceSha256 or transcriptSha256 that differs from the inputs.
    """
    value = bound_json(path.resolve(strict=True))
    require(set(value) == FILE_KEYS and type(value['scripts']) is list,
            f'{path} must be {{"sourceSha256", "transcriptSha256", "scripts": [{{clipId, scriptIdentity, wordRanges}}]}}')
    identity = source_identity(manifest, transcript)
    require(value['sourceSha256'] == identity['source'] and value['transcriptSha256'] == identity['transcript'],
            f'{path} names another source or transcript than --manifest and --transcript')
    return tuple(value['scripts'])


def inspection_request(request: ObservationRequest) -> dict:
    """Validate every input and freeze the worker's request; no media is opened.

    Args:
        request: The measurement request.

    Returns:
        The request ``run_inspection`` writes (it adds ``tools`` and ``pins``).

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
    """Re-observe the manifest, transcript and model the request froze.

    Args:
        request: The frozen inspection request.

    Returns:
        ``{source, words}``, equal to what ``inspection_request`` saw.

    Raises:
        ValueError: A changed file, a model other than FACE_TRACK's, or a changed source row or scripts.
    """
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
