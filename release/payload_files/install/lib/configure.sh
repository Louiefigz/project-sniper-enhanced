#!/bin/bash
# The installer's configuration step: the settings file every Sniper command loads.
# Sourced by install/install.command (and by the installer tests, which call these
# exact functions), never executed directly. Expects the variables the earlier
# steps set: DEPS_PREFIX, NODE_BIN, TOOL_*, BROWSER_BIN, MODEL_PATH, WORKSPACE_ARG.
#
# There is no provider setting: you talk to Sniper through your own Codex or Claude Code,
# signed in to your own subscription, and Sniper's commands never call either of them.

# The workspace kept from the last setup. One inside this folder moves with the folder: after
# a move or a copy it names the same place under the new location, never the old folder
# (which a move leaves behind and a copy still uses).
kept_workspace() {
  local workspace old_root
  workspace="$(settings_value SNIPER_WORKSPACE_ROOT)" || return 0
  old_root="$(settings_value PKG_ROOT)"
  if [ -z "$old_root" ] || [ "$old_root" = "$PKG_ROOT" ]; then printf '%s' "$workspace"; return 0; fi
  case "$workspace" in
    "$old_root"|"$old_root"/*) printf '%s' "$PKG_ROOT${workspace#"$old_root"}" ;;
    *) printf '%s' "$workspace" ;;
  esac
}

write_settings() {
  local workspace
  # Projects live inside this folder by default, where Codex's own sandbox lets it write.
  workspace="${WORKSPACE_ARG:-$(kept_workspace)}"; workspace="${workspace:-$PKG_ROOT/projects}"
  case "$workspace" in /*) ;; *) fail "The video workspace must be an absolute folder path: $workspace" ;; esac
  mkdir -p "$workspace" || fail "Cannot create the video workspace at $workspace"
  settings_write "$ENV_FILE" \
    "PKG_ROOT=$PKG_ROOT" "APP_DIR=$APP_DIR" \
    "PATH=$RUNTIME_BIN:$APP_DIR/.venv/bin:$DEPS_PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
    "SNIPER_DEPS_PREFIX=$DEPS_PREFIX" \
    "SNIPER_EXECUTION_MODE=local" "SNIPER_WORKSPACE_ROOT=$workspace" \
    "SNIPER_NODE_PATH=$NODE_BIN" "HYPERFRAMES_BROWSER_PATH=$BROWSER_BIN" \
    "HYPERFRAMES_FFMPEG_PATH=$TOOL_FFMPEG" "HYPERFRAMES_FFPROBE_PATH=$TOOL_FFPROBE" \
    "HYPERFRAMES_NO_TELEMETRY=1" "NEXT_TELEMETRY_DISABLED=1" \
    "HYPERFRAMES_NO_UPDATE_CHECK=1" "HYPERFRAMES_NO_AUTO_INSTALL=1" \
    "WHISPER_CPP_BIN=$TOOL_WHISPER_CLI" "WHISPER_CPP_MODEL=$MODEL_PATH" \
    "SNIPER_TRANSCRIBE_PROVIDER=local-whisper" "SNIPER_STUDIO_COMMAND=$PKG_ROOT/install/studio.command"
  SNIPER_WORKSPACE_ROOT="$workspace"
}

# The settings just written must load back exactly (the loader, not the writer,
# is what every launcher uses), and their PATH must find Sniper's own tools first.
verify_settings() {
  local workspace tool found
  workspace="$(settings_load "$ENV_FILE" && printf '%s' "$SNIPER_WORKSPACE_ROOT")" || fail "The settings just written do not load."
  [ "$workspace" = "$SNIPER_WORKSPACE_ROOT" ] || fail "The settings did not read back exactly. Please report this."
  for tool in node ffmpeg ffprobe whisper-cli tesseract yt-dlp; do
    found="$(settings_load "$ENV_FILE" && command -v "$tool")"
    [ "$found" = "$RUNTIME_BIN/$tool" ] || fail "The settings' PATH finds $tool at '$found', not Sniper's own. Please report this."
  done
  for tool in git npm; do
    found="$(settings_load "$ENV_FILE" && command -v "$tool")"
    [ "$found" = "$DEPS_PREFIX/bin/$tool" ] || fail "The settings' PATH finds $tool at '$found', not Sniper's own. Please report this."
  done
  # A plain "python3" (the editor's commands, scripts' #!/usr/bin/env python3) is the app's
  # environment: Sniper's own Python with the pinned packages the engine imports.
  found="$(settings_load "$ENV_FILE" && command -v python3)"
  [ "$found" = "$APP_DIR/.venv/bin/python3" ] || fail "The settings' PATH finds python3 at '$found', not the app's environment. Please report this."
}
