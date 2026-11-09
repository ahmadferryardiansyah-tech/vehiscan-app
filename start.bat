@echo off
rem VehiScan ITS - jalankan server. Klik dua kali, atau di terminal VS Code: .\start.bat
rem   start.bat        -> mulai tanpa data simulasi (disarankan)
rem   start.bat demo   -> isi 900 data simulasi + watchlist contoh (hanya untuk presentasi; JANGAN dicampur data riset)
cd /d "%~dp0"
if /i "%1"=="demo" set VEHISCAN_SEED=1
if not exist venv\Scripts\activate.bat (
  echo [!] venv belum ada. Buat dulu:  py -3.12 -m venv venv ^&^& venv\Scripts\activate ^&^& pip install -r requirements.txt
  pause & exit /b 1
)
call venv\Scripts\activate.bat
echo Buka http://127.0.0.1:8000  ^(Ctrl+C untuk berhenti^)
python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
pause
