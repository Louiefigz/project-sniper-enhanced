"""Local or attested-networkless execution of one sealed scene entry."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass

from graphics.composition_transform import set_root_duration
from graphics.graphics_render import (
    GSAP_CORE,
    HYPERFRAMES_BIN,
    MOTION_DIR,
    MOTION_TOKENS_JS,
    NODE_USER_PRELOAD,
    TOKENS_CSS,
)
from graphics.hyperframes_invocation import RenderInvocation, render_composition
from graphics.scene_bundle import BundleSnapshot
from graphics.scene_bundle_manifest import validate_bundle_manifest
from graphics.scene_contract import SceneContractError, canonical_json
from graphics.scene_snapshot import SceneSnapshotRequest, create_scene_snapshot
from headless.container_io import promote_regular
from headless.container_policy import required_runtime
from headless.container_renderer import (
    RenderRequest as ContainerRenderRequest,
    render_to as render_in_container,
)
from headless.safe_source_files import PinnedSourceRoot

_CLI_RELATIVE = "node_modules/hyperframes/dist/cli.js"
_PACKAGE_RELATIVE = "node_modules/hyperframes/package.json"
_LOCKS = ("package-lock.json", "node_modules/.package-lock.json")
_RUNTIME_ASSETS = (
    _CLI_RELATIVE, "node_modules/hyperframes/dist/hyperframe.runtime.iife.js",
    "node_modules/hyperframes/dist/hyperframe-runtime.js",
    "node_modules/hyperframes/dist/runtimeVersion.js",
)
_MAX_RUNTIME_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SceneExecution:
    """Resolved render inputs with no ambient authoring state."""

    bundle: BundleSnapshot
    relative: str
    html: str
    fmt: str
    variables: dict
    output: str
    fps: object
    duration: float
    scratch_root: str
    asset_bindings: tuple[dict, ...]
    expected_runtime: bytes | None = None


def _shared_sources() -> tuple[tuple[str, str], ...]:
    return (
        ("tokens.css", TOKENS_CSS),
        ("motion-tokens.js", MOTION_TOKENS_JS),
        ("vendor/gsap/gsap.min.js", GSAP_CORE),
        ("hyperframes.json", os.path.join(MOTION_DIR, "hyperframes.json")),
        ("index.html", os.path.join(MOTION_DIR, "index.html")),
        ("package.json", os.path.join(MOTION_DIR, "package.json")),
    )


def _runtime_file(path: str) -> bytes:
    """Read one bounded runtime leaf through the existing no-follow reader."""
    with PinnedSourceRoot(os.path.dirname(path)) as source:
        data = source.read(os.path.basename(path))
        source.assert_current()
    return data


def _runtime_document(data: bytes) -> dict:
    """Require installed package and lock metadata to be JSON objects."""
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SceneContractError("scene runtime metadata is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SceneContractError("scene runtime metadata must be an object")
    return value


def _runtime_files(root: str) -> tuple[dict, dict]:
    """Bind fixed installed assets and shared inputs, not every npm dependency."""
    metadata = {os.path.join(root, name) for name in (_PACKAGE_RELATIVE, *_LOCKS)}
    paths = metadata | {os.path.join(root, name) for name in _RUNTIME_ASSETS}
    paths.update(path for _, path in _shared_sources())
    hashes, documents, total = {}, {}, 0
    for path in sorted(paths):
        raw = _runtime_file(path)
        total += len(raw)
        if not raw or total > _MAX_RUNTIME_BYTES:
            raise SceneContractError("scene runtime closure exceeds its byte bound")
        hashes[path] = hashlib.sha256(raw).hexdigest()
        if path in metadata:
            documents[path] = _runtime_document(raw)
    return hashes, documents


def scene_runtime_identity(bundle: BundleSnapshot) -> bytes:
    """Match declared live runtime and hash selected installed bytes only."""
    version = validate_bundle_manifest(bundle.manifest)["runtime"]["hyperframesVersion"]
    cli = HYPERFRAMES_BIN
    if not os.path.isabs(cli) or not cli.endswith("/" + _CLI_RELATIVE):
        raise SceneContractError("scene runtime CLI path is not the installed entry")
    root = cli.removesuffix("/" + _CLI_RELATIVE)
    hashes, documents = _runtime_files(root)
    package = documents[os.path.join(root, _PACKAGE_RELATIVE)]
    if package.get("name") != "hyperframes" or package.get("version") != version:
        raise SceneContractError("scene runtime version differs from the bundle declaration")
    for name in _LOCKS:
        packages = documents[os.path.join(root, name)].get("packages")
        row = packages.get("node_modules/hyperframes") if isinstance(packages, dict) else None
        if not isinstance(row, dict) or row.get("version") != version:
            raise SceneContractError("scene runtime lock version differs from the installed package")
    return hashlib.sha256(canonical_json({
        "domain": "scene-live-runtime-v1", "version": version, "files": hashes,
    })).digest()


def assert_scene_runtime_identity(bundle: BundleSnapshot, expected: bytes | None) -> None:
    """Reject changes to the original selected live runtime, without rebasing."""
    if expected is not None and scene_runtime_identity(bundle) != expected:
        raise SceneContractError("scene runtime changed after cache identity capture")


def assert_scene_container_version(bundle: BundleSnapshot) -> None:
    """Join a readable declaration to the existing approved image's probe."""
    version = validate_bundle_manifest(bundle.manifest)["runtime"]["hyperframesVersion"]
    closure = required_runtime().approval.get("probedClosure")
    actual = closure.get("hyperframesVersion") if isinstance(closure, dict) else None
    if type(actual) is not str or actual != version:
        raise SceneContractError("scene runtime version differs from the approved image")


def _copy_regular(source: str, target: str) -> None:
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    digest = hashlib.sha256()
    with open(source, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    promote_regular(source, target, digest.hexdigest(), os.path.getsize(source))


def _copy_bundle_rows(
    bundle: BundleSnapshot,
    runtime: str,
    source: PinnedSourceRoot,
) -> None:
    for row in bundle.files:
        data = source.read(row["path"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise SceneContractError("bundle changed while staging render")
        _copy_regular(
            os.path.join(bundle.path, row["path"]),
            os.path.join(runtime, row["path"]))


def _copy_bundle(bundle: BundleSnapshot, runtime: str) -> None:
    with PinnedSourceRoot(bundle.path) as source:
        _copy_bundle_rows(bundle, runtime, source)
        source.assert_current()


def _stage_runtime(bundle: BundleSnapshot, runtime: str) -> None:
    for relative, source in _shared_sources():
        _copy_regular(source, os.path.join(runtime, relative))
    _copy_bundle(bundle, runtime)


def _replace_entry(request: SceneExecution, runtime: str) -> None:
    path = os.path.join(runtime, request.relative)
    transformed = set_root_duration(
        request.html, request.duration).encode("utf-8")
    temporary = path + ".duration"
    with open(temporary, "xb") as handle:
        handle.write(transformed)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _execute_local(request: SceneExecution) -> None:
    """Keep the original live runtime identity through staging to invocation."""
    runtime_identity = scene_runtime_identity(request.bundle)
    if request.expected_runtime is not None and request.expected_runtime != runtime_identity:
        raise SceneContractError("scene runtime changed before local staging")
    with tempfile.TemporaryDirectory(
            prefix=".scene-runtime-", dir=request.scratch_root) as runtime:
        _stage_runtime(request.bundle, runtime)
        _replace_entry(request, runtime)
        assert_scene_runtime_identity(request.bundle, runtime_identity)
        render_composition(
            RenderInvocation(
                runtime, request.relative, request.fmt, request.variables,
                request.output, request.fps),
            HYPERFRAMES_BIN, NODE_USER_PRELOAD)


def _execute_container(request: SceneExecution) -> None:
    """Require the approved runtime version before staging and sealed launch."""
    assert_scene_container_version(request.bundle)
    rendered = set_root_duration(request.html, request.duration)
    with tempfile.TemporaryDirectory(
            prefix=".scene-snapshot-", dir=request.scratch_root) as stage:
        snapshot = create_scene_snapshot(SceneSnapshotRequest(
            request.bundle, request.relative, rendered, request.variables,
            request.asset_bindings, stage))
        assert_scene_container_version(request.bundle)
        render_in_container(ContainerRenderRequest(
            request.relative, request.fmt, request.output, snapshot,
            f"sniper-render-{uuid.uuid4().hex}", request.fps))


def execute_scene(request: SceneExecution) -> None:
    """Render locally for development or through the approved OCI boundary."""
    if os.environ.get("SNIPER_RENDER_IMAGE_ID"):
        _execute_container(request)
    else:
        _execute_local(request)
