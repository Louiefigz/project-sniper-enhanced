"""Compare one concurrent qualification output with its serial reference, exactly.

Compared, and required equal:
- inputs: the export requests' input pins (every project file, source and
  implementation byte hash), so a difference cannot come from other code or sources;
- final status in both delivery receipts;
- checks.json after removing only run-specific values (attempt paths, elapsed time, the
  MP4 byte digest and output path); the decoded picture-slice digest, audio clock,
  packet checks and every audio check stay compared;
- decoded media: SHA-256 of the decoded video frames and of the decoded audio as 32-bit
  float PCM (ffmpeg hash muxer) for review.mp4, or for every moving-preview clip.
MP4 byte identity is reported (byteIdentical) but not required: container bytes may
differ between encodes that decode to identical frames and samples.
Reused work is reported separately: a job that took finished picture, audio donors,
verified or captured stages, restored preview sections or auto-resumed did not run its
full workload and cannot qualify concurrency. Two bindings every production final
carries are shared, not reused: the reviewed preview it follows (previewFrom: its
reviews pin that preview and discovery binds it) and an imported sealed audio stage.
They are allowed only when the serial reference carries exactly the same binding.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.pool_qualification_evidence import FULL_STATUSES, PREVIEW_STATUS

RUN_SPECIFIC = frozenset({'elapsedSeconds', 'output', 'audioReceipt', 'sha256'})
REUSE_FIELDS = ('pictureDonor', 'audioDonor', 'preparedMaster', 'verifyStage', 'captureStage')
SHARED_STAGE_PHASES = frozenset({'audio-stage-reused'})
DECODE_TIMEOUT_SECONDS = 900


def normalize(value: object, attempt: str) -> object:
    """Drop run-specific fields and replace the attempt path with a placeholder."""
    if isinstance(value, dict):
        return {key: normalize(item, attempt) for key, item in value.items() if key not in RUN_SPECIFIC}
    if isinstance(value, list):
        return [normalize(item, attempt) for item in value]
    return value.replace(attempt, '<attempt>') if isinstance(value, str) else value


def _hash(ffmpeg: str, media: Path, stream: list[str]) -> str:
    """Decode one stream fully and return the hash muxer's SHA-256 line."""
    result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i', str(media), *stream,
                             '-f', 'hash', '-hash', 'sha256', '-'],
                            capture_output=True, text=True, check=True, timeout=DECODE_TIMEOUT_SECONDS)
    line = result.stdout.strip()
    if not line.startswith('SHA256=') or result.stderr.strip():
        raise RuntimeError(f'Decode of {media} did not produce one clean hash')
    return line[len('SHA256='):]


def decoded(ffmpeg: str, media: Path) -> dict:
    """Decoded video and float-PCM audio digests plus the file's byte digest."""
    return {'video': _hash(ffmpeg, media, ['-map', '0:v:0']),
            'audio': _hash(ffmpeg, media, ['-map', '0:a:0', '-c:a', 'pcm_f32le']),
            'bytes': digest(media)}


def reused_work(attempt: Path) -> list[str]:
    """Everything the export took from another attempt instead of producing it."""
    request = bound_json(attempt / 'export-request.json')
    reused = [key for key in REUSE_FIELDS if request.get(key)]
    reused += ['previewSectionDonors'] if request.get('previewSectionDonors') else []
    selection = request.get('recoverySelection') or {}
    reused += [f"automatic recovery: {selection.get('reused')}"] if selection.get('mode') == 'automatic' else []
    delivery = bound_json(attempt / 'delivery.json')
    reused += [row['phase'] for row in delivery.get('stages', []) if str(row.get('phase', '')).endswith('-reused')
               and row['phase'] not in SHARED_STAGE_PHASES]
    return reused


def shared_bindings(attempt: Path) -> dict:
    """The reviewed-preview and audio-stage bindings a final shares with its reference."""
    request = bound_json(attempt / 'export-request.json')
    audio = request.get('audioStage') or {}
    imported = audio.get('mode') not in (None, 'attempt')
    return {'previewFrom': request.get('previewFrom'), 'audioStageMode': audio.get('mode'),
            'audioStageSeal': audio.get('seal') if imported else None,
            'audioStageSealSha256': audio.get('sealSha256') if imported else None}


def _media_pairs(candidate: Path, reference: Path, status: str) -> list[tuple[Path, Path]]:
    """review.mp4 for full exports; every clip, in order, for moving previews."""
    if status in FULL_STATUSES:
        return [(candidate / 'review.mp4', reference / 'review.mp4')]
    clips = [bound_json(root / 'motion-previews.json')['clips'] for root in (candidate, reference)]
    if len(clips[0]) != len(clips[1]):
        raise RuntimeError('Moving-preview clip counts differ from the reference')
    return [(Path(one['path']), Path(two['path'])) for one, two in zip(*clips)]


def _checks_problem(candidate: Path, reference: Path) -> str | None:
    """Compare every non-run-specific checks.json result."""
    ours, theirs = (normalize(bound_json(root / 'checks.json'), str(root)) for root in (candidate, reference))
    return None if ours == theirs else 'checks.json results differ from the serial reference'


def compare_job(candidate: Path, reference: Path) -> dict:
    """Return the comparison record; referenceMatched is True only with no problem."""
    requests = [bound_json(root / 'export-request.json') for root in (candidate, reference)]
    statuses = [bound_json(root / 'delivery.json').get('status') for root in (candidate, reference)]
    problems = []
    if requests[0]['pins'] != requests[1]['pins'] or requests[0]['project'] != requests[1]['project']:
        problems.append('reference was produced from different inputs or implementation')
    if shared_bindings(candidate) != shared_bindings(reference):
        problems.append('reviewed-preview or audio-stage binding differs from the serial reference')
    if statuses[0] != statuses[1] or statuses[0] not in FULL_STATUSES | {PREVIEW_STATUS}:
        problems.append(f'status {statuses[0]!r} does not match reference {statuses[1]!r}')
    if problems:
        return {'referenceMatched': False, 'problems': problems, 'media': []}
    if statuses[0] in FULL_STATUSES:
        problems += [problem for problem in [_checks_problem(candidate, reference)] if problem]
    ffmpeg = requests[0]['tools']['ffmpeg']
    media = []
    for ours, theirs in _media_pairs(candidate, reference, statuses[0]):
        pair = {'candidate': str(ours), 'reference': str(theirs),
                'candidateDecoded': decoded(ffmpeg, ours), 'referenceDecoded': decoded(ffmpeg, theirs)}
        pair['decodedEqual'] = all(pair['candidateDecoded'][key] == pair['referenceDecoded'][key]
                                   for key in ('video', 'audio'))
        pair['byteIdentical'] = pair['candidateDecoded']['bytes'] == pair['referenceDecoded']['bytes']
        media.append(pair)
    problems += [f"decoded media differs: {pair['candidate']}" for pair in media if not pair['decodedEqual']]
    return {'referenceMatched': not problems, 'problems': problems, 'media': media,
            'sharedBindings': shared_bindings(candidate),
            'byteIdentical': all(pair['byteIdentical'] for pair in media)}
