@echo off
cd /d "%~dp0"
echo Starting Mock Tally Light Server...
echo This server simulates an IP Power Switch for testing
echo.
echo Available endpoints:
echo   POST http://localhost:8001/api/switch/on  - Turn tally light ON
echo   POST http://localhost:8001/api/switch/off - Turn tally light OFF
echo   GET  http://localhost:8001/api/switch/status - Get current status
echo.
python mock_tally_server.py
pause