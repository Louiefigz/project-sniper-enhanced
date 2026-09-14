"""Source-derived native dialogue and encoded-picture checks, under one owner."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from audio.audio_mix_picture import observe_picture_source, packet_signature
from audio.channel_normalization import observe_channel_authority, system_program_request
from audio.channel_normalization_receipt import verify_channel_receipt
from audio.native_dialogue_delivery import NativeDialogueDelivery, finish_native_dialogue
from audio.dialogue_cleanup import DialogueSource
from audio.native_audio_finishing import finish_native_audio
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE, resolve_mastering_profile
from audio.program_audio_clock import exact_aac_audio_clock, exact_float_audio_clock
from edit.exact_timing import PositiveRational, ProjectClock
from studio.native_runtime import digest


def run(args: list[str]) -> str:
    """Bound each local stage; the parent also monitors its owned descendants."""
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=180).stdout


def clock(canvas: dict) -> ProjectClock:
    """Use the existing exact frame-to-sample policy shared with long form."""
    num, den = map(int, canvas['frameRate'].split('/'))
    return ProjectClock(PositiveRational(num, den), 48000)


def dialogue_reference(project: Path, canvas: dict, output: Path) -> Path:
    """Apply retained source cuts on the output clock, then pad the authored end hold."""
    timeline = clock(canvas)
    graph = []
    for index, (cut, segment) in enumerate(zip(canvas['cuts'], canvas['segments'], strict=True)):
        duration = (segment['endFrameExclusive'] - segment['startFrame']) / float(timeline.fps.fraction)
        samples = timeline.sample_at_frame(segment['endFrameExclusive']) - timeline.sample_at_frame(segment['startFrame'])
        graph.append(f"[0:a:0]atrim=start={cut['start']}:duration={duration},"
            'asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=flt:channel_layouts=stereo,'
            f'apad=whole_len={samples},atrim=end_sample={samples}[a{index}]')
    labels = ''.join(f'[a{index}]' for index in range(len(canvas['cuts'])))
    total = timeline.sample_at_frame(canvas['totalFrames'])
    graph.append(f'{labels}concat=n={len(canvas["cuts"])}:v=0:a=1,'
                 f'apad=whole_len={total},atrim=end_sample={total}[reference]')
    filters, destination = output / 'reference-filter.txt', output / 'reference.wav'
    filters.write_text(';\n'.join(graph))
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n',
         '-i', str(project / canvas['sourceFile']), '-filter_complex_script', str(filters),
         '-map', '[reference]', '-c:a', 'pcm_f32le', str(destination)])
    return destination


def finish_dialogue(request: dict, canvas: dict, audio_finishing: object = None) -> dict:
    """Share float mastering and AAC reuse; picture-only edits need no audio encode."""
    root, project = Path(request['output']), Path(request['project'])
    profile = resolve_mastering_profile(request.get('audioProfile', NATIVE_SHORT_MASTERING_PROFILE.identity))
    raw_reference = dialogue_reference(project, canvas, root)
    samples = clock(canvas).sample_at_frame(canvas['totalFrames'])
    reference = normalize_dialogue_reference(raw_reference, samples, root)
    source = DialogueSource(str(reference), samples, request['tools']['ffmpeg'], request['tools']['ffprobe'])
    reference = finish_native_audio(source, audio_finishing, root / 'dialogue-cleanup')
    picture = root / 'picture.mp4'
    donor = Path(request['audioDonor']) if request.get('audioDonor') else None
    return finish_native_dialogue(NativeDialogueDelivery(picture, reference,
        samples, root / 'audio',
        digest(picture), digest(reference), donor,
        profile=profile, review_sections=dialogue_review_sections(canvas)))


def dialogue_review_sections(canvas: dict) -> tuple[dict, ...]:
    """Use the executed frame-to-sample cut clock for dialogue level comparisons."""
    timeline = clock(canvas)
    return tuple({'start': timeline.sample_at_frame(row['startFrame']) / 48000,
                  'end': timeline.sample_at_frame(row['endFrameExclusive']) / 48000,
                  'label': f'dialogue cut {index + 1}'}
                 for index, row in enumerate(canvas['segments']))


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


def picture_payload(file: Path) -> str:
    """Hash H.264 picture slices independently of color metadata NAL units."""
    return run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(file), '-map', '0:v:0', '-an',
        '-c:v', 'copy', '-bsf:v', 'h264_mp4toannexb,filter_units=pass_types=1-5',
        '-f', 'hash', '-hash', 'sha256', '-']).strip()


def native_srgb_delivery(root: Path, audio: dict) -> dict:
    """Correct the measured native Chrome route only, preserving picture and AAC."""
    source, output = root / 'audio/candidate.mp4', root / 'review.mp4'
    if audio['status'] != 'audio-qualified' or digest(source) != audio['candidateSha256']:
        raise RuntimeError('Native audio candidate changed or did not qualify')
    samples = audio['audioClock']['presentedSamples']
    before = observe_picture_source(str(source), samples / 48000)
    stream = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_streams', '-of', 'json', str(source)]))['streams']
    if len(stream) != 1 or stream[0]['codec_name'] != 'h264' or stream[0].get('color_transfer') != 'bt709':
        raise RuntimeError('Unexpected native color route; no inferred correction')
    slices = picture_payload(source)
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
        '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-bsf:v',
        'h264_metadata=colour_primaries=1:transfer_characteristics=13:matrix_coefficients=1:video_full_range_flag=0',
        '-color_primaries', 'bt709', '-color_trc', 'iec61966-2-1', '-colorspace', 'bt709', '-color_range', 'tv',
        '-video_track_timescale', str(before.time_base.denominator), '-movie_timescale', '48000',
        '-movflags', '+faststart', str(output)])
    after = observe_picture_source(str(output), samples / 48000)
    if picture_payload(output) != slices or [row[0] for row in before.packets] != [row[0] for row in after.packets] \
            or packet_signature(str(source), 'a:0') != packet_signature(str(output), 'a:0'):
        raise RuntimeError('Native metadata correction changed picture or AAC payload/timing')
    return {'output': str(output), 'sha256': digest(output), 'pictureSliceSha256': slices,
            'aacPacketsIdentical': True, 'additionalPictureEncodes': 0, 'additionalAudioEncodes': 0,
            'audioClock': exact_aac_audio_clock(str(output), 'ffprobe', samples)}


def picture_metrics(reference: Path, actual: np.ndarray) -> dict:
    """Compare declared sRGB without fitted color, alignment or relaxed thresholds."""
    a, b = np.asarray(Image.open(reference).convert('RGB')), actual
    if a.shape != b.shape or a.shape != (1920, 1080, 3):
        raise RuntimeError('Native reference/output dimensions differ')
    delta = a.astype(np.float64) - b.astype(np.float64)
    mse, mae = float(np.mean(delta * delta)), float(np.mean(np.abs(delta)))
    psnr = float(10 * np.log10(255 * 255 / mse)) if mse else 100.0
    return {'mae': mae, 'psnrDb': psnr, 'passed': mae <= 2 and psnr >= 40}


def qualify_reverse_frames(native: dict) -> list[dict]:
    """Permit bounded browser edge antialiasing only after exact scene/source checks."""
    comparisons = []
    for row in (value for value in native['frames'] if value['repeat']):
        prior = next(value for value in native['frames'] if value['frame'] == row['frame'])
        files = [Path(value['path']) for value in (prior, row)]
        if any(digest(file) != value['sha256'] for file, value in zip(files, (prior, row))):
            raise RuntimeError('Reverse-seek image changed after capture')
        if prior['visualState'] != row['visualState'] or prior['payload'] != row['payload']:
            raise RuntimeError('Reverse-seek scene/source state changed')
        metrics = picture_metrics(files[0], np.asarray(Image.open(files[1]).convert('RGB')))
        passed = metrics['mae'] <= .01 and metrics['psnrDb'] >= 60
        comparisons.append({'frame': row['frame'], **metrics, 'passed': passed,
                            'byteIdentical': prior['sha256'] == row['sha256']})
    if not comparisons or not all(row['passed'] for row in comparisons):
        raise RuntimeError(f'Reverse-seek pixel stability failed: {comparisons}')
    return comparisons


def decode_selected_frames(candidate: Path, rows: list[dict], directory: Path) -> Path:
    """Decode all selected frames once, avoiding temporary PNG compression."""
    select = '+'.join(f'eq(n,{row["frame"]})' for row in rows)
    color = 'zscale=p=1:t=13:m=0:r=full:agamma=0,format=gbrpf32le,format=rgb24'
    raw = directory / 'selected.rgb'
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(candidate),
        '-map', '0:v:0', '-an', '-vf', f"select='{select}',{color}", '-fps_mode', 'passthrough',
        '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(raw)])
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(candidate),
         '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'])
    return raw


def compare_batch(raw: Path, rows: list[dict]) -> list[dict]:
    """Map one frame at a time without retaining the decoded batch in RAM."""
    comparisons = []
    frame_bytes = 1920 * 1080 * 3
    if raw.stat().st_size != len(rows) * frame_bytes:
        raise RuntimeError('Batched native RGB decode returned an incomplete frame inventory')
    for index, row in enumerate(rows):
        reference = Path(row['path'])
        if digest(reference) != row['sha256']:
            raise RuntimeError('Native picture reference changed')
        pixels = np.memmap(raw, dtype=np.uint8, mode='r', offset=index * frame_bytes, shape=(1920, 1080, 3))
        try:
            comparisons.append({'frame': row['frame'], **picture_metrics(reference, pixels)})
        finally:
            pixels._mmap.close()
    return comparisons


def qualify_picture(root: Path, canvas: dict) -> dict:
    """Decode a batch once and check the complete final audio/video stream."""
    candidate = root / 'review.mp4'
    native = json.loads((root / 'native-frames.json').read_text())
    if native['status'] != 'native-references-and-seek-states-pass':
        raise RuntimeError('Native capture/typography/seek checks failed')
    reverse = qualify_reverse_frames(native)
    rows = [row for row in native['frames'] if not row['repeat']]
    directory = root / 'picture-qc'
    directory.mkdir()
    duration = canvas['totalFrames'] / float(clock(canvas).fps.fraction)
    observed = observe_picture_source(str(candidate), duration)
    if len(observed.packets) != canvas['totalFrames']:
        raise RuntimeError('Encoded picture frame count differs from the strategy clock')
    raw = decode_selected_frames(candidate, rows, directory)
    comparisons = compare_batch(raw, rows)
    result = {'passed': all(row['passed'] for row in comparisons), 'candidateSha256': digest(candidate),
              'videoPackets': len(observed.packets), 'fullAudioVideoDecodePassed': True,
              'comparisons': comparisons, 'humanListeningApproved': False,
              'reverseSeekComparisons': reverse,
              'reverseSeekTolerance': {'maeMaximum': .01, 'psnrMinimumDb': 60,
                  'exactSceneStateAndSourceFramesRequired': True},
              'batchDecode': {'format': 'rgb24', 'frames': len(rows), 'sha256': digest(raw)}}
    (directory / 'result.json').write_text(json.dumps(result, indent=2))
    if not result['passed']:
        raise RuntimeError('Native encoded picture comparison failed; see picture-qc/result.json')
    raw.unlink()  # Derived scratch only; final MP4, native references and byte-bound measurements remain.
    return result
