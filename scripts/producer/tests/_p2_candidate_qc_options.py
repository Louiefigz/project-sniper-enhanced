"""Configuration object for the real-media candidate-QC fixture."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateQcOptions:
    whisper_text: str = "restore this phrase"
    aligner: bool = True
    duplicate_alignment: bool = False
    source_rate: int = 48_000
    target_start_sample: int | None = None
    dirty_start_frame: int = 30
