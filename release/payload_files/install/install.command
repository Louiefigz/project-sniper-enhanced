#!/bin/bash
# Project Sniper — Mac installer.
#
# Installs everything into this package's own runtime/ folder. It never edits
# your global Node, Python, Homebrew, Codex or Claude installation, and never
# touches your existing Codex or Claude login.
#
# Safe to run again: each step checks what is already correct and skips it, so
# an interrupted install resumes instead of starting over.

. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1

require_macos
require_safe_install_path
mkdir -p "$RUNTIME_DIR" "$STATE_DIR" "$LOG_DIR"
log_line "install started"

say "Project Sniper installer"
say "Installing into: $PKG_ROOT"
say "Nothing outside this folder and your chosen video workspace is modified."

# ---------------------------------------------------------------- prerequisites
step "1/8  Checking the two things you must already have"
if ! node_ok; then
  fail "Node 22 or newer is required and was not found.
  Install it once from https://nodejs.org (choose the LTS download), then run
  this installer again. Everything else is installed for you."
fi
say "Node $(node --version) — ok"

PYTHON_BIN="$(find_python)" || fail "Python 3.11 or newer is required and was not found.
  Install it once from https://www.python.org/downloads/macos/ then run this
  installer again."
say "Python $("$PYTHON_BIN" -c 'import sys;print(".".join(map(str,sys.version_info[:3])))') — ok"

for tool in ffmpeg ffprobe; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is required and was not found.
  Install both with Homebrew:   brew install ffmpeg
  Then run this installer again. ffmpeg must be built with libass, libx264,
  librubberband and libzimg; the Homebrew build is."
done
say "ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}') — ok"

command -v whisper-cli >/dev/null 2>&1 || fail "whisper-cli is required and was not found.
  Install it once with Homebrew:   brew install whisper-cpp
  Then run this installer again."
say "whisper-cli — ok"

# --------------------------------------------------------------- app dependencies
step "2/8  Installing the application's dependencies (two roots)"
if [ ! -d "$APP_DIR/node_modules" ]; then
  ( cd "$APP_DIR" && npm ci --no-audit --no-fund ) || fail "npm ci failed in app/.
  Check your internet connection and run the installer again; it resumes here."
else
  say "app/node_modules already present — skipped"
fi
if [ ! -d "$APP_DIR/templates/motion/node_modules" ]; then
  ( cd "$APP_DIR/templates/motion" && npm ci --no-audit --no-fund ) \
    || fail "npm ci failed in app/templates/motion/. Re-run the installer."
else
  say "app/templates/motion/node_modules already present — skipped"
fi

step "3/8  Creating the Python environment from the pinned list"
if [ ! -x "$APP_DIR/.venv/bin/python3" ]; then
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv" || fail "Could not create the Python environment."
fi
"$APP_DIR/.venv/bin/pip" install --disable-pip-version-check -q \
  -r "$PKG_ROOT/install/requirements.lock.txt" \
  || fail "Installing the Python packages failed. Re-run the installer."
say "Python packages installed at their pinned versions"

# ------------------------------------------------------------------ the browser
step "4/8  Installing the exact rendering browser this release needs"
CHROME_PIN="$("$APP_DIR/.venv/bin/python3" -c "
import json,sys
print(json.load(open('$PKG_ROOT/RELEASE.json'))['components']['chrome_headless_shell'])")"
BROWSER_BIN="$(ls -d "$BROWSER_CACHE"/chrome-headless-shell/*"$CHROME_PIN"*/*/chrome-headless-shell \
  2>/dev/null | head -1)"
if [ -z "$BROWSER_BIN" ]; then
  say "Downloading chrome-headless-shell $CHROME_PIN (about 150 MB) ..."
  mkdir -p "$BROWSER_CACHE"
  ( cd "$APP_DIR/templates/motion" && \
    PUPPETEER_CACHE_DIR="$BROWSER_CACHE" npx --yes @puppeteer/browsers install \
      "chrome-headless-shell@$CHROME_PIN" --path "$BROWSER_CACHE" ) \
    || fail "Downloading the rendering browser failed.
  Retry when your connection is stable — the installer resumes here. Nothing
  else is downloaded during rendering, so this step has to succeed once."
  BROWSER_BIN="$(ls -d "$BROWSER_CACHE"/chrome-headless-shell/*"$CHROME_PIN"*/*/chrome-headless-shell \
    2>/dev/null | head -1)"
fi
[ -x "$BROWSER_BIN" ] || fail "The rendering browser is still missing after download."
say "Rendering browser: $CHROME_PIN"

# ------------------------------------------------------------- transcription model
step "5/8  Installing the transcription model"
MODEL_PATH="$WHISPER_DIR/ggml-small.en.bin"
# SHA-256 measured on the copy this release was tested with (487,614,201 bytes).
MODEL_SHA="c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d"
mkdir -p "$WHISPER_DIR"
if [ ! -f "$MODEL_PATH" ]; then
  say "Downloading the speech model (about 465 MB) ..."
  curl -fL --retry 3 --retry-delay 2 -o "$MODEL_PATH.part" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin" \
    || { rm -f "$MODEL_PATH.part"; fail "Downloading the speech model failed.
  Re-run the installer to resume, or download the file yourself from
  https://huggingface.co/ggerganov/whisper.cpp and save it as:
    $MODEL_PATH"; }
  mv "$MODEL_PATH.part" "$MODEL_PATH"
fi
GOT_SHA="$(shasum -a 256 "$MODEL_PATH" | awk '{print $1}')"
if [ "$GOT_SHA" != "$MODEL_SHA" ]; then
  warn "The speech model's checksum does not match the recorded value.
  Expected $MODEL_SHA
  Found    $GOT_SHA
  Delete $MODEL_PATH and run the installer again."
fi
say "Speech model in place"

# ------------------------------------------------------- pinned editor-brain CLI
step "6/8  Installing the pinned editor CLI (your own login, kept separate)"
say "This release only accepts these exact versions:"
"$APP_DIR/.venv/bin/python3" -c "
import json
c=json.load(open('$PKG_ROOT/RELEASE.json'))['components']
print('  Codex :', c['codex_cli_admitted'])
print('  Claude:', c['claude_cli_admitted'])"
mkdir -p "$CLI_PREFIX" "$CLAUDE_CONFIG_DIR_LOCAL" "$CODEX_HOME_LOCAL"
chmod 700 "$CLAUDE_CONFIG_DIR_LOCAL" "$CODEX_HOME_LOCAL"
CODEX_PKG="@openai/codex@$("$APP_DIR/.venv/bin/python3" -c "
import json;print(json.load(open('$PKG_ROOT/RELEASE.json'))['components']['codex_cli_admitted'].split()[-1])")"
CLAUDE_PKG="@anthropic-ai/claude-code@$("$APP_DIR/.venv/bin/python3" -c "
import json;print(json.load(open('$PKG_ROOT/RELEASE.json'))['components']['claude_cli_admitted'].split()[0])")"
for pkg in "$CODEX_PKG" "$CLAUDE_PKG"; do
  say "Installing $pkg into this package (your global CLI is untouched) ..."
  npm install --prefix "$CLI_PREFIX" --no-audit --no-fund --silent "$pkg" \
    || warn "Could not install $pkg. You can retry by running the installer again;
  the rest of the install is already complete."
done

# ------------------------------------------------------------------ configuration
step "7/8  Writing this install's configuration"
WORKSPACE_DEFAULT="$HOME/ProjectSniper"
mkdir -p "$WORKSPACE_DEFAULT"
cat > "$ENV_FILE" <<ENVEOF
# Written by install.command. Every launcher and the doctor read this file.
# Delete it and re-run install.command to regenerate.
PKG_ROOT="$PKG_ROOT"
APP_DIR="$APP_DIR"
SNIPER_EXECUTION_MODE=local
SNIPER_WORKSPACE_ROOT="$WORKSPACE_DEFAULT"
SNIPER_NODE_PATH="$(command -v node)"
HYPERFRAMES_BROWSER_PATH="$BROWSER_BIN"
HYPERFRAMES_FFMPEG_PATH="$(command -v ffmpeg)"
HYPERFRAMES_FFPROBE_PATH="$(command -v ffprobe)"
HYPERFRAMES_NO_TELEMETRY=1
HYPERFRAMES_NO_UPDATE_CHECK=1
HYPERFRAMES_NO_AUTO_INSTALL=1
WHISPER_CPP_BIN="$(command -v whisper-cli)"
WHISPER_CPP_MODEL="$MODEL_PATH"
SNIPER_TRANSCRIBE_PROVIDER=local-whisper
SNIPER_CODEX_BIN="$CLI_PREFIX/node_modules/.bin/codex"
CLAUDE_BIN="$CLI_PREFIX/node_modules/.bin/claude"
CODEX_HOME="$CODEX_HOME_LOCAL"
CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR_LOCAL"
DISABLE_AUTOUPDATER=1
SNIPER_PORT=$PORT
ENVEOF
chmod 600 "$ENV_FILE"
[ -f "$APP_DIR/.env.local" ] || cp "$APP_DIR/.env.local.example" "$APP_DIR/.env.local"
say "Video projects will be created in: $WORKSPACE_DEFAULT"

step "8/8  Building the rendering runtime and checking the install"
( cd "$APP_DIR" && set -a; . "$ENV_FILE"; set +a
  PYTHONPATH="$APP_DIR/scripts/producer" "$APP_DIR/.venv/bin/python3" \
    "$APP_DIR/scripts/producer/studio/native_runtime.py" >/dev/null ) \
  || warn "The rendering runtime did not build. Run doctor.command for the reason."
log_line "install finished"

say ""
"$PKG_ROOT/install/doctor.command"
DOCTOR_STATUS=$?
say ""
say "Next: sign in to your editor CLI, then open START-HERE.html in this folder."
say "  Codex : \"$CLI_PREFIX/node_modules/.bin/codex\" login"
say "  Claude: \"$CLI_PREFIX/node_modules/.bin/claude\" auth login"
say "Run those commands from Terminal in this folder; they use this package's own"
say "settings folder, so your existing Codex or Claude login is not changed."
exit $DOCTOR_STATUS
