#!/usr/bin/env bash
# Waits for the file-agent server to become available, then opens the browser.
# Used by the com.fileagent.openbrowser LaunchAgent.

URL="http://localhost:8000"
MAX_WAIT=60   # seconds
INTERVAL=2    # seconds between retries

elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
    if curl -s -o /dev/null -w '' --max-time 2 "$URL" >/dev/null 2>&1; then
        open "$URL"
        exit 0
    fi
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
done

echo "file-agent: server did not respond within ${MAX_WAIT}s — not opening browser." >&2
exit 1
