"""The Studio preview server's record type, error and SDK readiness protocol.

Pure data and parsing, shared by ``studio_server`` (which re-exports them) so the
launcher stays within its size bound. Readiness binds the SDK's own started
foreground PID, project and port; anything else is a StudioServerError.
"""
from __future__ import annotations

import dataclasses
import json


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


def validate_ready(value: object, expected: tuple[str, int, int]) -> None:
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


def started_record(data: bytes, expected: tuple[str, int, int]) -> bool:
    """Read complete SDK lifecycle lines; a truncated line is never readiness."""
    for line in data.split(b"\n")[:-1]:
        if not line.startswith(b"{"):
            continue
        value = json.loads(line)
        if type(value) is not dict or value.get("operation") != "start":
            continue
        validate_ready(value, expected)
        return True
    return False
