# LocalGem Chat — Reglas de Arquitectura y Desarrollo (SDD)

## 1. Principio Fundamental: Specification-Driven Development (SDD)
Este proyecto se rige estrictamente bajo la metodología **Specification-Driven Development (SDD)**. La carpeta `/specs` constituye la **Fuente Única de Verdad (Single Source of Truth)** del sistema.

### Reglas de Oro antes de escribir código:
1. **Lectura Obligatoria**: Antes de crear, modificar o refactorizar cualquier archivo dentro de `/backend` o `/frontend`, **SIEMPRE debes leer y consultar los documentos en `/specs`**:
   - `specs/01-requirements-ears.md`: Requisitos funcionales y no funcionales en sintaxis EARS.
   - `specs/02-database-and-api.md`: Esquema exacto de base de datos SQLite (`localgem.db`) y contratos de la API REST.
   - `specs/03-ai-orchestration.md`: Integración con Ollama, ingeniería de prompts, parser con fallback para `---FOLLOW_UP_OPTIONS---`, flujo multimodal y generación dual A/B.
2. **Prohibición de Desviación de Esquemas**: Ningún modelo de SQLAlchemy, esquema Pydantic o interfaz TypeScript puede omitir o renombrar campos definidos en `specs/02-database-and-api.md`.
3. **Sincronización Especificación-Código**: Si surge la necesidad técnica de alterar un endpoint o tabla, primero debe actualizarse la especificación correspondiente en `/specs`.

---

## 2. Stack Tecnológico Obligatorio

### Backend (`/backend`)
- **Lenguaje**: Python 3.10+
- **Framework Web**: FastAPI (con validación Pydantic v2 y soporte CORS configurado para el frontend local).
- **Base de Datos**: SQLite (`localgem.db`) gestionada mediante **SQLAlchemy ORM** (modo síncrono o asíncrono limpio con sesiones inyectadas por dependencia `get_db`).
- **Motor de IA Local**: **Ollama** ejecutándose localmente en `http://localhost:11434` (consumido mediante `httpx` asíncrono).
- **Procesamiento Multimodal Local**:
  - **Imágenes (`.png`, `.jpg`, `.webp`)**: Codificación Base64 para modelos con soporte de visión en Ollama y metadatos de imagen (Pillow).
  - **Documentos (`.pdf`, `.txt`, `.csv`, `.md`)**: Extracción de texto local (`pypdf`/`PyPDF2` para PDF, lectura UTF-8 con fallback `latin-1` para texto/CSV/Markdown).
  - **Audios (`.mp3`, `.wav`, `.m4a`)**: Almacenamiento local y transcripción local (vía `faster-whisper`, `whisper` o `SpeechRecognition` con fallback gracioso si no hay binario disponible) para inyectar el contenido en `extracted_text`.

### Frontend (`/frontend`)
- **Framework**: Next.js 14+ utilizando exclusivamente **App Router** (`src/app` o `app/`).
- **Lenguaje**: TypeScript estricto (`strict: true`).
- **Estilos**: Tailwind CSS (diseño inspirado en Google Gemini: interfaz limpia, modo oscuro/claro elegante, animaciones fluidas, burbujas amplias y chips interactivos).
- **Iconografía**: `lucide-react` (Lucide Icons).
- **Voz Bidireccional Nativa**:
  - **STT (Dictado en tiempo real)**: Web Speech API (`window.SpeechRecognition` / `window.webkitSpeechRecognition`).
  - **TTS (Lectura en voz alta)**: Web Speech Synthesis API (`window.speechSynthesis` con controles de reproducir, pausar y detener en cada mensaje).

---

## 3. Convenciones de Código y Calidad

### Resiliencia con Modelos Pequeños/Antiguos en Ollama
- Nunca asumas que un modelo local (ej. `llama3.2:1b`, `tinyllama`, `mistral`, `gemma:2b`, `qwen2.5:0.5b`) respetará siempre el formato estructurado o JSON.
- La extracción de opciones de seguimiento (`---FOLLOW_UP_OPTIONS---`) **siempre** debe pasar por el parser tolerante a fallos documentado en `specs/03-ai-orchestration.md`, garantizando por código entre 2 y 3 opciones válidas en el array `follow_up_options`.
- Si Ollama no está disponible o el modelo solicitado no existe, el backend debe hacer fallback automático al primer modelo instalado en `/api/tags` o devolver un mensaje de error claro y accionable sin colapsar el servidor.

### Reglas de Negocio Críticas
1. **Opciones de Seguimiento**: Todo mensaje del asistente (`role = "assistant"`) debe persistir en `follow_up_options_json` (y devolver en la API) entre 2 y 3 opciones clicables. Al hacer clic en una opción en la UI, esta se envía inmediatamente como el siguiente mensaje del usuario.
2. **Modo de Satisfacción A/B**:
   - Se activa automáticamente **cada 3 mensajes del usuario** dentro de un mismo chat (`user_message_count % 3 == 0`) **o** manualmente cuando el usuario activa el botón **"Comparar 2 respuestas"** (`force_ab_test = true`).
   - En modo A/B, el backend genera **Respuesta A** (concisa, directa y al grano) y **Respuesta B** (detallada, explicativa y estructurada).
   - Cuando el usuario elige su candidata preferida (`A` o `B`), se actualiza `selected_candidate` y `content` en la tabla `messages`, y se inserta un registro en `user_preferences` (`preferred_style = "concise"` o `"detailed"`).
3. **Persistencia Total**: Todos los chats, mensajes, archivos adjuntos y preferencias deben sobrevivir reinicios tanto del navegador como del servidor FastAPI.
