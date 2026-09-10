"""Real PNG byte-structure faults; no subprocess, decoder or admission authority."""
from __future__ import annotations

import hashlib
import os
import struct
import unittest
from dataclasses import replace
from unittest.mock import patch

from _guided_presenter_observation_fixture import ObservationFixture, png_bytes, png_chunk
from guided_presenter_png import inspect_presenter_png, validate_presenter_png_metadata
from guided_presenter_probe_identity import PresenterProbePin


class PresenterPngTests(unittest.TestCase):
    """Metadata is real parsed bytes; compressed-pixel validity is not claimed here."""

    def inspect(self, payload: bytes) -> object:
        """Open the exact small TEST caller-held bytes through production no-follow pins."""
        fixture = ObservationFixture(True, payload)
        self.addCleanup(fixture.close)
        with PresenterProbePin(fixture.source, fixture.runtime) as pin:
            return inspect_presenter_png(pin)

    def test_explicit_srgb_square_pixels_and_metadata_inventory(self) -> None:
        """The retained raw metadata exactly covers header and chunk lengths to EOF."""
        data = png_bytes()
        value = self.inspect(data)
        self.assertEqual((value.width, value.height, value.color_chunks), (64, 36, ("sRGB",)))
        self.assertLess(value.metadata_bytes_read, len(data))
        validate_presenter_png_metadata(value, len(data))

    def test_exact_cicp_and_fallback_color_values_agree(self) -> None:
        """Both explicit profile paths agree; approximate fallback tags cannot override them."""
        extra = png_chunk(b"cICP", bytes((1, 13, 0, 1)))
        extra += png_chunk(b"gAMA", struct.pack(">I", 45455))
        extra += png_chunk(b"cHRM", struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000))
        self.assertEqual(self.inspect(png_bytes(extra)).color_chunks, ("sRGB", "cICP"))

    def test_cicp_cannot_hide_icc_hdr_orientation_alpha_or_animation(self) -> None:
        """Known decoder profile precedence cannot launder a shadowed forbidden chunk."""
        for kind in (b"iCCP", b"eXIf", b"cLLI", b"mDCV", b"tRNS", b"acTL", b"fcTL", b"fdAT", b"ABCD"):
            data = png_bytes(png_chunk(b"cICP", bytes((1, 13, 0, 1))) + png_chunk(kind, b"TEST"))
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "unsupported"):
                self.inspect(data)

    def test_untagged_missing_sar_and_conflicting_metadata_do_not_default(self) -> None:
        """Unknown color and square-pixel state remain unsupported, never assumed."""
        variants = [png_bytes().replace(png_chunk(b"sRGB", b"\x01"), b""),
            png_bytes().replace(png_chunk(b"pHYs", struct.pack(">IIB", 1, 1, 0)), b""),
            png_bytes(png_chunk(b"cICP", bytes((1, 13, 0, 0)))),
            png_bytes(png_chunk(b"gAMA", struct.pack(">I", 50000))),
            png_bytes(png_chunk(b"cHRM", bytes(32))),
            png_bytes().replace(png_chunk(b"sRGB", b"\x01"), png_chunk(b"sRGB", b"\x00")),
            png_bytes().replace(png_chunk(b"pHYs", struct.pack(">IIB", 1, 1, 0)), png_chunk(b"pHYs", struct.pack(">IIB", 2, 1, 0)))]
        for data in variants:
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                self.inspect(data)

    def test_ihdr_alpha_high_depth_interlace_and_oversize_are_refused(self) -> None:
        """Declared unsupported native pixels fail before any decoder is allowed."""
        original = png_chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 36, 8, 2, 0, 0, 0))
        for fields in ((64, 36, 8, 6, 0, 0, 0), (64, 36, 16, 2, 0, 0, 0),
                       (64, 36, 8, 2, 0, 0, 1), (8192, 36, 8, 2, 0, 0, 0)):
            data = png_bytes().replace(original, png_chunk(b"IHDR", struct.pack(">IIBBBBB", *fields)))
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.inspect(data)

    def test_crc_truncation_duplicate_length_and_trailing_bytes_refuse(self) -> None:
        """Malformed boundaries cannot create a partial successful inventory."""
        chunk = png_chunk(b"sRGB", b"\x01")
        variants = [png_bytes()[:-1], png_bytes() + b"trailing", png_bytes(chunk),
            png_bytes().replace(chunk, chunk[:-1] + bytes((chunk[-1] ^ 1,))),
            png_bytes().replace(chunk, struct.pack(">I", 0x7fffffff) + chunk[4:])]
        for data in variants:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                self.inspect(data)

    def test_idat_payload_is_seek_skipped_not_rehashed_as_metadata(self) -> None:
        """Only header and profile bytes are scanned; pixel validity belongs to actual decode."""
        reads, real_read = [], os.read

        def count_read(fd: int, size: int) -> bytes:
            """Count actual FD reads while preserving the real byte implementation."""
            reads.append(size)
            return real_read(fd, size)

        with patch("guided_presenter_png.os.read", side_effect=count_read):
            value = self.inspect(png_bytes())
        self.assertEqual(sum(reads), value.metadata_bytes_read)
        self.assertEqual([row[2] for row in value.chunks if row[0] == "IDAT"], [None])

    def test_oversized_metadata_refuses_before_reading_its_payload(self) -> None:
        """Declared metadata allocation cannot consume more than the original1MiB cap."""
        data = png_bytes(png_chunk(b"gAMA", b"0" * (1024 * 1024)))
        real_read = os.read

        def bounded_read(fd: int, size: int) -> bytes:
            """Fail the test if code tries the rejected large allocation."""
            self.assertLess(size, 1024 * 1024)
            return real_read(fd, size)

        with patch("guided_presenter_png.os.read", side_effect=bounded_read), self.assertRaises(ValueError):
            self.inspect(data)

    def test_retained_payload_hash_order_size_and_summary_tampering_refuse(self) -> None:
        """Typed frozen observations still require complete retained-byte consistency."""
        data = png_bytes()
        value = self.inspect(data)
        chunks = tuple((kind, size, "a" * 64 if kind == "sRGB" else sha) for kind, size, sha in value.chunks)
        variants = [replace(value, width=62), replace(value, metadata_bytes_read=1),
            replace(value, chunks=chunks), replace(value, chunks=tuple(reversed(value.chunks))),
            replace(value, color_chunks=("cICP",)),
            replace(value, metadata=value.metadata + (("sRGB", b"\x01"),))]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_presenter_png_metadata(changed, len(data))
        with self.assertRaises(ValueError):
            validate_presenter_png_metadata(value, len(data) + 1)

    def test_idat_cannot_acquire_a_fabricated_observed_metadata_hash(self) -> None:
        """Compressed-byte SHA authority is deliberately not provided by this reader."""
        data = png_bytes()
        value = self.inspect(data)
        changed = tuple((kind, size, hashlib.sha256(b"invented").hexdigest() if kind == "IDAT" else sha)
                        for kind, size, sha in value.chunks)
        with self.assertRaisesRegex(ValueError, "invented"):
            validate_presenter_png_metadata(replace(value, chunks=changed), len(data))


if __name__ == "__main__":
    unittest.main()
