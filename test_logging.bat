@echo off
echo Testing File Transfer Agent Logging System...
echo.

REM Installer dependencies hvis nødvendigt
echo Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo Running logging test...
echo.

python test_logging.py

echo.
echo Test completed! Check the following:
echo 1. Console output above for colored logs
echo 2. File logs/file_agent.log for JSON formatted logs
echo 3. Log rotation will happen at midnight

pause