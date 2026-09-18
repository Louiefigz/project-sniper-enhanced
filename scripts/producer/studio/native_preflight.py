"""Read-only native-project preflight using the installed official SDK linter.

An opt-in command for the exact staged project before expensive sample/master
renders. Success means static checks only, never quality or render approval.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import file_hash, read_bytes, real_directory, write_new
from graphics import comp_capability_lint as lint
from headless.process_runner import ProcessRequest, run_text
from stage_timing import stage_span
from studio.native_preflight_inputs import require_unchanged, source_state
from studio.native_reference_reuse import implementation_files, reference_snapshot

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
RUNNER = Path(__file__).with_name('sdk_native_preflight.mjs')
MAX_SECONDS = 30


def _tools() -> dict:
    """Reuse existing official validator pins and include this adapter's sources."""
    value = lint.lint_validator_state()
    paths = {Path(__file__), RUNNER, Path(__file__).with_name('native_preflight_inputs.py'),
             Path(__file__).with_name('native_preflight_dependencies.mjs'),
             Path(__file__).with_name('native_reference_reuse.py'), *implementation_files()}
    value['files'].update(lint._files(paths))
    value['parents'].update(lint._parents(paths))
    value['bindingScope'] = 'SDK lint/parser bundles, lockfile, Node and adapters; not full transitive dependency attestation'
    return value


def _envelope(value: dict, expected: str) -> None:
    """Reject malformed worker metadata and unperformed-work misstatements."""
    if type(value) is not dict or value.get('scope') != 'native-static-preflight-only' \
            or type(value.get('schemaVersion')) is not int or value.get('schemaVersion') != 1 \
            or value.get('version') != lint.VERSION or value.get('requestSha256') != expected \
            or value.get('codecProbePerformed') is not False or value.get('deniedAttempts') != []:
        raise RuntimeError('Malformed or mixed native static preflight output')
    result = value.get('result', {})
    elapsed = value.get('elapsedMs')
    if type(result) is not dict or type(elapsed) not in (int, float) \
            or not math.isfinite(elapsed) or not 0 <= elapsed <= MAX_SECONDS * 1000:
        raise RuntimeError('Malformed or over-deadline native preflight result')
    dependencies = value.get('dependencyFindings')
    if type(dependencies) is not list or len(dependencies) > 16384 \
            or any(type(row) is not dict or row.get('severity') != 'error'
            or not all(isinstance(row.get(key), str) and row[key]
                       for key in ('file', 'code', 'reference', 'message')) for row in dependencies):
        raise RuntimeError('Malformed native dependency findings')


def _result(raw: str, expected: str, sources: dict) -> dict:
    """Validate actual SDK diagnostics and every reported HTML content binding."""
    value = json.loads(raw, object_pairs_hook=lint._unique)
    _envelope(value, expected)
    result, dependencies = value['result'], value['dependencyFindings']
    rows = result.get('results', [])
    if type(rows) is not list or any(type(row) is not dict or type(row.get('file')) is not str for row in rows):
        raise RuntimeError('Malformed native preflight SDK rows')
    names = [row.get('file') for row in rows]
    if not 1 <= len(rows) <= 512 or names[0] != 'index.html' or len(set(names)) != len(names):
        raise RuntimeError('Native preflight returned incomplete or duplicate lint rows')
    expected_html = {name for name in sources['files'] if Path(name).suffix.lower() in {'.html', '.htm'}}
    unlinted = [row['file'] for row in dependencies if row['code'] == 'native_unlinted_html']
    if set(unlinted) != expected_html - set(names) or len(unlinted) != len(set(unlinted)):
        raise RuntimeError('Native preflight HTML coverage is incomplete or mixed')
    counts = [0, 0, 0]
    for row in rows:
        original = sources['files'].get(row['file'], {})
        hashed = original.get('sha256')
        if not hashed or row.get('contentHash') != hashed[:16]:
            raise RuntimeError('Native preflight SDK content differs from source')
        counts = [a + b for a, b in zip(counts, lint._findings(row['result']))]
    declared = [result.get(key) for key in ('totalErrors', 'totalWarnings', 'totalInfos')]
    if any(type(n) is not int for n in declared) or declared != counts \
            or value.get('blocked') is not (counts[0] > 0 or bool(dependencies)):
        raise RuntimeError('Native preflight SDK aggregate or strict gate disagrees')
    return value


def _execute(project: Path, output: Path, original: dict, end: float) -> tuple[dict, list[str]]:
    """Run the existing secret-free bounded text worker, without media children."""
    request = {'schemaVersion': 1, 'version': lint.VERSION, 'project': str(project),
               'packageRoot': str(ROOT / 'node_modules/@hyperframes/lint'),
               'files': original['source']['files']}
    target = output / 'request.json'
    write_new(target, request)
    request_hash = file_hash(target)
    request_identity = lint._identity(target)
    environment = lint._environment(output)
    process = ProcessRequest((original['tools']['node'], '--max-old-space-size=512',
        '--require', str(lint._PRELOAD), str(RUNNER), str(target), request_hash),
        '', str(ROOT), environment, lint._remaining(end), max_output_bytes=lint.MAX_OUTPUT)
    completed = run_text(process)
    write_new(output / 'process.json', {'returncode': completed.returncode,
        'stdout': completed.stdout, 'stderr': completed.stderr})
    if completed.stderr:
        raise RuntimeError('Native preflight worker refused; see process.json')
    result = _result(completed.stdout, request_hash, original['source'])
    if completed.returncode != int(result['blocked']):
        raise RuntimeError('Native preflight exit status disagrees with SDK findings')
    require_unchanged(project, original['source'])
    if _tools() != original['tools'] or lint._identity(target) != request_identity:
        raise RuntimeError('Native preflight validator or request changed')
    lint._remaining(end)
    return result, request_identity


def preflight(project: Path, output: Path, reference_map: Path | None = None) -> dict:
    """Collect static issues without altering the project or replacing old results.

    Args:
        project: Canonical staged native project, not its immutable archive root.
        output: New evidence directory outside the project, with an existing parent.
        reference_map: Explicit reference-match map; ordinary edits need no map.

    Returns:
        A timed static-only result retaining all SDK findings and input pins.
    """
    began = time.monotonic()
    real_directory(project)
    real_directory(output.parent)
    if output.is_relative_to(project):
        raise ValueError('Native preflight output must be outside the project')
    output.mkdir(mode=0o700)
    with stage_span(str(output), 'native_static_preflight'):
        return _check(project, output, began, reference_map)


def _check(project: Path, output: Path, began: float, reference_map: Path | None = None) -> dict:
    """Preserve failure evidence; never turn incomplete static work into a pass."""
    try:
        original = {'source': source_state(project), 'tools': _tools(),
                    'referenceMatch': reference_snapshot(project, reference_map)}
        write_new(output / 'inputs.json', original)
        result, request_identity = _execute(project, output, original, began + MAX_SECONDS)
        report = {'schemaVersion': 1, 'status': 'blocked' if result['blocked'] else 'static-checks-pass',
            'scope': 'static-only-not-render-or-quality-approval', 'project': str(project),
            'elapsedSeconds': time.monotonic() - began, 'inputsStable': True,
            'elapsedScope': 'before-publication; complete execution span is in stage_timings.jsonl',
            'sourceStateSha256': original['source']['sourceStateSha256'], 'sdk': result,
            'referenceMatch': original['referenceMatch'],
            'mediaContentQualified': False, 'renderApproved': False, 'qualityApproved': False,
            'nextChecks': ['native-animated-samples-at-intended-export-settings',
                           'final-whole-output-audio-color-layout-and-playback-qc']}
        write_new(output / 'result.json', {**report, 'status': 'pending-validation',
            'observedStatus': report['status'], 'completionRequired': True})
        require_unchanged(project, original['source'])
        if reference_snapshot(project, reference_map) != original['referenceMatch']:
            raise RuntimeError('Reference match evidence changed during native preflight')
        if _tools() != original['tools'] or lint._identity(output / 'request.json') != request_identity \
                or file_hash(output / 'request.json') != result['requestSha256']:
            raise RuntimeError('Native preflight validator or request changed before completion')
        lint._remaining(began + MAX_SECONDS)
        write_new(output / 'completion.json', {'schemaVersion': 1, 'status': report['status'],
            'resultSha256': file_hash(output / 'result.json'),
            'sourceStateSha256': report['sourceStateSha256'], 'completedAfterValidation': True,
            'renderApproved': False, 'qualityApproved': False})
        completed = read_completed(output)
        lint._remaining(began + MAX_SECONDS)
        return completed
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        LOGGER.error('Native preflight failed: %s', error)
        write_new(output / 'failure.json', {'status': 'failed', 'error': str(error),
            'elapsedSeconds': time.monotonic() - began, 'renderApproved': False})
        raise


def read_completed(output: Path) -> dict:
    """Read only completed matching observations; this is never render authority."""
    if (output / 'failure.json').exists():
        raise RuntimeError('Native preflight attempt has a failure marker')
    report = json.loads(read_bytes(output / 'result.json', lint.MAX_FILE), object_pairs_hook=lint._unique)
    completion = json.loads(read_bytes(output / 'completion.json', 4096), object_pairs_hook=lint._unique)
    if type(report) is not dict or type(completion) is not dict \
            or report.get('status') != 'pending-validation' or report.get('completionRequired') is not True \
            or type(completion.get('schemaVersion')) is not int or completion.get('schemaVersion') != 1 \
            or completion.get('completedAfterValidation') is not True \
            or completion.get('status') not in {'static-checks-pass', 'blocked'} \
            or completion['status'] != report.get('observedStatus') \
            or completion.get('resultSha256') != file_hash(output / 'result.json') \
            or completion.get('sourceStateSha256') != report.get('sourceStateSha256') \
            or any(row.get(key) is not False for row in (report, completion)
                   for key in ('renderApproved', 'qualityApproved')):
        raise RuntimeError('Native preflight completion does not match observations')
    return {**report, 'status': completion['status']}


def main() -> None:
    """Print a compact result; exit nonzero on SDK errors or incomplete work."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--reference-map', type=Path,
                        help='Require current mapping evidence for this explicit reference-match request')
    args = parser.parse_args()
    try:
        report = preflight(args.project, args.output_dir,
                           args.reference_map.absolute() if args.reference_map else None)
        print(json.dumps({key: report[key] for key in ('status', 'elapsedSeconds',
              'renderApproved', 'qualityApproved')} | {'report': str(args.output_dir / 'result.json'),
              'completion': str(args.output_dir / 'completion.json')}))
        raise SystemExit(1 if report['status'] == 'blocked' else 0)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error), 'renderApproved': False}))
        raise SystemExit(2) from error


if __name__ == '__main__':
    main()
