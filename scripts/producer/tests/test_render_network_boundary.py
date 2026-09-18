"""Native graphics renders run under the approved localhost-only profile."""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import unittest

from graphics.hyperframes_invocation import LOCALHOST_ONLY_PROFILE, SANDBOX_EXEC, RenderInvocation, _command

TOOLS = {"node": "/usr/local/bin/node", "browser": "/b", "ffmpeg": "/f", "ffprobe": "/p"}


class RenderNetworkBoundaryTests(unittest.TestCase):
    def test_render_command_is_wrapped_in_the_profile(self) -> None:
        command = _command(RenderInvocation("/root", "comp.html", "mp4", {}, "/out.mp4"), "/cli.js", TOOLS)
        self.assertEqual(command[:4], [SANDBOX_EXEC, "-f", LOCALHOST_ONLY_PROFILE, "/usr/local/bin/node"])

    @unittest.skipUnless(sys.platform == "darwin", "macOS sandbox")
    def test_profile_denies_outbound_and_allows_loopback(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        accepted = []
        thread = threading.Thread(target=lambda: accepted.append(listener.accept()[0].close()), daemon=True)
        thread.start()
        try:
            local = subprocess.run([SANDBOX_EXEC, "-f", LOCALHOST_ONLY_PROFILE, "/usr/bin/nc", "-z", "-w", "3",
                                    "127.0.0.1", str(port)], capture_output=True, timeout=20)
            remote = subprocess.run([SANDBOX_EXEC, "-f", LOCALHOST_ONLY_PROFILE, "/usr/bin/nc", "-z", "-w", "3",
                                     "1.1.1.1", "443"], capture_output=True, timeout=20)
        finally:
            thread.join(timeout=5)
            listener.close()
        self.assertEqual(local.returncode, 0)
        self.assertNotEqual(remote.returncode, 0)
        self.assertEqual(len(accepted), 1)


if __name__ == "__main__":
    unittest.main()
