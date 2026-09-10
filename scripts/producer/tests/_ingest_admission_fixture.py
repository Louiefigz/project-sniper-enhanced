"""Shared deterministic fixtures for Producer ingest-admission tests."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from headless.external_media_probe import POLICY_VERSION
from headless.external_media_probe_policy import MediaProbeLimits
from ingest_probe import MediaProbe


def decoded(size: int, image: bool = False) -> dict:
    """Return bounded decoded-media facts for a fixture payload."""
    facts = {
        "mediaKind": "still-image" if image else "timed-media",
        "durationSeconds": 0 if image else 1,
        "sizeBytes": size,
        "width": 32,
        "height": 18,
        "videoStreams": 1,
        "audioStreams": 0 if image else 1,
        "streamCount": 1 if image else 2,
        "declaredFrames": 1 if image else 24,
    }
    return {"schemaVersion": 1, "ok": True, "decoded": True, "facts": facts}


def runner(source: str, store: str) -> dict:
    """Snapshot a fixture and return a valid retained admission receipt."""
    data = Path(source).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    snapshot = Path(store) / f"{digest}.media"
    if not snapshot.exists():
        snapshot.write_bytes(data)
        os.chmod(snapshot, 0o600)
    image = Path(source).suffix.lower() == ".png"
    return {
        "schemaVersion": 1,
        "policy": POLICY_VERSION,
        "snapshot": {
            "path": str(snapshot),
            "sha256": digest,
            "sizeBytes": len(data),
        },
        "limits": vars(MediaProbeLimits()),
        "image": {"imageId": f"sha256:{'a' * 64}"},
        "isolation": {"networkMode": "none"},
        "network": {"schemaVersion": 1},
        "decoded": decoded(len(data), image),
    }


def probe(path: str) -> MediaProbe:
    """Return deterministic media metadata for an admitted fixture."""
    image = Path(path).read_bytes().startswith(b"image")
    return MediaProbe(
        duration=None if image else 1.0,
        fps=None if image else 24.0,
        vfr=False,
        width=32,
        height=18,
        rotation=0,
        audio_present=not image,
        audio_channels=None if image else 2,
        audio_sample_rate=None if image else 48000,
        frame_rate=None if image else "24/1",
    )
