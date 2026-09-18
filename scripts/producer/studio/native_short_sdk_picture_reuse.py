"""Recover an exact SDK picture after a supervised later audio or metadata failure.

This admits no failed audio, render-stage seal or final delivery. The fresh
attempt still performs the ordinary audio, color, native and encoded checks.
"""
from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path

from studio.native_runtime import digest
from studio.native_stage_evidence import require, verify_pins, verify_supervised_inputs
from studio.native_short_picture_reuse import (
    MAX_RECEIPT_BYTES, RUNTIME_FILES, STUDIO, copy_picture, project_dependencies, read_record,
)

MODE = 'sdk-streaming'
PICTURE_CODE = ('native_short_worker.py', 'native_runtime.py', 'native_run_config.py',
                'native_localhost_only.sb')
DONOR_FILES = ('export-request.json', 'pipeline.render.json', 'pipeline.render.log',
               'audio/receipt.json', 'render-failure.json', 'picture.mp4')


def manifest_files(project: Path) -> dict[str, str]:
    """Require a closed, nonaliased project payload inventory."""
    rows = read_record(project / 'PROJECT-MANIFEST.json')['files']
    result = {}
    for row in rows:
        name = row['file']
        require(isinstance(name, str) and not Path(name).is_absolute()
                and '..' not in Path(name).parts and name not in result, 'invalid project file inventory')
        file = project / name
        require(file.resolve(strict=True) == file and not file.is_symlink(), 'aliased project payload')
        result[name] = row['sha256']
    require({'index.html', 'SHORT-PROJECT.json', 'hyperframes.json'} <= result.keys(),
            'missing required native project payload')
    return result


def visual_dependencies(project: Path, previous: dict) -> dict[str, str]:
    """Allow audioFinishing alone to change while preserving the full visual closure."""
    original = Path(previous['project'])
    plans = [read_record(root / 'SHORT-PROJECT.json') for root in (original, project)]
    visual_plans = [{key: value for key, value in plan.items() if key != 'audioFinishing'} for plan in plans]
    require(visual_plans[0] == visual_plans[1], 'SDK picture source, cuts, captions or visual strategy changed')
    old_files, current_files = manifest_files(original), manifest_files(project)
    require(old_files.keys() == current_files.keys(), 'SDK picture project inventory changed')
    require(all(current_files[name] == sha for name, sha in old_files.items() if name != 'SHORT-PROJECT.json'),
            'SDK picture HTML/assets or other project payload changed')
    old_pins, current_pins = project_dependencies(original), project_dependencies(project)
    require(all(previous['pins'].get(file) == sha for file, sha in old_pins.items()),
            'original project closure differs from supervised request')
    old_external = {file: sha for file, sha in old_pins.items() if not Path(file).is_relative_to(original)}
    current_external = {file: sha for file, sha in current_pins.items() if not Path(file).is_relative_to(project)}
    require(old_external == current_external, 'SDK picture external source evidence changed')
    require(all(digest(root / name) == sha for root, files in ((original, old_files), (project, current_files))
                for name, sha in files.items()), 'SDK picture project payload drifted')
    return {**old_pins, **current_pins}


def picture_dependencies(previous: dict) -> dict[str, str]:
    """Bind the actual SDK execution path without invalidating audio-only code fixes."""
    paths = [STUDIO / name for name in PICTURE_CODE]
    paths += [Path(previous['runtime']) / 'dist' / name for name in RUNTIME_FILES]
    paths += [Path(previous['tools'][name]) for name in ('node', 'browser', 'ffmpeg', 'ffprobe')]
    require(all(str(file) in previous['pins'] for file in paths), 'SDK picture executable was not supervised')
    return {str(file): previous['pins'][str(file)] for file in paths}


def verify_worker_command(donor: Path, previous: dict, owner: dict) -> None:
    """Require the recorded SDK worker invocation whose pinned code emitted the proof."""
    args = owner.get('args')
    require(isinstance(args, list) and len(args) == 7 and args[:2] == ['/usr/bin/sandbox-exec', '-f']
            and args[2] == str(STUDIO / 'native_localhost_only.sb')
            and args[4:] == [str(STUDIO / 'native_short_worker.py'), str(donor / 'export-request.json'), 'render'],
            'SDK donor owner did not invoke the exact native render worker')
    require(isinstance(args[3], str) and str(Path(args[3]).resolve(strict=True)) in previous['pins'],
            'SDK worker interpreter was not pinned')


def verify_failed_owner(donor: Path, previous: dict, owner: dict) -> None:
    """Keep the failure label and require complete, nonaborted original ownership."""
    require(previous.get('captureMode') == MODE and not previous.get('pictureDonor'),
            'expected an original SDK-streaming picture attempt')
    verify_worker_command(donor, previous, owner)
    verify_supervised_inputs(Path(previous['project']), donor / 'export-request.json', previous, owner)
    require(owner.get('status') == 'failed' and type(owner.get('exitCode')) is int and owner['exitCode'] == 1
            and not owner.get('abortReason') and not owner.get('receiptOwnershipFailed'),
            'SDK picture owner aborted or did not fail cleanly after picture')
    require(owner.get('output') == str(donor / 'review.mp4')
            and owner.get('logPath') == str(donor / 'pipeline.render.log'), 'SDK owner output/log differs')
    identities, pid = owner.get('ownerIdentities'), owner.get('pid')
    require(type(pid) is int and pid > 0 and isinstance(identities, list) and bool(identities),
            'SDK picture owner identity missing')
    require(all(isinstance(row, dict) and all(type(row.get(key)) is int and row[key] > 0
                for key in ('pid', 'pgid', 'parent_pid')) and isinstance(row.get('started'), str)
                and bool(row['started'].strip()) for row in identities), 'SDK owner identity incomplete')
    require(len({row['pid'] for row in identities}) == len(identities)
            and any(row['pid'] == row['pgid'] == pid for row in identities), 'SDK root ownership missing')


def trace_rows(file: Path) -> tuple[list[dict], list[dict]]:
    """Read bounded retained SDK trace lines; never run or reinterpret the old command."""
    require(file.is_file() and not file.is_symlink() and file.stat().st_size <= MAX_RECEIPT_BYTES,
            'missing or oversized SDK picture log')
    with file.open('rb') as stream:
        content = stream.read(MAX_RECEIPT_BYTES + 1)
    require(len(content) <= MAX_RECEIPT_BYTES, 'SDK picture log grew beyond bound')
    rows, transports = [], []
    for line in content.decode().splitlines():
        if '[Render:trace] ' in line:
            rows.append(json.loads(line.split('[Render:trace] ', 1)[1]))
        if '[NativeFrameTransport] ' in line:
            transports.append(json.loads(line.split('[NativeFrameTransport] ', 1)[1]))
    require(all(isinstance(row, dict) for row in [*rows, *transports]), 'invalid SDK trace record')
    return rows, transports


def one_trace(rows: list[dict], values: dict) -> dict:
    """Require exactly one explicit SDK checkpoint for this render job."""
    matches = [row for row in rows if all(row.get(key) == value for key, value in values.items())]
    require(len(matches) == 1, f'missing/ambiguous SDK completion evidence: {values}')
    return matches[0]


def verify_sdk_completion(donor: Path, canvas: dict) -> None:
    """Require complete exact-frame capture, assembly, validation and transport close."""
    rows, transports = trace_rows(donor / 'pipeline.render.log')
    start = one_trace(rows, {'phase': 'pipeline', 'message': 'started'})
    metadata = one_trace(rows, {'phase': 'compile', 'message': 'composition metadata resolved'})
    capture = one_trace(rows, {'phase': 'capture_streaming', 'status': 'end'})
    assembly = one_trace(rows, {'phase': 'assemble', 'status': 'end'})
    validated = one_trace(rows, {'phase': 'pipeline', 'message': 'artifact validated'})
    require(len({row.get('renderJobId') for row in rows}) == 1 and bool(start.get('renderJobId')),
            'SDK log contains mixed or missing render identities')
    require(start.get('format') == 'mp4' and start.get('quality') == 'high'
            and start.get('requestedWorkers') == 1 and start.get('forceScreenshot') is True,
            'SDK picture render quality/route changed')
    require(metadata.get('width') == 1080 and metadata.get('height') == 1920
            and metadata.get('deviceScaleFactor') == 1, 'SDK picture geometry differs')
    require(all(row.get('totalFrames') == canvas['totalFrames'] and row.get('framesCompleted') == canvas['totalFrames']
                and row.get('captureMode') == 'screenshot' and row.get('captureOperation') == 'encode'
                for row in (capture, assembly)), 'SDK picture did not capture/assemble every frame')
    require(capture['elapsedMs'] <= assembly['elapsedMs'] <= validated['elapsedMs'], 'SDK completion order differs')
    closed = one_trace(transports, {'event': 'close'})
    require(closed.get('closed') is True and closed.get('failed') is False
            and all(closed.get(key) == 0 for key in ('errors', 'aborted', 'rejected', 'entries', 'activeStreams', 'activeSourceDescriptors'))
            and closed.get('completed') == closed.get('requests') and closed.get('mode') == 'same-origin-url',
            'SDK source transport failed or did not close')


def verify_later_failure(audio: dict, failure: dict) -> None:
    """Accept recorded signal/QC failure or a later failure after fully qualified audio."""
    require(audio.get('scope') == 'native-dialogue-audio-qualification-only'
            and failure.get('status') == 'failed' and isinstance(failure.get('error'), str)
            and bool(failure['error'].strip()), 'expected a recorded post-picture failure')
    quality, signal = audio.get('audioQuality'), audio.get('signal', {})
    checked = isinstance(quality, list) and bool(quality) and all(isinstance(row, dict) for row in quality)
    if audio.get('status') == 'audio-qualified':
        require(not audio.get('error') and checked
                and all(row.get('status') in {'pass', 'warn'} for row in quality)
                and signal.get('passed') is True and signal.get('inputsStable') is True,
                'missing qualified audio evidence before later failure')
        return
    require(audio.get('status') == 'failed' and bool(audio.get('error'))
            and failure['error'] == audio['error'], 'expected the recorded post-picture audio failure')
    signal_failed = (signal.get('status') == 'local-signal-checks-failed'
                     and signal.get('passed') is False and signal.get('inputsStable') is True)
    require((checked and any(row.get('status') == 'fail' for row in quality)) or signal_failed,
            'missing failed audio QC evidence')


def verify_audio_picture(donor: Path, canvas: dict) -> str:
    """Use already recorded packet/clock proof; failed audio receives no reuse authority."""
    audio = read_record(donor / 'audio/receipt.json')
    verify_later_failure(audio, read_record(donor / 'render-failure.json'))
    picture = audio.get('picture', {})
    expected = audio.get('inputPictureSha256')
    require(picture.get('picturePacketsIdentical') is True and picture.get('pictureSourceSha256') == expected
            and type(picture.get('picturePackets')) is int and picture['picturePackets'] == canvas['totalFrames']
            and Fraction(picture.get('pictureTimeBase', '0')) > 0, 'completed SDK picture packet proof missing')
    samples = Fraction(canvas['totalFrames'] * 48000, 1) / Fraction(canvas['frameRate'])
    require(samples.denominator == 1 and audio.get('audioClock', {}).get('presentedSamples') == samples.numerator
            and type(audio.get('additionalPictureEncodes')) is int and audio['additionalPictureEncodes'] == 0,
            'completed SDK picture clock/copy proof differs')
    require(digest(donor / 'picture.mp4') == expected, 'completed SDK picture bytes changed')
    return expected


def sdk_picture_reuse_pins(project: Path, donor: Path) -> dict[str, str]:
    """Admit retained SDK picture evidence and current visual identity for a new owner."""
    project, donor = project.resolve(strict=True), donor.resolve(strict=True)
    previous = read_record(donor / 'export-request.json')
    owner = read_record(donor / 'pipeline.render.json')
    verify_failed_owner(donor, previous, owner)
    pins = {str(donor / name): digest(donor / name) for name in DONOR_FILES}
    pins.update(visual_dependencies(project, previous))
    pins.update(picture_dependencies(previous))
    interpreter = str(Path(owner['args'][3]).resolve(strict=True))
    pins[interpreter] = previous['pins'][interpreter]
    canvas = read_record(project / 'SHORT-PROJECT.json')['canvas']
    require(type(canvas.get('totalFrames')) is int and 0 < canvas['totalFrames'] <= 10800,
            'invalid SDK picture frame count')
    verify_sdk_completion(donor, canvas)
    require(verify_audio_picture(donor, canvas) == pins[str(donor / 'picture.mp4')], 'SDK donor changed during admission')
    verify_pins(pins)
    return pins


def reuse_sdk_picture(request: dict) -> dict:
    """Copy exactly the admitted SDK picture; all current delivery checks still run."""
    require(request.get('captureMode') == MODE, 'SDK picture donor requires SDK-streaming mode')
    project, donor = Path(request['project']).resolve(strict=True), Path(request['pictureDonor']).resolve(strict=True)
    output = Path(request['output']).resolve(strict=True)
    require(output != donor and not output.is_relative_to(donor) and not donor.is_relative_to(output),
            'SDK reuse must preserve the donor directory')
    previous = read_record(donor / 'export-request.json')
    require(request['runtime'] == previous['runtime'] and request['tools'] == previous['tools'],
            'SDK picture runtime/tools differ from donor')
    pins = sdk_picture_reuse_pins(project, donor)
    require(all(request['pins'].get(file) == sha for file, sha in pins.items()), 'SDK donor evidence not pinned')
    source, target = donor / 'picture.mp4', output / 'picture.mp4'
    copy_picture(source, target, pins[str(source)])
    verify_pins(pins)
    return {'schemaVersion': 1, 'status': 'picture-reused-awaiting-parent-qc', 'pictureMode': MODE,
            'donor': str(donor), 'originalProject': previous['project'], 'project': str(project),
            'output': str(target), 'sha256': pins[str(source)], 'validatedPins': pins,
            'pictureRenderedAgain': False, 'humanApproved': False, 'audioFinishingMayDiffer': True,
            'scope': 'Completed SDK picture only; current audio/color/native/encoded QC still required'}
