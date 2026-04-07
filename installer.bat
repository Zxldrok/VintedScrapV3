@echo off
echo ============================================
echo   VintedScrap -- Installation des dependances
echo ============================================
echo.

set PYTHON="C:\Users\Adrien\AppData\Local\Programs\Python\Python311\python.exe"

%PYTHON% --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERREUR] Python introuvable au chemin specifie.
    echo Verifiez le chemin dans installer.bat
    pause
    exit /b 1
)

echo [INFO] Installation des bibliotheques requises...
%PYTHON% -m pip install -r requirements.txt

echo.
echo [OK] Installation terminee !
echo.
echo Pour lancer l'application : double-cliquez sur lancer.bat
echo.
pause
