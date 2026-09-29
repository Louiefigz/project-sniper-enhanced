"""Launch qualification jobs through the public exporter, bounded by one deadline.

Jobs are validated exactly before anything starts: canonical existing projects, new
attempt directories in canonical folders, string arguments passed through unchanged,
and completed reference attempts when required. A concurrent (profile-recording) batch
also requires each project to declare exactly one native plan, since a profile's format,
duration and picture bounds come from it. Concurrent batches start every job at
once; serial batches run one at a time. At the deadline survivors get SIGTERM (their
owners run the normal owned cleanup) and a bounded grace; the harness never SIGKILLs.
"""
from __future__ import annotations

import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import bound_json
from native_work_workload import plan_format
from studio.native_runtime import REPO

EXPORTER = Path(__file__).with_name('native_export.py')
JOB_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
MAXIMUM_JOBS, POLL_SECONDS, GRACE_SECONDS = 16, 0.5, 120.0


@dataclass
class Job:
    """One export: project, new attempt directory, exact exporter arguments, reference."""

    id: str
    project: str
    attempt: str
    args: list
    reference: str | None


@dataclass
class Running:
    """A launched exporter process with its log and monotonic start/end."""

    job: Job
    process: subprocess.Popen
    log: object
    started: float
    ended: float | None = None


def _require(condition: bool, message: str) -> None:
    """Refuse malformed jobs before any export starts."""
    if not condition:
        raise ValueError(message)


def _canonical_directory(value: object) -> bool:
    """An existing directory named by its canonical absolute path."""
    return isinstance(value, str) and Path(value).is_absolute() and Path(value).resolve() == Path(value) \
        and Path(value).is_dir()


def _job(row: object, need_reference: bool) -> Job:
    """Validate one job row exactly; nothing is inferred or defaulted except args."""
    _require(isinstance(row, dict) and set(row) <= {'id', 'project', 'attempt', 'args', 'reference'},
             'job rows take id, project, attempt, args and reference only')
    _require(isinstance(row.get('id'), str) and JOB_ID.fullmatch(row['id']) is not None, 'job id is invalid')
    _require(_canonical_directory(row.get('project')), f"job {row['id']}: project must be a canonical directory")
    attempt = row.get('attempt')
    _require(isinstance(attempt, str) and _canonical_directory(str(Path(attempt).parent))
             and not Path(attempt).exists(), f"job {row['id']}: attempt must be a new path in a canonical folder")
    args = row.get('args', [])
    _require(isinstance(args, list) and all(isinstance(item, str) for item in args), 'job args must be strings')
    reference = row.get('reference')
    _require(not need_reference or (_canonical_directory(reference) and Path(reference, 'delivery.json').is_file()),
             f"job {row['id']}: reference must be a completed attempt directory")
    _require(not need_reference or plan_format(Path(row['project'])) in ('short', 'long'),
             f"job {row['id']}: project must declare exactly one SHORT-PROJECT.json or LONG-PROJECT.json")
    return Job(row['id'], row['project'], attempt, list(args), reference)


def load_jobs(path: Path, need_reference: bool) -> list[Job]:
    """Read the bounded job list; ids and attempt directories must be unique."""
    value = bound_json(path)
    rows = value.get('jobs')
    _require(value.get('schemaVersion') == 1 and isinstance(rows, list) and 1 <= len(rows) <= MAXIMUM_JOBS,
             f'jobs file needs schemaVersion 1 and 1-{MAXIMUM_JOBS} jobs')
    jobs = [_job(row, need_reference) for row in rows]
    _require(len({job.id for job in jobs}) == len(jobs) and len({job.attempt for job in jobs}) == len(jobs),
             'job ids and attempt directories must be unique')
    return jobs


def export_command(job: Job) -> list[str]:
    """The normal public exporter; arguments pass through unchanged."""
    return [sys.executable, '-B', str(EXPORTER), job.project, job.attempt, *job.args]


def launch(job: Job, evidence: Path) -> Running:
    """Start one exporter with its output captured in the evidence folder."""
    log = (evidence / f'{job.id}.log').open('xb')
    process = subprocess.Popen(export_command(job), cwd=REPO, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT)
    return Running(job, process, log, time.monotonic())


def _reap(running: list[Running]) -> None:
    """Stamp each process's end once it has exited."""
    for row in running:
        if row.ended is None and row.process.poll() is not None:
            row.ended = time.monotonic()
            row.log.close()


def wait_all(running: list[Running], until: float) -> bool:
    """Wait to the deadline; then SIGTERM survivors and wait a bounded grace (no SIGKILL)."""
    while time.monotonic() < until and any(row.ended is None for row in running):
        _reap(running)
        time.sleep(POLL_SECONDS)
    _reap(running)
    expired = [row for row in running if row.ended is None]
    for row in expired:
        row.process.send_signal(signal.SIGTERM)
    grace = time.monotonic() + GRACE_SECONDS
    while time.monotonic() < grace and any(row.ended is None for row in running):
        _reap(running)
        time.sleep(POLL_SECONDS)
    return bool(expired)


def _row(item: Running) -> dict:
    """Invocation facts for one job; evidence and comparison are added later."""
    job = item.job
    return {'id': job.id, 'project': job.project, 'attempt': job.attempt, 'args': job.args,
            'reference': job.reference, 'exitCode': item.process.poll(),
            'wallSeconds': None if item.ended is None else item.ended - item.started,
            'supervisorStillRunning': item.ended is None}


def execute(jobs: list[Job], evidence: Path, until: float, concurrent: bool) -> tuple[list[dict], bool]:
    """Run all jobs together, or one after another; never past the deadline."""
    if concurrent:
        running = [launch(job, evidence) for job in jobs]
        expired = wait_all(running, until)
        return [_row(item) for item in running], expired
    rows, expired = [], False
    for job in jobs:
        if expired or time.monotonic() >= until:
            rows.append({'id': job.id, 'attempt': job.attempt, 'status': 'not-started', 'exitCode': None})
            expired = True
            continue
        item = launch(job, evidence)
        expired = wait_all([item], until)
        rows.append(_row(item))
    return rows, expired
