@echo off
chcp 65001 >nul
title 停止服务

echo 正在停止服务...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo   关闭端口 5000 (PID: %%a)
    taskkill /F /PID %%a >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8080 ^| findstr LISTENING') do (
    echo   关闭端口 8080 (PID: %%a)
    taskkill /F /PID %%a >nul 2>&1
)

echo 所有服务已停止
pause
