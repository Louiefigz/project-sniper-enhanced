"""Generated, technical-only inputs for owned Long review-package measurements.

The caller must provide a live inspection owner. These files are not production
windows, mastered speech evidence, editorial reviews, or delivery artifacts.
"""
from __future__ import annotations

import json
import shutil
from fractions import Fraction
from pathlib import Path

from audio.program_audio_clock import exact_float_audio_clock
from cut_preview_io import bound_json, file_hash, run_bounded, write_new
from graphics.graphics_render import HYPERFRAMES_BIN
from studio.native_runtime import REPO
from studio.native_segments.long_plan import MAX_WINDOW_FRAMES
from studio.native_segments.manifest import Tools, describe_piece
from studio.native_segments.review_media import PackageMediaInputs, local_pieces
from studio.native_short_dialogue import clock
from studio.native_stage_evidence import require

KIND = 'native-long-review-package-technical-inputs'
ENCODER_MODULE = REPO / 'scripts/producer/studio/native_segments/render.mjs'
ENCODER_SCRIPT = """
const {nativeSegmentEncoderArgs,segmentEncoderContract}=await import(process.argv[1]);
const {encoderVersion}=await import(new URL('../native_short_batched_render.mjs',process.argv[1]));
const options=JSON.parse(process.argv[2]);
options.version=encoderVersion(process.argv[3]);
const args=nativeSegmentEncoderArgs(options);
process.stdout.write(JSON.stringify({args,contract:segmentEncoderContract(args)}));
"""


def validate_spec(spec: dict) -> None:
    """Bound generated work and preserve exact rational absolute frame origins."""
    require(isinstance(spec, dict) and set(spec) == {'canvas', 'frameRange', 'pattern'},
            'invalid technical fixture specification')
    canvas, bounds = spec['canvas'], spec['frameRange']
    require(isinstance(canvas, dict) and set(canvas) == {'width', 'height', 'frameRate', 'totalFrames'},
            'invalid technical fixture canvas')
    require(all(type(canvas[key]) is int and canvas[key] > 0 for key in ('width', 'height', 'totalFrames')),
            'invalid technical fixture dimensions')
    require(canvas['width'] <= 3840 and canvas['height'] <= 2160
            and canvas['width'] % 2 == canvas['height'] % 2 == 0, 'unsupported fixture geometry')
    rate = Fraction(canvas['frameRate'])
    require(canvas['frameRate'] == f'{rate.numerator}/{rate.denominator}' and 0 < rate <= 120,
            'fixture frame rate must be canonical')
    require(isinstance(bounds, list) and len(bounds) == 2 and all(type(n) is int for n in bounds)
            and 0 <= bounds[0] < bounds[1] <= canvas['totalFrames'], 'invalid fixture frame range')
    require((bounds[1] - bounds[0]) / rate <= 120 and canvas['totalFrames'] / rate <= 1800,
            'fixture exceeds bounded scope or master duration')
    require(spec['pattern'] in ('motion', 'texture'), 'unsupported fixture pattern')


def pin(file: Path) -> dict:
    """Reuse the bounded no-follow hash reader for every technical artifact."""
    sha = file_hash(file)
    return {'path': str(file), 'bytes': file.stat().st_size, 'sha256': sha}


def check_pin(value: dict, root: Path) -> Path:
    """Reject linked, changed, or escaped technical media before decoding."""
    require(isinstance(value, dict) and set(value) == {'path', 'bytes', 'sha256'}, 'invalid fixture pin')
    file = Path(value['path'])
    require(file.is_absolute() and file.resolve(strict=True) == file and file.is_relative_to(root),
            'fixture media escaped its retained directory')
    require(type(value['bytes']) is int and file.stat().st_size == value['bytes']
            and pin(file) == value, 'technical fixture bytes changed')
    return file


def run(command: list[str]) -> bytes:
    """Retain bounded tool diagnostics and fail without substituting another codec."""
    result = run_bounded(command, timeout=600)
    result.check_returncode()
    return result.stdout


def encoder_args(spec: dict, bounds: tuple[int, int], tools: dict, file: Path) -> dict:
    """Reuse the actual native encoder options, substituting generated input only."""
    canvas, rate = spec['canvas'], Fraction(spec['canvas']['frameRate'])
    options = {'fps': {'num': rate.numerator, 'den': rate.denominator},
               'framesDir': str(file.parent), 'output': str(file), 'startFrame': bounds[0],
               'frames': bounds[1] - bounds[0], 'timescale': rate.numerator}
    native = json.loads(run([tools['node'], '--input-type=module', '-e', ENCODER_SCRIPT,
                             ENCODER_MODULE.as_uri(), json.dumps(options), str(Path(HYPERFRAMES_BIN).parent.parent)]))
    require(native['args'][:6] == ['-framerate', str(rate.numerator) if rate.denominator == 1 else str(rate),
                                  '-start_number', str(bounds[0]), '-i', str(file.parent / 'frame_%06d.jpg')],
            'native encoder input prefix changed')
    source = f"testsrc2=size={canvas['width']}x{canvas['height']}:rate={canvas['frameRate']}"
    if spec['pattern'] == 'texture':
        source += ',noise=alls=24:allf=t+u:all_seed=17'
    source += ',format=rgb24'
    args = ['-nostdin', '-v', 'error', '-xerror', '-f', 'lavfi', '-i', source, *native['args'][6:]]
    return {'command': [tools['ffmpeg'], *args], 'nativeArgs': native['args'],
            'encoderContractSha256': native['contract'], 'inputSubstitution': 'generated-lavfi-rgb'}


def prepare_window(spec: dict, bounds: tuple[int, int], tools: dict, root: Path) -> dict:
    """Generate one closed native-compatible window with actual packet evidence."""
    file = root / f'window-{bounds[0]}-{bounds[1]}.mp4'
    encoding = encoder_args(spec, bounds, tools, file)
    run(encoding['command'])
    piece = describe_piece(file, bounds, Tools.of({'tools': tools}))
    return {'piece': piece, 'pin': pin(file), 'encoding': encoding}


def audio_command(spec: dict, tools: dict, master: Path) -> list[str]:
    """Describe the exact bounded signal generator for later cold verification."""
    samples = clock(spec['canvas']).sample_at_frame(spec['canvas']['totalFrames'])
    return [tools['ffmpeg'], '-nostdin', '-v', 'error', '-xerror', '-n', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=48000', '-af', f'atrim=end_sample={samples}',
            '-ac', '2', '-c:a', 'pcm_f32le', str(master)]


def prepare_audio(spec: dict, tools: dict, root: Path) -> dict:
    """Create exact float samples; this is a test signal, never mastered speech."""
    samples = clock(spec['canvas']).sample_at_frame(spec['canvas']['totalFrames'])
    master, reference = root / 'master.wav', root / 'reference.wav'
    command = audio_command(spec, tools, master)
    run(command)
    with reference.open('xb') as output, master.open('rb') as source:
        shutil.copyfileobj(source, output)
    facts = exact_float_audio_clock(str(master), tools['ffprobe'], samples)
    receipt = root / 'technical-master.json'
    write_new(receipt, {'kind': 'technical-signal-only', 'output': str(master), 'masterSha256': pin(master)['sha256']})
    return {'master': pin(master), 'reference': pin(reference), 'receipt': pin(receipt),
            'clock': facts, 'command': command}


def prepare_fixture(spec: dict, tools: dict, root: Path) -> dict:
    """Prepare actual generated media inside an already admitted inspection owner."""
    validate_spec(spec)
    start, end = spec['frameRange']
    points = list(range(start, end, MAX_WINDOW_FRAMES)) + [end]
    windows = [prepare_window(spec, pair, tools, root) for pair in zip(points, points[1:])]
    value = {'schemaVersion': 1, 'kind': KIND, 'spec': spec, 'windows': windows,
             'audio': prepare_audio(spec, tools, root), 'encoderModule': pin(ENCODER_MODULE),
             'tools': {name: pin(Path(tools[name])) for name in ('node', 'ffmpeg', 'ffprobe')},
             'filesystemCache': 'unknown', 'productionAuthority': False}
    write_new(root / 'technical-inputs.json', value)
    return value


def read_fixture(file: Path, tools: dict) -> PackageMediaInputs:
    """Cold-check generated bytes/streams/clocks without creating production seals."""
    value, root = bound_json(file), file.parent
    require(set(value) == {'schemaVersion', 'kind', 'spec', 'windows', 'audio', 'encoderModule', 'tools',
                          'filesystemCache', 'productionAuthority'} and type(value['schemaVersion']) is int
            and value['schemaVersion'] == 1
            and value['kind'] == KIND and value['productionAuthority'] is False
            and value['filesystemCache'] == 'unknown', 'invalid technical input record')
    validate_spec(value['spec'])
    require(value['encoderModule'] == pin(ENCODER_MODULE), 'technical encoder implementation changed')
    require(value['tools'] == {name: pin(Path(tools[name])) for name in ('node', 'ffmpeg', 'ffprobe')},
            'technical fixture tools changed')
    canvas, bounds = value['spec']['canvas'], value['spec']['frameRange']
    require(isinstance(value['windows'], list) and 0 < len(value['windows']) <= 64, 'invalid technical window count')
    windows = [read_window(row, value['spec'], tools, root) for row in value['windows']]
    scope = {'id': 'technical-measurement', 'kind': 'technical-only', 'frameRange': bounds}
    local_pieces(windows, scope)
    audio = value['audio']
    require(set(audio) == {'master', 'reference', 'receipt', 'clock', 'command'}, 'invalid technical audio record')
    require(audio['command'] == audio_command(value['spec'], tools, Path(audio['master']['path'])),
            'technical audio generator changed')
    for name in ('master', 'reference', 'receipt'):
        check_pin(audio[name], root)
    samples = clock(canvas).sample_at_frame(canvas['totalFrames'])
    require(all(exact_float_audio_clock(audio[name]['path'], tools['ffprobe'], samples) == audio['clock']
                for name in ('master', 'reference')), 'technical PCM clock changed')
    master = bound_json(Path(audio['receipt']['path']), audio['receipt']['sha256'])
    require(master == {'kind': 'technical-signal-only', 'output': audio['master']['path'],
                       'masterSha256': audio['master']['sha256']}, 'technical master receipt changed')
    request = {'tools': tools, 'revision': {'canvas': canvas, 'grid': {'timescale': Fraction(canvas['frameRate']).numerator}}}
    prepared = {'masterReceipt': audio['receipt']['path'], 'masterReceiptSha256': audio['receipt']['sha256']}
    return PackageMediaInputs(request, scope, windows, prepared)


def read_window(row: dict, spec: dict, tools: dict, root: Path) -> dict:
    """Recompute exact generator command and packet facts instead of trusting labels."""
    require(set(row) == {'piece', 'pin', 'encoding'}, 'invalid technical window record')
    file = check_pin(row['pin'], root)
    piece = row['piece']
    bounds = piece['startFrame'], piece['endFrameExclusive']
    require(all(type(n) is int for n in bounds) and 0 < bounds[1] - bounds[0] <= MAX_WINDOW_FRAMES,
            'invalid technical window bounds')
    require(row['encoding'] == encoder_args(spec, bounds, tools, file), 'technical encoder arguments changed')
    require(piece == describe_piece(file, bounds, Tools.of({'tools': tools})), 'technical picture proof changed')
    canvas, stream = spec['canvas'], piece['stream']
    rate = Fraction(canvas['frameRate'])
    require(stream['width'] == canvas['width'] and stream['height'] == canvas['height']
            and Fraction(stream['r_frame_rate']) == rate and stream['codec_name'] == 'h264'
            and stream['pix_fmt'] == 'yuv420p' and stream['has_b_frames'] == 0
            and Fraction(stream['time_base']) == Fraction(1, rate.numerator)
            and piece['packets']['tick'] == rate.denominator, 'technical picture contract changed')
    return {'piece': piece}
