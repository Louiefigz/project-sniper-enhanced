#!/bin/bash
# Process identification for the Project Sniper launchers.
# Sourced by lib/common.sh, never executed directly.

port_listener_pids() {
  lsof -nP -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | sort -u
}

# Work that belongs to this install but is not the app server: background edits,
# renders and the CLI calls they make. A process counts when its working folder or
# its command line is inside this folder. Excluded: the app server — the supervisor's
# process group and the group of the Next server it starts (stop.command handles
# those) — and this script with its own parent shells. Edits and renders the app
# launches run detached in groups of their own, so they still count.
# This complements the maintenance lock (lib/common.sh): it also sees work that
# never took the lock, such as a command someone runs by hand inside the folder.
active_work_pids() {
  local sup app_groups=" " self_group p group ancestors=" " a="$$" child
  sup="$(cat "$STATE_DIR/app.pid" 2>/dev/null)"
  if pid_is_our_supervisor "$sup"; then
    app_groups=" $(ps -o pgid= -p "$sup" | tr -d ' ') "
    for child in $(pgrep -P "$sup"); do app_groups="$app_groups$(ps -o pgid= -p "$child" | tr -d ' ') "; done
  fi
  self_group="$(ps -o pgid= -p $$ | tr -d ' ')"
  while [ -n "$a" ] && [ "$a" != 0 ] && [ "$a" != 1 ]; do
    ancestors="$ancestors$a "; a="$(ps -o ppid= -p "$a" 2>/dev/null | tr -d ' ')"
  done
  { processes_in_folder; pgrep -f -- "$(literal_pattern "$PKG_ROOT/")" 2>/dev/null
  } | sort -un | while read -r p; do
    case "$ancestors" in *" $p "*) continue ;; esac
    # An idle shell whose folder is inside this one (a Terminal tab) is not work;
    # anything it runs is a process of its own and is still counted.
    case "$(basename -- "$(ps -o comm= -p "$p" 2>/dev/null)")" in
      zsh|-zsh|bash|-bash|sh|-sh|fish|tcsh|csh|login) continue ;; esac
    group="$(ps -o pgid= -p "$p" 2>/dev/null | tr -d ' ')" || continue
    [ -n "$group" ] || continue
    [ "$group" = "$self_group" ] && continue
    case "$app_groups" in *" $group "*) continue ;; esac
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

# A stored PID is only ours if that process is still this package's supervisor.
# PIDs are reused; signalling one blindly could stop an unrelated program.
pid_is_our_supervisor() {
  local pid="$1" cmd
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  cmd="$(ps -o command= -p "$pid" 2>/dev/null)"
  case "$cmd" in *"scripts/infra/next_supervisor.mjs"*) ;; *) return 1 ;; esac
  # Same folder = same inode as this install's app/. Compared by number, because
  # lsof escapes non-ASCII characters in the path it prints.
  [ "$(lsof -a -p "$pid" -d cwd -Fi 2>/dev/null | sed -n 's/^i//p')" = "$(stat -f %i "$APP_DIR")" ]
}
