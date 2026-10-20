@echo off
chcp 65001 >nul
title LocalGem Chat — Iniciador Local (FastAPI + Next.js + Ollama)

echo ============================================================================
echo   LocalGem Chat — Clon de Google Gemini 100%% Local y Gratuito
echo ============================================================================
echo.

set "ROOT_DIR=%~dp0"

REM ----------------------------------------------------------------------------
REM 1. Configurar e instalar dependencias del Backend (Python / FastAPI)
REM ----------------------------------------------------------------------------
echo [1/4] Verificando entorno virtual de Python en /backend...
cd /d "%ROOT_DIR%backend"

if not exist "venv\Scripts\python.exe" (
    echo       Creando entorno virtual en backend\venv...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual. Verifica que Python 3.10+ este instalado y en el PATH.
        pause
        exit /b 1
    )
)

if not exist "venv\.deps_installed" (
    echo       Instalando dependencias de Python desde requirements.txt...
    call "venv\Scripts\python.exe" -m pip install --upgrade pip
    call "venv\Scripts\pip.exe" install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Fallo la instalacion de paquetes en backend\requirements.txt.
        pause
        exit /b 1
    )
    echo ok > "venv\.deps_installed"
) else (
    echo       Dependencias de backend ya instaladas.
)

REM ----------------------------------------------------------------------------
REM 2. Configurar e instalar dependencias del Frontend (Node.js / Next.js)
REM ----------------------------------------------------------------------------
echo.
echo [2/4] Verificando dependencias de Node.js en /frontend...
cd /d "%ROOT_DIR%frontend"

if not exist "node_modules" (
    echo       Instalando paquetes npm en /frontend...
    call npm.cmd install
    if errorlevel 1 (
        echo [ERROR] Fallo npm install en /frontend. Verifica que Node.js 18+ este instalado.
        pause
        exit /b 1
    )
) else (
    echo       node_modules ya presente en /frontend.
)

REM ----------------------------------------------------------------------------
REM 3. Levantar Backend (Puerto 8000) y Frontend (Puerto 3000) simultaneamente
REM ----------------------------------------------------------------------------
echo.
echo [3/4] Iniciando servidor Backend FastAPI en http://localhost:8000 ...
start "LocalGem Backend (FastAPI :8000)" /d "%ROOT_DIR%backend" cmd /k "venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

echo [4/4] Iniciando servidor Frontend Next.js en http://localhost:3000 ...
start "LocalGem Frontend (Next.js :3000)" /d "%ROOT_DIR%frontend" cmd /k "npm.cmd run dev"

echo.
echo ============================================================================
echo   LocalGem Chat se esta iniciando en dos ventanas:
echo   - Frontend UI : http://localhost:3000
echo   - Backend API : http://localhost:8000/docs
echo   - Ollama Local: http://localhost:11434 (asegurate de tener Ollama abierto)
echo ============================================================================
echo.
pause
