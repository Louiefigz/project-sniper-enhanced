"""Source-cut float dialogue and channel normalization shared by native export phases."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from audio.channel_normalization import observe_channel_authority, system_program_request
from audio.channel_normalization_receipt import verify_channel_receipt
from audio.program_audio_clock import exact_float_audio_clock
from edit.exact_timing import PositiveRational, ProjectClock
from studio.native_runtime import digest
from studio.native_selected_sources import dialogue_inputs


def run(args: list[str], timeout: float = 180) -> str:
    """Bound each local stage; the parent also monitors its owned descendants."""
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout).stdout


def clock(canvas: dict) -> ProjectClock:
    """Use the existing exact frame-to-sample policy shared with long form."""
    num, den = map(int, canvas['frameRate'].split('/'))
    return ProjectClock(PositiveRational(num, den), 48000)


def dialogue_reference(project: Path, canvas: dict, output: Path) -> Path:
    """Apply retained source cuts on the output clock, then pad the authored end hold."""
    timeline = clock(canvas)
    inputs, offsets = dialogue_inputs(project, canvas)
    graph = []
    for index, (cut, segment) in enumerate(zip(canvas['cuts'], canvas['segments'], strict=True)):
        duration = (segment['endFrameExclusive'] - segment['startFrame']) / float(timeline.fps.fraction)
        samples = timeline.sample_at_frame(segment['endFrameExclusive']) - timeline.sample_at_frame(segment['startFrame'])
        source_index, source_start = offsets[index]
        graph.append(f"[{source_index}:a:0]atrim=start={source_start}:duration={duration},"
            'asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=flt:channel_layouts=stereo,'
            f'apad=whole_len={samples},atrim=end_sample={samples}[a{index}]')
    labels = ''.join(f'[a{index}]' for index in range(len(canvas['cuts'])))
    total = timeline.sample_at_frame(canvas['totalFrames'])
    graph.append(f'{labels}concat=n={len(canvas["cuts"])}:v=0:a=1,'
                 f'apad=whole_len={total},atrim=end_sample={total}[reference]')
    filters, destination = output / 'reference-filter.txt', output / 'reference.wav'
    filters.write_text(';\n'.join(graph))
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n',
         *inputs, '-filter_complex_script', str(filters),
         '-map', '[reference]', '-c:a', 'pcm_f32le', str(destination)])
    return destination


def normalize_dialogue_reference(source: Path, samples: int, directory: Path) -> Path:
    """Apply shared observed channel policy to the retained Short, before loudness mastering."""
    output = directory / 'reference-normalized.wav'
    record = {'schemaVersion': 1, 'scope': 'native-retained-dialogue-channel-normalization',
              'status': 'incomplete', 'inputPath': str(source), 'outputPath': str(output),
              'inputSha256Before': digest(source), 'samples': samples}
    try:
        authority = observe_channel_authority(system_program_request(str(source)))
        record['channelAuthority'] = verify_channel_receipt(authority.receipt)
        tools = authority.request.tools
        record['inputClock'] = exact_float_audio_clock(str(source), tools.ffprobe_path, samples)
        if authority.request.source_sha256 != record['inputSha256Before']:
            raise RuntimeError('Retained dialogue changed before channel normalization')
        channel_filter = authority.filter_for('stereo')
        chain = f'{channel_filter},aresample=48000,atrim=end_sample={samples},asetpts=PTS-STARTPTS'
        record['appliedFilter'] = chain
        authority.assert_stable()
        run([tools.ffmpeg_path, '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode', '-n',
             '-i', str(source), '-map', f"0:{authority.receipt['source']['selectedStreamIndex']}",
             '-af', chain, '-c:a', 'pcm_f32le', str(output)])
        authority.assert_stable()
        record['inputSha256After'] = digest(source)
        if record['inputSha256After'] != record['inputSha256Before']:
            raise RuntimeError('Retained dialogue changed during channel normalization')
        record.update(outputClock=exact_float_audio_clock(str(output), tools.ffprobe_path, samples),
                      outputSha256=digest(output), status='channel-policy-applied')
        return output
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        record.update(status='failed', error=str(error))
        raise
    finally:
        with (directory / 'channel-normalization.json').open('x') as handle:
            json.dump(record, handle, indent=2, allow_nan=False)
