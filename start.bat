@echo off
set "NUL=nul"
chcp 65001 1>%NUL% 2>&1
title Analysis System
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "VENV_PYTHON=%ROOT%venv\Scripts\python.exe"
set "VENV_PIP=%ROOT%venv\Scripts\pip.exe"

echo ========================================
echo   Building Drawing Analysis System
echo ========================================
echo.

echo [1/5] Check venv...
if not exist "%VENV_PYTHON%" (
    echo   Creating venv...
    python -m venv venv
    call "%VENV_PYTHON%" -m pip install --upgrade pip -q
    call "%VENV_PIP%" install -r "%BACKEND%\requirements-minimal.txt" -q
    echo   venv created.
) else (
    echo   venv ready.
)

echo [2/5] Stop old backend...
set "PORT_FILE=%BACKEND%\.port"
if exist "%PORT_FILE%" (
    set /p OLD_PORT=<"%PORT_FILE%"
    for /f "tokens=5" %%a in ('netstat -ano 2^>^&1 ^| findstr :!OLD_PORT!  ^| findstr LISTENING') do (
        echo   Kill port !OLD_PORT! (PID: %%a^)
        taskkill /F /PID %%a 1>%NUL% 2>&1
    )
)

echo [3/5] Start backend...
start "Backend-API" cmd /c "cd /d %BACKEND% && "%VENV_PYTHON%" run.py"

echo   Waiting for backend to be ready...
set "B_PORT=5050"
set "READY=0"
for /L %%i in (1,1,30) do (
    timeout /t 1 /nobreak 1>%NUL%
    if exist "%PORT_FILE%" (
        set /p B_PORT=<"%PORT_FILE%"
        netstat -ano 2>^&1 | findstr "!B_PORT!" | findstr LISTENING 1>%NUL%
        if not errorlevel 1 (
            set "READY=1"
        )
    )
    if "!READY!"=="1" goto :backend_ready
)
:backend_ready
if "!READY!"=="0" (
    echo   [WARN] Backend may not be ready, continuing...
    if exist "%PORT_FILE%" set /p B_PORT=<"%PORT_FILE%"
)
echo   Backend on port !B_PORT!

echo [4/5] Wait for backend startup...
timeout /t 3 /nobreak 1>%NUL%

echo [5/5] Start frontend...
if not exist "%FRONTEND%\node_modules" (
    echo   Installing frontend deps...
    cd /d "%FRONTEND%" && call npm install
    cd /d "%ROOT%"
)

set "FPORT_FILE=%BACKEND%\.frontend-port"
if exist "%FPORT_FILE%" del "%FPORT_FILE%"

start "Frontend-Dev" cmd /c "cd /d %FRONTEND% && npm run dev"

echo   Waiting for frontend to be ready...
set "F_PORT=8088"
set "F_READY=0"
for /L %%i in (1,1,30) do (
    timeout /t 1 /nobreak 1>%NUL%
    if exist "%FPORT_FILE%" (
        set /p F_PORT=<"%FPORT_FILE%"
        set "F_READY=1"
    )
    if "!F_READY!"=="1" goto :frontend_ready
)
:frontend_ready
if "!F_READY!"=="0" (
    echo   [WARN] Frontend port file not found, assuming !F_PORT!
)
echo   Frontend on port !F_PORT!

timeout /t 2 /nobreak 1>%NUL%

echo.
echo ========================================
echo   Backend : http://localhost:!B_PORT!
echo   Frontend: http://localhost:!F_PORT!
echo ========================================
echo.
echo   Press any key to open browser...
pause 1>%NUL%
start http://localhost:!F_PORT!
