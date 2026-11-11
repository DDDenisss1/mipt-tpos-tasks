#!/bin/sh
set -eu

STATE_FILE=/opt/service_state.json
PID_FILE=/var/run/nginx.pid

[ -f "$STATE_FILE" ] || exit 1
[ -f "$PID_FILE" ] || exit 1

NGINX_PID=$(cat "$PID_FILE")
SECONDS=$(ps -o etimes= -p "$NGINX_PID" | tr -d ' ')
MINUTES=$((SECONDS / 60))

TMP_FILE=$(mktemp /opt/.service_state.XXXXXX)
trap 'rm -f "$TMP_FILE"' EXIT

jq --argjson uptime "$MINUTES" \
  '.uptime = $uptime' \
  "$STATE_FILE" > "$TMP_FILE"

chmod 0644 "$TMP_FILE"
mv -f "$TMP_FILE" "$STATE_FILE"
