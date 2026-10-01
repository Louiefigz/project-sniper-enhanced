"""TEST driver: Studio-server look-alikes and a real opener that is killed mid-startup.

A "server" is the installed Node running a TEST ``cli.js`` that only sleeps, so its command line
is exactly a Sniper Studio server's:
``<node> <runtime>/dist/cli.js preview <project> --port <port> --foreground --json --no-open``.
Nothing here links to or modifies a real binary.

  spawn <node> <cli> <project> <port>             start one server in its own session, print its
                                                  PID, exit (the server is reparented, as a
                                                  killed opener's is)
  opener <node> <state root> <runtime> <project>  run the real managed open until readiness, print
                                                  ``SPAWNED <pid>`` and wait there to be killed
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parents[2]), str(HERE.parents[1])]


def start_server(node: str, cli: str, project: str, port: int) -> subprocess.Popen:
    """One inert server process with the exact Studio command line."""
    return subprocess.Popen([node, cli, 'preview', project, '--port', str(port), '--foreground', '--json',
                             '--no-open'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def run_opener(node: str, root: str, runtime: str, project: str) -> None:
    """The real open_preview with only the host reading and the SDK launch replaced."""
    import native_work_lease as work
    from native_render_resources import GIB, ProcessRequest, parse_snapshot
    from studio import managed_preview as managed
    from studio import managed_preview_launch as launching
    from test_native_render_resources import raw_sample

    work.state_root = lambda: Path(root)
    launching.read_snapshot = lambda _project: parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
    managed.install_runtime = lambda: Path(runtime)

    def launch(cli: str, studio: str, port: int, **_options: object) -> None:
        """Start the look-alike, report it, and wait as the real launcher waits for readiness."""
        print('SPAWNED', start_server(node, cli, studio, port).pid, flush=True)
        time.sleep(60)  # waiting for SDK readiness when the opener is killed

    launching.launch_preview = launch
    managed.open_preview(project, 3990, None, 5)


if __name__ == '__main__':
    if sys.argv[1] == 'spawn':
        print(start_server(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])).pid, flush=True)
    else:
        run_opener(*sys.argv[2:6])
