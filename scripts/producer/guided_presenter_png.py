"""Bounded explicit-sRGB PNG metadata, not ICC interpretation or image admission.

Only chunk metadata is read/CRC-checked. IDAT is seek-skipped; its bytes remain
bound by the caller's original admission hash and the subsequent actual decode.
Unknown or shadowed profiles, alpha, animation and orientation are unsupported.
"""
from __future__ import annotations

import hashlib
import os
import struct
import zlib
from dataclasses import dataclass

from guided_presenter_probe_identity import PresenterProbePin, probe_deadline_remaining
from opening_prefix_contract import valid_canvas

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ALLOWED = {b"IHDR", b"pHYs", b"sRGB", b"cICP", b"cHRM", b"gAMA", b"IDAT", b"IEND"}
_CHROMATICITIES = (31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)


@dataclass(frozen=True)
class PresenterPngMetadata:
    """Exact inspected metadata summaries; compressed pixel CRCs are not claimed."""
    width: int
    height: int
    color_chunks: tuple[str, ...]
    chunks: tuple[tuple[str, int, str | None], ...]
    metadata_bytes_read: int
    metadata: tuple[tuple[str, bytes], ...]


def _read(pin: PresenterProbePin, size: int) -> bytes:
    """Bound each header/metadata read and retain the original inode/clock scope."""
    probe_deadline_remaining(pin.runtime)
    pin.assert_current()
    if not 0 <= size <= 1024 * 1024:
        raise ValueError("Presenter PNG metadata read exceeds its byte bound")
    data = os.read(pin.fd, size)
    if len(data) != size:
        raise ValueError("Presenter PNG chunk is truncated")
    return data


def _metadata_chunk(kind: bytes, payload: bytes) -> None:
    """Require explicit supported fields, not metadata that is silently overridden."""
    if kind == b"sRGB" and payload != b"\x01":
        raise ValueError("Presenter PNG requires relative-colorimetric sRGB intent")
    if kind == b"cICP" and payload != bytes((1, 13, 0, 1)):
        raise ValueError("Presenter PNG cICP is not full-range BT709/sRGB RGB")
    if kind == b"cHRM" and (len(payload) != 32 or struct.unpack(">8I", payload) != _CHROMATICITIES):
        raise ValueError("Presenter PNG chromaticities disagree with the explicit sRGB profile")
    if kind == b"gAMA" and payload != struct.pack(">I", 45455):
        raise ValueError("Presenter PNG fallback gamma disagrees with explicit sRGB metadata")
    if kind == b"pHYs":
        _physical(payload)


def _physical(payload: bytes) -> None:
    """Require actual equal positive pixel dimensions rather than assuming SAR."""
    if len(payload) != 9:
        raise ValueError("Presenter PNG pHYs length is malformed")
    x, y, unit = struct.unpack(">IIB", payload)
    if x == 0 or x != y or unit not in (0, 1):
        raise ValueError("Presenter PNG requires explicit square-pixel pHYs metadata")


def _dimensions(payload: bytes) -> tuple[int, int]:
    """Admit only opaque8-bit truecolor, progressive PNG within existing dimensions."""
    if len(payload) != 13:
        raise ValueError("Presenter PNG IHDR length is malformed")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
    if not valid_canvas(width, height) or (depth, color, compression, filtering, interlace) != (8, 2, 0, 0, 0):
        raise ValueError("Presenter PNG requires bounded opaque8-bit progressive RGB")
    return width, height


def _chunk(pin: PresenterProbePin, offset: int, budget: int) -> tuple[bytes, int, bytes | None]:
    """Check exact chunk bounds/metadata CRC while avoiding a second IDAT byte scan."""
    if budget < 8:
        raise ValueError("Presenter PNG metadata exhausted its byte budget")
    length, kind = struct.unpack(">I4s", _read(pin, 8))
    if length > 0x7fffffff or offset + 12 + length > pin.value.size_bytes:
        raise ValueError("Presenter PNG chunk leaves the held file")
    if kind not in _ALLOWED:
        raise ValueError("Presenter PNG contains unsupported critical/profile/alpha/animation/orientation metadata")
    if kind == b"IDAT":
        os.lseek(pin.fd, length + 4, os.SEEK_CUR)
        return kind, length, None
    if length + 12 > budget:
        raise ValueError("Presenter PNG metadata chunk exceeds its remaining byte budget")
    payload, crc = _read(pin, length), _read(pin, 4)
    if struct.unpack(">I", crc)[0] != zlib.crc32(kind + payload):
        raise ValueError("Presenter PNG metadata CRC is invalid")
    return kind, length, payload


def _inventory(pin: PresenterProbePin) -> tuple[dict[bytes, bytes], tuple, int]:
    """Enforce unique metadata, contiguous IDAT, one terminal IEND and exact EOF."""
    metadata, chunks, read_bytes, seen_idat, ended_idat = {}, [], 8, False, False
    for _index in range(4096):
        offset = os.lseek(pin.fd, 0, os.SEEK_CUR)
        kind, length, payload = _chunk(pin, offset, 1024 * 1024 - read_bytes)
        read_bytes += 8 if payload is None else length + 12
        if read_bytes > 1024 * 1024 or (not chunks and kind != b"IHDR"):
            raise ValueError("Presenter PNG metadata exceeds bounds or lacks first IHDR")
        if kind == b"IDAT" and ended_idat:
            raise ValueError("Presenter PNG IDAT chunks must be contiguous")
        if kind != b"IDAT" and (kind in metadata or (seen_idat and kind != b"IEND")):
            raise ValueError("Presenter PNG metadata is duplicated or follows its image data")
        seen_idat = seen_idat or kind == b"IDAT"
        ended_idat = ended_idat or (seen_idat and kind != b"IDAT")
        chunks.append((kind.decode("ascii"), length, hashlib.sha256(payload).hexdigest() if payload is not None else None))
        if payload is not None:
            metadata[kind] = payload
        if kind == b"IEND":
            return _finish_inventory(pin, metadata, seen_idat), tuple(chunks), read_bytes
    raise ValueError("Presenter PNG exceeds its chunk-count bound")


def _finish_inventory(pin: PresenterProbePin, metadata: dict, seen_idat: bool) -> dict:
    """No trailing bytes, empty image or implicit default color/SAR can pass."""
    if not seen_idat or metadata[b"IEND"] or os.lseek(pin.fd, 0, os.SEEK_CUR) != pin.value.size_bytes:
        raise ValueError("Presenter PNG lacks exact image/IEND/EOF structure")
    if b"pHYs" not in metadata or not ({b"sRGB", b"cICP"} & metadata.keys()):
        raise ValueError("Presenter PNG requires explicit sRGB/cICP and square-pixel metadata")
    return metadata


def inspect_presenter_png(pin: PresenterProbePin) -> PresenterPngMetadata:
    """Inspect only the incoming held descriptor; never reopen or reseal its path."""
    os.lseek(pin.fd, 0, os.SEEK_SET)
    if _read(pin, 8) != _SIGNATURE:
        raise ValueError("Presenter still observation initially supports explicit tagged PNG only")
    metadata, chunks, byte_count = _inventory(pin)
    width, height = _dimensions(metadata[b"IHDR"])
    for kind, payload in metadata.items():
        _metadata_chunk(kind, payload)
    probe_deadline_remaining(pin.runtime)
    pin.assert_current()
    colors = tuple(name for name in ("sRGB", "cICP") if name.encode() in metadata)
    result = PresenterPngMetadata(width, height, colors, chunks, byte_count,
                                  tuple((key.decode("ascii"), value) for key, value in metadata.items()))
    validate_presenter_png_metadata(result, pin.value.size_bytes)
    return result


def validate_presenter_png_metadata(value: PresenterPngMetadata, file_size: int) -> None:
    """Revalidate retained metadata only; no reread, pixel CRC or cold authority claim."""
    if type(value) is not PresenterPngMetadata or type(value.metadata) is not tuple or type(value.chunks) is not tuple:
        raise ValueError("Presenter PNG observation has the wrong immutable shape")
    if not 1 <= len(value.chunks) <= 4096 or len(value.metadata) > len(_ALLOWED):
        raise ValueError("Presenter PNG retained inventory exceeds its original bounds")
    metadata = {}
    for row in value.metadata:
        if type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or type(row[1]) is not bytes:
            raise ValueError("Presenter PNG retained metadata is malformed")
        if row[0] in metadata or row[0].encode() not in _ALLOWED or row[0] == "IDAT":
            raise ValueError("Presenter PNG retained metadata is duplicated or unsupported")
        metadata[row[0]] = row[1]
        _metadata_chunk(row[0].encode(), row[1])
    if "IHDR" not in metadata or _dimensions(metadata["IHDR"]) != (value.width, value.height):
        raise ValueError("Presenter PNG retained dimensions differ from IHDR")
    colors = tuple(name for name in ("sRGB", "cICP") if name in metadata)
    if not colors or colors != value.color_chunks or "pHYs" not in metadata or metadata.get("IEND") != b"":
        raise ValueError("Presenter PNG retained profile/SAR/end marker is incomplete")
    _validate_inventory(value, metadata, file_size)


def _validate_inventory(value: PresenterPngMetadata, metadata: dict, file_size: int) -> None:
    """Bind every metadata payload, chunk order, skipped data length and exact EOF."""
    total, count, names, data_bytes, seen_data = 8, 8, [], 0, False
    for row in value.chunks:
        if type(row) is not tuple or len(row) != 3 or type(row[0]) is not str or type(row[1]) is not int:
            raise ValueError("Presenter PNG retained chunk row is malformed")
        kind, length, sha = row
        if kind.encode() not in _ALLOWED or not 0 <= length <= 0x7fffffff:
            raise ValueError("Presenter PNG retained chunk type/length is unsupported")
        total += length + 12
        count += 8 if kind == "IDAT" else length + 12
        if kind == "IDAT" and (sha is not None or "IEND" in names):
            raise ValueError("Presenter PNG compressed bytes acquired an invented metadata hash")
        if kind == "IDAT":
            seen_data, data_bytes = True, data_bytes + length
            continue
        if kind in names or (seen_data and kind != "IEND") or kind not in metadata:
            raise ValueError("Presenter PNG retained chunk ordering is unsupported")
        payload = metadata[kind]
        if length != len(payload) or sha != hashlib.sha256(payload).hexdigest():
            raise ValueError("Presenter PNG retained payload differs from its actual metadata hash")
        names.append(kind)
    if (names != list(metadata) or value.chunks[0][0] != "IHDR" or value.chunks[-1][0] != "IEND"
            or data_bytes <= 0 or total != file_size or count != value.metadata_bytes_read or count > 1024 * 1024):
        raise ValueError("Presenter PNG retained byte inventory does not cover its original file")
