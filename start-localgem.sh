#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================================"
echo "  LocalGem Chat — Clon de Google Gemini 100% Local y Gratuito"
echo "============================================================================"
echo ""

# ------------------------------------------------------------------------------
# 1. Configurar e instalar dependencias del Backend (Python / FastAPI)
# ------------------------------------------------------------------------------
echo "[1/4] Verificando entorno virtual de Python en /backend..."
cd "$ROOT_DIR/backend"

PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [ ! -d "venv" ]; then
  echo "      Creando entorno virtual en backend/venv..."
  "$PYTHON_BIN" -m venv venv
fi

if [ ! -f "venv/.deps_installed" ]; then
  echo "      Instalando dependencias de Python desde requirements.txt..."
  ./venv/bin/pip install --upgrade pip
  ./venv/bin/pip install -r requirements.txt
  touch venv/.deps_installed
else
  echo "      Dependencias de backend ya instaladas."
fi

# ------------------------------------------------------------------------------
# 2. Configurar e instalar dependencias del Frontend (Node.js / Next.js)
# ------------------------------------------------------------------------------
echo ""
echo "[2/4] Verificando dependencias de Node.js en /frontend..."
cd "$ROOT_DIR/frontend"

if [ ! -d "node_modules" ]; then
  echo "      Instalando paquetes npm en /frontend..."
  npm install
else
  echo "      node_modules ya presente en /frontend."
fi

# ------------------------------------------------------------------------------
# 3. Levantar Backend (:8000) y Frontend (:3000) simultáneamente
# ------------------------------------------------------------------------------
cleanup() {
  echo ""
  echo "Deteniendo servicios de LocalGem Chat..."
  if [ -n "${BACKEND_PID:-}" ]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [ -n "${FRONTEND_PID:-}" ]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
  exit 0
}
trap cleanup SIGINT SIGTERM

echo ""
echo "[3/4] Iniciando Backend FastAPI en http://localhost:8000 ..."
cd "$ROOT_DIR/backend"
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

echo "[4/4] Iniciando Frontend Next.js en http://localhost:3000 ..."
cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "============================================================================"
echo "  LocalGem Chat activo:"
echo "  - Frontend UI : http://localhost:3000"
echo "  - Backend API : http://localhost:8000/docs"
echo "  - Ollama Local: http://localhost:11434"
echo "  (Presiona Ctrl+C para detener ambos servidores)"
echo "============================================================================"

wait
