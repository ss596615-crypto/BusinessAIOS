@echo off
setlocal
chcp 65001 >nul
cd /d C:\DevelopmentEngine

if not exist ".env" (
    echo [오류] C:\DevelopmentEngine\.env 파일이 없습니다.
    echo OPENAI_API_KEY를 설정한 뒤 다시 실행하세요.
    pause
    exit /b 1
)

for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="OPENAI_API_KEY" set "OPENAI_API_KEY=%%B"
    if /I "%%A"=="OPENAI_MODEL" set "OPENAI_MODEL=%%B"
)

py development_engine_mvp.py
pause
