"""Copy selected picture packets and extract bounded lossless working dialogue."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path

from cut_preview_io import file_hash, run_bounded
from edit.selected_sources_contract import MAX_KEYFRAME_LEAD_SECONDS
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, require

PICTURE_FIELDS = ('codec_name', 'width', 'height', 'pix_fmt', 'sample_aspect_ratio',
                  'color_range', 'color_space', 'color_transfer', 'color_primaries')


@dataclass(frozen=True)
class SectionJob:
    """One bounded section executed beneath the native process supervisor."""

    source: dict
    section: dict
    output: Path
    tools: dict[str, str]


def command(args: list[str], timeout: float = 180) -> str:
    """Keep output and execution bounded while retaining the parent's process group."""
    result = run_bounded(args, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Selected-source command failed: {result.stderr.decode(errors="replace")[-4000:]}')
    return result.stdout.decode('utf-8')


def decimal(value: Fraction) -> str:
    """Supply sub-nanosecond decimal precision to FFmpeg's seconds interface."""
    from decimal import Decimal, localcontext
    with localcontext() as context:
        context.prec = 30
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def media_info(file: Path, tools: dict) -> dict:
    """Read the original streams without decoding or altering their color/geometry."""
    info = json.loads(command([tools['ffprobe'], '-v', 'error', '-show_streams', '-show_format',
                               '-of', 'json', str(file)]))
    videos = [row for row in info['streams'] if row['codec_type'] == 'video']
    audios = [row for row in info['streams'] if row['codec_type'] == 'audio']
    require(len(videos) == 1 and len(audios) <= 1, 'selection requires one picture and at most one audio stream')
    video = videos[0]
    require(video['codec_name'] in {'h264', 'hevc'}, 'packet-copy selection supports H.264/HEVC')
    require(Fraction(video.get('start_time', '0')) == 0, 'selection requires a zero-based source picture clock')
    if audios:
        audio = audios[0]
        require(audio['sample_rate'] == '48000' and audio['channels'] in (1, 2)
                and Fraction(audio.get('start_time', '0')) == 0,
                'selected dialogue currently requires zero-based 48 kHz mono/stereo source audio')
    return {'video': video, 'audio': audios[0] if audios else None,
            'duration': str(Fraction(video.get('duration', info['format']['duration'])))}


def packets(file: Path, tools: dict, interval: tuple[Fraction, Fraction] | None = None) -> list[dict]:
    """Observe packet hashes with integer timestamps on their rational time base."""
    args = [tools['ffprobe'], '-v', 'error', '-select_streams', 'v:0']
    if interval:
        args += ['-read_intervals', f'{decimal(interval[0])}%{decimal(interval[1])}']
    args += ['-show_packets', '-show_data_hash', 'sha256', '-show_entries',
             'stream=time_base:packet=pts,dts,duration,data_hash,flags', '-of', 'json', str(file)]
    result = json.loads(command(args))
    time_base = Fraction(result['streams'][0]['time_base'])
    rows = result['packets']
    require(bool(rows), 'selected packet inventory is empty')
    return [{**row, 'ptsTime': Fraction(row['pts']) * time_base,
             'dtsTime': Fraction(row['dts']) * time_base,
             'durationTime': Fraction(row['duration']) * time_base} for row in rows]


def packet_origin(original: list[dict], selected: list[dict]) -> Fraction:
    """Prove one contiguous original packet subsequence and one exact time translation."""
    expected = [row['data_hash'] for row in selected]
    matches = [index for index, row in enumerate(original) if row['data_hash'] == expected[0]
               and [item['data_hash'] for item in original[index:index + len(expected)]] == expected]
    require(len(matches) == 1, 'selected picture is not a unique complete original packet subsequence')
    source = original[matches[0]:matches[0] + len(selected)]
    origin = source[0]['ptsTime'] - selected[0]['ptsTime']
    for before, after in zip(source, selected, strict=True):
        require(before['ptsTime'] - after['ptsTime'] == origin
                and before['dtsTime'] - after['dtsTime'] == origin
                and before['durationTime'] == after['durationTime'],
                'selected picture changed exact packet timing')
    require('K' in selected[0]['flags'], 'selected picture does not begin with a keyframe')
    return origin


def content_asset(file: Path, suffix: str) -> dict:
    """Name prepared bytes by content after complete creation and verification."""
    sha = file_hash(file, MAX_NATIVE_FILE_BYTES)
    target = file.with_name(f'{sha}.{suffix}')
    require(not target.exists(), 'prepared asset destination already exists')
    file.rename(target)
    return {'file': f'assets/{target.name}', 'path': str(target), 'sha256': sha,
            'bytes': target.stat().st_size}


def picture(job: SectionJob, info: dict) -> dict:
    """Retain original compressed picture and its actual keyframe lead-in."""
    start, end = Fraction(job.section['start']), Fraction(job.section['end'])
    source, output = Path(job.source['path']), job.output / 'picture.mp4'
    intermediate = job.output / 'unshifted.mp4'
    command([job.tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n',
             '-ss', decimal(start), '-i', str(source), '-t', decimal(end - start),
             '-map', '0:v:0', '-an', '-c:v', 'copy', '-map_metadata', '0',
             '-avoid_negative_ts', 'make_zero', '-movflags', '+faststart', str(intermediate)])
    zero_picture_clock(intermediate, output, job.tools)
    lead = max(Fraction(0), start - MAX_KEYFRAME_LEAD_SECONDS)
    original = packets(source, job.tools, (lead, end + MAX_KEYFRAME_LEAD_SECONDS))
    selected = packets(output, job.tools)
    require(min(row['ptsTime'] for row in selected) == 0, 'prepared picture does not start at zero')
    origin = packet_origin(original, selected)
    coverage_start = min(row['ptsTime'] for row in selected) + origin
    coverage_end = max(row['ptsTime'] + row['durationTime'] for row in selected) + origin
    require(coverage_start <= start and coverage_end >= end,
            'copied picture does not cover the requested source interval')
    require(start - coverage_start <= MAX_KEYFRAME_LEAD_SECONDS,
            'source GOP exceeds the bounded keyframe lead-in')
    verify_picture_metadata(output, job.tools, info['video'])
    command([job.tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-i', str(output),
             '-map', '0:v:0', '-an', '-f', 'null', '-'])
    intermediate.unlink()
    return {**content_asset(output, 'mp4'), 'sourceOrigin': str(origin),
            'sourceStart': str(coverage_start), 'sourceEnd': str(coverage_end),
            'packetCount': len(selected), 'originalPacketsIdentical': True,
            'packetTimingTranslatedExactly': True, 'fullDecodePassed': True,
            'additionalPictureEncodes': 0}


def zero_picture_clock(source: Path, output: Path, tools: dict) -> None:
    """Remove keyframe decode lead from presentation time without re-encoding pixels."""
    first = min(row['ptsTime'] for row in packets(source, tools))
    command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-copyts',
             '-i', str(source), '-map', '0:v:0', '-c:v', 'copy', '-map_metadata', '0',
             '-output_ts_offset', decimal(-first), '-avoid_negative_ts', 'disabled',
             '-movflags', '+faststart', str(output)])


def verify_picture_metadata(file: Path, tools: dict, before: dict) -> None:
    """Reject metadata changes that would alter interpretation of copied pixels."""
    result = json.loads(command([tools['ffprobe'], '-v', 'error', '-select_streams', 'v:0',
                                '-show_streams', '-of', 'json', str(file)]))['streams'][0]
    require(all(before.get(key) == result.get(key) for key in PICTURE_FIELDS),
            'selected picture changed codec, geometry or color metadata')
    rotation = lambda row: [item.get('rotation') for item in row.get('side_data_list', [])
                            if item.get('side_data_type') == 'Display Matrix']
    require(rotation(before) == rotation(result), 'selected picture changed rotation')


def dialogue(job: SectionJob, info: dict) -> dict | None:
    """Decode only the selected interval into lossless 48 kHz stereo working audio."""
    if not info['audio']:
        return None
    start, end = Fraction(job.section['start']), Fraction(job.section['end'])
    preseek = max(Fraction(0), start - 10)
    samples = -(-(end - start) * 48000 // 1)
    output = job.output / 'dialogue.wav'
    chain = (f'atrim=start={decimal(start - preseek)}:end={decimal(end - preseek)},'
             'asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=flt:channel_layouts=stereo')
    command([job.tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n',
             '-ss', decimal(preseek), '-i', job.source['path'], '-map', '0:a:0', '-vn',
             '-af', chain, '-c:a', 'pcm_f32le', str(output)])
    observed = json.loads(command([job.tools['ffprobe'], '-v', 'error', '-select_streams', 'a:0',
                                   '-show_streams', '-of', 'json', str(output)]))['streams'][0]
    actual = int(Fraction(observed['duration_ts']) * Fraction(observed['time_base']) * 48000)
    require(observed['codec_name'] == 'pcm_f32le' and observed['sample_rate'] == '48000'
            and observed['channels'] == 2 and abs(actual - samples) <= 1,
            'selected dialogue has an unexpected sample clock')
    return {**content_asset(output, 'wav'), 'sourceOrigin': str(start),
            'sourceStart': str(start), 'sourceEnd': str(start + Fraction(actual, 48000)),
            'samples': actual, 'sampleRate': 48000, 'channels': 2, 'codec': 'pcm_f32le'}


def prepare_section(job: SectionJob, info: dict) -> dict:
    """Create separate reusable picture/audio without baking graphics or new cuts."""
    job.output.mkdir()
    return {**job.section, 'video': picture(job, info), 'audio': dialogue(job, info)}
