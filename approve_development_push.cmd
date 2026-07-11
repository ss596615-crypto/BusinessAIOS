@echo off
setlocal
cd /d C:\DevelopmentEngine

echo Development Engine - Representative Approval
echo.
set /p CONFIRM=Approve latest pending commit and push to ai-ceo-dev? (Y/N): 
if /I not "%CONFIRM%"=="Y" (
    echo Cancelled.
    pause
    exit /b 0
)

py development_engine_mvp.py approve
pause
