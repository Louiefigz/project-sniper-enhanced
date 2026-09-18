"""Pure HTML admission and preservation checks for editable Studio visibility."""
import hashlib
import unittest

from studio.native_media_visibility import adapt_media_visibility, media_windows


def fixture() -> str:
    """Include cut crops, a nested proof pose, audio and unrelated title pixels."""
    return '''<!doctype html><html><head><style>.crop{overflow:hidden}</style></head><body>
<div id="native-canvas" data-composition-id="native-canvas" data-duration="4">
<audio id="dialogue-0" class="clip" src="a.m4a" data-start="0" data-duration="4"></audio>
<div id="source-crop-0-0" class="crop"><video id="source-0-0" class="clip" src="a.mp4"
data-start="0" data-duration="2" style="left:-200px"></video></div>
<div id="source-crop-0-1" class="crop"><video id="source-0-1" class="clip" src="a.mp4"
data-start="2" data-duration="2"></video></div>
<div id="proof-crop"><div id="proof-pose"><video id="proof" class="clip" src="proof.mp4"
data-start="1.001" data-duration="0.5005"></video></div></div>
<div id="title" class="clip" data-start="0" data-duration="1">Actual title</div></div>
<script>const tl=gsap.timeline({paused:true});tl.set('#proof-pose',{x:-20},0);
tl.to({}, {duration:4}, 0);window.__timelines=window.__timelines||{};window.__timelines["native-canvas"]=tl;</script>
</body></html>'''


class NativeMediaVisibilityTests(unittest.TestCase):
    """Fail closed around malformed media containers and preserve unrelated bytes."""

    def test_exact_windows_and_full_source_recovery(self) -> None:
        source = fixture()
        adapted, proof = adapt_media_visibility(source)
        restored = adapted
        for insertion in proof['insertions']:
            restored = restored.replace(insertion['text'], '', 1)
        self.assertEqual(restored, source)
        self.assertEqual(proof['sourceSha256'], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(proof['adaptedSha256'], hashlib.sha256(adapted.encode()).hexdigest())
        self.assertEqual(proof['windows'][-1], {'wrapperId':'proof-crop','videoId':'proof',
                         'startSeconds':'1.001','endSecondsExclusive':'1.5015'})
        self.assertNotIn('"#dialogue-0"', proof['insertions'][1]['text'])
        self.assertNotIn('"#title"', proof['insertions'][1]['text'])
        self.assertNotIn('"#proof-pose"', proof['insertions'][1]['text'])
        self.assertEqual(adapt_media_visibility(source), (adapted, proof))

    def test_legacy_float_duration_is_preserved(self) -> None:
        source = fixture().replace('data-duration="4"', 'data-duration="21.4"')
        source = source.replace('data-start="2" data-duration="2"',
                                'data-start="18.96" data-duration="2.4399999999999977"')
        self.assertEqual(media_windows(source)[1]['endSecondsExclusive'], '21.3999999999999977')

    def test_duplicate_adaptation_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, 'existing'):
            adapt_media_visibility(adapt_media_visibility(fixture())[0])

    def test_display_gates_explicitly_visible_descendant(self) -> None:
        source = fixture().replace('src="proof.mp4"', 'src="proof.mp4" style="visibility:visible"')
        _, proof = adapt_media_visibility(source)
        style, commands = [row['text'] for row in proof['insertions']]
        self.assertIn('#source-crop-0-0{display:block}', style)
        self.assertIn('#proof-crop{display:none}', style)
        self.assertIn('tl.set("#proof-crop",{display:"block"},1.001);', commands)
        self.assertIn('tl.set("#proof-crop",{display:"none"},1.5015);', commands)
        self.assertNotIn('{visibility:', commands)

    def test_bad_clocks_and_ids_rejected(self) -> None:
        changes = [('data-start="1.001"', 'data-start="-1"'),
                   ('data-duration="0.5005"', 'data-duration="0"'),
                   ('data-duration="0.5005"', 'data-duration="NaN"'),
                   ('data-start="1.001"', 'data-start="3.999"'),
                   ('id="proof"', 'id="source-0-0"'),
                   ('id="proof"', 'id="proof[bad]"'),
                   ('src="proof.mp4"', '')]
        for old, new in changes:
            with self.subTest(new=new), self.assertRaises(ValueError):
                adapt_media_visibility(fixture().replace(old, new))

    def test_unrelated_content_and_ownership_rejected(self) -> None:
        changes = [('<div id="proof-pose">', '<div id="proof-pose">A label'),
                   ('</video></div></div>', '</video><span>Label</span></div></div>'),
                   ('id="proof-crop"', 'id="proof-crop" data-start="0"'),
                   ('id="proof-crop"', 'id="proof-crop" class="clip"'),
                   ('id="proof-pose"', 'id="proof-pose" style="visibility:hidden"'),
                   ('id="proof-crop"', 'id="wrong-crop"'),
                   ('id="proof-crop"', 'id="proof-crop" id="proof-crop"'),
                   ('id="proof-crop"', 'id="proof-crop" style="display:none"')]
        for old, new in changes:
            with self.subTest(new=new), self.assertRaises(ValueError):
                adapt_media_visibility(fixture().replace(old, new))

    def test_unknown_timeline_or_existing_visibility_rejected(self) -> None:
        changes = [('const tl=gsap.timeline({paused:true});', 'const tl=other();'),
                   ("{x:-20}", '{visibility:"hidden"}'),
                   ("{x:-20}", '{autoAlpha:0}'),
                   ('</head>', '</head></head>'),
                   ('</video></div></div>', '</video></div>')]
        for old, new in changes:
            with self.subTest(new=new), self.assertRaises(ValueError):
                adapt_media_visibility(fixture().replace(old, new))


if __name__ == '__main__':
    unittest.main()
