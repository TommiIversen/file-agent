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
- **Tally Light Integration:** Real-time recording status via IP Power 9255 switch (OFF/SOLID/BLINKING based on recording activity).

### Tally Light Configuration

```bash
# settings.env
TALLY_LIGHT_SWITCH_TYPE=ip_power_9255  # or "mock" for testing
TALLY_LIGHT_SWITCH_IP=10.65.77.9       # Your IP Power 9255 address
```

**Hardware Commands:**
- ON: `http://admin:12345678@IP/Set.cmd?cmd=setpower+p61=1`  
- OFF: `http://admin:12345678@IP/Set.cmd?cmd=setpower+p61=0`

### Output Folder Template System

Organize transferred files into categorized subfolders automatically based on filename patterns.

**Configuration (settings.env):**
```bash
OUTPUT_FOLDER_TEMPLATE_ENABLED=true
OUTPUT_FOLDER_RULES=pattern:*Cam*;folder:KAMERA/{date},pattern:*PGM*;folder:PROGRAM_CLEAN/{date}
OUTPUT_FOLDER_DEFAULT_CATEGORY=OTHER
OUTPUT_FOLDER_DATE_FORMAT=filename[0:6]
```

**Example 1 - Categorized Organization:**
```
With rules: pattern:*Cam*;folder:KAMERA/{date},pattern:*PGM*;folder:PROGRAM_CLEAN/{date}

251022_1400_Cam1.mxf  → \\NAS\KAMERA\251022\251022_1400_Cam1.mxf
251022_1500_PGM.mxf   → \\NAS\PROGRAM_CLEAN\251022\251022_1500_PGM.mxf
251022_1600_Other.mxf → \\NAS\OTHER\251022\251022_1600_Other.mxf (fallback)
```

**Example 2 - Date-Only Organization:**
```
With rules: pattern:*;folder:{date}

251022_1400_Cam1.mxf  → \\NAS\251022\251022_1400_Cam1.mxf
251022_1500_PGM.mxf   → \\NAS\251022\251022_1500_PGM.mxf
251022_1600_Other.mxf → \\NAS\251022\251022_1600_Other.mxf
```

**Available Variables:**
- `{date}` - Extracted from filename (e.g., first 6 chars for YYMMDD)
- `{filename}` - Full filename
- `{name_no_ext}` - Filename without extension

**Disable Template System:**
Set `OUTPUT_FOLDER_TEMPLATE_ENABLED=false` to copy all files directly to destination without subfolders.

## Architectural Overview

This application uses a clean, domain-driven architecture with CQRS and an event bus, built on a **Producer-Consumer** pattern.

- **`app/core/`** — Generic infrastructure: `FileRepository`, `FileStateMachine`, `EventBus`, `CommandBus`, `QueryBus`
- **`app/domains/file_discovery/`** — The Producer. Scans source directories, detects stable/growing files
- **`app/domains/file_processing/`** — The Consumer. Job queue, copy workers, retry logic
- **`app/domains/presentation/`** — Web UI, WebSocket real-time updates, Jinja2 templates
- **`app/domains/network_mount/`** — Network share mounting and health monitoring
- **`app/domains/lifecycle/`** — Periodic cleanup of completed/old files
- **`app/domains/ingest_monitor/`** — Just In Engine status monitoring
- **`app/domains/tally_light/`** — Recording indicator light control

Domains communicate via the EventBus (async, loose coupling) and QueryBus (sync queries across domains). Direct imports between domains are forbidden.

## Installation

### One-Command Install (macOS — no Python required)

On a fresh Mac, run:

```bash
curl -fsSL https://raw.githubusercontent.com/TommiIversen/file-agent/main/install.sh | bash
```

This will:
- Download the latest pre-built binary from GitHub Releases
- Install to `/usr/local/share/file-agent/`
- Set up a launchd service (auto-start on boot + restart on crash)
- Create a default config at `~/.config/file-agent/settings.env`
- Open the web UI at http://localhost:8000

**Install a specific version:**
```bash
curl -fsSL .../install.sh | bash -s -- --version v1.2.0
```

**Upgrade:**
```bash
curl -fsSL .../install.sh | bash -s -- --upgrade
```

**Uninstall:**
```bash
curl -fsSL .../install.sh | bash -s -- --uninstall
```

### Releasing a New Version

Push a git tag to trigger an automated build:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions will build a macOS binary and publish it as a GitHub Release. Tags containing `-` (e.g. `v1.1.0-beta`) are marked as pre-release.

### Development Setup

For local development (requires Python 3.13+):

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Start the application:**
```bash
# Development mode (with auto-reload)
uvicorn app.main:app --reload

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
chmod +x install-macos.sh

# Run the installer (user service, recommended for desktop)
./install-macos.sh

# Or as system service (for servers)
sudo ./install-macos.sh
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
./uninstall-macos.sh
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

This project uses the standalone Tailwind CSS executable instead of the CDN version for better performance and offline development.

## Files

- `tailwind/tailwind.css` - Input CSS file with Tailwind directives and custom styles
- `tailwind/build.bat` - One-time build script
- `tailwind/watch.bat` - Development watch script
- `app/domains/presentation/static/css/tailwind.css` - Generated output CSS file (auto-generated)

## Usage

### First Time Setup / Production Build

Run the build script to download Tailwind CSS and generate the CSS file:

```batch
.\tailwind\build.bat
```

This will:
1. Download `tailwindcss-windows-x64.exe` if not present
2. Generate the optimized CSS file at `app/domains/presentation/static/css/tailwind.css`
3. Include only the CSS classes actually used in your HTML templates

### Development with Watch Mode

For development, use the watch script to automatically rebuild CSS when files change:

```batch
.\tailwind\watch.bat
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

Jsdoc type

 npx tsc -p tsconfig.json