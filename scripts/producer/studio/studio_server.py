"""Owned foreground Studio startup, launched detached from the operator CLI.

SDK readiness binds the recorded PID/project/port. The generation manifest
does not track this runtime record; ``parked_record`` hides it during diffs.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import socket
import subprocess
import time
from typing import BinaryIO, Iterator
from graphics.render_tools import resolve_tools
from studio.studio_server_protocol import ServerRecord, StudioServerError, started_record  # noqa: F401 (re-exported)

SERVER_RECORD_NAME = ".studio-server.json"
PORT_RANGE = (3990, 3999)
_LOG_REL = os.path.join(".hyperframes", "preview-server.log")
_STARTUP_SECONDS, _CLEANUP_RESERVE, _STARTUP_BYTES = 10.0, 2.0, 65_536
# Every Studio ps read: C-format lstart (LC_TIME) and raw UTF-8 paths (LC_CTYPE; the C character set
# would print non-ASCII bytes in M- notation), whatever the caller's locale.
PS_ENVIRONMENT = {'PATH': '/usr/bin:/bin', 'LC_CTYPE': 'UTF-8', 'LC_TIME': 'C'}


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
    proc = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)],
                          capture_output=True, check=False, env=PS_ENVIRONMENT)
    line = proc.stdout.decode("utf-8", errors="replace").strip()
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
        ready = started_record(data, (studio_dir, port, proc.pid))
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


@contextlib.contextmanager
def _before_spawn(tagged: tuple[type[BaseException], ...] = (BaseException,)) -> Iterator[None]:
    """Tag a failure raised before the preview child exists (``preview_spawned = False``).

    A managed caller can then settle the launch as verified: nothing was started. Around Popen only
    ordinary errors are tagged (a failed exec leaves no live child); an interrupt there may land after
    the fork, so it stays untagged and the launch stays unverified.
    """
    try:
        yield
    except tagged as error:
        error.preview_spawned = False
        raise


def launch_preview(cli: str, studio_dir: str, port: int, open_browser: bool = True) -> ServerRecord:
    """Keep an owned foreground PID; publish only exact SDK-confirmed readiness.

    ``open_browser`` passes the CLI's own auto-open through (the managed lifecycle
    passes False: it prints the URL instead). Failed, reused or fallback-port launches do not
    become records; only this call's own child is stopped on startup failure.
    """
    deadline = time.monotonic() + _STARTUP_SECONDS
    with _before_spawn():
        if not os.path.isfile(cli):
            raise StudioServerError(f"pinned hyperframes CLI missing: {cli}")
        node, environment = local_sdk_environment()
        studio_dir = os.path.abspath(studio_dir)
        log_path = os.path.join(studio_dir, _LOG_REL)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log = open(log_path, "a+b")
    with log:
        with _before_spawn((Exception,)):
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
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
            error.preview_pid = proc.pid  # Lets a managed caller verify this exact child is gone.
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
