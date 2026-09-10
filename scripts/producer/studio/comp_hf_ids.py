"""One bounded installed-parser batch for NEW Studio composition artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from headless.process_runner import ProcessRequest, run_text
from studio import StudioProjectError

NORMALIZER = "hf-ids-0.8.31"
_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = Path(__file__).with_suffix(".mjs")
_MAX_INPUT, _MAX_OUTPUT = 4 * 1024 * 1024, 8 * 1024 * 1024


def _instances(value: object, maximum: int) -> dict[str, str]:
    """Validate finite supplied HTML before encoding or handing it to the SDK."""
    if type(value) is not dict or not 0 < len(value) <= 1024:
        raise StudioProjectError("Studio ID batch requires 1..1024 compositions")
    total = 0
    for key, html in value.items():
        if type(key) is not str or not key.startswith("compositions/") or not key.endswith(".html") \
                or len(key) > 256 or Path(key).parts != ("compositions", Path(key).name):
            raise StudioProjectError("Studio ID batch has an invalid composition key")
        if type(html) is not str or not 0 < len(html) <= 1024 * 1024:
            raise StudioProjectError("Studio ID batch composition exceeds 1 MiB characters")
        total += len(key.encode("utf8")) + len(html.encode("utf8"))
        if total > maximum:
            raise StudioProjectError("Studio ID batch exceeds aggregate byte limit")
    return dict(value)


def _node() -> str:
    """Resolve installed Node only; no renderer, browser or package installation."""
    supplied = os.environ.get("SNIPER_NODE_PATH")
    node = supplied or shutil.which("node")
    if not node or not os.path.isabs(node):
        raise StudioProjectError("Studio ID generation requires installed absolute Node")
    node = os.path.realpath(node)
    if not os.path.isfile(node) or not os.access(node, os.X_OK):
        raise StudioProjectError("Studio ID generation Node is unavailable")
    return node


def _decode(text: str, keys: set[str]) -> dict[str, str]:
    """Require the exact response identity and original file keys."""
    value = json.loads(text)
    if type(value) is not dict or set(value) != {"schemaVersion", "normalizer", "instances"} \
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["normalizer"] != NORMALIZER:
        raise StudioProjectError("Studio ID batch returned an unknown response")
    result = _instances(value["instances"], _MAX_OUTPUT)
    if set(result) != keys:
        raise StudioProjectError("Studio ID batch changed composition keys")
    return result


def normalize_instances(instances: dict[str, str]) -> dict[str, str]:
    """Normalize one full generated batch using only pinned ensureHfIds semantics."""
    original = _instances(instances, _MAX_INPUT)
    raw = json.dumps({"schemaVersion": 1, "normalizer": NORMALIZER, "instances": original},
                     ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf8")
    if len(raw) > _MAX_INPUT:
        raise StudioProjectError("Studio ID request exceeds 4 MiB")
    node = _node()
    with tempfile.TemporaryDirectory(prefix="sniper-studio-ids-") as directory:
        target = os.path.join(os.path.realpath(directory), "request.json")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        request = ProcessRequest((node, str(_SCRIPT), target, hashlib.sha256(raw).hexdigest(), str(len(raw))),
            "", str(_ROOT), {"PATH": os.path.dirname(node), "LANG": "C.UTF-8", "TZ": "UTC"},
            30, max_output_bytes=_MAX_OUTPUT)
        completed = run_text(request)
    if completed.returncode or completed.stderr:
        raise StudioProjectError("Installed Studio ID parser refused the generated batch")
    return _decode(completed.stdout, set(original))
