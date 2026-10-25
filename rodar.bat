@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo [PriceRadar] Iniciando o Monitor de Precos e Promocoes...
echo ============================================================
echo.
if exist ".venv\Scripts\python.exe" (
    start "" http://127.0.0.1:5000
    ".venv\Scripts\python.exe" app.py
) else (
    echo Ambiente virtual .venv nao encontrado.
    pause
)
