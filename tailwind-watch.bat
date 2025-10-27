@echo off
setlocal enabledelayedexpansion

REM Define paths and variables
set TAILWIND_VERSION=v4.1.16
set TAILWIND_EXE=tailwindcss-windows-x64.exe
set TAILWIND_URL=https://github.com/tailwindlabs/tailwindcss/releases/download/%TAILWIND_VERSION%/%TAILWIND_EXE%
set PROJECT_ROOT=%~dp0
set INPUT_CSS=%PROJECT_ROOT%tailwind.css
set OUTPUT_CSS=%PROJECT_ROOT%app\static\css\tailwind.css
set CONTENT_PATH1=%PROJECT_ROOT%app\templates\**\*.html
set CONTENT_PATH2=%PROJECT_ROOT%app\static\js\**\*.js

echo.
echo ========================================
echo   Tailwind CSS Setup for File Agent
echo ========================================
echo.

REM Check if Tailwind CSS executable exists
if not exist "%PROJECT_ROOT%%TAILWIND_EXE%" (
    echo [INFO] Tailwind CSS executable not found. Downloading...
    echo [INFO] Downloading from: %TAILWIND_URL%
    echo.
    
    REM Download using PowerShell (works on all Windows systems)
    curl -L -o "%PROJECT_ROOT%%TAILWIND_EXE%" "%TAILWIND_URL%"
    
    if !errorlevel! equ 0 (
        echo [SUCCESS] Downloaded Tailwind CSS successfully!
    ) else (
        echo [ERROR] Failed to download Tailwind CSS.
    )
    
    if !errorlevel! neq 0 (
        echo [ERROR] Download failed. Please check your internet connection.
        pause
        exit /b 1
    )
    
    echo.
) else (
    echo [INFO] Tailwind CSS executable found.
)

REM Check if input CSS file exists
if not exist "%INPUT_CSS%" (
    echo [ERROR] Input CSS file not found: %INPUT_CSS%
    echo [INFO] Please ensure tailwind.css exists in the project root.
    pause
    exit /b 1
)

REM Create output directory if it doesn't exist
if not exist "%PROJECT_ROOT%app\static\css\" (
    echo [INFO] Creating output directory: app\static\css\
    mkdir "%PROJECT_ROOT%app\static\css\"
)

echo [INFO] Starting Tailwind CSS in watch mode...
echo [INFO] Input:   %INPUT_CSS%
echo [INFO] Output:  %OUTPUT_CSS%
echo [INFO] Content: %CONTENT_PATH1%
echo [INFO]          %CONTENT_PATH2%
echo.
echo [INFO] Press Ctrl+C to stop watching
echo.

REM Run Tailwind CSS in watch mode with JIT compilation
"%PROJECT_ROOT%%TAILWIND_EXE%" -i "%INPUT_CSS%" -o "%OUTPUT_CSS%" --content="%CONTENT_PATH1%" --content="%CONTENT_PATH2%" --watch --minify

echo.
echo [INFO] Tailwind CSS watch stopped.
pause