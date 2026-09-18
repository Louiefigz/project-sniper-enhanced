"""Optional reusable raw speech recognition; text and timestamp quality stay separate."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from local_asr_deadline import LocalAsrDeadline, use_local_asr_deadline
from local_whisper import resolve_runtime, _extract_pcm, _run_whisper
from local_whisper_parser import parse_whisper_json, WhisperParseError, PARSER_POLICY
from transcript_timing_quality import timing_quality_report
from cut_preview_io import bound_json, real_directory, write_new
from studio.native_run import NativeRun
from studio.native_run_config import NativeRunConfig, local_environment
from studio.native_runtime import digest, install_runtime
from studio.native_stage_evidence import require, verify_pins

STATUS = 'native-review-recognition-recorded'
HERE = Path(__file__).resolve().parent


def interpret(payload: dict) -> dict:
    """Retain recognized text even when the existing timestamp policy rejects it."""
    rows = payload.get('transcription')
    require(type(rows) is list and bool(rows) and all(type(row) is dict and isinstance(row.get('text'), str) for row in rows), 'invalid raw recognition text')
    text = ' '.join(''.join(row['text'] for row in rows).split())
    require(bool(text), 'recognition returned no spoken text')
    try:
        timing = timing_quality_report({'transcript': parse_whisper_json(payload, 0, None)})
    except WhisperParseError as error:
        timing = {'status': 'fail', 'error': str(error)}
    return {'recognizedText': text, 'timingQuality': timing, 'parserPolicy': PARSER_POLICY,
            'timingApproved': False, 'wordSyncApproved': False, 'humanListeningApproved': False}


def worker(file: Path) -> None:
    """Produce raw recognition once under shared local ASR ownership and deadline."""
    request = bound_json(file); root = Path(request['root'])
    with use_local_asr_deadline(LocalAsrDeadline.start()):
        verify_pins(request['pins'])
        wav, prefix = root / 'recognition.wav', root / 'raw-recognition'
        _extract_pcm(request['audio'], str(wav))
        payload, cpu = _run_whisper(resolve_runtime(), str(wav), str(prefix), print)
        raw = Path(str(prefix) + '.json')
        result = {'status': STATUS, 'audio': request['audio'], 'audioSha256': request['audioSha256'],
                  'runtime': request['recognizer'], 'raw': str(raw), 'rawSha256': digest(raw),
                  'executionPath': 'cpu' if cpu else 'gpu', **interpret(payload)}
        verify_pins(request['pins']); write_new(root / 'recognition.json', result)


def read_existing(receipt: Path, audio: Path) -> dict:
    """Reuse exact retained raw bytes; failed timing never becomes a fresh pass."""
    record = bound_json(receipt)
    require(record.get('status') == STATUS and record.get('audio') == str(audio)
            and record.get('audioSha256') == digest(audio), 'recognition source changed')
    owner = bound_json(Path(record['owner']), record['ownerSha256'])
    require(owner.get('status') == STATUS and owner.get('exitCode') == 0
            and owner.get('cleanup', {}).get('verified') is True and owner.get('leaseCleanupVerified') is True,
            'recognition lacks owned cleanup')
    result = bound_json(Path(record['result']), record['resultSha256'])
    require(owner.get('output') == record['result'] and not owner.get('abortReason'), 'recognition owner output differs')
    request_file = receipt.parent / 'owner-input/request.json'
    request = bound_json(request_file)
    require(owner.get('additionalFilePinsBefore') == owner.get('additionalFilePinsAfter')
            and owner.get('additionalFilePinsBefore', {}).get(str(request_file)) == digest(request_file)
            and request.get('audioSha256') == record['audioSha256'] and request.get('audio') == record['audio'],
            'recognition request/source was not supervised')
    raw = bound_json(Path(result['raw']), result['rawSha256'])
    require(result['audioSha256'] == record['audioSha256'] and result['audio'] == record['audio'], 'raw recognition belongs to another source')
    interpreted = interpret(raw)
    require(interpreted == {key: result[key] for key in interpreted}, 'recognition interpretation changed')
    return result


def execute(audio: Path, output: Path) -> dict:
    """Run a separate diagnostic; it is never required for Studio publication."""
    audio = audio.resolve(strict=True); output = output.absolute(); real_directory(output.parent)
    require(not output.exists() and not output.is_symlink(), 'recognition requires a fresh attempt')
    tools, environment = local_environment(); runtime = resolve_runtime()
    environment.update(WHISPER_CPP_BIN=str(Path(runtime.binary).resolve()), WHISPER_CPP_MODEL=str(Path(runtime.model).resolve()),
                       WHISPER_CPP_THREADS='4', WHISPER_CPP_NO_GPU='1', WHISPER_CPP_TIMEOUT_SECONDS='240')
    runtime = resolve_runtime(environment)
    files = [audio, Path(runtime.binary), Path(runtime.model), Path(sys.executable).resolve(), Path(__file__).resolve()]
    files += list(HERE.parents[1].glob('local_whisper*.py')) + list(HERE.parents[1].glob('local_asr*.py'))
    files += [HERE.parents[1] / 'transcript_timing_quality.py', *map(Path, tools.values())]
    pins = {str(file): digest(file) for file in files}
    output.mkdir(); project = output / 'owner-input'; project.mkdir()
    request = project / 'request.json'
    write_new(request, {'root': str(output), 'audio': str(audio), 'audioSha256': pins[str(audio)],
                        'recognizer': asdict(runtime), 'pins': pins})
    cli, sandbox = install_runtime() / 'dist/cli.js', HERE / 'native_localhost_only.sb'
    settings = NativeRunConfig(project, output, cli,
        ['/usr/bin/sandbox-exec', '-f', str(sandbox), sys.executable, str(Path(__file__).resolve()), '--worker', str(request)],
        environment, {'output': str(output / 'recognition.json'), 'sdkSha256': digest(cli), 'sandboxSha256': digest(sandbox)},
        additional_pins={**pins, str(request): digest(request)}, deadline=300, success_status=STATUS)
    owner = NativeRun('review-recognition', settings)
    require(owner.execute() and owner.result.get('cleanup', {}).get('verified') is True
            and owner.result.get('leaseCleanupVerified') is True, 'recognition owner failed; preserve attempt')
    verify_pins(pins)
    record = {'status': STATUS, 'audio': str(audio), 'audioSha256': pins[str(audio)], 'owner': str(owner.path),
              'ownerSha256': digest(owner.path), 'result': str(output / 'recognition.json'),
              'resultSha256': digest(output / 'recognition.json')}
    write_new(output / 'RECOGNITION-RECEIPT.json', record)
    return read_existing(output / 'RECOGNITION-RECEIPT.json', audio)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--worker': worker(Path(sys.argv[2]))
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('audio', type=Path); parser.add_argument('output', type=Path, nargs='?')
        parser.add_argument('--reuse', type=Path); args = parser.parse_args()
        require(bool(args.output) != bool(args.reuse), 'supply a fresh output or an existing recognition receipt')
        print(json.dumps(read_existing(args.reuse, args.audio.resolve(strict=True)) if args.reuse else execute(args.audio, args.output)))
