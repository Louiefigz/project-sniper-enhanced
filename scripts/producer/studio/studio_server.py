"""Owned foreground Studio startup, launched detached from the operator CLI.

SDK readiness binds the recorded PID/project/port. The generation manifest
does not track this runtime record; ``parked_record`` hides it during diffs.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import os
import socket
import subprocess
import time
from typing import BinaryIO, Iterator
from graphics.render_tools import resolve_tools

SERVER_RECORD_NAME = ".studio-server.json"
PORT_RANGE = (3990, 3999)
_LOG_REL = os.path.join(".hyperframes", "preview-server.log")
_STARTUP_SECONDS, _CLEANUP_RESERVE, _STARTUP_BYTES = 10.0, 2.0, 65_536


class StudioServerError(RuntimeError):
    """The review lane cannot proceed (inputs, server, or sync module)."""


@dataclasses.dataclass(frozen=True)
class ServerRecord:
    """One launched preview server, as persisted in ``.studio-server.json``."""

    port: int
    pid: int
    url: str
    started_at: str

    def to_json(self) -> dict:
        """The record's on-disk JSON shape."""
        return {"port": self.port, "pid": self.pid, "url": self.url,
                "startedAt": self.started_at}


def record_path(studio_dir: str) -> str:
    """Absolute path of the server record inside one studio project dir."""
    return os.path.join(os.path.abspath(studio_dir), SERVER_RECORD_NAME)


def read_record(studio_dir: str) -> ServerRecord | None:
    """Load the server record, or None when no record file exists.

    Raises:
        StudioServerError: the file exists but cannot be parsed.
    """
    path = record_path(studio_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return ServerRecord(port=int(data["port"]), pid=int(data["pid"]),
                            url=str(data["url"]),
                            started_at=str(data["startedAt"]))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise StudioServerError(
            f"unreadable {SERVER_RECORD_NAME} ({exc}) — remove it and rerun")


def write_record(studio_dir: str, record: ServerRecord) -> None:
    """Persist the record beside the project files."""
    with open(record_path(studio_dir), "w", encoding="utf-8") as handle:
        json.dump(record.to_json(), handle, indent=2, sort_keys=True)
        handle.write("\n")


def remove_record(studio_dir: str) -> None:
    """Delete the record file if present."""
    try:
        os.remove(record_path(studio_dir))
    except FileNotFoundError:
        pass


def _port_available(port: int) -> bool:
    """Probe the same loopback address without nesting the range traversal."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def pick_free_port(port_range: tuple[int, int] = PORT_RANGE) -> int:
    """First locally bindable port in the inclusive review-lane range.

    Raises:
        StudioServerError: every port in the range is occupied.
    """
    low, high = port_range
    for port in range(low, high + 1):
        if _port_available(port):
            return port
    raise StudioServerError(
        f"no free preview port in {low}-{high} — stop stale servers "
        "(studio_review.py stop) or free the range")


def pid_command(pid: int) -> str | None:
    """The pid's full command line via ``ps``; None when the pid is gone."""
    proc = subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                          capture_output=True, text=True, check=False)
    line = proc.stdout.strip()
    return line or None


def command_is_preview(command: str, studio_dir: str, port: int) -> bool:
    """Whether a ps command line is OUR preview server.

    Ours = the hyperframes CLI's ``preview`` subcommand serving THIS studio
    directory on the recorded port. Marker-substring matching alone (BUG-6)
    also matched a ``tail -f`` of the preview log and another project's
    preview on a recycled pid — stop would have SIGTERMed those.
    """
    tokens = command.split()
    if not tokens or os.path.basename(tokens[0]) != "node" \
            or not any("hyperframes" in token for token in tokens):
        return False
    signature = f" preview {os.path.abspath(studio_dir)} --port {port}"
    return signature + " " in command or command.endswith(signature)


def is_live_preview(studio_dir: str, record: ServerRecord) -> bool:
    """Whether the recorded pid is alive AND still our preview server."""
    command = pid_command(record.pid)
    return bool(command) and command_is_preview(command, studio_dir,
                                                record.port)


def _startup_remaining(deadline: float, reserve: float = _CLEANUP_RESERVE) -> float:
    """Borrow the same startup cutoff, leaving time to reap a failed child."""
    remaining = deadline - time.monotonic() - reserve
    if remaining <= 0:
        raise StudioServerError("Studio preview startup deadline exhausted")
    return remaining


def local_sdk_environment() -> tuple[str, dict[str, str]]:
    """Reject runtime overrides and pin local tools retaining ps-based ownership."""
    environment = dict(os.environ)
    if environment.get("HYPERFRAME_RUNTIME_URL", "").strip():
        raise StudioServerError("unsupported Studio runtime override: unset HYPERFRAME_RUNTIME_URL "
                                "to use the installed, pinned runtime")
    tools = resolve_tools()
    for name in ("node", "browser", "ffmpeg", "ffprobe"):
        path = tools[name]
        if not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise StudioServerError(f"installed Studio {name} is unavailable: {path}")
    if os.path.basename(tools["node"]) != "node" or any(char.isspace() for char in tools["node"]):
        raise StudioServerError("unsupported Studio Node pin: require whitespace-free executable named node")
    return tools["node"], {**environment, "HYPERFRAMES_PREVIEW_HOST": "127.0.0.1",
        "SNIPER_NODE_PATH": tools["node"], "HYPERFRAMES_BROWSER_PATH": tools["browser"],
        "PRODUCER_HEADLESS_SHELL_PATH": tools["browser"],
        "HYPERFRAMES_FFMPEG_PATH": tools["ffmpeg"], "HYPERFRAMES_FFPROBE_PATH": tools["ffprobe"],
        "HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_NO_AUTO_INSTALL": "1",
        "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}


def _validate_ready(value: object, expected: tuple[str, int, int]) -> None:
    """Accept only the SDK's own started foreground PID, project and port."""
    studio_dir, port, pid = expected
    if type(value) is not dict or set(value) != {"schemaVersion", "operation", "ok", "result"} \
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["operation"] != "start" or value["ok"] is not True:
        raise StudioServerError("Studio preview did not report successful startup")
    result = value["result"]
    required = {"state", "mode", "projectName", "projectDir", "host", "port", "pid",
                "serverUrl", "studioUrl", "ready"}
    if type(result) is not dict or set(result) != required \
            or any(result[key] != item for key, item in {
                "state": "started", "mode": "foreground", "projectDir": studio_dir,
                "host": "127.0.0.1", "port": port, "pid": pid,
                "serverUrl": f"http://127.0.0.1:{port}", "ready": True}.items()) \
            or type(result["port"]) is not int or type(result["pid"]) is not int \
            or result["ready"] is not True:
        raise StudioServerError("Studio preview readiness has foreign PID/project/port or reused mode")


def _started_record(data: bytes, expected: tuple[str, int, int]) -> bool:
    """Read complete SDK lifecycle lines; a truncated line is never readiness."""
    for line in data.split(b"\n")[:-1]:
        if not line.startswith(b"{"):
            continue
        value = json.loads(line)
        if type(value) is not dict or value.get("operation") != "start":
            continue
        _validate_ready(value, expected)
        return True
    return False


def _wait_ready(proc: subprocess.Popen, log: BinaryIO, context: tuple) -> None:
    """Hold the original log offset and one cutoff across bounded startup reads."""
    studio_dir, port, offset, deadline = context
    data = b""
    while True:
        _startup_remaining(deadline)
        if proc.poll() is not None:
            raise StudioServerError("Studio preview exited before readiness")
        data += os.pread(log.fileno(), _STARTUP_BYTES + 1 - len(data), offset + len(data))
        _startup_remaining(deadline)
        if len(data) > _STARTUP_BYTES:
            raise StudioServerError("Studio preview startup output exceeds its bound")
        ready = _started_record(data, (studio_dir, port, proc.pid))
        _startup_remaining(deadline)
        if ready and proc.poll() is not None:
            raise StudioServerError("Studio preview exited after readiness")
        if ready:
            return
        time.sleep(min(0.05, _startup_remaining(deadline)))


def _stop_failed_preview(proc: subprocess.Popen, deadline: float) -> None:
    """Terminate only this call's owned child within the original startup cap."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=min(0.5, max(0, deadline - time.monotonic())))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=max(0, deadline - time.monotonic()))


def _failed_launch(proc: subprocess.Popen, deadline: float, publication: tuple) -> None:
    """Remove only this launch's record; always attempt to reap its own child."""
    studio_dir, record, published = publication
    try:
        if published and read_record(studio_dir) == record:
            remove_record(studio_dir)
    finally:
        _stop_failed_preview(proc, deadline)


def launch_preview(cli: str, studio_dir: str, port: int, open_browser: bool = True) -> ServerRecord:
    """Keep an owned foreground PID; publish only exact SDK-confirmed readiness.

    Browser auto-open stays on. Failed, reused or fallback-port launches do not
    become records; only this call's own child is stopped on startup failure.
    """
    deadline = time.monotonic() + _STARTUP_SECONDS
    if not os.path.isfile(cli):
        raise StudioServerError(f"pinned hyperframes CLI missing: {cli}")
    node, environment = local_sdk_environment()
    studio_dir = os.path.abspath(studio_dir)
    log_path = os.path.join(studio_dir, _LOG_REL)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a+b") as log:
        offset = log.tell()
        _startup_remaining(deadline)
        proc = subprocess.Popen(
            [node, cli, "preview", studio_dir, "--port", str(port), "--foreground", "--json"]
            + ([] if open_browser else ["--no-open"]),
            cwd=studio_dir, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True, env=environment)
        published = False
        record = None
        try:
            _wait_ready(proc, log, (studio_dir, port, offset, deadline))
            record = ServerRecord(port, proc.pid,
                f"http://localhost:{port}/#project/{os.path.basename(studio_dir)}",
                datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
            _startup_remaining(deadline)
            write_record(studio_dir, record)
            published = True
            _startup_remaining(deadline)
            return record
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt):
            _failed_launch(proc, deadline, (studio_dir, record, published))
            raise


@contextlib.contextmanager
def parked_record(studio_dir: str) -> Iterator[ServerRecord | None]:
    """Remove ``.studio-server.json`` for the block, restore it afterwards.

    Manifest diffs (``view_manifest.unsynced_changes``, the generator's
    overwrite guard, the sync differ) would misread the record as an
    unexpected Studio edit; parking keeps those checks clean while the
    server itself keeps running.
    """
    record = read_record(studio_dir)
    remove_record(studio_dir)
    try:
        yield record
    finally:
        if record is not None and os.path.isdir(studio_dir) \
                and read_record(studio_dir) is None:
            write_record(studio_dir, record)
