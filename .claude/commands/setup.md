---
description: One-time setup — checks your machine and installs only what's missing (asks before every system install).
argument-hint: (no arguments)
---

You are running **first-time setup** for PROJECT SNIPER for someone who may not be
technical. Your job: find out what their machine is missing and install **only the
gaps**, asking permission before anything that touches the system (Homebrew packages,
the ~465 MB Whisper model download). Cheap project steps (`.venv`, `npm install`,
copying `.env.local`) can be grouped under a single confirmation. Be calm, plain-spoken,
and never dump a wall of commands at the user — you run them, you report back.

Follow these steps in order. Do not skip the doctor.

## Step 1 — Run the doctor (detect only, changes nothing)

Run this command **exactly** with the Bash tool, then read the `SUMMARY` block it prints:

```bash
bash -c '
set +e
ROOT="$(pwd)"
ok(){   printf "  \xe2\x9c\x85  %-14s %s\n" "$1" "$2"; }
warn(){ printf "  \xe2\x9a\xa0\xef\xb8\x8f  %-14s %s\n" "$1" "$2"; }
bad(){  printf "  \xe2\x9d\x8c  %-14s %s\n" "$1" "$2"; }
SYS=""; PROJ=""
echo "PROJECT SNIPER — machine check"
echo

# OS
case "$(uname -s)" in
  Darwin) ok "macOS" "$(sw_vers -productVersion 2>/dev/null)";;
  *) warn "OS" "not macOS — file pickers use a native macOS dialog; the app UI will not pick files here";;
esac

# Homebrew (needed to install any missing system tools)
if command -v brew >/dev/null 2>&1; then ok "Homebrew" "$(brew --version 2>/dev/null | head -1)"
else bad "Homebrew" "missing — needed to install ffmpeg/whisper; install from https://brew.sh"; SYS="$SYS brew"; fi

# Node >= 20.9
NV="$(node -v 2>/dev/null)"
if [ -n "$NV" ]; then
  MJ=$(echo "$NV" | sed "s/^v//" | cut -d. -f1); MN=$(echo "$NV" | sed "s/^v//" | cut -d. -f2)
  if [ "$MJ" -gt 20 ] 2>/dev/null || { [ "$MJ" -eq 20 ] 2>/dev/null && [ "$MN" -ge 9 ] 2>/dev/null; }; then ok "Node.js" "$NV"
  else bad "Node.js" "$NV found, need 20.9+"; SYS="$SYS node"; fi
else bad "Node.js" "missing, need 20.9+"; SYS="$SYS node"; fi

# Python >= 3.9
PV="$(python3 --version 2>&1 | awk "{print \$2}")"
if [ -n "$PV" ]; then
  PMJ=$(echo "$PV" | cut -d. -f1); PMN=$(echo "$PV" | cut -d. -f2)
  if [ "$PMJ" -eq 3 ] 2>/dev/null && [ "$PMN" -ge 9 ] 2>/dev/null; then ok "Python" "$PV"
  else bad "Python" "$PV found, need 3.9+"; SYS="$SYS python"; fi
else bad "Python" "missing, need 3.9+"; SYS="$SYS python"; fi

# ffmpeg + ffprobe
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then ok "ffmpeg" "on PATH"
else bad "ffmpeg" "missing (needs ffmpeg + ffprobe)"; SYS="$SYS ffmpeg"; fi

# whisper-cli (local, no-audio-egress transcription)
if command -v whisper-cli >/dev/null 2>&1 || [ -x /opt/homebrew/bin/whisper-cli ] || [ -x /usr/local/bin/whisper-cli ]; then ok "whisper-cli" "on PATH"
else bad "whisper-cli" "missing (brew whisper-cpp)"; SYS="$SYS whisper"; fi

# whisper model file (exact paths the app searches — no auto-download at runtime)
MODEL=""
for c in "$WHISPER_CPP_MODEL" "$HOME/.cache/hyperframes/whisper/models/ggml-small.en.bin" "$ROOT/models/ggml-small.en.bin" "/opt/homebrew/share/whisper-cpp/models/ggml-small.en.bin" "/usr/local/share/whisper-cpp/models/ggml-small.en.bin"; do
  [ -n "$c" ] && [ -f "$c" ] && { MODEL="$c"; break; }
done
if [ -n "$MODEL" ]; then ok "whisper model" "$MODEL"
else bad "whisper model" "missing ggml-small.en.bin (~465 MB)"; SYS="$SYS model"; fi

# Claude CLI (the default editor brain) + Codex (optional alternative)
if command -v claude >/dev/null 2>&1; then ok "claude CLI" "found (the default brain)"
else bad "claude CLI" "missing — the editor brain. Install: https://claude.com/claude-code"; SYS="$SYS claude"; fi
if command -v codex >/dev/null 2>&1; then ok "codex CLI" "found (optional alt brain)"; else warn "codex CLI" "not found (optional — only if you want the Codex brain)"; fi

# tesseract (optional — only Frame.io Review --mode ocr)
if command -v tesseract >/dev/null 2>&1; then ok "tesseract" "found (optional)"; else warn "tesseract" "not found (optional — only Frame.io OCR mode)"; fi

# Project deps
[ -x .venv/bin/python3 ] && ok ".venv" "python deps installed" || { bad ".venv" "not created"; PROJ="$PROJ venv"; }
[ -d node_modules ]      && ok "node_modules" "installed"        || { bad "node_modules" "not installed"; PROJ="$PROJ npm"; }
[ -f .env.local ]        && ok ".env.local" "present"            || { warn ".env.local" "not created (no keys needed for the local Claude+Whisper path)"; PROJ="$PROJ env"; }

# Palmier Pro (optional live NLE mirror — only if the app is open)
if command -v curl >/dev/null 2>&1; then
  PC=$(curl -s -o /dev/null -m 1 -w "%{http_code}" http://127.0.0.1:19789/mcp 2>/dev/null)
  if [ -n "$PC" ] && [ "$PC" != "000" ]; then ok "Palmier Pro" "running (MCP up)"; else warn "Palmier Pro" "not running (optional — open the app if you want the NLE mirror)"; fi
fi

echo
echo "SUMMARY"
echo "  need_system:$SYS"
echo "  need_project:$PROJ"
[ -z "$SYS" ] && [ -z "$PROJ" ] && echo "  ALL_GREEN: nothing to install"
exit 0
'
```

## Step 2 — If everything is green

If `SUMMARY` shows `ALL_GREEN`, do **not** install anything. Skip to **Step 5**.

## Step 3 — Install missing system tools (ASK before each)

Only for tokens listed in `need_system`. Tell the user in one sentence what each is and why,
then ask a simple yes/no before running it. Never batch system installs silently.

- `brew` — Homebrew is missing and is required to install the tools below. **Do not try to
  install it for them** (it's an interactive script). Give them this one line to paste into
  their own terminal, then stop and wait: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- `node` — ask, then `brew install node` (or point them to https://nodejs.org for the LTS installer).
- `python` — ask, then `brew install python@3.12`.
- `ffmpeg` — ask, then `brew install ffmpeg` (installs ffprobe too).
- `whisper` — ask, then `brew install whisper-cpp`.
- `model` — this is the ~465 MB local speech model. Ask clearly ("Download the ~465 MB
  Whisper model? one-time"), then:
  `mkdir -p "$HOME/.cache/hyperframes/whisper/models" && curl -L --fail --progress-bar -o "$HOME/.cache/hyperframes/whisper/models/ggml-small.en.bin" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin`
  Never download it into the repo's `models/` folder (that folder is committed).
- `claude` — the editor brain. If it's missing, they can't run an edit yet. Point them to
  https://claude.com/claude-code to install, and note that once installed they should run
  `claude` once to log in (it shares the same subscription as Claude Code desktop).

## Step 4 — Set up project dependencies (one confirmation is fine)

Only for tokens in `need_project`. Ask once ("Set up the project dependencies now?"), then run
whichever apply:

- `venv` → `python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt`
- `npm` → `npm install`
- `env` → `cp .env.local.example .env.local`
  (The default path — Claude brain + local Whisper — needs **no** API keys. Only mention
  `DEEPGRAM_API_KEY` / `ANTHROPIC_API_KEY` if they later ask about the live-provider lanes.)

Then re-run the **Step 1** doctor to confirm everything is green.

## Step 5 — You're ready

Confirm the machine is set up in one or two sentences, then tell them how to actually use it —
the whole point is that they **don't run a dev server**; they just ask you:

> You're all set. You don't need to start any server. Just tell me what to make — for example:
> - "Cut a Punch-produced short from ~/Desktop/raw-footage.mp4"
> - "Clean-cut this long recording: <path to your .mp4>"
>
> I'll load the `producer` skill and drive the whole pipeline (ingest → gated edit plan →
> render). Your finished `final.mp4` lands in `~/ProjectSniper/<slug>/`.
>
> Optional extras: open **Palmier Pro** if you want the approved one-clip flat mirror for
> manual review. The editable native-candidate branch is an isolated P5-blocked experiment.
> There's also an optional web GUI at `npm run dev` (http://localhost:3000), but neither is
> required.

Keep the closing short. Do not paste the full README back at them.
