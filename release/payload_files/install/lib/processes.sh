#!/bin/bash
# Process identification for the Project Sniper launchers.
# Sourced by lib/common.sh, never executed directly.

# Work that belongs to this install: edits, renders and the tools they run. A process
# counts when its working folder or its command line is inside this folder. Excluded:
# this script with its own parent shells, idle shells, and your own Codex or Claude
# Code (the app you opened this folder in is your editor, not Sniper's work; anything it
# runs is a process of its own and is still counted).
# This complements the maintenance lock (lib/common.sh): it also sees work that never
# took the lock, such as a command someone runs by hand inside the folder.
active_work_pids() {
  local self_group p group ancestors=" " a="$$"
  self_group="$(ps -o pgid= -p $$ | tr -d ' ')"
  while [ -n "$a" ] && [ "$a" != 0 ] && [ "$a" != 1 ]; do
    ancestors="$ancestors$a "; a="$(ps -o ppid= -p "$a" 2>/dev/null | tr -d ' ')"
  done
  { processes_in_folder; pgrep -f -- "$(literal_pattern "$PKG_ROOT/")" 2>/dev/null
  } | sort -un | while read -r p; do
    case "$ancestors" in *" $p "*) continue ;; esac
    case "$(basename -- "$(ps -o comm= -p "$p" 2>/dev/null)")" in
      zsh|-zsh|bash|-bash|sh|-sh|fish|tcsh|csh|login) continue ;;
      codex|Codex|"Codex Helper"*|claude|Claude|"Claude Helper"*) continue ;;
    esac
    group="$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" || continue
    [ -n "$group" ] || continue
    [ "$group" = "$self_group" ] && continue
    printf '%s\n' "$p"
  done
}
# lsof prints non-ASCII bytes of a path as \xNN; decode before comparing, and
# compare literally (a folder like "project-sniper (1)" must match itself).
processes_in_folder() {
  local line p="" n
  lsof -a -d cwd -Fpn 2>/dev/null | while IFS= read -r line; do
    case "$line" in
      p*) p="${line#p}" ;;
      n*) n="$(printf '%b' "${line#n}")"; case "$n/" in "$PKG_ROOT/"*) printf '%s\n' "$p" ;; esac ;;
    esac
  done
}
literal_pattern() { printf '%s' "$1" | sed 's/[][\\.*^$+?(){}|]/\\&/g'; }
describe_pids() {  # pid... -> "name (pid N), ..."
  local p out=""
  for p in "$@"; do out="$out$(basename "$(ps -o comm= -p "$p" 2>/dev/null)") (pid $p), "; done
  printf '%s' "${out%, }"
}

# Refuse when an edit or render from this install is running (see active_work_pids).
refuse_if_active_work() {  # what-would-happen
  local active
  active="$(active_work_pids | tr '\n' ' ')"
  [ -z "${active// }" ] && return 0
  # shellcheck disable=SC2086
  fail "An edit or render from this install is still running: $(describe_pids $active).
  $1 Let it finish (or cancel it from its project), then run this again."
}
