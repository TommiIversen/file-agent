@echo off
REM File Transfer Agent - Windows Service Setup Script
REM This script sets up the File Transfer Agent as a Windows service using NSSM

setlocal enabledelayedexpansion

REM Configuration
set SERVICE_NAME=FileTransferAgent
set SERVICE_DISPLAY_NAME=File Transfer Agent
set SERVICE_DESCRIPTION=Automated video file transfer service for MXF files
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..\..
set NSSM_URL=https://nssm.cc/release/nssm-2.24.zip
set NSSM_ZIP=%TEMP%\nssm.zip
set NSSM_DIR=%TEMP%\nssm-2.24

REM Colors for output (using PowerShell for colored output)
set "info_color=Write-Host '[INFO]' -ForegroundColor Blue -NoNewline; Write-Host ' '"
set "success_color=Write-Host '[SUCCESS]' -ForegroundColor Green -NoNewline; Write-Host ' '"
set "warning_color=Write-Host '[WARNING]' -ForegroundColor Yellow -NoNewline; Write-Host ' '"
set "error_color=Write-Host '[ERROR]' -ForegroundColor Red -NoNewline; Write-Host ' '"

echo ========================================
echo 🚀 File Transfer Agent - Windows Service Setup
echo ========================================
echo.

REM Check if running as administrator
net session >nul 2>&1
if %errorLevel% == 0 (
    powershell -Command "%info_color% 'Running as Administrator - proceeding with system service installation'"
) else (
    powershell -Command "%error_color% 'This script must be run as Administrator'"
    echo Please right-click and select "Run as administrator"
    pause
    exit /b 1
)

REM Check prerequisites
powershell -Command "%info_color% 'Checking prerequisites...'"

REM Check Python 3.8+
python --version >nul 2>&1
if %errorLevel% neq 0 (
    powershell -Command "%error_color% 'Python is required but not found in PATH'"
    echo Please install Python 3.8+ and add it to PATH
    pause
    exit /b 1
)

REM Get Python version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
powershell -Command "%info_color% 'Found Python version: %PYTHON_VERSION%'"

REM Check if project directory exists
if not exist "%PROJECT_DIR%" (
    powershell -Command "%error_color% 'Project directory not found: %PROJECT_DIR%'"
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist "%PROJECT_DIR%\venv" (
    powershell -Command "%warning_color% 'Virtual environment not found, creating...'"
    call :create_virtual_environment
)

REM Download and setup NSSM if not exists
set NSSM_EXE=%NSSM_DIR%\win64\nssm.exe
if not exist "%NSSM_EXE%" (
    powershell -Command "%info_color% 'Downloading NSSM (Non-Sucking Service Manager)...'"
    call :download_nssm
)

REM Stop existing service if running
sc query "%SERVICE_NAME%" >nul 2>&1
if %errorLevel% == 0 (
    powershell -Command "%info_color% 'Stopping existing service...'"
    "%NSSM_EXE%" stop "%SERVICE_NAME%"
    "%NSSM_EXE%" remove "%SERVICE_NAME%" confirm
    timeout /t 3 /nobreak >nul
)

REM Create Windows service
powershell -Command "%info_color% 'Creating Windows service...'"
call :create_service

REM Start the service
powershell -Command "%info_color% 'Starting File Transfer Agent service...'"
"%NSSM_EXE%" start "%SERVICE_NAME%"

REM Wait for service to start
timeout /t 5 /nobreak >nul

REM Check service status
sc query "%SERVICE_NAME%" | find "RUNNING" >nul
if %errorLevel% == 0 (
    powershell -Command "%success_color% 'File Transfer Agent service started successfully'"
    
    REM Test web interface
    timeout /t 5 /nobreak >nul
    powershell -Command "try { Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing | Out-Null; Write-Host '[SUCCESS] Web interface is responding at http://localhost:8000' -ForegroundColor Green } catch { Write-Host '[WARNING] Web interface not responding yet, check logs' -ForegroundColor Yellow }"
) else (
    powershell -Command "%error_color% 'Failed to start service'"
    "%NSSM_EXE%" status "%SERVICE_NAME%"
    pause
    exit /b 1
)

REM Create uninstall script
call :create_uninstall_script

REM Show completion info
call :show_completion_info

goto :eof

:create_virtual_environment
powershell -Command "%info_color% 'Creating virtual environment...'"
cd /d "%PROJECT_DIR%"
python -m venv venv
call venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip

REM Install dependencies
if exist "requirements.txt" (
    pip install -r requirements.txt
) else (
    powershell -Command "%info_color% 'Installing basic dependencies...'"
    pip install fastapi uvicorn aiofiles pydantic python-dotenv
)

powershell -Command "%success_color% 'Virtual environment created and dependencies installed'"
goto :eof

:download_nssm
REM Download NSSM using PowerShell
powershell -Command "Invoke-WebRequest -Uri '%NSSM_URL%' -OutFile '%NSSM_ZIP%'"

REM Extract NSSM
powershell -Command "Expand-Archive -Path '%NSSM_ZIP%' -DestinationPath '%TEMP%' -Force"

if not exist "%NSSM_EXE%" (
    powershell -Command "%error_color% 'Failed to download or extract NSSM'"
    exit /b 1
)

powershell -Command "%success_color% 'NSSM downloaded and extracted successfully'"
goto :eof

:create_service
set PYTHON_EXE=%PROJECT_DIR%\venv\Scripts\python.exe
set WORK_DIR=%PROJECT_DIR%
set LOG_DIR=%PROJECT_DIR%\logs

REM Create logs directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM Install service
"%NSSM_EXE%" install "%SERVICE_NAME%" "%PYTHON_EXE%" "-m" "uvicorn" "app.main:app" "--host" "0.0.0.0" "--port" "8000" "--log-level" "info"

REM Configure service
"%NSSM_EXE%" set "%SERVICE_NAME%" DisplayName "%SERVICE_DISPLAY_NAME%"
"%NSSM_EXE%" set "%SERVICE_NAME%" Description "%SERVICE_DESCRIPTION%"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppDirectory "%WORK_DIR%"

REM Configure startup
"%NSSM_EXE%" set "%SERVICE_NAME%" Start SERVICE_AUTO_START

REM Configure logging
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStdout "%LOG_DIR%\file-agent.log"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppStderr "%LOG_DIR%\file-agent-error.log"
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateFiles 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateOnline 1
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRotateBytes 10485760

REM Configure restart policy
"%NSSM_EXE%" set "%SERVICE_NAME%" AppExit Default Restart
"%NSSM_EXE%" set "%SERVICE_NAME%" AppRestartDelay 30000

REM Configure environment
"%NSSM_EXE%" set "%SERVICE_NAME%" AppEnvironmentExtra "PYTHONPATH=%PROJECT_DIR%"

powershell -Command "%success_color% 'Service created successfully'"
goto :eof

:create_uninstall_script
set UNINSTALL_SCRIPT=%PROJECT_DIR%\scripts\service-setup\uninstall-windows.bat

(
echo @echo off
echo REM File Transfer Agent - Windows Uninstall Script
echo.
echo set SERVICE_NAME=FileTransferAgent
echo set SCRIPT_DIR=%%~dp0
echo set NSSM_DIR=%%TEMP%%\nssm-2.24
echo set NSSM_EXE=%%NSSM_DIR%%\win64\nssm.exe
echo.
echo echo Uninstalling File Transfer Agent service...
echo.
echo REM Stop and remove service
echo sc query "%%SERVICE_NAME%%" ^>nul 2^>^&1
echo if %%errorLevel%% == 0 ^(
echo     echo Stopping service...
echo     "%%NSSM_EXE%%" stop "%%SERVICE_NAME%%"
echo     timeout /t 3 /nobreak ^>nul
echo     echo Removing service...
echo     "%%NSSM_EXE%%" remove "%%SERVICE_NAME%%" confirm
echo ^)
echo.
echo echo File Transfer Agent service uninstalled successfully
echo echo Note: Virtual environment and project files were not removed
echo pause
) > "%UNINSTALL_SCRIPT%"

powershell -Command "%success_color% 'Uninstall script created: %UNINSTALL_SCRIPT%'"
goto :eof

:show_completion_info
echo.
powershell -Command "%success_color% '🎉 File Transfer Agent Windows service setup complete!'"
echo.
powershell -Command "%info_color% 'Service Details:'"
echo   • Service Name: %SERVICE_NAME%
echo   • Display Name: %SERVICE_DISPLAY_NAME%
echo   • Working Directory: %PROJECT_DIR%
echo   • Log Files: %PROJECT_DIR%\logs\
echo.
powershell -Command "%info_color% 'Service Management Commands:'"
echo   • View Status: sc query "%SERVICE_NAME%"
echo   • Stop Service: net stop "%SERVICE_NAME%"
echo   • Start Service: net start "%SERVICE_NAME%"
echo   • View Logs: type "%PROJECT_DIR%\logs\file-agent.log"
echo   • Service Manager: services.msc
echo.
powershell -Command "%info_color% 'Web Interface:'"
echo   • URL: http://localhost:8000
echo   • Health Check: http://localhost:8000/health
echo   • API Documentation: http://localhost:8000/docs
echo.
powershell -Command "%info_color% 'To uninstall:'"
echo   • Run: %PROJECT_DIR%\scripts\service-setup\uninstall-windows.bat
echo.
pause
goto :eof