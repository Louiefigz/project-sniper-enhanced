"""Qualify the host work pool with real concurrent exports and write the host record.

  show    host identity, the pool mode it currently yields and the policy constants
  serial  run each job alone through the public exporter (references, serial baseline)
  run     run every job together under a qualification session of --heavy-slots N,
          compare each output with its serial reference; with --record, add one versioned
          profile to the host's schema-2 record (studio/pool_qualification_profile.py) only
          when every job passed as a complete, non-reused full export, matched its
          reference, N jobs held heavy work at the same instant, every job recorded its
          format, duration, picture size and source-cache state, the engine identity was
          unchanged from start to end, and a --class-mix mixed claim is backed by the jobs'
          own audio-stage owners overlapping heavy owners
Jobs file: {"schemaVersion": 1, "jobs": [{"id", "project", "attempt", "args", "reference"}]}.
Each job runs studio/native_export.py <project> <attempt> <args...>; the harness never edits
projects. Every wait is bounded by the required --deadline-seconds; at the deadline the
harness sends SIGTERM (never SIGKILL) and waits a bounded grace. Serial references must
differ from the concurrent batch in an auto-resume policy field (for example a distinct
--cache), or the exporter resumes their completed media and the job reports reused work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native_work_lease as lease_module  # noqa: E402
import native_work_pool_policy as policy  # noqa: E402
import native_work_qualification as qualification  # noqa: E402
import native_work_workload as workloads  # noqa: E402
from cut_preview_io import real_directory, write_new  # noqa: E402
from headless.durable_files import DurableFileError  # noqa: E402
from native_work_session import open_session  # noqa: E402
from studio.native_runtime import digest  # noqa: E402
from studio.pool_qualification_runner import GRACE_SECONDS, execute, load_jobs  # noqa: E402
from studio.pool_qualification_compare import compare_job, reused_work  # noqa: E402
from studio.pool_qualification_evidence import batch_evidence, studio_views  # noqa: E402
from studio.pool_qualification_profile import profile_refusals, write_profile  # noqa: E402

def _judge(row: dict, session_nonce: str | None) -> dict:
    """Pass only a clean, complete, reference-matched run admitted under the session."""
    attempt = Path(row['attempt'])
    if not (attempt / 'delivery.json').is_file():
        return {**row, 'passed': False, 'referenceMatched': False, 'problems': ['no delivery receipt']}
    comparison = compare_job(attempt, Path(row['reference'])) if row.get('reference') else {}
    reused = reused_work(attempt)
    modes = {owner['mode'] for owner in row['owners']}
    problems = list(comparison.get('problems', []))
    problems += [f'reused work: {", ".join(reused)}'] if reused else []
    problems += [f'owners admitted outside the qualification session: {sorted(modes)}'] \
        if session_nonce and modes != {'qualification-session'} else []
    problems += ['exporter failed or owners lacked verified cleanup'] \
        if row['exitCode'] != 0 or not row['allOwnersCleanupVerified'] else []
    return {**row, 'comparison': comparison, 'reusedWork': reused, 'problems': problems,
            'referenceMatched': comparison.get('referenceMatched') is True, 'passed': not problems}


def summarize(jobs: list[dict], context: dict) -> dict:
    """Evidence summary for serial or concurrent batches."""
    attempts = {row['id']: Path(row['attempt']) for row in jobs}
    evidence = batch_evidence([row for row in jobs if row.get('status') != 'not-started'], attempts)
    if context.get('judge'):
        evidence['jobs'] = [_judge(row, context.get('session')) for row in evidence['jobs']]
    judged = evidence['jobs']
    return {'schemaVersion': 1, 'kind': 'sniper-native-pool-qualification-summary', **context,
            'host': policy.host_identity(), 'policy': policy.policy_identity(),
            'harness': {'path': str(Path(__file__).resolve()), 'sha256': digest(Path(__file__).resolve())},
            'createdAt': datetime.now(timezone.utc).isoformat(), **evidence,
            'allJobsPassed': bool(judged) and len(judged) == len(jobs) and all(row.get('passed') for row in judged),
            'fullExports': bool(judged) and all(row['fullExport'] for row in judged)}


def record_refusals(summary: dict, slots: dict) -> list[str]:
    """Every reason the evidence cannot become the host's pool size."""
    reasons = ['the batch exceeded its deadline'] if summary['deadlineExceeded'] else []
    reasons += [f"failed jobs: {[row['id'] for row in summary['jobs'] if not row.get('passed')]}"] \
        if not summary['allJobsPassed'] else []
    reasons += ['only complete final exports can qualify the pool'] if not summary['fullExports'] else []
    if summary['peakConcurrentJobs'] < slots['heavy']:
        reasons.append(f"only {summary['peakConcurrentJobs']} job(s) held heavy work together, not {slots['heavy']}")
    return reasons


def _evidence_directory(path: Path) -> Path:
    """A new private evidence folder inside an existing canonical folder."""
    path = path.absolute()
    real_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise ValueError('The evidence directory must be new')
    path.mkdir(mode=0o700)
    return path


def _deadline(seconds: float) -> float:
    """One explicit monotonic bound for the whole batch."""
    if not 60 <= seconds <= 21600:
        raise ValueError('--deadline-seconds must be between 60 and 21600')
    return time.monotonic() + seconds


def _publish(evidence: Path, name: str, value: dict) -> str:
    """Write one immutable evidence file and return its digest."""
    write_new(evidence / name, value)
    return hashlib.sha256((evidence / name).read_bytes()).hexdigest()


def _profile_view(profile: dict, engine: str) -> dict:
    """What one committed profile covers and whether it matches this checkout's engine."""
    bound = profile['engine']['identity'] if profile['engine'] else None
    return {'id': profile['id'], 'legacy': profile['legacy'], 'slots': profile['slots'], 'engine': bound,
            'engineMatches': None if bound is None else bound == engine, 'workload': profile['workload']}


def command_show(_args: argparse.Namespace) -> int:
    """Print host identity, the committed profiles, what a Short render forecast gets and the policy."""
    host = policy.host_identity()
    record, engine = qualification.committed(host), workloads.current_engine()
    # A Short render whose length is not yet known (M-031: the call omitted the required output_seconds).
    forecast = qualification.mode_for(record, workloads.forecast_workload(engine, None))[0]
    print(json.dumps({'host': host, 'policy': policy.policy_identity(), 'engine': engine,
                      'record': record.source, 'rejected': record.rejected,
                      'profiles': [_profile_view(profile, engine) for profile in record.profiles],
                      'shortRenderForecast': {'name': forecast.name, 'slots': forecast.slots,
                                              'rejected': forecast.rejected, 'record': forecast.record},
                      'stateRoot': str(lease_module.state_root()),
                      'recordDirectory': str(qualification.record_directory())}, indent=2))
    return 0


def _batch(args: argparse.Namespace, jobs: list, concurrent: bool) -> tuple[Path, list[dict], dict]:
    """Create evidence, run the batch and return rows plus summary context."""
    evidence = _evidence_directory(args.evidence)
    _publish(evidence, 'jobs.json', {'schemaVersion': 1, 'jobs': [vars(job) for job in jobs]})
    until = _deadline(args.deadline_seconds)
    views, started = studio_views(), time.monotonic()
    rows, expired = execute(jobs, evidence, until, concurrent)
    return evidence, rows, {'deadlineSeconds': args.deadline_seconds, 'deadlineExceeded': expired,
                            'batchWallSeconds': time.monotonic() - started, 'evidenceDirectory': str(evidence),
                            'studioViewsAtStart': views, 'studioViewsAtEnd': studio_views()}


def command_serial(args: argparse.Namespace) -> int:
    """Run each job alone under the normal pool rules; no record is ever written."""
    jobs = load_jobs(args.jobs, need_reference=False)
    evidence, rows, context = _batch(args, jobs, concurrent=False)
    summary = summarize(rows, {'mode': 'serial', 'judge': True, **context})
    _publish(evidence, 'summary.json', summary)
    print(json.dumps({key: summary[key] for key in ('mode', 'allJobsPassed', 'batchWallSeconds',
                                                    'deadlineExceeded', 'evidenceDirectory')}))
    return 0 if summary['allJobsPassed'] and not summary['deadlineExceeded'] else 1


def _record(args: argparse.Namespace, summary: dict, summary_sha: str, refusals: list[str]) -> dict:
    """Write the batch's profile when requested and nothing refuses it; report either way."""
    if not args.record or refusals:
        return {'requested': args.record, 'written': False, 'refusals': refusals}
    try:
        written = write_profile(summary, summary_sha, args.class_mix)
    except (ValueError, OSError, DurableFileError) as error:  # PoolRecordError is a ValueError
        return {'requested': True, 'written': False, 'refusals': [f'record refused: {type(error).__name__}: {error}']}
    return {'requested': True, 'written': True, 'refusals': [], **written}


def command_run(args: argparse.Namespace) -> int:
    """Run all jobs under a session; record a profile only from complete passing evidence."""
    jobs = load_jobs(args.jobs, need_reference=True)
    slots = {'heavy': args.heavy_slots, 'audio': args.audio_slots}
    configuration = {'heavySlots': slots['heavy'], 'audioSlots': slots['audio']}
    engine = workloads.engine_record()  # frozen before any export starts
    session = open_session(configuration, [{'project': job.project, 'attempt': job.attempt} for job in jobs],
                           args.deadline_seconds + GRACE_SECONDS + 60)
    try:
        evidence, rows, context = _batch(args, jobs, concurrent=True)
    finally:
        session.close()
    summary = summarize(rows, {'mode': 'concurrent', 'judge': True, 'configuration': configuration,
                               'classMix': args.class_mix, 'engine': engine,
                               'session': session.value['nonce'], **context})
    summary_sha = _publish(evidence, 'summary.json', summary)
    refusals = record_refusals(summary, slots) + profile_refusals(summary, args.class_mix,
                                                                  (engine, workloads.engine_record()))
    result = _record(args, summary, summary_sha, refusals)
    _publish(evidence, 'record-result.json', result)
    print(json.dumps({'allJobsPassed': summary['allJobsPassed'], 'peakConcurrentJobs': summary['peakConcurrentJobs'],
                      'batchWallSeconds': summary['batchWallSeconds'], 'record': result,
                      'evidenceDirectory': str(evidence)}))
    return 0 if summary['allJobsPassed'] and (result['written'] or not args.record) else 1


def main() -> None:
    """Parse one command; every batch needs explicit jobs, evidence folder and deadline."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('show')
    for name in ('serial', 'run'):
        command = commands.add_parser(name)
        command.add_argument('--jobs', type=Path, required=True)
        command.add_argument('--evidence', type=Path, required=True)
        command.add_argument('--deadline-seconds', type=float, required=True)
        if name == 'run':
            command.add_argument('--heavy-slots', type=int, required=True)
            command.add_argument('--audio-slots', type=int, default=1)
            command.add_argument('--class-mix', choices=('heavy-only', 'mixed'), required=True)
            command.add_argument('--record', action='store_true')
    args = parser.parse_args()
    handler = {'show': command_show, 'serial': command_serial, 'run': command_run}[args.command]
    raise SystemExit(handler(args))


if __name__ == '__main__':
    main()
