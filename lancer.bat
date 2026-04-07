@echo off
cd /d "%~dp0"
"C:\Users\Adrien\AppData\Local\Programs\Python\Python311\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [ERREUR] L'application a rencontre une erreur.
    pause
)
