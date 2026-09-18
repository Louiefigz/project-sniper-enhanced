"""Pure native review HTML contracts: exact clocks, bytes and wrapper boundaries."""
from __future__ import annotations
import copy
import sys
import unittest
from fractions import Fraction
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.native_review_html import adapt_html, canvas_clock, decimal_text, frame_points, without_audio


def fixture(rate: str = '25/1', total: int = 25, name: str = 'native-canvas') -> tuple[str, dict]:
    """Generate a small native-shaped fixture without browser or media work."""
    fps = Fraction(rate); duration = decimal_text(Fraction(total, 1) / fps)
    canvas = {'frameRate': rate, 'totalFrames': total, 'segments': [{'startFrame': 0, 'endFrameExclusive': total}]}
    source = ('<html><head></head><body>'
        f'<div id="{name}" data-composition-id="{name}" data-width="1920" data-height="1080" '
        f'data-fps="{decimal_text(fps)}" data-duration="{duration}">'
        '<div id="source-crop-0-0"><video id="source-0-0" class="clip" src="assets/source.mp4" '
        f'data-start="0" data-duration="{duration}"></video></div>'
        f'<audio id="spoken-source" class="clip" src="assets/source.wav" data-start="0" data-duration="{duration}"></audio>'
        '<p>Unchanged captions and graphics</p></div><script>const tl=gsap.timeline({paused:true});'
        f'window.__timelines=window.__timelines||{{}};window.__timelines["{name}"]=tl;</script></body></html>')
    return source, canvas


class NativeReviewHtmlTests(unittest.TestCase):
    """Shared preparation never needs fake 25fps or fixed project identities."""

    def test_rational_and_long_form_named_canvas(self) -> None:
        """Rational and long form named canvas."""
        for rate, total in [('25/1', 25), ('30000/1001', 18000), ('24/1', 14400), ('60/1', 60)]:
            source, canvas = fixture(rate, total, 'customer-story')
            with self.subTest(rate=rate):
                result, proof = adapt_html(source, canvas)
                self.assertIn('studio-dialogue-master', result)
                self.assertEqual(proof['audio']['removedIds'], ['spoken-source'])
                self.assertEqual(len(proof['visibility']['windows']), 1)
                self.assertEqual(canvas_clock(canvas)[0].sample_at_frame(total), round(Fraction(total * 48000, 1) / Fraction(rate)))
                restored = result
                for row in proof['visibility']['insertions']:
                    restored = restored.replace(row['text'], '', 1)
                self.assertEqual(without_audio(restored), without_audio(source))

    def test_invalid_clock_audio_and_wrapper_contracts_reject(self) -> None:
        """Invalid clock audio and wrapper contracts reject."""
        source, canvas = fixture()
        changes = [source.replace('data-fps="25"', 'data-fps="30"'),
                   source.replace('data-duration="1"></audio>', 'data-duration="0.9"></audio>'),
                   source.replace('<div id="source-crop-0-0">', '<div id="source-crop-0-0">Meaningful text'),
                   source.replace('<audio id="spoken-source"', '<audio id="spoken-source" id="duplicate"'),
                   source.replace('</audio>', ''), source.replace('spoken-source', 'studio-dialogue-master')]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises((ValueError, KeyError)):
                adapt_html(changed, canvas)
        for rate in ['0/1', '1/0', '-25/1', '61/1']:
            with self.subTest(rate=rate), self.assertRaises((ValueError, ZeroDivisionError)):
                canvas_clock({**canvas, 'frameRate': rate})

    def test_adapted_and_noncontiguous_projects_reject(self) -> None:
        """Adapted and noncontiguous projects reject."""
        source, canvas = fixture(); adapted, _proof = adapt_html(source, canvas)
        with self.assertRaises(ValueError): adapt_html(adapted, canvas)
        changed = copy.deepcopy(canvas); changed['segments'][0]['startFrame'] = 1
        with self.assertRaises(ValueError): canvas_clock(changed)

    def test_exact_checkpoint_indices_include_both_title_sides(self) -> None:
        """Exact checkpoint indices include both title sides."""
        _source, canvas = fixture('30000/1001', 30)
        canvas['titleCard'] = {'endFrame': 12}
        plan = {'canvas': canvas, 'strategy': {'scenes': [{'startFrame': 0, 'endFrame': 30}]}}
        points = frame_points(plan)
        self.assertEqual([row['frame'] for row in points], [0, 11, 12, 14, 29])
        self.assertLess(abs(Fraction(points[-1]['seconds']) - Fraction(29 * 1001, 30000)), Fraction(1, 10**12))

    def test_real_long_shape_keeps_visual_bytes_and_scene_checkpoints(self) -> None:
        """Long export does not promise Short wrappers, root IDs or audio CSS classes."""
        source, canvas = fixture('30/1', 120, 'long-test')
        source = source.replace('id="long-test"', 'id="root"', 1)
        source = source.replace('<div id="source-crop-0-0">', '').replace('</video></div>', '</video>')
        source = source.replace('id="spoken-source" class="clip"', 'id="spoken-source"')
        adapted, proof = adapt_html(source, canvas, native_long=True)
        self.assertEqual(without_audio(source), without_audio(adapted))
        self.assertEqual(proof['visibility']['mode'], 'preserved-native-long-visuals')
        points = frame_points({'canvas': canvas, 'scenes': [
            {'startFrame': 0, 'endFrame': 60}, {'startFrame': 60, 'endFrame': 120}]})
        self.assertEqual([row['frame'] for row in points], [0, 29, 59, 60, 89, 119])


if __name__ == '__main__': unittest.main()
