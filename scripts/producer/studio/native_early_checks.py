"""One consolidated early defect report for a built native Short, before previews.

Runs the static package preflight, prepares (or confirms) the sealed whole-program
audio stage, checks font readiness, reports the route canary for the current
engine/runtime/tool identity and seeks the catalog mounts once in the pinned runtime
for premature reveals (report schema 2). Writes ONE ``early-check-report.json``. It never
claims motion, layout, semantic or listening quality; those need rendered review.
Exit status: 0 no early defects found, 1 defects found, 2 incomplete or invalid use.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from audio.mastering_profile import MASTERING_PROFILE_IDENTITIES, NATIVE_SHORT_MASTERING_PROFILE
from cut_preview_io import real_directory, write_new
from studio.native_reveal_probe import RevealProbeOptions, reveal_check, reveal_defects
from studio.native_stage_evidence import require

CLAIMS = {'motionQualityProven': False, 'semanticQualityProven': False, 'layoutQualityProven': False,
          'listeningApproved': False, 'renderApproved': False}


@dataclass(frozen=True)
class EarlyCheckOptions:
    """Explicit inputs; audio bounds come from the caller (and later its budget)."""

    project: Path
    output: Path
    profile: str = NATIVE_SHORT_MASTERING_PROFILE.identity
    search_root: Path | None = None
    canary_fixture: Path | None = None
    reference_map: Path | None = None
    capture_from: Path | None = None
    work_seconds: float = 300.0
    capacity_wait_seconds: float = 600.0


def sdk_findings(sdk: dict) -> list[dict]:
    """Flatten SDK lint errors/warnings and native dependency findings."""
    rows = [{'check': 'staticPreflight', 'severity': row['severity'], 'code': row['code'], 'file': row['file'],
             'message': row['message']} for row in sdk.get('dependencyFindings', [])]
    for result in sdk.get('result', {}).get('results', []):
        rows.extend({'check': 'staticPreflight', 'severity': row.get('severity'), 'code': row.get('code'),
                     'file': result['file'], 'message': row.get('message')}
                    for row in result.get('result', {}).get('findings', []) if row.get('severity') in ('error', 'warning'))
    return rows


def static_check(options: EarlyCheckOptions) -> dict:
    """Run the existing bounded static preflight into this report directory."""
    from studio.native_preflight import preflight
    try:
        report = preflight(options.project, options.output / 'static', options.reference_map)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return {'status': 'failed', 'error': str(error), 'findings': []}
    return {'status': report['status'], 'elapsedSeconds': report['elapsedSeconds'],
            'evidence': str(options.output / 'static'), 'findings': sdk_findings(report['sdk'])}


def audio_check(options: EarlyCheckOptions) -> dict:
    """Confirm a compatible sealed stage by identity, else prepare one here, supervised."""
    from graphics.render_tools import resolve_tools
    from studio.native_audio_contract import audio_input_contract, audio_input_identity
    from studio.native_audio_seal import discover_stage
    from studio.native_audio_stage import AudioStageFailure, AudioStagePlan, prepare_stage
    identity = audio_input_identity(audio_input_contract(options.project, options.profile, resolve_tools()))
    found = discover_stage(options.search_root or options.output.parent, identity)
    if found is not None:
        seal, record = found
        return {'status': 'sealed-compatible', 'seal': str(seal), 'audioInputSha256': identity,
                'masterSha256': record['master']['sha256'], 'audioReviewRequired': record['audioReviewRequired']}
    started = time.monotonic()
    plan = AudioStagePlan(options.project, options.output / 'audio-stage', options.profile,
                          options.work_seconds, options.capacity_wait_seconds)
    try:
        record = prepare_stage(plan)
    except AudioStageFailure as error:
        return {'status': 'failed', 'audioInputSha256': identity, 'error': error.record.get('error'),
                'failure': str(plan.root / 'audio-stage-failed.json'), 'elapsedSeconds': time.monotonic() - started}
    return {'status': 'sealed-new', 'seal': str(plan.root / 'audio-stage.json'), 'audioInputSha256': identity,
            'masterSha256': record['master']['sha256'], 'audioReviewRequired': record['audioReviewRequired'],
            'elapsedSeconds': time.monotonic() - started}


def capture_check(options: EarlyCheckOptions) -> dict:
    """Diagnose an earlier attempt's captured references of this same project, if supplied."""
    if options.capture_from is None:
        return {'status': 'not-run', 'reason': 'Pass --capture-from <preview attempt> to diagnose its captures.'}
    from cut_preview_io import bound_json
    from studio.native_capture_diagnostics import capture_diagnostics
    attempt = options.capture_from.resolve(strict=True)
    if bound_json(attempt / 'export-request.json').get('project') != str(options.project):
        return {'status': 'not-applicable', 'reason': 'The supplied capture belongs to another project revision.'}
    return capture_diagnostics(attempt / 'native-frames.json', options.project)


def canary_check(fixture: Path | None) -> dict:
    """Report whether the route canary passed for the current engine/runtime/tool identity."""
    if fixture is None:
        return {'status': 'not-configured', 'reason': 'Pass --canary-fixture to check the route canary identity.'}
    from studio.native_route_canary import canary_status
    try:
        return canary_status(fixture.resolve(strict=True))
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        return {'status': 'failed', 'error': str(error)}


def capture_defects(report: dict) -> list[dict]:
    """Reverse-seek drift blocks the final gate later; small captured text is a review finding."""
    reverse, text = report.get('reverseSeek'), report.get('phoneText') or {}
    rows = [{'check': 'captureDiagnostics', 'severity': 'warning', 'code': 'captured-text-below-phone-floor', **row}
            for row in text.get('elements', [])]
    if reverse and reverse['status'] != 'reverse-seek-stable':
        rows.append({'check': 'captureDiagnostics', 'severity': 'error', 'code': reverse['status'],
                     'message': f"{reverse.get('failedCount', 0)} of {reverse.get('compared', 0)} reverse seeks "
                                'exceed the final-gate thresholds', 'failed': reverse.get('failed', [])})
    return rows


def defects(checks: dict) -> list[dict]:
    """Consolidate every blocking or reviewable early finding into one list."""
    rows = list(checks['staticPreflight'].get('findings', []))
    if checks['staticPreflight']['status'] == 'failed':
        rows.append({'check': 'staticPreflight', 'severity': 'error', 'code': 'preflight-failed',
                     'message': checks['staticPreflight']['error']})
    if checks['audio']['status'] == 'failed':
        rows.append({'check': 'audio', 'severity': 'error', 'code': 'audio-stage-failed',
                     'message': checks['audio']['error']})
    if checks['audio'].get('audioReviewRequired'):
        rows.append({'check': 'audio', 'severity': 'warning', 'code': 'audio-review-required',
                     'message': 'Shared audio checks returned a review warning; listen before final approval.'})
    rows.extend({'check': 'fonts', 'severity': 'error', **row} for row in checks['fonts']['defects'])
    rows.extend({'check': 'phoneText', 'severity': 'warning', 'code': 'text-declared-below-phone-floor', **row}
                for row in checks['phoneText']['declarations'])
    rows.extend(capture_defects(checks['captureDiagnostics']))
    rows.extend(reveal_defects(checks['revealProbe']))
    if checks['canary']['status'] in ('no-current-pass', 'failed'):
        rows.append({'check': 'canary', 'severity': 'error', 'code': 'canary-not-current',
                     'message': 'No verified route canary pass exists for the current engine/runtime/tools.'})
    return rows


def early_report(options: EarlyCheckOptions) -> dict:
    """Run every early check and publish the one consolidated defect report."""
    from studio.native_font_readiness import font_readiness
    real_directory(options.output.parent)
    require(not options.output.exists() and not options.output.is_relative_to(options.project),
            'early checks need a new directory outside the project')
    options.output.mkdir(mode=0o700)
    started = time.monotonic()
    from studio.native_font_readiness import declared_text_sizes
    static = static_check(options)
    hints = tuple(row for row in static['findings'] if row['severity'] == 'warning')  # lint points where; probe decides
    checks = {'staticPreflight': static, 'audio': audio_check(options),
              'fonts': font_readiness(options.project), 'phoneText': declared_text_sizes(options.project),
              'captureDiagnostics': capture_check(options), 'canary': canary_check(options.canary_fixture),
              'revealProbe': reveal_check(RevealProbeOptions(options.project, options.output / 'reveal', hints))}
    found = defects(checks)
    incomplete = checks['fonts']['status'] == 'incomplete' or checks['canary']['status'] == 'not-configured'
    status = 'defects-found' if any(row['severity'] == 'error' for row in found) else \
        'incomplete' if incomplete else 'no-early-defects-found'
    report = {'schemaVersion': 2, 'scope': 'native-short-early-defect-report', 'status': status,
              'project': str(options.project), 'elapsedSeconds': time.monotonic() - started,
              'defects': found, 'checks': checks, 'claims': CLAIMS}
    write_new(options.output / 'early-check-report.json', report)
    return report


def main() -> None:
    """Parse explicit options and print the report path and status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--audio-profile', choices=MASTERING_PROFILE_IDENTITIES,
                        default=NATIVE_SHORT_MASTERING_PROFILE.identity)
    parser.add_argument('--audio-stage-search', type=Path, help='Directory whose children may hold sealed stages')
    parser.add_argument('--canary-fixture', type=Path, help='TEST route canary fixture root to check')
    parser.add_argument('--reference-map', type=Path)
    parser.add_argument('--capture-from', type=Path, help='Earlier export attempt of this project whose captures to diagnose')
    parser.add_argument('--work-seconds', type=float, default=300.0)
    parser.add_argument('--capacity-wait-seconds', type=float, default=600.0)
    args = parser.parse_args()
    options = EarlyCheckOptions(args.project.resolve(strict=True), args.output.absolute(), args.audio_profile,
                                args.audio_stage_search, args.canary_fixture, args.reference_map,
                                args.capture_from, args.work_seconds, args.capacity_wait_seconds)
    try:
        report = early_report(options)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}))
        raise SystemExit(2) from error
    print(json.dumps({'status': report['status'], 'defects': len(report['defects']),
                      'report': str(options.output / 'early-check-report.json'),
                      'elapsedSeconds': report['elapsedSeconds']}))
    raise SystemExit({'no-early-defects-found': 0, 'defects-found': 1}.get(report['status'], 2))


if __name__ == '__main__':
    main()
