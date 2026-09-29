"""Client session for a Codex app-server this probe started with `--listen unix://PATH`.

That transport speaks WebSocket over the Unix socket (the server answers an HTTP
upgrade with 101). This is a minimal RFC 6455 client: masked text frames out,
unmasked frames in, ping answered with pong. It exposes the same send/wait/
snapshot surface as StreamChild so RpcClient works over either transport.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
from pathlib import Path

from studio.production.host_conformance.stream_child import EventLog

TEXT, CLOSE, PING, PONG = 0x1, 0x8, 0x9, 0xA


def _frame(opcode: int, payload: bytes) -> bytes:
    """One masked client frame."""
    head = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        head += bytes([0x80 | size])
    elif size < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack("!H", size)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", size)
    mask = os.urandom(4)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


def _exact(sock: socket.socket, count: int) -> bytes:
    """Read exactly count bytes or raise when the peer closes."""
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError("socket closed")
        data += chunk
    return data


def _read_frame(sock: socket.socket) -> tuple[int, bytes]:
    """One server frame (opcode, payload); servers do not mask."""
    first, second = _exact(sock, 2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", _exact(sock, 2))[0]
    elif size == 127:
        size = struct.unpack("!Q", _exact(sock, 8))[0]
    mask = _exact(sock, 4) if second & 0x80 else b""
    payload = _exact(sock, size)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return first & 0x0F, payload


class SocketSession(EventLog):
    """One WebSocket connection to a probe-owned unix-socket app-server."""

    def __init__(self, path: str, raw_log: Path) -> None:
        """Connect, complete the upgrade handshake and start reading frames."""
        super().__init__()
        self.raw_log = raw_log
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self._handshake()
        self.lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _handshake(self) -> None:
        """HTTP upgrade; refuse anything other than 101."""
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            reply += _exact(self.sock, 1)
        if not reply.startswith(b"HTTP/1.1 101"):
            raise ConnectionError(f"upgrade refused: {reply[:80]!r}")

    def reading(self) -> bool:
        """True while the connection is being read."""
        return self._reader.is_alive()

    def _read(self) -> None:
        """Record text frames; answer pings; stop on close or disconnect."""
        with open(self.raw_log, "w") as log:
            while (frame := self._next()) is not None:
                log.write(frame + "\n")
                log.flush()
                self.record(frame)

    def _next(self) -> str | None:
        """Next text payload; None at close or disconnect."""
        try:
            return self._next_text()
        except (ConnectionError, OSError):
            return None

    def _next_text(self) -> str | None:
        """Skip control frames (answering pings) until a text frame or close."""
        opcode, payload = _read_frame(self.sock)
        while opcode != TEXT:
            if opcode == CLOSE:
                return None
            if opcode == PING:
                self._send_raw(_frame(PONG, payload))
            opcode, payload = _read_frame(self.sock)
        return payload.decode(errors="replace")

    def _send_raw(self, data: bytes) -> None:
        """Serialize writes from the reader (pong) and the caller."""
        with self.lock:
            self.sock.sendall(data)

    def send(self, message: dict) -> float:
        """Send one JSON-RPC message as a text frame; returns the send time."""
        self._send_raw(_frame(TEXT, json.dumps(message).encode()))
        return self.elapsed()

    def close_stdin(self) -> None:
        """Close the connection (the socket analogue of EOF)."""
        try:
            self._send_raw(_frame(CLOSE, b""))
        except OSError:
            pass
        self.sock.close()
