@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   RECY - Crypto Intelligence Terminal (One-Click Launcher)
echo ============================================================
echo.

REM --- 1. Cek virtual environment .venv ---
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment ".venv" tidak ditemukan!
    echo Jalankan dulu: python -m venv .venv
    echo            dan: .venv\Scripts\pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo [OK] Virtual environment ditemukan.
echo.

REM --- 2. Buka browser otomatis setelah server sempat start (2 detik) ---
start "" cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:8000/dashboard"

REM --- 3. Jalankan Uvicorn (Ctrl+C untuk berhenti) ---
echo [RUN] Menjalankan Uvicorn di http://127.0.0.1:8000
echo       Dashboard: http://127.0.0.1:8000/dashboard
echo       Tekan Ctrl+C untuk menghentikan server.
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload

echo.
echo Server berhenti.
pause
