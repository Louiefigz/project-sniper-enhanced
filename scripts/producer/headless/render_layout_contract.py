"""Distinct explicit sealed native observation classes; no default promotion."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import stat
import tarfile
from fractions import Fraction

from headless.container_io import SealedInput
from headless.sealed_archive import verify_archive_file

POLICY = "sealed-agenda-css-layout-v1"
PIPELINE_POLICY = "sealed-pipeline-css-layout-v1"
COMPOSITIONS = {POLICY: "compositions/agenda-slide.html",
                PIPELINE_POLICY: "compositions/nateherk-pipeline.html"}
SCOPE = "actual-css-range-envelopes-not-glyph-pixel-legibility-or-approval"
CLI_SHA256 = "95be44729e244283cb685833a20b94e00c96aaafba7848b9182db01771477c78"
MAX_RESULT_BYTES = 16 * 1024 * 1024
OBSERVER_FILES = tuple(f"layout_observer_{name}.mjs" for name in (
    "browser", "host", "launch", "loader", "patch"))


def canonical(value: object) -> bytes:
    """Preserve the exact request encoding shared with the container."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def closed(value: object, keys: set[str], label: str) -> dict:
    """Reject unknown/missing fields without compatibility coercion."""
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{label} fields differ")
    return value


def sha(value: object) -> str:
    """Validate one exact SHA text; the hash alone is not authority."""
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("layout SHA is malformed")
    return value


def bounded_bytes(path: str, limit: int) -> bytes:
    """Read one stable no-follow regular inode with a strict allocation ceiling."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or before.st_uid != os.geteuid() or not 0 < before.st_size <= limit:
            raise ValueError("layout evidence file type/size/ownership differs")
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode,
                                 item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if len(raw) != before.st_size or identity(before) != identity(after):
            raise ValueError("layout evidence changed while reading")
        return raw
    finally:
        if fd >= 0:
            os.close(fd)


def validate_request(value: object) -> dict:
    """Explicit <=60-second 1080p native classes; no cross-profile coercion."""
    row = closed(value, {"schemaVersion", "profile", "snapshotSha256",
                        "composition", "frameRate", "totalFrames", "width", "height"}, "layout request")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or type(row["profile"]) is not str or row["profile"] not in COMPOSITIONS \
            or row["composition"] != COMPOSITIONS[row["profile"]]:
        raise ValueError("layout observation profile is unsupported")
    sha(row["snapshotSha256"])
    rate = Fraction(row["frameRate"]) if type(row["frameRate"]) is str else Fraction(0)
    if row["frameRate"] != f"{rate.numerator}/{rate.denominator}" \
            or not 0 < rate <= 60 or max(rate.numerator, rate.denominator) > 999999:
        raise ValueError("layout observation rational clock is unsupported")
    if type(row["totalFrames"]) is not int or not 1 <= row["totalFrames"] <= 3600 \
            or row["totalFrames"] / rate > 60:
        raise ValueError("layout observation exceeds bounded frame duration")
    if type(row["width"]) is not int or type(row["height"]) is not int \
            or (row["width"], row["height"]) != (1920, 1080):
        raise ValueError("layout observation requires the native 1080p canvas")
    return row


def encoded_request(value: dict) -> str:
    """Encode only validated closed owner-held control metadata."""
    return base64.b64encode(canonical(validate_request(value))).decode("ascii")


def sealed_documents(snapshot: SealedInput, request: dict) -> dict[str, bytes]:
    """Verify the complete retained tar, then read its exact captured documents."""
    validate_request(request)
    if request["snapshotSha256"] != snapshot.sha256:
        raise ValueError("layout request differs from held sealed input")
    verify_archive_file(snapshot.path, snapshot.sha256, snapshot.manifest)
    raw = bounded_bytes(snapshot.path, 128 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != snapshot.sha256:
        raise ValueError("layout sealed archive changed")
    names = ("request/variables.json", "motion/" + request["composition"])
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        documents = {name: archive.extractfile(name).read() for name in names}
    spec = json.loads(documents[names[0]])
    if type(spec) is not dict or spec.get("layout") != "caption-safe-upper-v1":
        raise ValueError("layout observation requires explicit native variant intent")
    return documents


def finite_number(value: object) -> float:
    """Require actual finite numeric measurements, excluding booleans."""
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("layout measurement is nonfinite or malformed")
    return float(value)


def role_inventory(documents: dict[str, bytes], profile: str = POLICY) -> list[dict]:
    """Derive exact lexical roles from the captured spec and declared defaults."""
    from graphics.template_contract import declared_variables
    if type(profile) is not str or profile not in COMPOSITIONS:
        raise ValueError("layout role profile is unsupported")
    html = documents["motion/" + COMPOSITIONS[profile]].decode("utf-8")
    defaults = {key: row["default"] for key, row in declared_variables(html).items()}
    values = {**defaults, **json.loads(documents["request/variables.json"])}
    if profile == PIPELINE_POLICY:
        return _pipeline_roles(values)
    return _agenda_roles(values)


def _agenda_roles(values: dict) -> list[dict]:
    """Preserve the original agenda policy's exact sparse lexical class."""
    names = ["title", "eyebrow", *[f"{prefix}{index}" for index in range(1, 6)
                                  for prefix in ("num", "title", "sub")]]
    if any(type(values.get(name)) is not str for name in names) or not values["title"].strip():
        raise ValueError("layout requires the exact agenda string-copy class")
    roles = [{"id": "title", "text": values["title"]}, {"id": "title-accent", "text": ""}]
    if values["eyebrow"].strip():
        roles.append({"id": "eyebrow", "text": values["eyebrow"].strip()})
    active = [index for index in range(1, 6) if values[f"title{index}"].strip()]
    if not 1 <= len(active) <= 3:
        raise ValueError("layout requires one to three actual agenda rows")
    for index in active:
        roles.extend([{"id": f"step-{index}-marker", "text": values[f"num{index}"].strip() or str(index)},
                      {"id": f"step-{index}-title", "text": values[f"title{index}"].strip()}])
        if values[f"sub{index}"].strip():
            roles.append({"id": f"step-{index}-subtitle", "text": values[f"sub{index}"].strip()})
    return sorted(roles, key=lambda row: row["id"])


def _pipeline_roles(values: dict) -> list[dict]:
    """Keep every explicit native pipeline label and actual hairline connector."""
    names = ("eyebrow", "headlineLines", "explainer", "nodes", "footChip")
    if any(type(values.get(name)) is not str for name in names) \
            or values.get("layout") != "caption-safe-upper-v1" \
            or values.get("presenterFrame") is not False or values.get("exit") != "hold":
        raise ValueError("layout requires exact native pipeline intent and string copy")
    text = {name: values[name].strip() for name in names}
    nodes = [item.split("~") for item in text["nodes"].split("|")]
    if not 2 <= len(nodes) <= 6 or any(len(item) != 2 or not all(part.strip() for part in item) for item in nodes):
        raise ValueError("layout requires two to six complete pipeline nodes")
    lines = [item.strip() for item in text["headlineLines"].split("|")] if text["headlineLines"] else []
    if len(lines) > 2 or any(not line for line in lines):
        raise ValueError("layout pipeline headline lines are incomplete")
    roles = [{"id": f"node-{index + 1}", "text": "".join(part.strip() for part in item)}
             for index, item in enumerate(nodes)]
    roles.extend({"id": f"connector-{index + 1}", "text": ""} for index in range(len(nodes) - 1))
    roles.extend({"id": f"headline-line-{index + 1}", "text": line} for index, line in enumerate(lines))
    roles.extend({"id": role, "text": text[name]} for name, role in (
        ("eyebrow", "eyebrow"), ("explainer", "explainer"), ("footChip", "footnote")) if text[name])
    return sorted(roles, key=lambda row: row["id"])
