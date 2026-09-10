"""Real-media fixture builder for exact dialogue-program controller tests."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from audio.dialogue_program_contracts import AuxiliaryStemSnapshot
from audio.dialogue_stem_contracts import (
    DialogueSourceSnapshot,
    DialogueStemTools,
    dialogue_source_snapshot_set_hash,
)
from edit.dialogue_authority import (
    compile_dialogue_map,
    dialogue_map_hash,
    dialogue_track_hash,
)
from edit.picture_lock_common import canonical_json
from fingerprints import file_sha256

FIXTURE = Path(__file__).parent / "fixtures" / "dialogue-authority-v1.json"
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def supports_rubberband() -> bool:
    """Return whether the real-media acceptance dependency is available."""
    if not FFMPEG or not FFPROBE:
        return False
    result = subprocess.run(
        [FFMPEG, "-hide_banner", "-filters"],
        text=True, capture_output=True, check=False)
    return result.returncode == 0 and "rubberband" in result.stdout


def _audio(
    path: str,
    rate: int,
    frequency: int,
    output: tuple[str, str],
) -> None:
    duration, codec = output
    command = [
        str(FFMPEG), "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i",
        f"sine=frequency={frequency}:sample_rate={rate}:duration={duration}",
        "-af", "volume=0.06", "-c:a", codec, path,
    ]
    subprocess.run(command, check=True)


def _write_json(path: str, value: object) -> None:
    Path(path).write_text(
        canonical_json(value) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ProgramRequestSpec:
    """Names and execution selection for one fixture request."""

    mode: str
    dialogue_name: str
    program_name: str
    auxiliary_version: int


class DialogueProgramFixture:
    """Own immutable source, authority, auxiliary, and request snapshots."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.tools = self._tools()
        self.sources = self._sources()
        raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.track = copy.deepcopy(raw["track"])
        self.track["sourceSnapshotSetHash"] = \
            dialogue_source_snapshot_set_hash(self.sources)
        self.dialogue_map = compile_dialogue_map(self.track)
        self.track_path = os.path.join(root, "dialogue-track.json")
        self.map_path = os.path.join(root, "dialogue-map.json")
        _write_json(self.track_path, self.track)
        _write_json(self.map_path, self.dialogue_map)
        self.auxiliary = {
            1: self._auxiliary("v1", 221),
            2: self._auxiliary("v2", 277),
        }

    def _tools(self) -> DialogueStemTools:
        ffmpeg = os.path.realpath(str(FFMPEG))
        ffprobe = os.path.realpath(str(FFPROBE))
        return DialogueStemTools(
            ffmpeg, file_sha256(ffmpeg),
            ffprobe, file_sha256(ffprobe))

    def _sources(self) -> tuple[DialogueSourceSnapshot, ...]:
        specs = (
            ("source-a", 48_000, 300, "3"),
            ("source-b", 44_100, 600, "3"),
            ("source-c", 48_000, 900, "2"),
        )
        result = []
        for source_id, rate, frequency, duration in specs:
            path = os.path.join(self.root, f"{source_id}.wav")
            _audio(path, rate, frequency, (duration, "pcm_s24le"))
            result.append(DialogueSourceSnapshot(
                source_id, path, file_sha256(path), 0))
        return tuple(result)

    def _auxiliary(
        self,
        version: str,
        music_frequency: int,
    ) -> tuple[AuxiliaryStemSnapshot, ...]:
        specs = (
            ("music-bed", "music", music_frequency),
            ("room-tone-bed", "room-tone", 113),
            ("sfx-bed", "sfx", 1409),
        )
        rows = []
        for stem_id, role, frequency in specs:
            path = os.path.join(
                self.root, f"{version}-{role}.wav")
            _audio(path, 48_000, frequency, ("6", "pcm_s32le"))
            rows.append(AuxiliaryStemSnapshot(
                stem_id, role, path, file_sha256(path), 0))
        return tuple(rows)

    def request(
        self,
        spec: ProgramRequestSpec,
    ) -> dict[str, object]:
        """Build one closed request with exact expected role closure."""
        auxiliary = self.auxiliary[spec.auxiliary_version]
        return {
            "schemaVersion": 1,
            "kind": "exact-dialogue-program-render",
            "executionMode": spec.mode,
            "authority": {
                "trackPath": self.track_path,
                "trackFileSha256": file_sha256(self.track_path),
                "dialogueTrackHash": dialogue_track_hash(self.track),
                "mapPath": self.map_path,
                "mapFileSha256": file_sha256(self.map_path),
                "dialogueMapHash": dialogue_map_hash(self.dialogue_map),
            },
            "sources": [{
                **source.authority_row(), "path": source.path,
            } for source in self.sources],
            "auxiliaryStems": [{
                **stem.authority_row(), "path": stem.path,
            } for stem in auxiliary],
            "expectedAuxiliaryCounts": {
                "room-tone": 1, "music": 1, "sfx": 1,
            },
            "dialogueGenerationDir":
                os.path.join(self.root, spec.dialogue_name),
            "programGenerationDir":
                os.path.join(self.root, spec.program_name),
            "tools": {
                "ffmpegPath": self.tools.ffmpeg_path,
                "ffmpegSha256": self.tools.ffmpeg_sha256,
                "ffprobePath": self.tools.ffprobe_path,
                "ffprobeSha256": self.tools.ffprobe_sha256,
            },
        }

    def write_request(self, name: str, request: dict) -> str:
        """Write one canonical single-link request for the CLI boundary."""
        path = os.path.join(self.root, name)
        _write_json(path, request)
        return path
