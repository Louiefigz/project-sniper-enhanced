"""Bound large native capture reports consistently without executing media work."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cut_preview_io as bounded
from studio import native_short_delivery as delivery
from studio import native_stage_evidence as stages
from studio.native_short_pipeline import NativeShortPipeline


class NativeCaptureReceiptTests(unittest.TestCase):
    """A larger explicit report budget retains every existing exact-file safeguard."""

    def setUp(self) -> None:
        """Keep tiny private TEST evidence with no actual image or video assets."""
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix='capture-receipt-'))
        self.root = Path(temporary).resolve()
        self.path = self.root / 'native-frames.json'
        self.record = {'status': 'native-references-and-seek-states-pass',
                       'frames': [{'frame': 0, 'repeat': False}]}
        self.path.write_text(json.dumps(self.record))

    def test_general_json_budget_stays_sixteen_mib(self) -> None:
        """Larger native diagnostics never loosen ordinary request or receipt limits."""
        self.assertEqual(bounded.MAX_JSON, 16 * 1024 * 1024)
        self.assertEqual(stages.MAX_NATIVE_CAPTURE_JSON_BYTES, 256 * 1024 * 1024)
        with patch.object(bounded, 'read_bytes', wraps=bounded.read_bytes) as read:
            self.assertEqual(bounded.bound_json(self.path), self.record)
        bound = read.call_args.kwargs.get('maximum')
        if bound is None and len(read.call_args.args) > 1:
            bound = read.call_args.args[1]
        self.assertEqual(bound, bounded.MAX_JSON)

    def test_real_json_above_general_limit_loads_with_explicit_native_budget(self) -> None:
        """Reproduce the failed handoff with valid padding, using only 16 MiB plus one byte."""
        raw = self.path.read_bytes()
        remaining = bounded.MAX_JSON + 1 - len(raw)
        with self.path.open('ab') as handle:
            while remaining:
                count = min(1024 * 1024, remaining)
                handle.write(b' ' * count)
                remaining -= count
        with patch.object(bounded.os, 'read', side_effect=AssertionError('oversize must fail before reading')):
            with self.assertRaisesRegex(RuntimeError, 'exceeds byte limit'):
                bounded.bound_json(self.path)
        expected = bounded.file_hash(self.path)
        self.assertEqual(stages.read_native_capture_receipt(self.path, expected), self.record)

    def test_explicit_budget_boundary_is_inclusive(self) -> None:
        """A caller-selected bound accepts exactly that many real unchanged bytes."""
        length = self.path.stat().st_size
        self.assertEqual(bounded.bound_json(self.path, maximum=length), self.record)
        with self.assertRaisesRegex(RuntimeError, f'{length} > {length - 1}'):
            bounded.bound_json(self.path, maximum=length - 1)

    def test_over_native_budget_rejects_sparse_file_before_allocating(self) -> None:
        """A 256 MiB limit is a cap, not permission to allocate larger diagnostics."""
        maximum = stages.MAX_NATIVE_CAPTURE_JSON_BYTES
        with self.path.open('wb') as handle:
            handle.truncate(maximum + 1)
        with patch.object(bounded.os, 'read', side_effect=AssertionError('no oversize reads')):
            with self.assertRaisesRegex(RuntimeError, f'{maximum + 1} > {maximum}'):
                stages.read_native_capture_receipt(self.path)

    def test_invalid_explicit_budgets_fail_before_opening(self) -> None:
        """Nonfinite, fractional and boolean limits cannot weaken the byte boundary."""
        for maximum in [0, -1, True, float('nan'), float('inf'), 1.5, '256']:
            with self.subTest(maximum=maximum), patch.object(bounded.os, 'open') as opened:
                with self.assertRaises(ValueError):
                    bounded.bound_json(self.path, maximum=maximum)
                opened.assert_not_called()

    def test_nonobject_invalid_utf8_and_empty_reports_are_rejected(self) -> None:
        """A larger size budget does not relax the exact JSON-object contract."""
        for content in [b'[]', b'null', b'1', b'true', b'"text"', b'{bad', b'{"x":"\xff"}', b'']:
            self.path.write_bytes(content)
            with self.subTest(content=content), self.assertRaises((RuntimeError, ValueError, UnicodeError)):
                stages.read_native_capture_receipt(self.path)

    def test_expected_hash_binds_bytes_even_when_json_meaning_is_unchanged(self) -> None:
        """Whitespace changes invalidate the bound original receipt just like content changes."""
        expected = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.path.write_text(json.dumps(self.record) + '\n')
        with self.assertRaisesRegex(RuntimeError, 'hash changed'):
            stages.read_native_capture_receipt(self.path, expected)

    def test_symlink_and_hardlink_reports_are_not_accepted(self) -> None:
        """References must be one regular file, not alternate links to mutable evidence."""
        alias = self.root / 'alias.json'
        alias.symlink_to(self.path)
        with self.assertRaises((OSError, RuntimeError)):
            stages.read_native_capture_receipt(alias)
        alias.unlink()
        os.link(self.path, alias)
        with self.assertRaisesRegex(RuntimeError, 'bounded regular'):
            stages.read_native_capture_receipt(self.path)

    def test_linked_parent_cannot_redirect_capture_evidence(self) -> None:
        """No-follow protection covers the ancestor path as well as the final file."""
        alias = self.root / 'parent-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'canonical'):
            stages.read_native_capture_receipt(alias / self.path.name)

    def test_changed_file_during_read_is_not_accepted(self) -> None:
        """The shared reader compares descriptor and pathname identity after reading."""
        real_read = os.read

        def mutate(descriptor: int, maximum: int) -> bytes:
            """Return real read bytes, then alter the source before final identity validation."""
            result = real_read(descriptor, maximum)
            self.path.write_text('{"status":"changed"}')
            return result

        with patch.object(bounded.os, 'read', side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, 'changed during read'):
                stages.read_native_capture_receipt(self.path)

    def pipeline(self) -> NativeShortPipeline:
        """Use real capture handoff with its owner explicitly replaced by an inert stub."""
        request = {'output': str(self.root), 'captureMode': 'sdk-streaming', 'verifyStage': 'TEST already rendered',
                   'tools': {'node': 'TEST-NO-LAUNCH'}}
        pipeline = NativeShortPipeline(request, {})
        self.enterContext(patch.object(pipeline, 'supervise'))
        self.enterContext(patch('studio.native_short_pipeline.complete_capture', return_value=({}, {})))
        return pipeline

    def qualify_without_media(self) -> dict:
        """Exercise report consumption while stubbing all frame/codec inspection."""
        (self.root / 'review.mp4').write_bytes(b'TEST fixture, not playable media')
        replacements = {'qualify_reverse_frames': [],
                        'observe_picture_source': SimpleNamespace(packets=[{}]),
                        'reference_identities': {}, 'full_decode': None,
                        'compare_selected_frames': ([{'passed': True}], {'scratchBytes': 0})}
        for name, value in replacements.items():
            self.enterContext(patch.object(delivery, name, return_value=value))
        self.enterContext(patch.object(delivery, 'run', side_effect=AssertionError('no media commands')))
        return delivery.qualify_picture(self.root, {'totalFrames': 1, 'frameRate': '25/1'})

    def test_capture_handoff_and_encoded_verification_use_the_same_bounded_reader(self) -> None:
        """Both production consumers forward the single shared native-report limit."""
        with patch.object(stages, 'bound_json', wraps=bounded.bound_json) as read:
            pipeline = self.pipeline()
            pipeline.capture()
            result = self.qualify_without_media()
        self.assertTrue(result['passed'])
        self.assertEqual(read.call_count, 2)
        self.assertEqual([call.args[0] for call in read.call_args_list], [self.path, self.path])
        self.assertEqual([call.kwargs['maximum'] for call in read.call_args_list],
                         [stages.MAX_NATIVE_CAPTURE_JSON_BYTES] * 2)
        self.assertEqual(pipeline.evidence[str(self.path)], bounded.file_hash(self.path))

    def test_both_consumers_reject_shared_reader_failure_before_qc(self) -> None:
        """A rejected report cannot reach frame decoding or become retained evidence."""
        with patch.object(stages, 'bound_json', side_effect=RuntimeError('TEST reader rejected')):
            pipeline = self.pipeline()
            with self.assertRaisesRegex(RuntimeError, 'TEST reader rejected'):
                pipeline.capture()
            with patch.object(delivery, 'qualify_reverse_frames') as reverse:
                with self.assertRaisesRegex(RuntimeError, 'TEST reader rejected'):
                    delivery.qualify_picture(self.root, {'totalFrames': 1, 'frameRate': '25/1'})
                reverse.assert_not_called()
        self.assertNotIn(str(self.path), pipeline.evidence)


if __name__ == '__main__':
    unittest.main()
