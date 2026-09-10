"""TEST-only original-clock process/evidence scope for the1080p sample benchmark."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from _guided_presenter_observation_fixture import held
from guided_presenter_probe_identity import HeldPresenterProbeFile, presenter_stat_identity
from headless.process_runner import ProcessRequest, run_text
from opening_prefix_contract import HeldPrefixInput, verify_held_input
from opening_prefix_presenter import _file_record
from render_effect_discovery import local_python_import_closure

COHORT_SECONDS = 300
PROCESS_SECONDS = 60


class BenchmarkClock:
    """One fixed allowance, including setup; no request/environment/retry override."""

    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        """Capture the original origin before any temporary files or source preparation."""
        self.now = now
        self.started = now()
        self.end = self.started + COHORT_SECONDS

    def remaining(self) -> float:
        """Reject expiry rather than returning a renewed per-stage allowance."""
        remaining = self.end - self.now()
        if remaining <= 0:
            raise RuntimeError("TEST1080p original300s benchmark deadline expired")
        return remaining

    def process_seconds(self, requested: float = PROCESS_SECONDS) -> float:
        """Every child has the stricter original remainder and fixed60s maximum."""
        if type(requested) not in (int, float) or not 0 < requested <= COHORT_SECONDS:
            raise ValueError("TEST benchmark process allowance is invalid")
        return min(PROCESS_SECONDS, requested, self.remaining())


class BenchmarkIO:
    """Retain actual command output, byte references, failure timing and source pins."""

    def __init__(self, clock: BenchmarkClock) -> None:
        """Use only installed local tools and one fresh retained TEST root."""
        self.clock = clock
        self.root = Path(tempfile.mkdtemp(prefix="sniper-presenter-1080p-", dir="/private/tmp"))
        self.records: list[dict] = []
        self.references: list[HeldPresenterProbeFile] = []
        self.stage = "setup"
        self.ffmpeg = self._tool("ffmpeg")
        self.ffprobe = self._tool("ffprobe")
        print(f"TEST1080p benchmark root: {self.root}", flush=True)

    def _tool(self, name: str) -> HeldPresenterProbeFile:
        """Hash the installed executable; no install, network or environment override."""
        self.clock.remaining()
        found = shutil.which(name)
        if found is None:
            raise RuntimeError(f"TEST benchmark requires installed {name}")
        return self.hold(Path(found).resolve(strict=True))

    def hold(self, path: Path) -> HeldPresenterProbeFile:
        """Link actual original bytes to stat identity once, before their observation."""
        self.clock.remaining()
        row = held(path)
        self.references.append(row)
        self.clock.remaining()
        return row

    def hold_code(self, paths: list[Path]) -> None:
        """Capture benchmark/production import closure before source/media work."""
        for path in local_python_import_closure(paths):
            self.hold(path)

    def guard(self) -> None:
        """Cheap phase-boundary stat checks, not a source rehash inside frame loops."""
        self.clock.remaining()
        for row in self.references:
            path = Path(row.path)
            if str(path.resolve(strict=True)) != row.path or presenter_stat_identity(path.lstat()) != row.stat_identity:
                raise RuntimeError("TEST benchmark held source/tool/code changed")
        self.clock.remaining()

    def request(self, command: list[str], maximum: int = 1024 * 1024) -> ProcessRequest:
        """Construct the existing strict bounded process request without changing encoding."""
        return ProcessRequest(tuple(command), "", str(self.root), {"LANG": "C", "LC_ALL": "C", "TZ": "UTC"},
            self.clock.process_seconds(), max_output_bytes=maximum)

    def execute(self, request: ProcessRequest) -> subprocess.CompletedProcess:
        """Capture unchanged owned runner success/failure; never retry a timed-out sample."""
        self.guard()
        bounded = replace(request, timeout_seconds=self.clock.process_seconds(request.timeout_seconds))
        name = f"{len(self.records):03d}-{self.stage}"
        row = {"name": name, "stage": self.stage, "argv": list(bounded.command),
               "timeoutSeconds": bounded.timeout_seconds, "startedSeconds": time.monotonic() - self.clock.started}
        self.records.append(row)
        started = time.monotonic()
        try:
            result = run_text(bounded)
        except BaseException as error:
            row.update(elapsedSeconds=time.monotonic() - started, error=f"{type(error).__name__}: {error}")
            raise
        row.update(elapsedSeconds=time.monotonic() - started, returncode=result.returncode)
        (self.root / f"{name}.stdout").write_text(result.stdout)
        (self.root / f"{name}.stderr").write_text(result.stderr)
        self.guard()
        if result.returncode or result.stderr:
            raise RuntimeError("TEST benchmark command failed/diagnosed: " + result.stderr[-2000:])
        return result

    def final_hashes(self) -> None:
        """Rehash all exact held files once at final completion under original remainder."""
        for row in self.references:
            identity = verify_held_input(HeldPrefixInput(row.path, row.sha256, row.size_bytes), self.clock)
            if identity != row.stat_identity:
                raise RuntimeError("TEST benchmark final bytes/stat differ from original hold")

    def report(self, value: dict) -> None:
        """Retain failures as well as completed work; reporting never launches more work."""
        result = {**value, "commands": self.records, "references": [_file_record(row) for row in self.references],
            "elapsedSeconds": time.monotonic() - self.clock.started, "cohortLimitSeconds": COHORT_SECONDS,
            "processLimitSeconds": PROCESS_SECONDS, "noRetry": True, "productionPerformanceQualified": False}
        (self.root / "TEST-benchmark-evidence.json").write_text(json.dumps(result, indent=2) + "\n")


def observed_group_absence(path: Path) -> dict:
    """Read exact existing runner ledger; unknown or reused/live groups stay unproved."""
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    spawned = [row["pid"] for row in rows if row.get("event") == "spawned"]
    reaped = [row["pid"] for row in rows if row.get("event") == "reaped"]
    complete = bool(spawned) and spawned == reaped and len(spawned) == len([r for r in rows if r.get("event") == "intent"])
    absent = []
    for pid in spawned:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            absent.append(pid)
        except PermissionError:
            continue
    return {"ledger": str(path), "spawned": spawned, "reaped": reaped, "observedAbsent": absent,
            "exactGroupsAbsent": complete and spawned == absent, "scope": "actual-local-owned-groups-no-Docker"}
