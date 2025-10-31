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


- **`WebSocketManager` (The Notifier):** This service subscribes to the `StateManager` and broadcasts any state changes to the web UI in real-time, providing a live view of the operations.

This decoupled nature means that each component has a single responsibility, making the system easier to understand, test, and scale.

## Installation

### Prerequisites
- **Python 3.13+** (required)
- **pip** (usually included with Python)

### Quick Setup

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Start the application:**
```bash
# Development mode (with auto-reload)
uvicorn app.main:app --reload

# Or alternatively:
python -m uvicorn app.main:app --reload

# Production mode (external access)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

3. **Access the web interface:**
   - Local: http://localhost:8000
   - Health check: http://localhost:8000/health
   - API docs: http://localhost:8000/docs

### macOS Service Setup

For automatic startup as a system service on macOS:

```bash
# Make the script executable
chmod +x scripts/service-setup/install-macos.sh

# Run the installer
./scripts/service-setup/install-macos.sh
```

The installer will:
- Check for Python 3.13+
- Install dependencies via pip
- Test application startup
- Create a macOS launchd service
- Start the service automatically

### Service Management

Once installed as a service, you can manage it with these commands:

#### macOS Service Commands

```bash
# Check service status
launchctl list | grep com.fileagent.service

# Stop the service
sudo launchctl unload /Library/LaunchDaemons/com.fileagent.service.plist
# (or for user service: launchctl unload ~/Library/LaunchAgents/com.fileagent.service.plist)

# Start the service
sudo launchctl load /Library/LaunchDaemons/com.fileagent.service.plist
# (or for user service: launchctl load ~/Library/LaunchAgents/com.fileagent.service.plist)

# Restart the service (stop + start)
sudo launchctl unload /Library/LaunchDaemons/com.fileagent.service.plist
sudo launchctl load /Library/LaunchDaemons/com.fileagent.service.plist

# View service logs
tail -f logs/file-agent.log
tail -f logs/file-agent-error.log

# Uninstall the service
./scripts/service-setup/uninstall-macos.sh
```

#### Manual Application Control

If you're running the app manually (not as a service):

```bash
# Start manually (development mode)
python3 -m uvicorn app.main:app --reload

# Start manually (production mode)
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

debug 
$env:PYTHONASYNCIODEBUG=1; python -m uvicorn app.main:app

# Stop manual app
Ctrl+C (in the terminal where it's running)
```

#### Troubleshooting

```bash
# Check Python version
python3 --version

# Test app startup manually
cd /path/to/file-agent
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# Check if port 8000 is in use
lsof -i :8000

# Check service file exists
ls -la /Library/LaunchDaemons/com.fileagent.service.plist
# or for user service:
ls -la ~/Library/LaunchAgents/com.fileagent.service.plist
```

# Tailwind CSS Setup for File Agent

This project now uses the standalone Tailwind CSS executable instead of the CDN version for better performance and offline development.

## Files Created

- `tailwind.css` - Input CSS file with Tailwind directives and custom styles
- `tailwind-build.bat` - One-time build script
- `tailwind-watch.bat` - Development watch script
- `app/static/css/tailwind.css` - Generated output CSS file (auto-generated)

## Usage

### First Time Setup / Production Build

Run the build script to download Tailwind CSS and generate the CSS file:

```batch
.\tailwind-build.bat
```

This will:
1. Download `tailwindcss-windows-x64.exe` if not present
2. Generate the optimized CSS file at `app/static/css/tailwind.css`
3. Include only the CSS classes actually used in your HTML templates

### Development with Watch Mode

For development, use the watch script to automatically rebuild CSS when files change:

```batch
.\tailwind-watch.bat
```

This will:
1. Download Tailwind CSS if needed
2. Start watching for changes in HTML templates and JS files
3. Automatically rebuild CSS when changes are detected
4. Run until you stop it with Ctrl+C


### Development Tools

```bash
# Find alle unused/dead code patterns
ruff check . --select F,E

# Find kompleksitets issues  
ruff check . --select C901

# Find alle potentielle bugs
ruff check . --select B

# Find style issues
ruff check . --select E,W

# Fix issues automatically
ruff check . --fix

```