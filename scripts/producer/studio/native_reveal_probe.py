"""The runtime reveal probe as one early check (MASTER-PLAN M-068, P2-EARLY-CHECKS P2-03).

For a built native Short that mounts catalog compositions, ``reveal_check`` writes a graphics-only probe project
with the TS CLI (``native-short.ts reveal-probe-project``), then seeks it once in the pinned runtime under the
shared owned-inspection supervision (``owned_inspection.run_inspection``: NativeRun lane, deadline, capacity wait,
cleanup verification, pinned implementation) and reads the owner-captured result. ``reveal_defects`` turns every
finding into a blocking defect; a probe that did not run is a blocking defect too, never a pass. A matching
``gsap_timeline_set_initial_hide`` lint warning travels with a finding as a hint (the lint points where; the probe
decides). The worker entry (``--worker``) runs ``native_reveal_probe.mjs`` under the live owner only.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import bound_json, run_bounded, write_new
from studio.native_stage_evidence import require

HERE = Path(__file__).resolve()
PROBE = HERE.with_name('native_reveal_probe.mjs')
REPO = HERE.parents[3]
LINT_HINT = 'gsap_timeline_set_initial_hide'
PROJECT_SECONDS = 60
PROBE_SECONDS = 300
PROBE_STATUSES = {True: 'premature-reveal-found', False: 'reveal-probe-pass'}
FAILURES = (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError)


@dataclass(frozen=True)
class RevealProbeOptions:
    """One probe of a built project into a new output directory, with the static lint warnings as hints."""

    project: Path
    output: Path
    lint_warnings: tuple[dict, ...] = ()


def _write_probe_project(options: RevealProbeOptions, tools: dict, environment: dict) -> Path:
    """Write the graphics-only probe project with the TS CLI; a refusal names its reason."""
    project = options.output / 'project'
    completed = subprocess.run(
        [tools['node'], '--import', 'tsx', str(REPO / 'scripts/producer/native-short.ts'), 'reveal-probe-project',
         str(options.project), str(project)],
        cwd=REPO, env=environment, capture_output=True, text=True, timeout=PROJECT_SECONDS, check=False)
    require(completed.returncode == 0, f'reveal probe project refused: {completed.stderr[-2048:]}')
    return project


def _checked_result(report: dict) -> dict:
    """Fail closed on a result the probe could not have written, or whose status disagrees with its findings."""
    findings = report.get('findings')
    require(report.get('schemaVersion') == 1 and report.get('scope') == 'native-reveal-probe'
            and type(findings) is list and type(report.get('visibleAtMount')) is list
            and report.get('status') == PROBE_STATUSES[bool(findings)],
            'reveal probe result is malformed or its status disagrees with its findings')
    return report


def _probe(options: RevealProbeOptions) -> dict:
    """Write the probe project, run the owned inspection, and read the owner-captured result."""
    from studio.native_run_config import local_environment
    from studio.native_runtime import install_runtime
    from studio.owned_inspection import read_inspection, run_inspection
    options.output.mkdir(mode=0o700)
    tools, environment = local_environment()
    project = _write_probe_project(options, tools, environment)
    reference = run_inspection(HERE, options.output / 'probe', {'project': str(project), 'runtime': str(install_runtime())})
    report = _checked_result(read_inspection(reference, require_owner_digest=True))
    manifest = bound_json(project / 'REVEAL-PROBE.json')
    return {'status': report['status'], 'evidence': reference['path'], 'resultSha256': reference['sha256'],
            'findings': report['findings'], 'visibleAtMount': report['visibleAtMount'],
            'mounts': [{'id': row['id'], 'file': row['file']} for row in manifest['mounts']],
            'lintWarnings': list(options.lint_warnings)}


def reveal_check(options: RevealProbeOptions) -> dict:
    """Probe the project's catalog mounts; not applicable without any, and ``failed`` (blocking) if it cannot run.

    Args:
        options: The built project, a new output directory and the static lint warnings.

    Returns:
        The ``revealProbe`` entry of the early report.
    """
    started = time.monotonic()
    try:
        if not bound_json(options.project / 'SHORT-PROJECT.json').get('catalogFiles'):
            return {'status': 'not-applicable', 'reason': 'no catalog mounts'}
        return {**_probe(options), 'elapsedSeconds': time.monotonic() - started}
    except FAILURES as error:
        return {'status': 'failed', 'error': str(error), 'elapsedSeconds': time.monotonic() - started}


def _lint_hint(warnings: list[dict], file: str | None) -> dict | None:
    """The first ``gsap_timeline_set_initial_hide`` warning for the finding's composition file, if any."""
    return next((row for row in warnings if row.get('code') == LINT_HINT and row.get('file') == file), None)


def _defect(finding: dict, hint: dict | None) -> dict:
    """One blocking early defect for one probe finding."""
    before, after = finding['opacity']
    return {'check': 'revealProbe', 'severity': 'error', 'code': 'premature-reveal', 'condition': finding['condition'],
            **{key: finding[key] for key in ('mount', 'element', 'frame', 'localFrame', 'order', 'opacity')},
            'lintHint': hint,
            'message': f"Premature reveal ({finding['condition']}) in mount {finding['mount']}: element "
                       f"{finding['element']} at frame {finding['frame']} (local {finding['localFrame']}, "
                       f"{finding['order']} seek), opacity {before} then {after}"}


def reveal_defects(report: dict) -> list[dict]:
    """Every probe finding as a blocking defect; a probe that did not run is one blocking ``reveal-probe-failed``.

    Args:
        report: The ``revealProbe`` entry written by ``reveal_check``.

    Returns:
        Defect rows for the early report (none when the probe passed or was not applicable).
    """
    if report['status'] == 'failed':
        return [{'check': 'revealProbe', 'severity': 'error', 'code': 'reveal-probe-failed', 'message': report['error']}]
    files = {row['id']: row['file'] for row in report.get('mounts', [])}
    return [_defect(row, _lint_hint(report.get('lintWarnings', []), files.get(row['mount'])))
            for row in report.get('findings', [])]


def worker(file: Path) -> None:
    """Run the Node probe under its live inspection owner and publish its report as the owned result.

    Args:
        file: The inspection request that ``run_inspection`` wrote and pinned.
    """
    from studio.owned_inspection import require_worker
    request = require_worker(file, HERE)
    completed = run_bounded([request['tools']['node'], str(PROBE), str(file)], timeout=PROBE_SECONDS)
    require(completed.returncode == 0,
            f"reveal probe failed: {completed.stderr.decode('utf-8', errors='replace')[-2048:]}")
    require_worker(file, HERE)
    write_new(file.parent / 'result.json', bound_json(file.parent / 'reveal' / 'reveal-probe.json'))


def main() -> None:
    """Worker entry only: the early report runs ``reveal_check`` in process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker)


if __name__ == '__main__':
    main()
