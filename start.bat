@echo off
chcp 65001 >nul
title 建筑图纸分析系统

echo ========================================
echo   海南机器管招投标项目 - 建筑图纸分析系统
echo ========================================
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%backend
set FRONTEND=%ROOT%frontend

echo [1/4] 检查端口占用...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo   关闭端口 5000 (PID: %%a)
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
    echo   关闭端口 8080 (PID: %%a)
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [2/4] 启动后端服务 (端口 5000)...
start "Backend" cmd /c "cd /d %BACKEND% && python run.py"

echo [3/4] 等待后端就绪...
timeout /t 6 /nobreak >nul

echo [4/4] 启动前端服务 (端口 8080)...
start "Frontend" cmd /c "cd /d %FRONTEND% && npm run dev"

timeout /t 4 /nobreak >nul

echo.
echo ========================================
echo   启动完成!
echo   后端: http://localhost:5000
echo   前端: http://localhost:8080
echo ========================================
echo.
echo   按任意键打开前端页面...
pause >nul
start http://localhost:8080
