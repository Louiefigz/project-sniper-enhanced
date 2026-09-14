"""Reuse only a completed, unchanged native batch picture; delivery still needs QC."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from studio.native_run_config import source_hashes
from studio.native_runtime import digest

STUDIO = Path(__file__).resolve().parent
PICTURE_CODE = ('native_short_batched_render.mjs', 'native_short_capture_context.mjs',
                'native_short_capture_checks.mjs', 'native_short_capture.mjs',
                'native_source_cache.mjs', 'native_original_media.mjs', 'native_forward_qc.mjs',
                'native_run_config.py', 'native_runtime.py', 'native_localhost_only.sb')
RUNTIME_FILES = ('cli.js', 'native-capture-library.mjs', 'hyperframe.runtime.iife.js',
                 'hyperframe.manifest.json', 'frame-source-transport.mjs')
DONOR_FILES = ('export-request.json', 'pipeline.render.json', 'batched-picture.json', 'picture.mp4')
MODE = 'cached-native-batches'
MAX_RECEIPT_BYTES = 32 * 1024 * 1024


def require(value: bool, message: str) -> None:
    """Reject incomplete evidence without relying on optimizable assertions."""
    if not value:
        raise ValueError(f'Native picture reuse: {message}')


def read_record(file: Path) -> dict:
    """Bound receipt parsing before loading untrusted local JSON."""
    require(file.is_file() and not file.is_symlink(), f'not a regular receipt: {file}')
    require(file.stat().st_size <= MAX_RECEIPT_BYTES, f'receipt exceeds 32 MiB: {file}')
    with file.open('rb') as handle:
        content = handle.read(MAX_RECEIPT_BYTES + 1)
    require(len(content) <= MAX_RECEIPT_BYTES, f'receipt grew beyond 32 MiB: {file}')
    value = json.loads(content)
    require(isinstance(value, dict), f'receipt must be an object: {file}')
    return value


def verify_pins(pins: dict[str, str]) -> None:
    """Rehash the actual files; recorded labels never establish current identity."""
    for filename, expected in pins.items():
        require(isinstance(expected, str) and len(expected) == 64,
                f'missing SHA256 pin: {filename}')
        require(digest(Path(filename)) == expected, f'changed input: {filename}')


def project_dependencies(project: Path) -> dict[str, str]:
    """Bind the whole manifest, selected sources and prepared asset evidence."""
    manifest = read_record(project / 'PROJECT-MANIFEST.json')
    plan = read_record(project / 'SHORT-PROJECT.json')
    expected = {str(project / row['file']): row['sha256'] for row in manifest['files']}
    expected[str(project / 'PROJECT-MANIFEST.json')] = digest(project / 'PROJECT-MANIFEST.json')
    expected.update({asset['path']: asset['sha256'] for asset in plan['assets']})
    if plan['strategy']['schemaVersion'] >= 3:
        report = read_record(project / 'ASSET-USE-REPORT.json')
        expected.update({row['path']: row['sha256'] for row in report['originEvidenceFiles']})
    packet_ref = plan.get('requestPacket')
    if packet_ref:
        expected[packet_ref['path']] = packet_ref['sha256']
        packet = read_record(Path(packet_ref['path']))
        expected.update({row['transcript']['path']: row['transcript']['sha256']
                         for row in packet['sources'] if row.get('transcript')})
        expected.update({row['path']: row['sha256']
                         for row in packet.get('availableSupportingAssets', [])})
    for asset in plan['assets']:
        if asset.get('webCapture'):
            expected.update({asset['webCapture'][key]: digest(Path(asset['webCapture'][key]))
                             for key in ('path', 'supervisionPath')})
    return expected


def picture_dependencies(project: Path, previous: dict) -> dict[str, str]:
    """Select actual picture executables, not audio/mastering implementation files."""
    paths = [STUDIO / name for name in PICTURE_CODE]
    paths += [Path(previous['runtime']) / 'dist' / name for name in RUNTIME_FILES]
    paths += [Path(previous['tools'][key]) for key in ('node', 'browser', 'ffmpeg', 'ffprobe')]
    expected = project_dependencies(project)
    for file in paths:
        require(str(file) in previous['pins'], f'picture dependency was not pinned: {file}')
        expected[str(file)] = previous['pins'][str(file)]
    for filename, value in expected.items():
        require(previous['pins'].get(filename) == value, f'project binding changed: {filename}')
    return expected


def verify_supervision(project: Path, donor: Path, previous: dict, pipeline: dict) -> None:
    """Require complete before/after pin evidence and independently completed cleanup."""
    require(previous.get('project') == str(project) and previous.get('output') == str(donor),
            'donor request belongs to a different project or output')
    require(previous.get('captureMode') == MODE and pipeline.get('project') == str(project),
            'donor is not the same native batch project')
    for key in ('sourceStable', 'sdkStable', 'sandboxStable', 'additionalFilesStable', 'leaseCleanupVerified'):
        require(pipeline.get(key) is True, f'donor supervision did not verify {key}')
    cleanup = pipeline.get('cleanup', {})
    require(cleanup.get('verified') is True and cleanup.get('survivors') == [],
            'donor owned cleanup is incomplete')
    before, after = pipeline.get('additionalFilePinsBefore', {}), pipeline.get('additionalFilePinsAfter', {})
    require(bool(before) and before == after, 'donor additional before/after pins disagree')
    require(all(before.get(key) == value for key, value in previous['pins'].items()),
            'donor request pins were not supervised')
    require(before.get(str(donor / 'export-request.json')) == digest(donor / 'export-request.json'),
            'donor request changed after supervision')
    sources = pipeline.get('sourceHashesBefore', {})
    require(bool(sources) and sources == pipeline.get('sourceHashesAfter') == source_hashes(project),
            'current authored project differs from supervised sources')


def verify_inventory(donor: Path, receipt: dict, canvas: dict) -> dict[str, str]:
    """Require every original screenshot and disposed batch, with exact frame indices."""
    count = canvas['totalFrames']
    require(type(count) is int and 0 < count <= 10800, 'invalid frame count')
    require(receipt.get('width') == 1080 and receipt.get('height') == 1920,
            'picture geometry differs from the native 1080x1920 contract')
    require(all(receipt.get(key) == canvas[key] for key in ('frameRate', 'totalFrames')),
            'picture canvas differs from current project')
    require([row.get('frame') for row in receipt['frames']] == list(range(count)),
            'picture screenshot inventory is incomplete')
    pins, observed = {}, []
    maximum = batch_size(receipt)
    for index, batch in enumerate(receipt['batches']):
        frames = list(range(index * maximum, min((index + 1) * maximum, count)))
        require(bool(frames) and batch.get('frames') == frames and batch.get('index') == index,
                'picture batch inventory is incomplete')
        require(batch.get('status') == 'captured-and-disposed' and batch.get('transport', {}).get('errors') == 0,
                'picture batch capture did not complete')
        require(all(batch.get(key) is True for key in ('sessionClosed', 'browserPoolDrained', 'serverClosed')),
                'picture batch disposal was not verified')
        observed += frames
    require(observed == list(range(count)), 'picture batch coverage is incomplete')
    for row in receipt['frames']:
        file = donor / 'batched-native-render/frames' / f"frame_{row['frame']:06d}.jpg"
        require(row.get('path') == str(file) and file.is_file() and not file.is_symlink()
                and file.resolve(strict=True).is_relative_to(donor),
                'screenshot is not the recorded donor output')
        pins[str(file)] = row['sha256']
    compiled = donor / 'batched-native-render/compiled/index.html'
    require(compiled.is_file() and not compiled.is_symlink()
            and compiled.resolve(strict=True).is_relative_to(donor), 'compiled picture evidence missing')
    pins[str(compiled)] = receipt['compiledSha256']
    return pins


def batch_size(receipt: dict) -> int:
    """Read the bounded plan from the pinned renderer; historical receipts used 48."""
    plan = receipt.get('batchPlan')
    if plan is None:
        return 48
    require(isinstance(plan, dict) and plan.get('schemaVersion') == 1
            and plan.get('rule') == 'admitted-source-rgba-v1', 'unknown picture batch plan')
    maximum = plan.get('maximumFrames')
    require(type(maximum) is int and maximum in (1, 2, 4, 8, 12, 24, 48),
            'picture batch plan exceeds supported session bounds')
    return maximum


def verify_picture(project: Path, donor: Path, previous: dict, receipt: dict) -> dict[str, str]:
    """Tie completed picture bytes and encoder evidence to the exact prior request."""
    require(receipt.get('status') == 'picture-encoded-awaiting-parent-qc'
            and receipt.get('pictureMode') == MODE, 'donor picture did not finish')
    require(receipt.get('project') == str(project) and receipt.get('output') == str(donor / 'picture.mp4'),
            'picture receipt belongs to another project or output')
    require(receipt.get('referenceEncoding') == 'jpeg95-matching-opaque-render', 'unexpected picture mode')
    encoder = receipt.get('encoder', {})
    require(encoder.get('command') == previous['tools']['ffmpeg']
            and receipt.get('encodeResult', {}).get('exitCode') == 0, 'picture encoder did not complete')
    require(all(encoder.get(key) == value for key, value in
                {'quality': 'high', 'crf': 15, 'preset': 'slow', 'codec': 'h264', 'passes': 1,
                 'pixelFormat': 'yuv420p', 'width': 1080, 'height': 1920}.items()), 'picture quality differs')
    pins = verify_inventory(donor, receipt, read_record(project / 'SHORT-PROJECT.json')['canvas'])
    pins[str(donor / 'picture.mp4')] = receipt['sha256']
    require((donor / 'picture.mp4').is_file() and not (donor / 'picture.mp4').is_symlink()
            and (donor / 'picture.mp4').stat().st_size > 0, 'missing regular donor picture')
    require(receipt['sourceHtmlSha256'] == previous['pins'].get(str(project / 'index.html')),
            'picture HTML evidence differs')
    runtime = Path(previous['runtime']) / 'dist'
    require(receipt['runtimeLibrarySha256'] == previous['pins'].get(str(runtime / 'native-capture-library.mjs'))
            and encoder['sdkCliSha256'] == previous['pins'].get(str(runtime / 'cli.js')), 'picture SDK evidence differs')
    return pins


def picture_reuse_pins(project: Path, donor: Path) -> dict[str, str]:
    """Validate a prior attempt and return all picture dependencies/evidence to pin."""
    project, donor = project.resolve(strict=True), donor.resolve(strict=True)
    for name in DONOR_FILES[:3]:
        require((donor / name).stat().st_size <= MAX_RECEIPT_BYTES, f'donor receipt exceeds 32 MiB: {name}')
    evidence = {str(donor / name): digest(donor / name) for name in DONOR_FILES}
    previous, pipeline, receipt = (read_record(donor / name) for name in DONOR_FILES[:3])
    verify_supervision(project, donor, previous, pipeline)
    pins = picture_dependencies(project, previous)
    pins.update(verify_picture(project, donor, previous, receipt))
    pins.update(evidence)
    require(evidence[str(donor / 'picture.mp4')] == receipt['sha256'], 'picture digest differs from receipt')
    verify_pins(pins)
    return pins


def copy_picture(source: Path, target: Path, expected: str) -> None:
    """Copy exclusively in bounded chunks, retaining failed artifacts for diagnosis."""
    require(not source.is_symlink() and digest(source) == expected, 'donor picture changed before copy')
    before = source.stat()
    with source.open('rb') as reader, target.open('xb') as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    after = source.stat()
    require((before.st_ino, before.st_dev, before.st_mtime_ns, before.st_size)
            == (after.st_ino, after.st_dev, after.st_mtime_ns, after.st_size), 'donor changed while copied')
    require(digest(source) == expected == digest(target), 'copied picture checksum mismatch')


def reuse_native_picture(request: dict) -> dict:
    """Copy a validated completed picture; current audio/color/native QC remain mandatory."""
    require(request.get('captureMode') == MODE, 'picture reuse requires explicit cached native batches')
    project, donor = Path(request['project']).resolve(strict=True), Path(request['pictureDonor']).resolve(strict=True)
    output = Path(request['output']).resolve(strict=True)
    require(output != donor and not output.is_relative_to(donor), 'reuse must preserve the donor directory')
    pins = picture_reuse_pins(project, donor)
    previous = read_record(donor / 'export-request.json')
    require(request['runtime'] == previous['runtime'] and request['tools'] == previous['tools'],
            'current picture runtime/tools differ from donor')
    require(all(request['pins'].get(key) == value for key, value in pins.items()),
            'reuse evidence was not pinned in the current request')
    target, source = output / 'picture.mp4', donor / 'picture.mp4'
    copy_picture(source, target, pins[str(source)])
    verify_pins(pins)
    return {'schemaVersion': 1, 'status': 'picture-reused-awaiting-parent-qc', 'pictureMode': MODE,
            'donor': str(donor), 'output': str(target), 'sha256': pins[str(source)],
            'validatedPins': pins, 'pictureRenderedAgain': False, 'humanApproved': False,
            'scope': 'Completed native picture only; current audio/color/native/encoded QC still required'}
