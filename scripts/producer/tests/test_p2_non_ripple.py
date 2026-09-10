"""P2 early/middle/late non-ripple repair and honest fallback tests."""
from __future__ import annotations

import unittest

from edit.exact_timing import (
    FrameRange,
    PositiveRational,
    ProjectClock,
    SampleRange,
)
from edit.non_ripple import enumerate_non_ripple
from edit.non_ripple_contracts import (
    CompiledCutSegment,
    DependentTiming,
    RemovableSilence,
    RepairContext,
    RepairContractError,
)
from edit.target_resolver import (
    ResolvedWordRange,
)

HASH = "a" * 64
CLOCK = ProjectClock(PositiveRational(30, 1), 48_000)


def _target() -> ResolvedWordRange:
    return ResolvedWordRange(
        source_id="raw",
        word_ids=("w-" + "1" * 16,),
        first_word_index=1,
        last_word_index=1,
        occurrence=1,
        samples=SampleRange(48_000, 52_800),
        text="automation",
        speaker="host",
        transcript_timing_hash=HASH,
    )


def _segment(seam: int, side: str = "end") -> CompiledCutSegment:
    samples = (SampleRange(20_000, 50_400) if side == "end"
               else SampleRange(50_400, 100_000))
    frames = (FrameRange(max(0, seam - 30), seam) if side == "end"
              else FrameRange(seam, seam + 30))
    return CompiledCutSegment(
        segment_id=f"seg-{seam}",
        element_version=1,
        source_id="raw",
        source_rate=48_000,
        source_samples=samples,
        output_frames=frames,
        speed=PositiveRational(1, 1),
        source_fps=PositiveRational(30, 1),
    )


def _context(seam: int, side: str = "end",
             candidates: bool = True) -> RepairContext:
    segment = _segment(seam, side)
    audio_window = (FrameRange(seam, seam + 2) if side == "end"
                    else FrameRange(seam - 2, seam))
    silence = RemovableSilence(
        silence_id=f"sil-{seam}",
        segment_id=segment.segment_id,
        source_id="raw",
        source_samples=(SampleRange(30_000, 33_200) if side == "end"
                        else SampleRange(60_000, 63_200)),
        output_frames=FrameRange(segment.output_frames.start_frame + 5,
                                 segment.output_frames.start_frame + 7),
    )
    return RepairContext(
        target=_target(),
        segments=(segment,),
        protected_speech=(SampleRange(1_000, 2_000),),
        silences=(silence,) if candidates else (),
        covered_picture=(audio_window,) if candidates else (),
        replaceable_audio=(
            CLOCK.samples_for_frames(audio_window),) if candidates else (),
        replaceable_audio_evidence_hash="d" * 64,
        dependents=(
            DependentTiming(
                "caption-1", "caption", FrameRange(seam + 5, seam + 10),
                "content"),
            DependentTiming(
                "card-1", "scene", FrameRange(seam + 15, seam + 25),
                "output-locked"),
        ),
        clock=CLOCK,
        total_frames=360,
        parent_timeline_map_hash="b" * 64,
        parent_picture_lock_hash="c" * 64,
        max_dirty_frames=120,
        max_audio_overlap_frames=15,
    )


class NonRippleCandidateTests(unittest.TestCase):
    def test_early_middle_late_repairs_are_duration_neutral(self) -> None:
        for seam in (30, 180, 330):
            with self.subTest(seam=seam):
                result = enumerate_non_ripple(_context(seam))
                self.assertEqual(result.status, "eligible")
                methods = {
                    row.operation["method"] for row in result.candidates
                }
                self.assertEqual(
                    methods,
                    {"audio-lj-overlap", "extend-and-reclaim-silence"})
                for row in result.candidates:
                    self.assertEqual(
                        row.operation["totalOutputFramesBefore"], 360)
                    self.assertEqual(
                        row.operation["totalOutputFramesAfter"], 360)
                    self.assertEqual(row.operation["extensionFrames"], 2)
                    self.assertRegex(row.operation_hash, r"^[0-9a-f]{64}$")
                picture = next(row for row in result.candidates
                               if row.operation["method"]
                               == "extend-and-reclaim-silence")
                self.assertEqual(
                    picture.operation["quantizationResidualSamples"], 800)
                self.assertEqual(
                    picture.operation["residualPolicy"],
                    "reclaimed-proved-silence")
                self.assertEqual(
                    picture.operation["sourceVideoFrameRange"],
                    {"startFrame": 31, "endFrameExclusive": 33})
                self.assertEqual(
                    picture.operation["sourceFrameRate"],
                    {"numerator": "30", "denominator": "1"})
                audio = next(row for row in result.candidates
                             if row.operation["method"] == "audio-lj-overlap")
                self.assertNotIn("quantizationResidualSamples", audio.operation)

    def test_onset_repair_emits_a_true_audio_lead_window(self) -> None:
        result = enumerate_non_ripple(_context(100, "start"))
        audio = next(row for row in result.candidates
                     if row.operation["method"] == "audio-lj-overlap")
        self.assertEqual(
            audio.operation["audioDirtyWindows"],
            [{"startFrame": 98, "endFrameExclusive": 100}])
        self.assertEqual(
            audio.operation["audioDirtySampleRanges"],
            [{"startSample": 157_600, "endSampleExclusive": 160_000}])
        self.assertEqual(audio.operation["extensionOutputSamples"], 2_400)
        self.assertEqual(audio.operation["segment"]["edge"], "start")

    def test_audio_overlap_never_steps_on_unproved_existing_words(self) -> None:
        context = _context(180)
        result = enumerate_non_ripple(RepairContext(**{
            **context.__dict__,
            "replaceable_audio": (),
        }))
        self.assertEqual(result.status, "eligible")
        self.assertEqual(
            {row.operation["method"] for row in result.candidates},
            {"extend-and-reclaim-silence"})

    def test_candidate_discloses_exact_dependent_revalidation_closure(self) -> None:
        context = _context(180)
        dependents = (
            DependentTiming(
                "outside", "scene", FrameRange(220, 225), "output-locked"),
            DependentTiming(
                "inside", "dialogue-mix", FrameRange(180, 182), "source"),
        )
        result = enumerate_non_ripple(RepairContext(**{
            **context.__dict__,
            "dependents": dependents,
        }))
        audio = next(row for row in result.candidates
                     if row.operation["method"] == "audio-lj-overlap")
        self.assertEqual(audio.operation["revalidatedDependentIds"], ["inside"])
        self.assertEqual(audio.operation["unchangedDependentIds"], ["outside"])

    def test_speed_adjusted_segment_uses_exact_requested_ratio(self) -> None:
        context = _context(180)
        segment = context.segments[0]
        fast = CompiledCutSegment(
            segment.segment_id, segment.element_version, segment.source_id,
            segment.source_rate, segment.source_samples,
            segment.output_frames, PositiveRational(2, 1))
        result = enumerate_non_ripple(RepairContext(**{
            **context.__dict__,
            "segments": (fast,),
        }))
        self.assertEqual(result.status, "eligible")
        self.assertTrue(all(row.operation["extensionFrames"] == 1
                            for row in result.candidates))
        self.assertTrue(all(row.operation["extensionOutputSamples"] == 1_200
                            for row in result.candidates))
        self.assertTrue(all(row.operation["speed"] == {
            "numerator": "2", "denominator": "1"}
                            for row in result.candidates))

    def test_word_straddling_two_segments_is_not_repaired_halfway(self) -> None:
        context = _context(180, candidates=False)
        first = _segment(180, "end")
        second = CompiledCutSegment(
            "seg-second", 1, "raw", 48_000,
            SampleRange(50_800, 100_000), FrameRange(180, 210),
            PositiveRational(1, 1))
        result = enumerate_non_ripple(RepairContext(**{
            **context.__dict__,
            "segments": (first, second),
        }))
        self.assertEqual(result.status, "NON_RIPPLE_IMPOSSIBLE")
        self.assertEqual(
            result.ripple_impact["blockingReason"],
            "WORD_STRADDLES_SEGMENTS")

    def test_overlapping_compiled_picture_segments_fail_closed(self) -> None:
        context = _context(180)
        overlap = CompiledCutSegment(
            "overlap", 1, "raw", 48_000, SampleRange(60_000, 80_000),
            FrameRange(170, 200), PositiveRational(1, 1))
        with self.assertRaisesRegex(RepairContractError, "overlap"):
            RepairContext(**{
                **context.__dict__,
                "segments": (*context.segments, overlap),
            })

    def test_impossible_case_has_exact_ripple_impact(self) -> None:
        result = enumerate_non_ripple(_context(180, candidates=False))
        self.assertEqual(result.status, "NON_RIPPLE_IMPOSSIBLE")
        impact = result.ripple_impact
        assert impact is not None
        self.assertTrue(impact["exact"])
        self.assertEqual(impact["requiredDurationDeltaFrames"], 2)
        self.assertEqual(impact["newTotalOutputFrames"], 362)
        self.assertEqual(
            impact["unchangedOutputLockedIds"], ["card-1"])
        self.assertEqual(
            impact["movedDependents"][0]["to"],
            {"startFrame": 187, "endFrameExclusive": 192})
        self.assertTrue(impact["reopensPictureLock"])

    def test_ripple_impact_is_independent_of_input_order(self) -> None:
        context = _context(180, candidates=False)
        reversed_context = RepairContext(**{
            **context.__dict__,
            "dependents": tuple(reversed(context.dependents)),
        })
        first = enumerate_non_ripple(context)
        second = enumerate_non_ripple(reversed_context)
        self.assertEqual(first.ripple_impact, second.ripple_impact)

    def test_picture_candidate_cannot_dirty_the_complete_timeline(self) -> None:
        segment = CompiledCutSegment(
            "all", 1, "raw", 48_000, SampleRange(20_000, 50_400),
            FrameRange(0, 10), PositiveRational(1, 1))
        context = RepairContext(
            target=_target(),
            segments=(segment,),
            protected_speech=(),
            silences=(RemovableSilence(
                "sil-all", "all", "raw", SampleRange(30_000, 33_200),
                FrameRange(0, 2)),),
            covered_picture=(),
            replaceable_audio=(),
            replaceable_audio_evidence_hash="d" * 64,
            dependents=(),
            clock=CLOCK,
            total_frames=10,
            parent_timeline_map_hash="b" * 64,
            parent_picture_lock_hash="c" * 64,
            max_dirty_frames=10,
            max_audio_overlap_frames=15,
        )
        result = enumerate_non_ripple(context)
        self.assertEqual(result.status, "NON_RIPPLE_IMPOSSIBLE")
        self.assertFalse(result.candidates)

    def test_complete_word_is_a_noop_not_an_impossible_repair(self) -> None:
        context = _context(180)
        complete = CompiledCutSegment(
            "complete", 1, "raw", 48_000,
            SampleRange(40_000, 60_000), FrameRange(150, 200),
            PositiveRational(1, 1))
        result = enumerate_non_ripple(
            RepairContext(**{
                **context.__dict__,
                "segments": (complete,),
                "silences": (),
            }))
        self.assertEqual(result.status, "already-complete")
        self.assertIsNone(result.ripple_impact)

if __name__ == "__main__":
    unittest.main(verbosity=2)
