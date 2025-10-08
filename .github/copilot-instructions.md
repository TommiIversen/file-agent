# Project: Python File Transfer Agent

## 1. Project Overview

The goal is to build a robust, automated background service in Python. Its primary function is to reliably move video files (MXF) from a local source folder on macOS to a network-attached storage (NAS) destination. The service must be resilient to network failures and restarts. The architecture is heavily inspired by Clean Code and SOLID principles.

## 2. Core Architecture & Python Stack

The application is built using Python with FastAPI for the API/UI layer and `asyncio` for concurrent background tasks.

- **Central State Management**: The application's "single source of truth" is a singleton-like `FileStateService`. This service manages a list of `TrackedFile` objects.
    - `TrackedFile` should be a Pydantic model representing a file's metadata (path, status, size, progress, etc.).
    - `FileStatus` should be an Enum with states like `Discovered`, `Ready`, `InQueue`, `Copying`, `Completed`, `Failed`.

- **Producer/Consumer Pattern**: The core logic is split into two decoupled background services (running as `asyncio` tasks):
    1.  **Producer (`FileScannerService`)**: Polls the source directory, identifies "stable" files, and adds their paths to a job queue.
    2.  **Consumer (`FileCopyService`)**: Takes file paths from the job queue and performs the copy operation.

- **Job Queue**: The producer and consumer are decoupled using an `asyncio.Queue`. This queue is registered as a singleton to ensure a single, shared instance.

- **Configuration**: All key parameters (SourcePath, DestinationPath, PollingIntervalSeconds, etc.) must be loaded from a configuration file (e.g., `config.json` or an `.env` file).

## 3. Key Logic & Principles

- **File Stability Logic**: A file is considered "stable" and ready to be copied only when its modification time (`os.path.getmtime`) has not changed for a configured duration (`FileStableTimeSeconds`).

- **Robust Error Handling**:
    - **Global Errors (e.g., destination unavailable)**: The `FileCopyService` must pause all operations and enter an infinite retry loop with a long, configurable delay.
    - **Local Errors (e.g., source file is locked)**: The service should attempt to copy a specific file a limited number of times (e.g., 3 retries) with short delays. If it fails all retries, the file's status is set to `Failed`, and the service moves to the next job.

- **Safe File Copy**: When copying, first write to a temporary file (e.g., `filename.mxf.tmp`). Only after a successful copy and a file size verification (source vs. destination) should the temporary file be renamed to its final name and the original source file be deleted.

- **API & Real-time UI**: The FastAPI app exposes API endpoints (e.g., `/api/status`, `/api/health`). For the UI, the backend should push real-time state updates to the frontend using **WebSockets**.

## Core Principles

- **Structure with `APIRouter`**: The application is modular. Each resource or domain (e.g., users, items) has its own router file in the `app/routers/` directory.

- **Central Entrypoint**: `app/main.py` is the main entry point that imports and includes all `APIRouter` instances into the primary `FastAPI` app.

- **Dependency Injection**: Reusable logic, like database sessions or authentication wirering up classes ang background services), is placed in `app/dependencies.py` and injected into path operations using `Depends()`.

- **SOLID Principles**: Adhere to SOLID principles where it matters (but we don't default to using interfaces unless necessary).

- **Type Hints**: Always use Python type hints for function parameters, return values, and Pydantic models to ensure data validation and code clarity.