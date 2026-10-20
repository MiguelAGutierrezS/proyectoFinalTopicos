# LocalGem Chat ✨ — Clon de Google Gemini 100% Local y Gratuito

**LocalGem Chat** es una aplicación web multimodal inspirada en Google Gemini, diseñada bajo **Specification-Driven Development (SDD)** para ejecutarse de forma **100% local, privada y sin costos de API** utilizando **FastAPI**, **SQLite (`localgem.db`)**, **Ollama** y **Next.js (App Router + TypeScript + Tailwind CSS)**.

---

## 🚀 Características Principales

1. **Persistencia Local en SQLite (`localgem.db`)**:
   - Creación de nuevos chats, autogeneración de títulos según la primera consulta y guardado persistente de todo el historial, archivos adjuntos y preferencias del usuario.
2. **Entrada Multimodal 100% Local**:
   - **Fotos (`.png`, `.jpg`, `.jpeg`, `.webp`)**: Redimensionado inteligente con `Pillow` ($\le 1024\text{px}$) y envío en Base64 a modelos con visión en Ollama, más extracción de metadatos descriptivos para modelos solo-texto.
   - **Documentos (`.pdf`, `.txt`, `.csv`, `.md`)**: Extracción de texto local con `PyMuPDF` (`fitz`) y lectura multi-encoding limitada de forma segura a 12,000 caracteres por archivo.
   - **Audios (`.mp3`, `.wav`, `.m4a`, `.ogg`)**: Transcripción local en CPU (`int8`) mediante `faster-whisper` con carga perezosa (*lazy-loading*) y manejo tolerante a fallos si no está instalado `ffmpeg`.
3. **Voz Bidireccional Gratuita**:
   - **Dictado por Voz en Vivo (STT)**: Captura en tiempo real en español (`es-ES`) mediante la `Web Speech API` del navegador con animación de pulso en vivo.
   - **Lectura en Voz Alta (TTS)**: Botón **"Escuchar en voz alta"** en cada respuesta de la IA (y en las tarjetas A/B) usando `window.speechSynthesis`.
4. **Opciones de Seguimiento Inteligentes (`---FOLLOW_UP_OPTIONS---`)**:
   - Al final de **cada** respuesta de la IA se generan entre **2 y 3 opciones clicables** para continuar la conversación con un solo clic.
   - Incluye un **fallback automático determinista en Python** para que incluso modelos antiguos o ultraligeros que olviden el separador muestren siempre 3 sugerencias contextuales.
5. **Modo de Satisfacción A/B (Aprendizaje de Estilo)**:
   - Se activa automáticamente **cada 3 mensajes del usuario** o manualmente con el botón **"Comparar 2 respuestas"**.
   - Genera **Respuesta A (Enfoque Directo / Conciso)** (`temperature=0.3`) y **Respuesta B (Enfoque Detallado / Explicativo)** (`temperature=0.8`) lado a lado para que elijas cuál prefieres, guardando tu preferencia en la tabla `user_preferences` para adaptar futuras respuestas.

---

## 🛠️ Requisitos Previos

1. **Python 3.10+** instalado y agregado al `PATH`.
2. **Node.js 18+** y `npm`.
3. **Ollama** instalado desde [https://ollama.com](https://ollama.com).
4. *(Opcional)* **FFmpeg** instalado en el sistema si deseas transcribir archivos de audio comprimidos (`.mp3`, `.m4a`) subidos como adjuntos. El dictado por micrófono en vivo funciona directamente en el navegador sin requerir FFmpeg.

---

## 🧠 Paso 1: Tener Ollama Abierto con un Modelo Gratuito

LocalGem Chat se conecta automáticamente a `http://localhost:11434` y detecta cualquier modelo que tengas descargado en Ollama.

Abre una terminal y ejecuta **cualquiera** de los siguientes comandos según la capacidad de tu equipo:

### Opción A — Modelos ultraligeros (ideales para CPU o laptops con poca RAM):
```bash
ollama run llama3.2:1b
```
o bien:
```bash
ollama run qwen2.5:1.5b
```

### Opción B — Modelos equilibrados de alta calidad (4 GB – 8 GB RAM):
```bash
ollama run gemma3:4b
```
o bien:
```bash
ollama run llama3.2
```

### Opción C — Modelos con Visión (para analizar fotos `.png` / `.jpg` / `.webp`):
```bash
ollama run llava
```

> **Nota:** Una vez que el modelo descargue y veas el prompt en tu terminal (o tengas `ollama serve` activo en segundo plano), ya puedes usar LocalGem Chat. En la barra lateral izquierda podrás cambiar entre todos tus modelos instalados en cualquier momento.

---

## ⚡ Paso 2: Cómo Ejecutar el Proyecto

### En Windows (Inicio Automático con 1 Clic)
Ejecuta el script en la raíz del proyecto:
```bat
.\start-localgem.bat
```
Este script:
1. Creará automáticamente el entorno virtual `backend/venv` e instalará las dependencias de `backend/requirements.txt` si aún no existen.
2. Instalará las dependencias de `frontend/package.json` si no existe `node_modules`.
3. Levantará simultáneamente el backend de **FastAPI en `http://localhost:8000`** y el frontend de **Next.js en `http://localhost:3000`**.

### En Linux / macOS (Inicio Automático)
```bash
chmod +x start-localgem.sh
./start-localgem.sh
```

---

## 🔧 Ejecución Manual (Alternativa en 2 Terminales)

Si prefieres iniciar cada servidor manualmente:

### Terminal 1 — Backend (FastAPI en puerto 8000)
```bash
cd backend
python -m venv venv
# En Windows:
venv\Scripts\activate
# En Linux/Mac:
# source venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Terminal 2 — Frontend (Next.js en puerto 3000)
```bash
cd frontend
npm install
npm run dev
```

Luego abre tu navegador en **[http://localhost:3000](http://localhost:3000)**.

---

## 📂 Estructura del Proyecto (SDD)

```text
├── .gemini                              # Reglas de arquitectura SDD y stack obligatorio
├── specs/                               # Fuente Única de Verdad (Especificaciones SDD)
│   ├── 01-requirements-ears.md          # Requisitos funcionales en formato EARS
│   ├── 02-database-and-api.md           # Esquema SQLite (4 tablas) y contratos REST API
│   └── 03-ai-orchestration.md           # Orquestación Ollama, fallback y flujo dual A/B
├── backend/                             # Servidor Python FastAPI + SQLAlchemy + SQLite
│   ├── database.py                      # Conexión a sqlite:///./localgem.db e init_db()
│   ├── models.py                        # Modelos ORM: Chat, Message, Attachment, UserPreference
│   ├── schemas.py                       # Esquemas Pydantic v2 de entrada/salida
│   ├── main.py                          # Endpoints REST API y servidor de archivos /uploads
│   └── services/
│       ├── multimodal_processor.py      # Procesador local de imágenes, PDFs/CSV/TXT y audios
│       └── ollama_service.py            # Cliente Ollama, parser ---FOLLOW_UP_OPTIONS--- y modo A/B
├── frontend/                            # Aplicación Next.js (App Router, TypeScript, Tailwind)
│   └── src/
│       ├── lib/api.ts                   # Cliente HTTP tipado hacia localhost:8000/api
│       ├── components/
│       │   ├── Sidebar.tsx              # Historial de chats, selector de modelo y toggle A/B
│       │   ├── ABComparisonSelector.tsx # Vista comparativa lado a lado (Tarjeta A vs Tarjeta B)
│       │   ├── FollowUpOptions.tsx      # Chips clicables de seguimiento al final de cada respuesta
│       │   └── MultimodalInputBar.tsx   # Subida multimodal, micrófono Web Speech y controles
│       └── app/
│           ├── globals.css              # Tema oscuro Google Gemini (#131314 / #1e1f20)
│           ├── layout.tsx               # Layout raíz en español
│           └── page.tsx                 # Vista principal con TTS y regeneración comparativa
├── start-localgem.bat                   # Lanzador automático para Windows
└── start-localgem.sh                    # Lanzador automático para Linux / macOS
```
