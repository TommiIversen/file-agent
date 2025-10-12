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

## Architectural Overview

This application is built on a clean, decoupled architecture inspired by SOLID principles, primarily using a **Producer-Consumer** pattern. This design ensures robustness and maintainability.

The core components reside in the `app/services` directory:

- **`StateManager` (The Brain):** This is the single source of truth. It's a singleton service that holds the state of every file (`TrackedFile`) in a thread-safe manner. It uses a pub/sub model to notify other services of state changes.

- **`FileScannerService` (The Producer):** This service continuously scans the source directory. It discovers new files, determines if they are "stable" (no longer being written to) or "growing," and updates their status in the `StateManager`.

- **`JobQueueService` (The Buffer):** This service listens for files that become `READY` in the `StateManager` and adds them to an `asyncio.Queue`. This decouples the file discovery process from the copying process.

- **`FileCopyService` & `JobProcessor` (The Consumer):** These services work together to consume jobs from the queue. `JobProcessor` handles the logic for a single job (like checking for destination space), while `FileCopyService` manages the worker pool.

- **Strategy Pattern (`CopyStrategyFactory`, `FileCopyExecutor`):** The actual file copying is handled by different "strategies." The `CopyStrategyFactory` selects the best strategy for a given file (e.g., `NormalFileCopyStrategy`, `GrowingFileCopyStrategy`, `ResumableNormalFileCopyStrategy`). This makes the copy logic flexible and easy to extend.

- **`WebSocketManager` (The Notifier):** This service subscribes to the `StateManager` and broadcasts any state changes to the web UI in real-time, providing a live view of the operations.

This decoupled nature means that each component has a single responsibility, making the system easier to understand, test, and scale.

## Installation

```cmd
pip install -r requirements.txt
```

uvicorn app.main:app --reload

eller

python -m uvicorn app.main:app --reload