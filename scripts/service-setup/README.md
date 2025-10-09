# Service Setup Scripts

This directory contains platform-specific scripts to install File Transfer Agent as a system service.

## 🎯 **Supported Platforms**

- ✅ **macOS** - Using launchd
- ✅ **Linux** - Using systemd  
- ✅ **Windows** - Using NSSM (Non-Sucking Service Manager)

---

## 🚀 **Quick Installation**

### **macOS:**
```bash
# As user service (recommended for desktop):
./scripts/service-setup/install-macos.sh

# As system service (for servers):
sudo ./scripts/service-setup/install-macos.sh
```

### **Linux (Ubuntu/Debian/CentOS/RHEL):**
```bash
# As user service:
./scripts/service-setup/install-linux.sh

# As system service (recommended):
sudo ./scripts/service-setup/install-linux.sh
```

### **Windows:**
```batch
REM Run as Administrator (required):
scripts\service-setup\install-windows.bat
```

---

## 📋 **Prerequisites**

### **All Platforms:**
- Python 3.8 or higher
- Git (for cloning the repository)
- Network access for downloading dependencies

### **macOS:**
- macOS 10.14+ (Mojave or later)
- Developer tools (xcode-select --install)

### **Linux:**
- systemd-based distribution
- sudo access (for system service)

### **Windows:**
- Windows 10/Server 2016 or later
- Administrator privileges
- PowerShell (for enhanced output)

---

## 🔧 **What the Scripts Do**

### **Automatic Setup:**
1. **Check prerequisites** - Python version, dependencies
2. **Create virtual environment** - Isolated Python environment
3. **Install dependencies** - All required Python packages
4. **Create service configuration** - Platform-specific service files
5. **Install and start service** - Register with system service manager
6. **Verify installation** - Test web interface and health check

### **Service Configuration:**
- **Auto-start** - Service starts automatically on boot
- **Auto-restart** - Service restarts on crashes
- **Logging** - Comprehensive logging to files
- **Security** - Runs with minimal privileges
- **Resource limits** - Memory and file descriptor limits

---

## 📊 **Service Details**

### **Service Names:**
- **macOS:** `com.fileagent.service`
- **Linux:** `file-transfer-agent`
- **Windows:** `FileTransferAgent`

### **Default Ports:**
- **Web Interface:** http://localhost:8000
- **WebSocket:** ws://localhost:8000/api/ws/live

### **Log Locations:**
- **macOS:** `~/file-agent/logs/` or `/var/log/` (system service)
- **Linux:** `journalctl -u file-transfer-agent` or `~/file-agent/logs/`
- **Windows:** `file-agent\logs\file-agent.log`

---

## 🛠️ **Service Management**

### **macOS (launchd):**
```bash
# Status
launchctl list | grep com.fileagent.service

# Stop
launchctl unload ~/Library/LaunchAgents/com.fileagent.service.plist

# Start  
launchctl load ~/Library/LaunchAgents/com.fileagent.service.plist

# Logs
tail -f ~/file-agent/logs/file-agent.log
```

### **Linux (systemd):**
```bash
# Status
systemctl status file-transfer-agent

# Stop
systemctl stop file-transfer-agent

# Start
systemctl start file-transfer-agent

# Restart
systemctl restart file-transfer-agent

# Logs
journalctl -u file-transfer-agent -f
```

### **Windows (NSSM):**
```batch
REM Status
sc query FileTransferAgent

REM Stop
net stop FileTransferAgent

REM Start
net start FileTransferAgent

REM Service Manager GUI
services.msc

REM Logs
type file-agent\logs\file-agent.log
```

---

## 🔄 **Uninstallation**

Each installation creates an uninstall script:

### **macOS:**
```bash
./scripts/service-setup/uninstall-macos.sh
```

### **Linux:**
```bash
./scripts/service-setup/uninstall-linux.sh
```

### **Windows:**
```batch
scripts\service-setup\uninstall-windows.bat
```

---

## ⚙️ **Configuration**

### **Environment Configuration:**
Edit `settings.env` before installation:

```bash
# Source and destination directories
SOURCE_DIRECTORY=/path/to/source
DESTINATION_DIRECTORY=/path/to/destination

# File monitoring settings
POLLING_INTERVAL_SECONDS=10
FILE_STABLE_TIME_SECONDS=10

# Storage monitoring
STORAGE_CHECK_INTERVAL_SECONDS=60
SOURCE_WARNING_THRESHOLD_GB=10.0
DESTINATION_WARNING_THRESHOLD_GB=50.0

# Space management
COPY_SAFETY_MARGIN_GB=1.0
ENABLE_PRE_COPY_SPACE_CHECK=true
```

### **Platform-Specific Paths:**

**macOS Examples:**
```bash
SOURCE_DIRECTORY=/Users/username/Desktop/source
DESTINATION_DIRECTORY=/Volumes/NAS/destination
```

**Linux Examples:**
```bash
SOURCE_DIRECTORY=/home/username/source
DESTINATION_DIRECTORY=/mnt/nas/destination
```

**Windows Examples:**
```batch
SOURCE_DIRECTORY=C:\temp_input
DESTINATION_DIRECTORY=\\NAS\destination
```

---

## 🧪 **Testing Installation**

After installation, verify the service:

### **1. Check Service Status:**
```bash
# All platforms - check if service is running
curl http://localhost:8000/health
```

### **2. Test Web Interface:**
Open browser to: http://localhost:8000

### **3. Test API:**
```bash
# Check storage status
curl http://localhost:8000/api/storage

# Check file status
curl http://localhost:8000/api/state
```

### **4. Test File Processing:**
1. Place a test `.mxf` file in source directory
2. Watch web interface for file discovery
3. Verify file appears in destination

---

## 🐛 **Troubleshooting**

### **Common Issues:**

#### **"Permission Denied" Errors:**
- **macOS/Linux:** Run with `sudo` for system service
- **Windows:** Run as Administrator

#### **"Python not found" Errors:**
- Ensure Python 3.8+ is installed and in PATH
- Try `python3` instead of `python` on macOS/Linux

#### **Service Won't Start:**
- Check logs for error messages
- Verify source/destination directories exist
- Check network port 8000 is available

#### **Web Interface Not Responding:**
- Wait 30 seconds after service start
- Check if port 8000 is blocked by firewall
- Verify service is actually running

### **Log Analysis:**
```bash
# macOS
tail -f ~/file-agent/logs/file-agent.log

# Linux
journalctl -u file-transfer-agent -f --since "10 minutes ago"

# Windows
type file-agent\logs\file-agent.log | more
```

---

## 🔒 **Security Considerations**

### **Service User:**
- Services run with minimal privileges
- Dedicated service user on Linux/macOS
- No interactive login capabilities

### **File Permissions:**
- Service needs read access to source directory
- Service needs write access to destination directory
- Log directory needs write access

### **Network Security:**
- Web interface binds to localhost by default
- No external network access required
- WebSocket traffic is unencrypted (local only)

---

## 📈 **Performance Tuning**

### **Resource Limits:**
- **Memory:** 1GB default limit (Linux systemd)
- **File Descriptors:** 65536 limit
- **CPU:** No limit (background processing)

### **Monitoring Intervals:**
Adjust in `settings.env`:
```bash
# Faster file discovery (higher CPU usage)
POLLING_INTERVAL_SECONDS=5

# Slower storage monitoring (lower overhead)  
STORAGE_CHECK_INTERVAL_SECONDS=300
```

---

## 🆘 **Support**

### **Getting Help:**
1. Check logs first
2. Verify configuration in `settings.env`
3. Test manually: `python -m uvicorn app.main:app --reload`
4. Check GitHub issues: https://github.com/TommiIversen/file-agent

### **Reporting Issues:**
Include:
- Operating system and version
- Python version (`python --version`)
- Service logs
- Configuration file (`settings.env`)
- Steps to reproduce