"""Explicit, supervised six-second native long-form compatibility test."""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, correlation_lags

from cut_preview_io import bound_json, write_new
from edit.selected_sources import read_package
from edit.selected_sources_media import command, decimal
from studio.long_sources_project import check_project, hash_file
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import install_runtime
from studio.native_stage_evidence import require


def frame_hashes(request: dict, source: Path, start: Fraction, frames: int = 72) -> list[str]:
    """Compare every requested decoded frame without changing picture dimensions."""
    raw = command([request['tools']['ffmpeg'], '-nostdin', '-v', 'error', '-xerror',
        '-ss', decimal(start), '-i', str(source), '-map', '0:v:0', '-an',
        '-vf', 'fps=24000/1001', '-frames:v', str(frames), '-pix_fmt', 'rgb24', '-f', 'framemd5', '-'])
    return [line.split(',')[-1].strip() for line in raw.splitlines() if line and not line.startswith('#')]


def audio_samples(request: dict, source: Path, start: Fraction, target: Path) -> np.ndarray:
    """Read a selected three-second passage onto the original 48 kHz sample clock."""
    command([request['tools']['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n',
        '-ss', decimal(start), '-i', str(source), '-map', '0:a:0', '-vn', '-t', '3.003',
        '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le', str(target)])
    rate, values = wavfile.read(target)
    require(rate == 48000 and values.shape == (144144, 2), 'unexpected selected audio clock')
    return values


def compare_sources(request: dict, record: dict) -> tuple[list, np.ndarray]:
    """Use both independent source offsets; do not infer identity from metadata."""
    project, output = Path(request['project']), Path(request['output'])
    original = Path(record['inputs']['project'])
    rows, dialogue = [], []
    for index, mapping in enumerate(record['mappings']):
        before, after = original / mapping['originalFile'], project / mapping['preparedFile']
        start, local = Fraction(mapping['originalStart']), Fraction(mapping['preparedStart'])
        if mapping['kind'] == 'video':
            left, right = frame_hashes(request, before, start), frame_hashes(request, after, local)
            rows.append({'id': mapping['id'], 'kind': 'picture', 'frames': len(left),
                         'identical': len(left) == len(right) == 72 and left == right})
            continue
        left = audio_samples(request, before, start, output / f'original-{index}.wav')
        right = audio_samples(request, after, local, output / f'prepared-{index}.wav')
        rows.append({'id': mapping['id'], 'kind': 'audio', 'stereoSampleFrames': len(left),
                     'identical': np.array_equal(left, right)})
        dialogue.append(left)
    return rows, np.concatenate(dialogue)


def baseline_reference(request: dict, expected: np.ndarray) -> np.ndarray:
    """Compare against the same native renderer operating on original source ranges."""
    output, ffmpeg = Path(request['output']), request['tools']['ffmpeg']
    command([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-n', '-i', request['baseline'],
             '-map', '0:a:0', '-c:a', 'pcm_f32le', str(output / 'baseline-audio.wav')])
    rate, values = wavfile.read(output / 'baseline-audio.wav')
    require(rate == 48000 and values.shape[1] == 2 and len(values) >= len(expected), 'invalid AAC control clock')
    return values[:len(expected)]


def inspect_render(request: dict, expected: np.ndarray) -> dict:
    """Check the native output clock and AAC audio alignment across the join."""
    output, render, tools = Path(request['output']), request['render'], request['tools']
    info = json.loads(command([tools['ffprobe'], '-v', 'error', '-count_frames',
                              '-show_streams', '-of', 'json', render]))
    video = next(row for row in info['streams'] if row['codec_type'] == 'video')
    audio = next(row for row in info['streams'] if row['codec_type'] == 'audio')
    command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-i', render,
             '-map', '0:a:0', '-c:a', 'pcm_f32le', str(output / 'rendered-audio.wav')])
    rate, values = wavfile.read(output / 'rendered-audio.wav')
    require(rate == 48000 and values.ndim == 2 and values.shape[1] == 2
            and len(values) >= len(expected), 'native render shortened or changed the audio clock')
    control = baseline_reference(request, expected)
    channel = int(np.argmax(np.mean(expected ** 2, axis=0)))
    correlations = []
    for start in (0, 144144):
        left, right = control[start:start + 144144, channel], values[start:start + 144144, channel]
        cross = correlate(right, left, mode='full', method='fft')
        lag = int(correlation_lags(len(right), len(left))[np.argmax(cross)])
        correlations.append({'startSample': start, 'channel': channel, 'bestLagSamples': lag,
                             'correlation': float(np.corrcoef(left, right)[0, 1])})
    for index in (0, 71, 72, 143):
        command([tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-i', render,
                 '-vf', f'select=eq(n\\,{index})', '-frames:v', '1', str(output / f'frame-{index}.png')])
    return {'width': video['width'], 'height': video['height'], 'frames': int(video['nb_read_frames']),
            'fps': video['r_frame_rate'], 'duration': video['duration'],
            'audioRate': audio['sample_rate'], 'audioChannels': audio['channels'],
            'nativeBaselineAllStereoSamplesIdentical': np.array_equal(control, values[:len(expected)]),
            'nativeBaselineMaxAbsoluteDifference': float(np.max(np.abs(control - values[:len(expected)]))),
            'audioAlignment': correlations}


def worker(request_path: Path) -> None:
    """Run decode checks beneath the shared native process owner."""
    request = bound_json(request_path)
    record = check_project(Path(request['project']))
    sources, reference = compare_sources(request, record)
    rendered = inspect_render(request, reference)
    before = frame_hashes(request, Path(request['baseline']), Fraction(0), 144)
    after = frame_hashes(request, Path(request['render']), Fraction(0), 144)
    rendered['nativeBaselineAllDecodedFramesIdentical'] = len(before) == len(after) == 144 and before == after
    passed = all(row['identical'] for row in sources)
    passed = passed and (rendered['width'], rendered['height'], rendered['frames']) == (1920, 1080, 144)
    passed = passed and rendered['fps'] == '24000/1001' and Fraction(rendered['duration']) == Fraction('6.006')
    passed = passed and rendered['nativeBaselineAllStereoSamplesIdentical']
    passed = passed and rendered['nativeBaselineAllDecodedFramesIdentical']
    passed = passed and all(row['bestLagSamples'] == 0 and row['correlation'] > .999
                            for row in rendered['audioAlignment'])
    write_new(Path(request['output']) / 'compatibility.json',
              {'passed': passed, 'selectedSources': sources, 'nativeRender': rendered,
               'scope': 'Six-second landscape regression; not a full-episode qualification or speed benchmark'})
    require(passed, 'long-form compatibility failed; inspect compatibility.json')


def input_pins(project: Path, runtime: Path, tools: dict, record: dict) -> dict:
    """Bind test media, shared source evidence, code and the current native runtime."""
    _result, pins = read_package(record['package'])
    files = [project / name for name in (*record['files'], 'LONG-SOURCES.json')]
    files += [Path(value) for value in tools.values()]
    files += list(Path(__file__).parents[1].glob('studio/long_sources*.py'))
    files += [Path(__file__).resolve(), Path(sys.executable).resolve()]
    files += [file for file in (runtime / 'dist').iterdir() if file.is_file()]
    return {**pins, **record['inputs']['pins'], **{str(file): hash_file(file) for file in files}}


def supervise(operation: str, project: Path, output: Path, references: dict) -> bool:
    """Use the same resource, ownership and localhost restrictions as production."""
    project, output = project.resolve(strict=True), output.absolute()
    record = check_project(project)
    require(record['inputs']['canvas'] == {'data-width': '1920', 'data-height': '1080',
            'data-duration': '6.006', 'data-fps': '24000/1001'}, 'this test is limited to its six-second fixture')
    output.mkdir(mode=0o700)
    tools, environment = local_environment()
    runtime = install_runtime()
    cli, sandbox = runtime / 'dist/cli.js', Path(__file__).parents[1] / 'studio/native_localhost_only.sb'
    pins = input_pins(project, runtime, tools, record)
    request = {'project': str(project), 'output': str(output), 'tools': tools,
               **{name: str(file.resolve(strict=True)) if file else None for name, file in references.items()},
               'pins': pins}
    write_new(output / 'request.json', request)
    pins[str(output / 'request.json')] = hash_file(output / 'request.json')
    command_args = [sys.executable, str(Path(__file__).resolve()), 'worker', str(output / 'request.json')]
    result = output / 'compatibility.json'
    owner_project = Path(record['inputs']['project']) if operation == 'baseline' else project
    if operation in ('render', 'baseline'):
        result = output / 'review.mp4'
        command_args = [tools['node'], str(cli), 'render', str(owner_project), '--fps', '24000/1001',
            '--quality', 'high', '--crf', '15', '--workers', '1', '--low-memory-mode', '--no-browser-gpu',
            '--video-frame-format', 'png', '--no-best-effort', '--frames-cache-dir', str(output / 'cache'),
            '--output', str(result)]
    else:
        pins.update({request[name]: hash_file(Path(request[name])) for name in ('render', 'baseline')})
    settings = NativeRunConfig(project=owner_project, root=output, cli=cli, environment=environment,
        command=['/usr/bin/sandbox-exec', '-f', str(sandbox), *command_args],
        admission={'output': str(result), 'sdkSha256': hash_file(cli), 'sandboxSha256': hash_file(sandbox)},
        additional_pins=pins, success_status=f'long-test-{operation}-passed')
    return NativeRun(operation, settings).execute()


def main() -> None:
    """Keep this expensive real-media test out of the normal unit-test suite."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('render', 'baseline', 'compare', 'worker'))
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--render', type=Path)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    if args.operation == 'worker':
        worker(args.project)
        return
    require(args.output is not None and (args.operation != 'compare' or (args.render and args.baseline)),
            'test needs a new output directory and compare needs --render and --baseline')
    references = {'render': args.render, 'baseline': args.baseline}
    raise SystemExit(0 if supervise(args.operation, args.project, args.output, references) else 1)


if __name__ == '__main__':
    main()
