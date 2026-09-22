@echo off
chcp 65001 > nul
echo =========================================================================
echo    📚 BIBLIOTHEQUE LIBRE - DOMAINE PUBLIC & GENERATEUR EPUB
echo =========================================================================
echo.

cd /d "%~dp0"

:: Check if py launcher or python is available
where py >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Demarrage du serveur avec Python (py)...
    py -3 pd_epub.py serve --port 8000
    goto end
)

where python >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Demarrage du serveur avec Python...
    python pd_epub.py serve --port 8000
    goto end
)

echo [ERREUR] Python n'a pas ete trouve dans votre variable d'environnement PATH.
echo Veuillez installer Python depuis https://www.python.org/ ou verifier votre installation.
echo.

:end
pause
