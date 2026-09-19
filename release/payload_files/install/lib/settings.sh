#!/bin/bash
# Settings file handling for the Project Sniper installer and launchers.
# Sourced by lib/common.sh, never executed directly.
#
# runtime/sniper.env is DATA, written by the installer: one KEY=VALUE per line,
# the value taken literally up to the end of the line. It is never run as shell,
# so a folder named "Budget$97", one with a backtick or quotes, or an accented
# name reads back exactly as written. A value that cannot be one line (a newline
# or another control character) is refused when the file is written.
#
# runtime/sniper.local.env is YOURS and is the one file read as shell syntax, so
# quote a value that contains $, `, \, quotes or spaces: KEY='value'.

SETTINGS_HEADER="# sniper-settings-v1"

# A value can be stored when it has no control character (newline, tab, escape...).
settings_value_ok() {
  local stripped
  stripped="$(printf '%s' "$1" | LC_ALL=C tr -d '\000-\037\177')"
  [ "$stripped" = "$1" ]
}

settings_key_ok() {
  case "$1" in ''|[0-9]*|*[!A-Za-z0-9_]*) return 1 ;; esac
  return 0
}

# settings_write FILE KEY=VALUE... — atomic, literal, mode 600.
settings_write() {
  local file="$1" pair key value
  shift
  for pair in "$@"; do
    key="${pair%%=*}"; value="${pair#*=}"
    settings_key_ok "$key" || fail "Internal error: '$key' is not a settings name."
    settings_value_ok "$value" || fail "The setting $key contains a line break or another control
  character, which Sniper cannot store: $(printf '%s' "$value" | LC_ALL=C tr '\000-\037\177' '?')
  Choose a folder or file whose name has none."
  done
  {
    printf '%s — written by install/install.command; one KEY=VALUE per line, read\n' "$SETTINGS_HEADER"
    printf '# literally (never run as shell). Your own settings go in runtime/sniper.local.env.\n'
    for pair in "$@"; do printf '%s\n' "$pair"; done
  } > "$file.tmp" && chmod 600 "$file.tmp" && mv "$file.tmp" "$file" \
    || fail "Could not write $file"
}

# Print one KEY's literal value from a settings file without running anything.
# A file without the v1 header came from rc3, which wrapped values in double
# quotes without escaping; strip exactly that one pair.
settings_value() {  # KEY [FILE]
  local file="${2:-$ENV_FILE}" line found="" legacy=1
  [ -f "$file" ] || return 1
  IFS= read -r line < "$file"
  case "$line" in "$SETTINGS_HEADER"*) legacy=0 ;; esac
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in "$1="*) found="${line#*=}" ;; esac
  done < "$file"
  if [ "$legacy" = 1 ]; then
    case "$found" in \"*\") found="${found#\"}"; found="${found%\"}" ;; esac
  fi
  printf '%s' "$found"
}

# Export every KEY=VALUE of a settings file, literally.
settings_load() {  # FILE
  local line key value legacy=1
  IFS= read -r line < "$1"
  case "$line" in "$SETTINGS_HEADER"*) legacy=0 ;; esac
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    settings_key_ok "$key" || fail "runtime/sniper.env has a line Sniper did not write: ${line%%=*}
  Run install/install.command again to rewrite it."
    if [ "$legacy" = 1 ]; then
      case "$value" in \"*\") value="${value#\"}"; value="${value%\"}" ;; esac
    fi
    export "$key=$value"
  done < "$1"
}
