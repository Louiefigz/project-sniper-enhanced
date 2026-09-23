"""Call the shared offline review validator before ordinary full-render work."""
from __future__ import annotations

import os
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReadinessRequest:
    """Exact canonical inputs of a proposed ordinary render."""

    plan: str
    manifest: str
    producer_dir: str
    draft: bool = False


def require_readiness(request: ReadinessRequest) -> None:
    """Fail before rendering unless reviews, previews and gate approval are current.

    Args:
        request: The same inputs the renderer is about to consume.
    """
    _validate(request, 'check-draft' if request.draft else 'check')


def readiness_packet(request: ReadinessRequest) -> dict:
    """Read current dependencies using the same canonical plan resolver."""
    return json.loads(_validate(request, 'packet'))


def _validate(request: ReadinessRequest, command: str) -> str:
    """Invoke the one offline validator without inheriting an approval shortcut."""
    root = Path(__file__).resolve().parents[2]
    node = os.environ.get('SNIPER_NODE_PATH') or shutil.which('node')
    if not node:
        raise RuntimeError('Render readiness requires Sniper Node; run through ./sniper')
    arguments = [node, '--import', 'tsx', str(root / 'scripts/infra/plan-readiness.ts'), command,
               os.path.abspath(request.producer_dir), os.path.abspath(request.plan),
               os.path.abspath(request.manifest)]
    try:
        result = subprocess.run(arguments, cwd=root, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Render readiness validator could not finish') from error
    if result.returncode:
        raise RuntimeError('Render readiness refused: ' + (result.stderr or result.stdout)[-4000:])
    return result.stdout


def require_draft_destination(producer_dir: str, output: str) -> None:
    """Keep draft admission inside its dedicated watermarked-output directory."""
    from draft_render import assert_no_approval_sidecar
    expected = Path(producer_dir).resolve() / 'draft'
    if Path(output).resolve() != expected or expected.is_symlink():
        raise ValueError('Draft-only rendering must use <producer_dir>/draft')
    assert_no_approval_sidecar(str(expected))


def finish_draft(plan: str, manifest: str, producer_dir: str, font: str | None = None) -> str:
    """Burn and retain only the explicit draft through the existing watermark owner."""
    from draft_render import DraftJob, burn_watermark, scrub_intermediates
    job = DraftJob(plan, manifest, producer_dir, fontfile=font)
    result = burn_watermark(job)
    scrub_intermediates(job.draft_dir)
    return result
