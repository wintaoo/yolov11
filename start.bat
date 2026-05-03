@echo off
set "NUL=nul"
chcp 65001 1>%NUL% 2>&1
title Analysis System

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

echo [2/5] Stop old ports...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo   Kill port 5000 (PID: %%a)
    taskkill /F /PID %%a 1>%NUL% 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
    echo   Kill port 8080 (PID: %%a)
    taskkill /F /PID %%a 1>%NUL% 2>&1
)
timeout /t 2 /nobreak 1>%NUL%

echo [3/5] Start backend (port 5000)...
start "Backend-API" cmd /c "cd /d %BACKEND% && "%VENV_PYTHON%" run.py"

echo [4/5] Wait for backend...
timeout /t 6 /nobreak 1>%NUL%

echo [5/5] Start frontend (port 8080)...
if not exist "%FRONTEND%\node_modules" (
    echo   Installing frontend deps...
    cd /d "%FRONTEND%" && call npm install
    cd /d "%ROOT%"
)
start "Frontend-Dev" cmd /c "cd /d %FRONTEND% && npm run dev"

timeout /t 4 /nobreak 1>%NUL%

echo.
echo ========================================
echo   Backend : http://localhost:5000
echo   Frontend: http://localhost:8080
echo ========================================
echo.
echo   Press any key to open browser...
pause 1>%NUL%
start http://localhost:8080
