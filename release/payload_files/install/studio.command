#!/bin/bash
# Project Sniper — review and adjust a finished edit in HyperFrames Studio.
#
#   install/studio.command open    <project>/producer   build the review project and open Studio
#   install/studio.command status  <project>/producer   where the review stands, and what to do next
#   install/studio.command sync    <project>/producer --apply   fold your Studio edits into the plan
#   install/studio.command rebuild <project>/producer   rebuild the video from the updated plan
#   install/studio.command stop    <project>/producer   shut the preview server down
#
# Runs app/scripts/producer/studio/studio_review.py with this install's settings
# (its Node, browser, ffmpeg and PATH, and no API keys from your shell), which
# running the environment's Python directly would skip.
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" || exit 1
load_env
require_installed_node
case "${1:-}" in open|status|sync|rebuild|stop|context) ;;
  *) fail "Usage: install/studio.command open|status|sync|rebuild|stop <project>/producer [options]" ;; esac
hold_maintenance shared "Studio ($1)" "Sniper is being installed, repaired, cleaned or removed right
  now; open Studio again when that has finished." "$@"
cd "$APP_DIR" || exit 1
export SNIPER_STUDIO_COMMAND="$PKG_ROOT/install/studio.command"
exec "$APP_DIR/.venv/bin/python3" "$APP_DIR/scripts/producer/studio/studio_review.py" "$@"
