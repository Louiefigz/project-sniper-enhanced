"""Path authority for one current-render graph execution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOTION_ROOT = PROJECT_ROOT / "templates" / "motion"
DEFAULT_CACHE = MOTION_ROOT / "renders" / "cache"


@dataclass(frozen=True)
class GraphBuildInputs:
    """Separate graph-store authority from private rendered artifacts."""

    producer_dir: Path
    plan_path: Path
    manifest_path: Path
    base_path: Path
    output_path: Path
    cache_dir: Path
    execution_mode: str = "incremental"
    artifact_dir: Path | None = None
    audio_clock_policy: str = "legacy-v1"

    def __post_init__(self) -> None:
        """Reject undeclared audio modes before graph cache lookup or media work."""
        if self.audio_clock_policy not in {"legacy-v1", "source-float-v2"}:
            raise ValueError("unsupported current-render graph audio policy")

    @property
    def artifact_root(self) -> Path:
        """Directory containing timeline, caption, and composite sidecars."""
        return self.artifact_dir or self.producer_dir
