"""Private, interactive Deepgram connection setup; never transcribes or prints keys.

The fixed HTTPS auth endpoint checks credentials without uploading media.
Connection settings are literal data, outside app/ and support-bundle inputs.
Connecting is not paid-ASR consent: scripts/asr_policy.py remains authoritative.
"""
from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

AUTH_URL = "https://api.deepgram.com/v1/auth/token"
HEADER = "# sniper-settings-v1"


class ConnectionProblem(Exception):
    """A fixed, safe message that may be shown without leaking credentials."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward an Authorization header to a redirected destination."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        """Refuse redirects rather than forwarding the secret."""
        raise ConnectionProblem("Deepgram redirected the check. No key was saved; try again later.")


def verify_key(key: str) -> None:
    """Validate via Deepgram's auth endpoint, retrying transient errors at most twice."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", key):
        raise ConnectionProblem("Paste only the API key, without quotes, spaces or 'Token'.")
    request = urllib.request.Request(AUTH_URL, headers={"Authorization": f"Token {key}"})
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(3):
        try:
            with opener.open(request, timeout=10) as response:
                result = json.loads(response.read(65537))
                if response.status != 200 or not isinstance(result, dict) or not result:
                    raise ConnectionProblem("Deepgram returned an unexpected response. No key was saved.")
            return
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            if code in (401, 403):
                raise ConnectionProblem("Deepgram did not accept this key. Create or copy a key and retry.") from None
            if code != 429 and code < 500:
                raise ConnectionProblem("Deepgram could not verify this key. No key was saved.") from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            pass
        except (ValueError, UnicodeError):
            raise ConnectionProblem("Deepgram returned an unreadable response. No key was saved.") from None
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise ConnectionProblem("Deepgram is unavailable or your connection is offline. Retry, or skip for now.")


def save_connection(path: Path, key: str) -> None:
    """Atomically store one literal setting, readable only by the current account."""
    if key and not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", key):
        raise ConnectionProblem("The key could not be saved. Paste only the API key.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".deepgram-", dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(f"{HEADER}\nDEEPGRAM_API_KEY={key}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def connected(path: Path) -> bool:
    """Inspect presence only, never print or return a stored key."""
    if not path.exists():
        return False
    return any(line.startswith("DEEPGRAM_API_KEY=") and line.removeprefix("DEEPGRAM_API_KEY=")
               for line in path.read_text(encoding="utf-8").splitlines())


def connect(path: Path) -> None:
    """Prompt privately; failed validation and cancellation keep the old setting."""
    print("Create a key at https://console.deepgram.com/ (API Keys).")
    print("Paste it below. It stays hidden while you type; press Enter to cancel.")
    key = getpass.getpass("Deepgram API key: ").strip()
    if not key:
        print("Cancelled. Your previous settings are unchanged.")
        return
    verify_key(key)
    save_connection(path, key)
    print("Deepgram key accepted and saved privately on this computer.")
    print("This checks the key, not your balance or permission for every model.")


def configure(path: Path) -> None:
    """Offer connection, skip and removal without ever requiring a text editor."""
    print("\nConnect Deepgram (optional)")
    print("Local transcription is already included and needs no API key.")
    print("Deepgram sends audio to Deepgram and bills your Deepgram account when used.")
    print("Connecting checks only the key; no audio is uploaded here.")
    print("Sniper still asks before a paid Deepgram transcription for an edit.")
    print("A saved key is present." if connected(path) else "No key has been saved by this setup.")
    while True:
        choice = input("1) Connect/replace key   2) Skip/keep current   3) Remove key\nChoose [2]: ").strip() or "2"
        if choice == "2":
            return
        if choice == "3":
            save_connection(path, "")
            print("Deepgram disconnected for this install. Local transcription remains available.")
            return
        if choice != "1":
            print("Please choose 1, 2 or 3.")
            continue
        try:
            connect(path)
            return
        except ConnectionProblem as error:
            print(str(error))


def main() -> int:
    """Run only at a terminal; never fall back to echoing a secret into piped logs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-needed", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[2] / "runtime/deepgram.env"
    if args.if_needed and path.exists():
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Deepgram setup needs an interactive Terminal or PowerShell window.")
        return 1
    try:
        configure(path)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled; saved settings are unchanged.")
        return 130
    except OSError:
        print("Could not save the connection. Check that this install folder is writable.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
