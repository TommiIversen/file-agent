# File Transfer Agent - FastAPI App

This application is a robust file transfer agent for automated and reliable file movement.

## Key Features

- **Automated File Transfer:** Moves files from a local source to a network destination.
- **Web UI for Monitoring:** Real-time monitoring of transfer status.
- **Resilient & Reliable:** Handles network failures and errors gracefully.
- **Stable & Growing File Detection:** Intelligently scans for files that are static or still being written to.
- **Producer-Consumer Model:** Decouples file discovery from the copy process.
- **Safe Copy Mechanism:** Uses temporary files and size verification before finalizing the transfer.
- **Configurable Retries:** Manages both temporary and permanent transfer errors.
- **Real-time Updates:** Uses WebSockets to push status updates to the UI.

### Advanced Features

- **Resumable Transfers:** Automatically resumes interrupted copies from the last verified byte, making it resilient to network failures.
- **"Growing File" Mode:** Can start copying large files (like video recordings) *while* they are still being written, significantly reducing end-to-end transfer time.
- **Destination Space Check:** Monitors available space on the destination to prevent failed transfers.

## Installation

```cmd
pip install -r requirements.txt
```

uvicorn app.main:app --reload

eller

python -m uvicorn app.main:app --reload