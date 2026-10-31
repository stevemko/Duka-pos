@echo off
rem Start the shop server on this machine.
rem Any other till in the shop then opens http://THIS-PC-NAME:8000 (or its 192.168.x.x address).
rem The app itself must be built first:  cd ..\frontend  and  npm run build
cd /d "%~dp0"

if not exist "backend_venv\Scripts\python.exe" (
    echo A virtual environment is needed before the shop can be started.
    echo     python -m venv backend_venv
    echo     backend_venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Applying any database changes...
"backend_venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo The database could not be updated. Read the message above before continuing.
    pause
    exit /b 1
)

"backend_venv\Scripts\python.exe" manage.py collectstatic --noinput >nul 2>&1

echo.
echo Greenlight POS is running. Keep this window open while the shop is trading.
echo     This machine:  http://127.0.0.1:8000
echo     Other tills:   http://<this computer's name or 192.168 address>:8000
echo Press Ctrl+C, or close this window, to stop trading from this server.
echo.
"backend_venv\Scripts\python.exe" -m waitress --listen=0.0.0.0:8000 config.wsgi:application
