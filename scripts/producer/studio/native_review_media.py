"""Shared packet-preserving AAC and exact encoded-frame review preparation."""
from __future__ import annotations

import json
from pathlib import Path

from audio.audio_mix_picture import packet_signature
from audio.program_audio_clock import exact_aac_audio_clock
from cut_preview_io import bound_json, run_bounded, write_new
from studio.native_runtime import digest
from studio.native_stage_evidence import require, verify_pins

STATUS = 'native-review-media-prepared'


def run(command: list[str]) -> bytes:
    """Bound each codec command under the outer native resource owner."""
    result = run_bounded(command, timeout=120)
    require(result.returncode == 0, result.stderr.decode(errors='replace')[-3000:])
    return result.stdout


def extract_audio(row: dict, tools: dict) -> dict:
    """Copy checked AAC packets and compare the complete presentation clock."""
    source, target = row['video'], str(Path(row['root']) / 'studio-dialogue.m4a')
    before = exact_aac_audio_clock(source, tools['ffprobe'], row['samples'])
    command = [tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-i', source,
               '-map', '0:a:0', '-vn', '-c:a', 'copy', '-map_metadata', '-1',
               '-movie_timescale', '48000', '-movflags', '+faststart', target]
    run(command)
    after = exact_aac_audio_clock(target, tools['ffprobe'], row['samples'])
    streams = json.loads(run([tools['ffprobe'], '-v', 'error', '-show_streams', '-of', 'json', target]))['streams']
    require(len(streams) == 1 and streams[0].get('codec_type') == 'audio', 'review AAC must contain one audio stream only')
    require(packet_signature(source, 'a:0') == packet_signature(target, 'a:0'), 'review AAC packets or timing changed')
    return {'path': target, 'sha256': digest(Path(target)), 'sourceClock': before, 'audioClock': after,
            'audioPacketsIdentical': True, 'additionalAudioEncodes': 0, 'additionalVideoEncodes': 0, 'command': command}


def extract_frames(row: dict, tools: dict) -> list[dict]:
    """Select exact frame indices in one decode, including rational frame clocks."""
    root = Path(row['root']) / 'encoded-frames'; root.mkdir()
    selection = '+'.join(f'eq(n,{point["frame"]})' for point in row['frames'])
    command = [tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-i', row['video'],
               '-an', '-vf', f"select='{selection}'", '-fps_mode', 'passthrough', '-q:v', '2',
               '-threads', '1', str(root / 'frame-%08d.jpg')]
    run(command)
    files = sorted(root.glob('frame-*.jpg'))
    require(len(files) == len(row['frames']), 'encoded review checkpoint inventory is incomplete')
    return [{**point, 'path': str(file), 'sha256': digest(file), 'command': command}
            for point, file in zip(row['frames'], files, strict=True)]


def worker(file: Path) -> None:
    """Prepare each composition sequentially; recognition is a separate diagnostic."""
    request = bound_json(file); verify_pins(request['pins'])
    results = []
    for row in request['compositions']:
        require(digest(Path(row['video'])) == row['videoSha256'], 'checked review MP4 changed')
        results.append({'id': row['id'], 'videoSha256': row['videoSha256'],
                        'audio': extract_audio(row, request['tools']), 'frames': extract_frames(row, request['tools'])})
    verify_pins(request['pins'])
    write_new(Path(request['root']) / 'media-preparation.json', {'status': STATUS, 'compositions': results,
              'subjectiveListeningApproved': False, 'encodedVisualApproval': False})
