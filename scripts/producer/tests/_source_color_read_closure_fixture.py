"""Tiny actual AST/hash inventory entirely beneath an owned canonical TEST root.

These Python-looking files are parsed only, never imported or executed. No
repository code, interpreter, original source media or dependency is mutated.
The lock/media rows are explicit fixture data, not production authentication.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from collections.abc import Iterator
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import patch

from cut_preview_io import digest
from guided_body_execution import BodyHeldFile, _identity
from guided_opening_execution import OpeningExecutionClock
import guided_opening_pipeline as pipeline
import render_effect_discovery as discovery


class ReadClosureFixture:
    """One shared media dependency and two additional current read-only imports."""

    def __init__(self) -> None:
        """Author new-only inert files and retain their independently calculated hashes."""
        self.temporary = tempfile.TemporaryDirectory(prefix="source-color-read-closure-TEST-")
        self.root = Path(self.temporary.name).resolve()
        self.producer = self.root / "scripts/producer"
        self.producer.mkdir(parents=True, mode=0o700)
        sources = {"guided_opening_pipeline.py": b"# TEST root marker, never executed\n",
            "guided_opening_media.py": b"import shared\n", "shared.py": b"VALUE = 1\n",
            "guided_opening_read.py": b"import shared\nimport read_leaf\n",
            "read_leaf.py": b"VALUE = 2\n"}
        self.paths, rows = {}, []
        for name, raw in sources.items():
            target = self.producer / name
            with target.open("xb") as stream:
                stream.write(raw)
            target.chmod(0o600)
            self.paths[name] = target
            rows.append({"path": str(target.relative_to(self.root)), "hash": hashlib.sha256(raw).hexdigest()})
        self.lock = {"schemaVersion": 1, "state": "pinned", "runId": "TEST", "files": sorted(rows, key=lambda row: row["path"])}
        self.lock["digest"] = digest(self.lock["files"])
        self.executed = {"executionClosure": [{"path": row["path"], "sha256": row["hash"]}
            for row in rows if Path(row["path"]).name in {"guided_opening_media.py", "shared.py"}]}
        self.clock, self.held, self.calls = OpeningExecutionClock(1300.0), (), 0

    def leaves(self) -> ExitStack:
        """Use the real static walker against only this TEST directory, not current code."""
        stack = ExitStack()
        stack.enter_context(patch.object(pipeline, "__file__", str(self.paths["guided_opening_pipeline.py"])))
        stack.enter_context(patch.object(discovery, "PRODUCER_ROOT", self.producer))
        return stack

    def capture(self, refs: tuple) -> None:
        """Capture actual original stat evidence before verification callbacks, no extra hash."""
        for path, sha in refs:
            self.capture_one(path, sha)

    def capture_one(self, path: Path, sha: str) -> None:
        """Retain an addition before its first AST read; never replace an old baseline."""
        self.guard()
        row = BodyHeldFile(path, sha, _identity(path.lstat()))
        previous = next((held for held in self.held if held.path == path), None)
        if previous is not None and previous != row:
            raise RuntimeError("TEST attempted to rebaseline original read addition")
        if previous is None:
            self.held += (row,)

    def guard(self) -> None:
        """An actual finite same-cutoff guard detects any changed previously captured file."""
        self.calls += 1
        self.clock.remaining()
        if any(_identity(row.path.lstat()) != row.identity for row in self.held):
            raise RuntimeError("TEST original captured read closure changed")
        self.clock.remaining()

    def change(self, name: str, raw: bytes | None = None) -> None:
        """Fault only one original regular single-link canonical TEST file by exact name."""
        target = self._target(name)
        target.write_bytes(target.read_bytes() if raw is None else raw)

    def _target(self, name: str) -> Path:
        """Resolve only an initial allowlisted canonical owned single-link TEST file."""
        if name not in self.paths:
            raise RuntimeError("TEST mutation name is not allowlisted")
        target = self.paths[name]
        if target.resolve(strict=True) != target or not target.is_relative_to(self.root):
            raise RuntimeError("TEST mutation escaped original root")
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("TEST mutation is not owned regular single-link metadata")
        return target

    @contextmanager
    def temporarily_absent(self, name: str) -> Iterator[None]:
        """Temporarily park one exact inert TEST file without deleting or overwriting it."""
        target = self._target(name)
        parked = target.with_name(target.name + ".TEST-parked")
        if parked.exists():
            raise RuntimeError("TEST parked path must be new-only")
        target.rename(parked)
        try:
            yield
        finally:
            if target.exists():
                raise RuntimeError("TEST restore would overwrite an unexpected file")
            parked.rename(target)

    def cleanup(self) -> None:
        """Remove only the exact temporary tree created by this fixture."""
        self.temporary.cleanup()
