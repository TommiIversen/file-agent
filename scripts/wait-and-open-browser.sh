#!/usr/bin/env bash
# Waits for the file-agent server to become available, then opens the browser.
# Used by the com.fileagent.openbrowser LaunchAgent.

URL="http://localhost:8000"
HEALTH_URL="${URL}/api/initial-state"
MAX_WAIT=90   # seconds (lifespan may take a while)
INTERVAL=2    # seconds between retries

elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
    # Check the initial-state endpoint so we know the full lifespan is done,
    # not just that uvicorn is accepting TCP connections.
    if curl -sf --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then
        open "$URL"
        exit 0
    fi
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
done

echo "file-agent: server did not respond within ${MAX_WAIT}s — not opening browser." >&2
exit 1
