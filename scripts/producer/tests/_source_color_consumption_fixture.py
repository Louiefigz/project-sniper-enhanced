"""Actual held TEST source metadata plus memory-only picture/proof leaves.

No FFmpeg, frame decode, cache or media artifact is produced. The original
batch/identity holders are production returns over inert owned TEST files;
admission and native observations retain their explicit inherited TEST stubs.
"""
from __future__ import annotations

import hashlib
import subprocess
from contextlib import ExitStack
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from _source_color_base_context_fixture import SourceOnlyBaseFixture
from audio.audio_mix_picture import PictureSource
from audio import master
from compile_timeline import compile_plan
from cut_elementary_proof import ElementaryStream, SequenceProof
import cut_manifestation_authority as manifestation
import cut_speed as cut
from guided_source_color_consumption import SourceColorPictureConsumption


class SourceColorConsumptionFixture(SourceOnlyBaseFixture):
    """Align synthetic declaration/cut clocks before any original holder starts."""

    def _opening(self) -> Path:
        """Keep the inherited real source bindings at24fps and18 actual TEST cut frames."""
        result = super()._opening()
        self.inputs.documents["authority"].update(frameRate="24", totalFrames=18)
        return result

    def recorder(self, holder: object) -> SourceColorPictureConsumption:
        """Construct an actual recorder with the same inherited guard, not a fake owner."""
        return SourceColorPictureConsumption(holder, self.guard)

    def segment(self, index: int) -> object:
        """Use the actual compiler and preserve repeated source occurrence order."""
        return compile_plan(self.inputs.documents["candidatePlan"]).segments[index]

    def part(self, index: int) -> str:
        """Name only uncreated TEST outputs; every writer/native leaf is stubbed."""
        return str(self.root / f"part_{index:04d}.mp4")

    def job(self, recorder: object, index: int = 0) -> cut.EncodeJob:
        """The actual source path comes from the held original manifest metadata."""
        source = self.segment(index).source_id
        row = next(row for row in self.inputs.documents["manifest"]["sources"] if row["id"] == source)
        return cut.EncodeJob(row["path"], cut.Profile(1920, 1080, Fraction(24), "yuv420p"),
                             before_encode=self.guard, picture_consumption=recorder)

    def cut(self, recorder: object, index: int = 0) -> int:
        """Run the real compiler-derived part builder with two native leaves stubbed."""
        with patch.object(cut, "run_ff"), patch.object(cut, "_clamp_part_audio", return_value=6):
            return cut.encode_segment(self.segment(index), self.job(recorder, index), self.part(index), index * 6)

    def manifestation(self, inputs: manifestation.ManifestationInputs | None = None) -> dict:
        """Use the real closed receipt builder; artifact/elementary/probe/writer are TEST stubs."""
        timeline = compile_plan(self.inputs.documents["candidatePlan"]).to_dict()
        paths = inputs.part_paths if inputs else [self.part(index) for index in range(3)]
        concat = inputs.concat_path if inputs else str(self.root / "mezzanine.mp4")
        proof = {"videoDuration": .75, "expectedDuration": .75, "videoFrames": 18,
                 "driftFrames": 0.0, "toleranceFrames": 2.5, "segments": 3}
        stream = ElementaryStream("a" * 64, 12)
        sequence = SequenceProof([stream] * 3, ElementaryStream("b" * 64, 36), ElementaryStream("b" * 64, 36))
        artifact = lambda value: {"path": value, "sha256": hashlib.sha256(value.encode()).hexdigest(),
                                   "videoFrames": 18 if value == concat else 6}
        with ExitStack() as stack:
            stack.enter_context(patch.object(manifestation, "_read_object", return_value=timeline))
            stack.enter_context(patch.object(manifestation, "prove_video_sequence", return_value=sequence))
            stack.enter_context(patch.object(manifestation, "_artifact", side_effect=artifact))
            stack.enter_context(patch.object(manifestation, "file_sha256", return_value="c" * 64))
            stack.enter_context(patch.object(manifestation, "write_json_atomic"))
            selected = inputs or manifestation.ManifestationInputs(
                self.inputs.documents["candidatePlan"], str(self.root / "timeline_map.json"), paths, concat, "24/1", proof)
            return manifestation.write_manifestation(selected)

    def cuts(self, recorder: SourceColorPictureConsumption) -> dict:
        """Finish all three actual cut hooks and the independently built TEST proof join."""
        for index in range(3):
            self.cut(recorder, index)
        result = self.manifestation()
        recorder.join_cut_manifestation(result, tuple(self.part(index) for index in range(3)), str(self.root / "mezzanine.mp4"))
        return result

    def spec(self, recorder: object) -> master.MasterSpec:
        """Create the actual picture-only spec, not an executed media claim."""
        return master.MasterSpec(str(self.root / "mezzanine.mp4"), str(self.root / "picture-master.mp4"),
            fps=24, frame_count=18, duration=.75, picture_consumption=recorder)

    def master(self, recorder: SourceColorPictureConsumption) -> PictureSource:
        """Run the actual master command then return explicitly synthetic packet evidence."""
        spec = self.spec(recorder)
        with patch.object(master, "_run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                patch.object(master.os.path, "isfile", return_value=True):
            master.encode_picture_only(spec, self.guard)
        rows = tuple((Fraction(index, 24), None, "SHA256:" + "d" * 64, "[]") for index in range(18))
        return PictureSource(spec.out, "e" * 64, Fraction(1, 24), rows)
