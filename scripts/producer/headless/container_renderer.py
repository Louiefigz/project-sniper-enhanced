"""Exact, networkless OCI adapter for one sealed HyperFrames render."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass

from headless.container_io import SealedInput, promote_regular
from headless.container_live_policy import ContainerExpectation, attest_container
from headless.docker_identity import daemon_identity, file_sha256
from headless.network_probe import probe_container
from headless.runtime_receipt import write_runtime_receipt
from headless.container_policy import (
    DockerRuntime,
    attest_image,
    command as docker_command,
    docker_env,
    reconcile_launch_abort,
    remove_container,
    required_runtime,
    wait_and_copy,
)

_COMPOSITION = re.compile(r"compositions/[A-Za-z0-9._-]+\.html")
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
_CONTAINER_NAME = re.compile(r"sniper-render-[0-9a-f]{32}")
_BROWSER = ("/ms-playwright/chromium_headless_shell-1194/"
            "chrome-linux/headless_shell")
_PRELOAD = "/opt/sniper-motion/container/node_isolated_user.cjs"
RENDER_POLICY_VERSION = "sniper-oci-render-v2"


@dataclass(frozen=True)
class RenderRequest:
    """Validated host request for one isolated container render."""

    composition: str
    fmt: str
    output: str
    snapshot: SealedInput
    container_name: str


@dataclass(frozen=True)
class RenderPaths:
    """Attempt-private control, input, and output paths."""

    runtime: DockerRuntime
    docker_config: str
    snapshot: SealedInput
    copied_output: str


def _container_env(snapshot: SealedInput) -> dict[str, str]:
    return {
        "DO_NOT_TRACK": "1", "HYPERFRAMES_BROWSER_PATH": _BROWSER,
        "HEYGEN_CONFIG_DIR": "/scratch/heygen",
        "HYPERFRAMES_EXTRACT_CACHE_DIR": "/scratch/extract",
        "HYPERFRAMES_FFMPEG_PATH": "/usr/bin/ffmpeg",
        "HYPERFRAMES_FFPROBE_PATH": "/usr/bin/ffprobe",
        "HYPERFRAMES_FONT_CACHE_DIR": "/scratch/fonts",
        "HYPERFRAMES_NO_AUTO_INSTALL": "1", "HYPERFRAMES_NO_TELEMETRY": "1",
        "HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_SKIP_SKILLS": "1",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "LC_CTYPE": "C.UTF-8",
        "NODE_OPTIONS": f"--require={_PRELOAD}", "NO_COLOR": "1",
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "PUPPETEER_CACHE_DIR": "/scratch/cache",
        "PRODUCER_HEADLESS_SHELL_PATH": _BROWSER,
        "PRODUCER_LOW_MEMORY_MODE": "false",
        "SNIPER_INPUT_SHA256": snapshot.sha256,
        "SNIPER_ISOLATED_USER_DIR": "/scratch/user", "TZ": "UTC",
        "TEMP": "/scratch", "TMP": "/scratch", "TMPDIR": "/scratch",
        "XDG_CACHE_HOME": "/scratch/cache", "XDG_CONFIG_HOME": "/scratch/config",
        "XDG_DATA_HOME": "/scratch/data", "XDG_STATE_HOME": "/scratch/state",
    }


def _tmpfs(path: str, size: str, user_id: str) -> str:
    uid, gid = user_id.split(":", 1)
    return f"{path}:rw,nosuid,nodev,noexec,size={size},uid={uid},gid={gid},mode=0700"


def _command(paths: RenderPaths, request: RenderRequest, name: str) -> list[str]:
    runtime = paths.runtime
    archive = (f"type=bind,src={paths.snapshot.path},"
               "dst=/request/render-input.tar,readonly")
    result = docker_command(
        runtime, "run", "--detach", "--rm", "--pull", "never", "--name", name,
        "--platform", "linux/arm64", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
        "--user", runtime.user_id, "--pids-limit", "256", "--memory", "4g",
        "--memory-swap", "4g", "--cpus", "4", "--init", "--stop-timeout", "10",
        "--shm-size", "1g", "--log-driver", "none",
        "--ulimit", "nofile=4096:4096", "--hostname", "sniper-render",
        "--label", f"io.project-sniper.render-name={name}",
        "--tmpfs", _tmpfs("/scratch", "2g", runtime.user_id),
        "--tmpfs", _tmpfs("/output", "512m", runtime.user_id),
        "--mount", archive, "--workdir", "/scratch")
    for key, value in sorted(_container_env(paths.snapshot).items()):
        result.extend(("--env", f"{key}={value}"))
    result.extend((
        runtime.image_id, "render", "/scratch/project/motion", "-c",
        request.composition, "--format", request.fmt, "--variables-file",
        "/scratch/project/request/variables.json", "-o",
        f"/output/render.{request.fmt}", "--fps", "30", "--quality", "high",
        "--workers", "1", "--no-browser-gpu", "--strict",
        "--strict-variables", "--json"))
    return result


def _reap_client(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Docker client could not be reaped") from exc


def _abort(proc: subprocess.Popen, paths: RenderPaths, name: str) -> None:
    reap_error = None
    try:
        _reap_client(proc)
    except Exception as exc:
        reap_error = exc
    try:
        reconcile_launch_abort(paths.runtime, paths.docker_config, name)
    except Exception as cleanup_error:
        raise RuntimeError("render abort could not prove container removal") \
            from cleanup_error
    if reap_error is not None:
        raise RuntimeError("render abort could not reap Docker client") from reap_error


def _run(command: list[str], paths: RenderPaths,
         name: str) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=os.path.dirname(paths.docker_config),
        env=docker_env(paths.docker_config))
    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired as exc:
        _abort(proc, paths, name)
        raise RuntimeError("networkless render container launch exceeded 60s") from exc
    except BaseException:
        try:
            _abort(proc, paths, name)
        except Exception as cleanup_exc:
            raise RuntimeError("render cancelled but container cleanup failed") \
                from cleanup_exc
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _validate_request(request: RenderRequest) -> None:
    if any("," in path for path in (request.snapshot.path, request.output)):
        raise RuntimeError("container render paths must not contain commas")
    if (request.fmt not in {"mov", "mp4"}
            or not _COMPOSITION.fullmatch(request.composition)
            or not _CONTAINER_NAME.fullmatch(request.container_name)):
        raise RuntimeError("container render format or composition path is invalid")
    if (not os.path.isfile(request.snapshot.path)
            or not os.path.isdir(os.path.dirname(request.output))
            or os.path.lexists(request.output)):
        raise RuntimeError("container render output must be a new path in an existing dir")


def _container_id(stdout: str) -> str:
    value = stdout.strip()
    if not _CONTAINER_ID.fullmatch(value):
        raise RuntimeError("detached Docker launch returned an invalid container ID")
    return value


def _receipt(runtime: DockerRuntime, request: RenderRequest,
             copied: str, evidence: dict) -> dict:
    return {"schemaVersion": 1, "policy": RENDER_POLICY_VERSION,
            "imageId": runtime.image_id,
            "snapshotSha256": request.snapshot.sha256,
            "snapshotManifest": list(request.snapshot.manifest),
            "outputSha256": file_sha256(copied),
            "imageAttestation": evidence["image"],
            "containerBeforeOutput": evidence["before"],
            "containerAfterOutput": evidence["after"],
            "activeNetworkProof": evidence["network"],
            "dockerRuntime": evidence["daemon"],
            "attestationScope": {
                "checks": ["before-output-stream", "after-output-stream"],
                "concurrentSameUidDockerMutation": "excluded"}}


def _promote_outputs(request: RenderRequest, copied: str) -> None:
    promote_regular(copied, request.output)
    try:
        promote_regular(copied + ".runtime.json", request.output + ".runtime.json")
        promote_regular(request.snapshot.path, request.output + ".input.tar",
                        request.snapshot.sha256, request.snapshot.size_bytes)
    except Exception:
        os.unlink(request.output)
        try:
            os.unlink(request.output + ".runtime.json")
        except FileNotFoundError:
            pass
        raise


def _execute_container(paths: RenderPaths, request: RenderRequest,
                       name: str, evidence: dict) -> tuple[dict, str]:
    launch = _command(paths, request, name)
    result = _run(launch, paths, name)
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).splitlines()[-10:])
        raise RuntimeError(f"networkless HyperFrames render failed:\n{tail}")
    container_ref = _container_id(result.stdout)
    expected = ContainerExpectation(
        container_ref, name, request.snapshot.path, _container_env(request.snapshot),
        tuple(launch[launch.index(paths.runtime.image_id) + 1:]))
    evidence["before"] = attest_container(
        paths.runtime, paths.docker_config, expected)
    evidence["network"] = probe_container(
        paths.runtime, paths.docker_config, container_ref)
    wait_and_copy(paths.runtime, paths.docker_config,
                  container_ref, paths.copied_output)
    evidence["after"] = attest_container(
        paths.runtime, paths.docker_config, expected)
    return _receipt(paths.runtime, request, paths.copied_output, evidence), container_ref


def render_to(request: RenderRequest) -> dict:
    """Render through the approved image and promote only a regular output."""
    runtime = required_runtime()
    request = RenderRequest(request.composition, request.fmt,
                            os.path.abspath(request.output), request.snapshot,
                            request.container_name)
    _validate_request(request)
    out_dir = os.path.dirname(request.output)
    with tempfile.TemporaryDirectory(prefix=".container-render-", dir=out_dir) as stage:
        docker_config = os.path.join(stage, "docker-config")
        os.mkdir(docker_config, 0o700)
        copied = os.path.join(stage, f"copied.{request.fmt}")
        paths = RenderPaths(runtime, docker_config, request.snapshot, copied)
        image_attestation = attest_image(runtime, docker_config)
        docker_runtime = daemon_identity(runtime, docker_config)
        name = request.container_name
        container_ref = name
        try:
            evidence = {"image": image_attestation, "daemon": docker_runtime}
            receipt, container_ref = _execute_container(
                paths, request, name, evidence)
        finally:
            removal = remove_container(runtime, docker_config, container_ref)
        receipt["containerRemoval"] = removal
        write_runtime_receipt(copied, receipt)
        _promote_outputs(request, copied)
        return receipt


def cache_identity(pipeline_root: str) -> bytes:
    """Bind cache authority to every host policy and proof executable."""
    runtime = required_runtime()
    policy_dir = os.path.dirname(__file__)
    files = {
        "adapter": __file__,
        "ioPolicy": os.path.join(policy_dir, "container_io.py"),
        "livePolicy": os.path.join(policy_dir, "container_live_policy.py"),
        "dockerIdentityPolicy": os.path.join(policy_dir, "docker_identity.py"),
        "networkProbePolicy": os.path.join(policy_dir, "network_probe.py"),
        "imageApproval": os.path.join(policy_dir, "render_image_approval.json"),
        "imagePolicy": os.path.join(policy_dir, "container_policy.py"),
        "docker": runtime.docker,
    }
    proof_tools = {}
    for label, env_key in (("ffmpeg", "SNIPER_PROOF_FFMPEG_PATH"),
                           ("ffprobe", "SNIPER_PROOF_FFPROBE_PATH")):
        path = os.path.realpath(os.environ.get(env_key, ""))
        if not path or not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise RuntimeError(f"{env_key} is required for container cache identity")
        proof_tools[label] = {"path": path, "sha256": file_sha256(path)}
    with tempfile.TemporaryDirectory(prefix=".docker-identity-") as config_dir:
        os.chmod(config_dir, 0o700)
        daemon = daemon_identity(runtime, config_dir)
    value = {"digests": {key: file_sha256(path) for key, path in files.items()},
             "dockerRuntime": daemon,
             "environment": _container_env(SealedInput("", "0" * 64, ())),
             "imageId": runtime.image_id, "policy": RENDER_POLICY_VERSION,
             "proofTools": proof_tools, "userId": runtime.user_id}
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")
