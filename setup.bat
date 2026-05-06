@echo off
echo ============================================================
echo  Edge TTS Web App - Setup
echo ============================================================

REM Create venv if it doesn't exist
if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Could not create venv. Is Python installed?
        pause
        exit /b 1
    )
)

echo Activating venv and installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt

echo.
echo ============================================================
echo  Setup complete! Run the app with:  run.bat
echo ============================================================
pause
