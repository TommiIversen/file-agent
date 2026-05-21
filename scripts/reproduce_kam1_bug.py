"""
Reproduces P3_KAM_1 response corruption on MF91328.
Logs every HTTP response to reproduce_kam1_bug.log.

Requires a fresh Justin Engine restart before running.

pip install httpx
"""
import httpx
import json
from datetime import datetime
from pathlib import Path

BASE = "http://mf91328:8080"
LOG_FILE = Path(__file__).parent / "reproduce_kam1_bug.log"


def log(f, step: str, method: str, url: str, payload: dict, response: httpx.Response):
    body_json = response.text.replace("\n", " ").replace("  ", "")
    # Human-readable summary line
    status = response.status_code
    try:
        parsed = response.json()
        if "errors" in parsed:
            summary = f"OK — errors response (channel={parsed.get('channel')})"
        elif "rec" in parsed:
            summary = f"OK — recording status (channel={parsed.get('channel')}, rec={parsed.get('rec')})"
        elif "error" in parsed:
            summary = f"WRONG — {parsed.get('status')} {parsed.get('error')}"
        else:
            summary = f"UNEXPECTED — keys: {list(parsed.keys())[:5]}"
    except Exception:
        summary = f"HTTP {status} (non-JSON)"

    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    f.write(f"[{ts}] [{step}] {method} {url}\n")
    f.write(f"  Request body: {json.dumps(payload)}\n")
    f.write(f"  Response: HTTP {status} — {summary}\n")
    f.write(f"  Response body: {body_json}\n\n")


def post(client, endpoint, payload, step, log_file):
    url = f"{BASE}{endpoint}"
    r = client.post(url, json=payload)
    log(log_file, step, "POST", url, payload, r)
    return r


def main():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"{'='*70}\n")
        f.write(f"  P3_KAM_1 Response Corruption — Reproduction Log\n")
        f.write(f"  Target: {BASE}\n")
        f.write(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*70}\n\n")

        with httpx.Client(base_url=BASE, timeout=10.0) as client:

            # Step 1: Verify P3_KAM_1 is healthy with BOTH endpoints
            f.write(f"--- STEP 1: Verify P3_KAM_1 responds correctly to both endpoints ---\n\n")
            r = post(client, "/ingest/errors", {"channel": "P3_KAM_1", "clear": 0},
                     "1a-verify-errors", f)
            body = r.json()
            if "errors" not in body:
                print(f"P3_KAM_1 already broken — restart Justin first. Got: {body}")
                f.write("ABORT: P3_KAM_1 was not healthy at start.\n")
                return
            r = post(client, "/ingest/requestRecordingStatus", {"channel": "P3_KAM_1"},
                     "1b-verify-status", f)
            body = r.json()
            if "rec" not in body:
                print(f"P3_KAM_1 status broken — restart Justin first. Got: {body}")
                f.write("ABORT: P3_KAM_1 status was not healthy at start.\n")
                return
            print("1. P3_KAM_1 is healthy (both endpoints verified)")

            # Step 2: Query 10 unique channels
            f.write(f"\n--- STEP 2: Query requestRecordingStatus for 10 unique channels ---\n")
            f.write(f"    (P3_KAM_1 is NOT included in this sweep)\n\n")
            for i in range(2, 12):
                ch = f"P3_KAM_{i}"
                post(client, "/ingest/requestRecordingStatus", {"channel": ch},
                     f"2-sweep-{ch}", f)
            print("2. Queried 10 unique channels (P3_KAM_2..11)")

            # Step 3: Check P3_KAM_1 with BOTH endpoints
            f.write(f"\n--- STEP 3: Query P3_KAM_1 with both endpoints ---\n")
            f.write(f"    (these worked fine in step 1)\n\n")

            r = post(client, "/ingest/errors", {"channel": "P3_KAM_1", "clear": 0},
                     "3a-errors-after-sweep", f)
            body_errors = r.json()
            errors_ok = "errors" in body_errors

            r = post(client, "/ingest/requestRecordingStatus", {"channel": "P3_KAM_1"},
                     "3b-status-after-sweep", f)
            body_status = r.json()
            status_ok = "rec" in body_status

            if errors_ok and status_ok:
                f.write("\n>>> RESULT: No bug — both endpoints OK. <<<\n\n")
                print("3. P3_KAM_1 OK — bug did not trigger (unexpected)")
            else:
                f.write("\n>>> RESULT: BUG CONFIRMED <<<\n")
                if not errors_ok:
                    f.write(f">>> /ingest/errors returned wrong body: {list(body_errors.keys())} <<<\n")
                if not status_ok:
                    f.write(f">>> /ingest/requestRecordingStatus returned wrong body: {list(body_status.keys())} <<<\n")
                f.write("\n")
                print(f"3. BUG confirmed:")
                if not errors_ok:
                    print(f"   errors: got {body_errors}")
                if not status_ok:
                    print(f"   status: got {body_status}")

            # Step 4: Show cross-contamination pattern
            f.write(f"\n--- STEP 4: Demonstrate cross-contamination (alternating endpoints) ---\n\n")
            print("\n4. Alternating endpoints on P3_KAM_1:")
            for i in range(5):
                r1 = post(client, "/ingest/requestRecordingStatus", {"channel": "P3_KAM_1"},
                          f"4-alternate-status-{i+1}", f)
                r2 = post(client, "/ingest/errors", {"channel": "P3_KAM_1", "clear": 0},
                          f"4-alternate-errors-{i+1}", f)
                b1 = r1.json()
                b2 = r2.json()
                ok1 = "rec" in b1
                ok2 = "errors" in b2
                if ok1 and ok2:
                    print(f"   Round {i+1}: both OK")
                else:
                    parts = []
                    if not ok1:
                        parts.append(f"status got {list(b1.keys())[:3]}")
                    if not ok2:
                        parts.append(f"errors got {list(b2.keys())[:3]}")
                    print(f"   Round {i+1}: WRONG — {', '.join(parts)}")

            # Step 5: Show other channels are unaffected
            f.write(f"\n--- STEP 5: Verify other channels are NOT affected ---\n\n")
            print("\n5. Other channels (should all be OK):")
            for ch in ["P3_KAM_5", "P3_KAM_8", "P3_KAM_10", "P3_PGM_12"]:
                r = post(client, "/ingest/errors", {"channel": ch, "clear": 0},
                         f"5-other-{ch}", f)
                body = r.json()
                ok = "errors" in body
                print(f"   {ch}: {'OK' if ok else 'BUG'}")

    print(f"\nLog written to: {LOG_FILE}")


if __name__ == "__main__":
    main()
