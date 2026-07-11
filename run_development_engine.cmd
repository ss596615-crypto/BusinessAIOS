@echo off
setlocal
cd /d C:\DevelopmentEngine

if not exist ".env" (
    echo [ERROR] .env file not found.
    pause
    exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="OPENAI_API_KEY" set "OPENAI_API_KEY=%%B"
    if /I "%%A"=="OPENAI_MODEL" set "OPENAI_MODEL=%%B"
)

py development_engine_mvp.py run
pause
