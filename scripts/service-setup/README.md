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


---

## 📋 **Prerequisites**

### **All Platforms:**
- Python 3.13 or higher
- Git (for cloning the repository)
- Network access for downloading dependencies

### **macOS:**
- macOS 10.14+ (Mojave or later)
- Developer tools (xcode-select --install)


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

### **Default Ports:**
- **Web Interface:** http://localhost:8000
- **WebSocket:** ws://localhost:8000/api/ws/live

### **Log Locations:**
- **macOS:** `~/file-agent/logs/` or `/var/log/` (system service)


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

## 🔄 **Uninstallation**

Each installation creates an uninstall script:

### **macOS:**
```bash
./scripts/service-setup/uninstall-macos.sh
```

### **Platform-Specific Paths:**

**macOS Examples:**
```bash
SOURCE_DIRECTORY=/Users/username/Desktop/source
DESTINATION_DIRECTORY=/Volumes/NAS/destination
```


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


### **Log Analysis:**
```bash
# macOS
tail -f ~/file-agent/logs/file-agent.log

# Linux
journalctl -u file-transfer-agent -f --since "10 minutes ago"

# Windows
type file-agent\logs\file-agent.log | more
```


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
