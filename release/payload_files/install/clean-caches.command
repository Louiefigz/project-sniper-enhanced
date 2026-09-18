#!/bin/bash
# Project Sniper — preview and remove only regenerable render caches.
# Refuses while an edit or render from this install is running, while a cache file
# is open, or while an export attempt is unfinished (its resume may need the cache).
# Never touches footage, edit plans, approved finals, exports, export attempts and
# their history, receipts or unsynced Studio work.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
# Holding the maintenance lock exclusively means no app, editor window, doctor or
# render that resolved the runtime is running, and none can start until this ends.
hold_maintenance exclusive "cache cleaning" "Caches cannot be cleaned while Sniper is in use. Stop the
  app (install/stop.command), close any Sniper editor window and let running edits finish." "$@"
ROOT="$APP_DIR/templates/motion/.sniper-native-runtime"
CANDIDATES=()
for d in "$ROOT"/*/frame-cache "$ROOT"/*/long-frame-cache; do [ -d "$d" ] && CANDIDATES+=("$d"); done
if [ ${#CANDIDATES[@]} -eq 0 ]; then say "No render caches to remove."; exit 0; fi

# Also refuse for work that never took the lock (a command run by hand in this folder).
ACTIVE="$(active_work_pids | tr '\n' ' ')"
OPEN="$(lsof +D "$ROOT" 2>/dev/null | awk 'NR>1 {print $2}' | sort -u | tr '\n' ' ')"
if [ -n "${ACTIVE// }${OPEN// }" ]; then
  fail "Work from this install is still running: $(describe_pids $ACTIVE $OPEN).
  Nothing was removed. Run this again when it has finished."
fi
# An export attempt without a final delivery record was interrupted or is still
# being written; resuming it may rely on these caches.
UNFINISHED="$("$APP_DIR/.venv/bin/python3" - "$ROOT/native-export-history" <<'PY'
import json, pathlib, sys
history = pathlib.Path(sys.argv[1])
for pointer in sorted(history.glob("*/*.json")) if history.is_dir() else []:
    try:
        attempt = pathlib.Path(json.loads(pointer.read_text(encoding="utf-8"))["attempt"])
    except (OSError, ValueError, KeyError, TypeError):
        continue
    if attempt.is_dir() and not (attempt / "delivery.json").is_file():
        print(attempt)
PY
)"
if [ -n "$UNFINISHED" ]; then
  fail "These export attempts never finished, and resuming them may need the caches:
$(printf '%s\n' "$UNFINISHED" | sed 's/^/    /')
  Nothing was removed. Resume or re-run those exports first. If you have abandoned
  one, delete its folder, then run this again."
fi

say "Candidates (regenerable render caches only):"
for d in "${CANDIDATES[@]}"; do say "  $(du -sh "$d" 2>/dev/null | cut -f1)  $d"; done
say ""
say "Never removed by this script: your footage, edit plans, final.mp4 files, exports,"
say "export attempts and their history, approval receipts and unsynced Studio edits."
if [ "${1:-}" != "--yes" ]; then printf 'Type CLEAN to remove the caches listed above: '; read -r answer
  [ "$answer" = "CLEAN" ] || { say "Nothing was removed."; exit 0; }; fi
for d in "${CANDIDATES[@]}"; do rm -rf "$d"; done
say "Caches removed. The next render rebuilds what it needs."
