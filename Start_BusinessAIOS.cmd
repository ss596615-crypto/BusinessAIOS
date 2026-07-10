@echo off
cd /d C:\BusinessAIOS\AgentsSDK
start "" cmd /c "py -m streamlit run ceo_meeting.py --server.port 8501"
timeout /t 5 /nobreak >nul
start "" http://localhost:8501
exit