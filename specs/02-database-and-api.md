# 02 — Esquema de Base de Datos (`localgem.db`) y Contratos de API REST

**Proyecto:** LocalGem Chat  
**Versión:** 2.1.0  
**Base de Datos:** SQLite 3 (`backend/localgem.db`) con SQLAlchemy 2.0 ORM  
**Servidor API:** FastAPI (`http://localhost:8000`) + Motor Agéntico LangGraph (`StateGraph`)  

---

## 1. Esquema Exacto de Base de Datos SQLite (`localgem.db`)

La base de datos consta de **4 tablas obligatorias** con integridad referencial activada (`PRAGMA foreign_keys = ON;`) y migración automática (`ALTER TABLE`) al iniciar `init_db()` para preservar datos existentes.

### 1.1 Diagrama Entidad-Relación (Mermaid)

```mermaid
erDiagram
    chats ||--o{ messages : "contiene (CASCADE)"
    messages ||--o{ attachments : "adjunta (CASCADE)"
    messages ||--o{ user_preferences : "origina preferencia"

    chats {
        TEXT id PK "UUID v4"
        TEXT title "Título del chat"
        TEXT context_summary "Resumen compactado del historial antiguo (NULL si no aplica)"
        INTEGER compacted_up_to_index "Índice del último mensaje incluido en el resumen"
        DATETIME created_at "UTC timestamp"
        DATETIME updated_at "UTC timestamp"
    }

    messages {
        TEXT id PK "UUID v4"
        TEXT chat_id FK "Referencia a chats.id"
        TEXT role "'user' | 'assistant' | 'system'"
        TEXT content "Texto principal o candidata ganadora"
        TEXT follow_up_options_json "JSON array de 2-3 strings"
        BOOLEAN is_ab_test "0 o 1 (True si es respuesta A/B)"
        TEXT candidate_a "Respuesta A (concisa/directa)"
        TEXT candidate_b "Respuesta B (detallada/explicativa)"
        TEXT selected_candidate "'A' | 'B' | NULL"
        TEXT active_skill "ID de la Skill aplicada en el turno (ej. 'code-architect' o NULL)"
        TEXT mcp_calls_json "JSON array con trazas de herramientas MCP ejecutadas"
        DATETIME created_at "UTC timestamp"
    }

    attachments {
        TEXT id PK "UUID v4"
        TEXT message_id FK "Referencia a messages.id"
        TEXT file_name "Nombre original del archivo"
        TEXT file_type "'image' | 'document' | 'audio'"
        TEXT mime_type "Ej. image/png, application/pdf, audio/wav"
        TEXT local_path "Ruta relativa/absoluta en disco"
        TEXT extracted_text "Texto extraído, transcripción faster-whisper o descripción Vision Bridge"
    }

    user_preferences {
        TEXT id PK "UUID v4"
        TEXT preferred_style "'concise' | 'detailed'"
        TEXT message_id FK "Referencia a messages.id"
        DATETIME created_at "UTC timestamp"
    }
```

---

### 1.2 Definición DDL Exacta (SQLite)

#### Tabla 1: `chats`
Almacena las sesiones de conversación.
```sql
CREATE TABLE IF NOT EXISTS chats (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Nuevo Chat',
    context_summary TEXT DEFAULT NULL,         -- Resumen compactado del historial antiguo (NULL = no compactado aún)
    compacted_up_to_index INTEGER DEFAULT NULL, -- Índice (orden creado_at ASC) del último mensaje incluido en el resumen
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### Tabla 2: `messages`
Almacena todos los mensajes enviados por el usuario y generados por la IA, incluyendo las opciones de seguimiento, datos de pruebas A/B, la Skill activa y las trazas de ejecución MCP.
```sql
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL DEFAULT '',
    follow_up_options_json TEXT DEFAULT '[]',
    is_ab_test BOOLEAN NOT NULL DEFAULT 0,
    candidate_a TEXT DEFAULT NULL,
    candidate_b TEXT DEFAULT NULL,
    selected_candidate TEXT DEFAULT NULL CHECK(selected_candidate IN ('A', 'B') OR selected_candidate IS NULL),
    active_skill TEXT DEFAULT NULL,            -- ID de la Skill activa en este mensaje (v2.0)
    mcp_calls_json TEXT NOT NULL DEFAULT '[]', -- JSON array de llamadas MCP ejecutadas (v2.0)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);
```

#### Tabla 3: `attachments`
Almacena los archivos multimodales subidos por el usuario y asociados a un mensaje específico. Para imágenes, `extracted_text` almacena tanto los metadatos técnicos de Pillow como la descripción visual generada por el **Vision Bridge** (`moondream` / `llava`).
```sql
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK(file_type IN ('image', 'document', 'audio')),
    mime_type TEXT NOT NULL,
    local_path TEXT NOT NULL,
    extracted_text TEXT DEFAULT '',
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_attachments_message_id ON attachments(message_id);
```

#### Tabla 4: `user_preferences`
Registra el historial de elecciones del usuario en el Modo de Satisfacción A/B (`"A"` $\rightarrow$ `"concise"`, `"B"` $\rightarrow$ `"detailed"`).
```sql
CREATE TABLE IF NOT EXISTS user_preferences (
    id TEXT PRIMARY KEY,
    preferred_style TEXT NOT NULL CHECK(preferred_style IN ('concise', 'detailed')),
    message_id TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_user_preferences_message_id ON user_preferences(message_id);
```

---

## 2. Reglas de Mapeo en SQLAlchemy (`backend/models.py`)

1. Todos los `id` se generan en Python mediante `str(uuid.uuid4())`.
2. En el modelo `Message`, se deben incluir las propiedades de conveniencia:
   - `@property def follow_up_options(self) -> list[str]` que deserialice `follow_up_options_json` con `json.loads()` (devolviendo `[]` si es nulo o inválido).
   - `@property def mcp_tool_calls(self) -> list[dict]` que deserialice `mcp_calls_json` con `json.loads()` (devolviendo `[]` si es nulo o inválido).
3. Las relaciones deben declararse con `cascade="all, delete-orphan"`:
   - `Chat.messages` $\rightarrow$ `relationship("Message", back_populates="chat", cascade="all, delete-orphan", order_by="Message.created_at")`
   - `Message.attachments` $\rightarrow$ `relationship("Attachment", back_populates="message", cascade="all, delete-orphan")`
   - `Message.preferences` $\rightarrow$ `relationship("UserPreference", back_populates="message", cascade="all, delete-orphan")`

---

## 3. Contratos de la API REST en FastAPI

Prefijo base: `/api`  
Puerto por defecto: `8000` (`http://localhost:8000`)  
Archivos estáticos servidos en: `/uploads/{filename}` para visualizar imágenes y reproducir audios subidos.

---

### 3.1 Estado de Salud y Modelos de Ollama

#### `GET /api/health`
Verifica el estado del backend, la conexión con SQLite y la disponibilidad de Ollama en `http://localhost:11434`.

- **Response `200 OK`**:
```json
{
  "status": "ok",
  "database": "connected",
  "ollama_reachable": true,
  "active_model": "llama3.2:latest",
  "available_models": ["moondream:latest", "llama3.2:1b", "llama3.2:latest"]
}
```

#### `GET /api/models`
Lista los modelos instalados localmente en Ollama consultando `http://localhost:11434/api/tags`.

- **Response `200 OK`**:
```json
{
  "models": [
    {
      "name": "llama3.2:latest",
      "size": 2019393189,
      "modified_at": "2026-10-19T10:00:00Z"
    }
  ],
  "default_model": "llama3.2:latest"
}
```

---

### 3.2 Gestión de Chats

#### `GET /api/chats`
Obtiene todos los chats guardados ordenados por `updated_at` descendente.

- **Response `200 OK`**:
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Análisis de ventas Q3 en CSV",
    "created_at": "2026-10-19T10:15:00Z",
    "updated_at": "2026-10-19T10:20:30Z",
    "message_count": 4
  }
]
```

#### `POST /api/chats`
Crea un nuevo chat vacío.

- **Request Body (`application/json`, opcional)**:
```json
{
  "title": "Nuevo Chat"
}
```
- **Response `201 Created`**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Nuevo Chat",
  "created_at": "2026-10-19T10:15:00Z",
  "updated_at": "2026-10-19T10:15:00Z",
  "messages": []
}
```

#### `GET /api/chats/{chat_id}`
Obtiene el detalle completo de un chat incluyendo todos sus mensajes ordenados cronológicamente y sus archivos adjuntos.

- **Response `200 OK`**:
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Explicación de arquitectura limpia",
  "created_at": "2026-10-19T10:15:00Z",
  "updated_at": "2026-10-19T10:20:30Z",
  "user_message_count": 3,
  "messages": [
    {
      "id": "msg-user-001",
      "chat_id": "550e8400-e29b-41d4-a716-446655440000",
      "role": "user",
      "content": "Explícame qué es Clean Architecture y revisa este documento",
      "follow_up_options": [],
      "is_ab_test": false,
      "candidate_a": null,
      "candidate_b": null,
      "selected_candidate": null,
      "active_skill": "code-architect",
      "mcp_tool_calls": [],
      "created_at": "2026-10-19T10:15:05Z",
      "attachments": [
        {
          "id": "att-001",
          "message_id": "msg-user-001",
          "file_name": "arquitectura.pdf",
          "file_type": "document",
          "mime_type": "application/pdf",
          "local_path": "uploads/att-001_arquitectura.pdf",
          "extracted_text": "Clean Architecture separa las reglas de negocio..."
        }
      ]
    },
    {
      "id": "msg-ai-001",
      "chat_id": "550e8400-e29b-41d4-a716-446655440000",
      "role": "assistant",
      "content": "Clean Architecture es un patrón de diseño...",
      "follow_up_options": [
        "¿Cómo aplico esto en un proyecto con FastAPI?",
        "Muéstrame un ejemplo práctico de casos de uso",
        "¿Qué diferencias tiene con la Arquitectura Hexagonal?"
      ],
      "is_ab_test": false,
      "candidate_a": null,
      "candidate_b": null,
      "selected_candidate": null,
      "active_skill": "code-architect",
      "mcp_tool_calls": [],
      "created_at": "2026-10-19T10:15:12Z",
      "attachments": []
    }
  ]
}
```

#### `PATCH /api/chats/{chat_id}`
Actualiza manualmente el título de un chat.

- **Request Body (`application/json`)**:
```json
{
  "title": "Nuevo título personalizado"
}
```
- **Response `200 OK`**: Objeto del chat actualizado.

#### `DELETE /api/chats/{chat_id}`
Elimina un chat, todos sus mensajes, sus registros de `attachments` y borra los archivos físicos asociados en `backend/uploads/`.

- **Response `200 OK`**:
```json
{
  "deleted": true,
  "chat_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### 3.3 Envío de Mensajes Multimodales, Skills, MCP y Generación de IA

#### `POST /api/chats/{chat_id}/messages`
Envía un mensaje del usuario (con texto y/o archivos multimodales), procesa los adjuntos (ejecutando el **Vision Bridge** para imágenes y `faster-whisper` para audios), aplica la **Skill** seleccionada o auto-detectada, ejecuta las herramientas **MCP** pertinentes si `enable_mcp=true`, verifica si corresponde activar el **Modo A/B** (`user_msg_count % 3 == 0` o `force_ab_test=true`), invoca a Ollama y devuelve el mensaje del usuario y la respuesta del asistente.

- **Content-Type**: `multipart/form-data`
- **Form Fields**:
  - `content` (`string`, obligatorio si no hay archivos): Texto del mensaje del usuario.
  - `force_ab_test` (`boolean`, opcional, default `false`): Si es `true` (botón "Comparar 2 respuestas"), fuerza generación dual A/B.
  - `model` (`string`, opcional): Nombre del modelo en Ollama (ej. `llama3.2:latest`). Si se omite, usa el modelo activo por defecto.
  - `skill_id` (`string`, opcional): Identificador de la Skill a aplicar (ej. `code-architect`, `data-analyst`, `auto`, o vacío).
  - `enable_mcp` (`boolean`, opcional, default `true`): Si es `true`, habilita el Router Híbrido MCP para ejecutar herramientas locales cuando la consulta lo requiera.
  - `files` (`list[UploadFile]`, opcional): Archivos subidos (`.png`, `.jpg`, `.jpeg`, `.webp`, `.pdf`, `.txt`, `.csv`, `.md`, `.mp3`, `.wav`, `.m4a`, `.ogg`).

- **Lógica de Activación A/B en este Endpoint**:
  1. Se inserta el nuevo mensaje con `role = "user"` en la base de datos.
  2. Se cuenta el total de mensajes con `role = "user"` en este `chat_id` (`user_msg_count`).
  3. `should_run_ab = force_ab_test or (user_msg_count % 3 == 0)`.

- **Response `201 Created`**:
```json
{
  "chat_id": "550e8400-e29b-41d4-a716-446655440000",
  "chat_title": "Explicación de arquitectura limpia",
  "user_message_count": 3,
  "user_message": {
    "id": "msg-user-003",
    "chat_id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "user",
    "content": "¿Cómo estructuro las carpetas en Python?",
    "follow_up_options": [],
    "is_ab_test": false,
    "candidate_a": null,
    "candidate_b": null,
    "selected_candidate": null,
    "active_skill": "code-architect",
    "mcp_tool_calls": [],
    "created_at": "2026-10-19T10:25:00Z",
    "attachments": []
  },
  "assistant_message": {
    "id": "msg-ai-003",
    "chat_id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "assistant",
    "content": "Usa una estructura de 4 capas: `domain/`, `application/`, `infrastructure/` y `presentation/`...",
    "follow_up_options": [
      "¿Qué archivos van dentro de la carpeta domain?",
      "Dame un ejemplo de repositorio en infrastructure",
      "¿Cómo inyecto dependencias con FastAPI?"
    ],
    "is_ab_test": true,
    "candidate_a": "Usa una estructura de 4 capas: `domain/` (entidades), `application/` (casos de uso), `infrastructure/` (SQLAlchemy/Ollama) y `presentation/` (rutas FastAPI).",
    "candidate_b": "Para estructurar un proyecto Python siguiendo Clean Architecture de forma profesional, te recomiendo dividir el proyecto en 4 capas concéntricas:\n\n1. **Domain (`domain/`)**: Contiene las entidades puras...\n2. **Application (`application/`)**: Orquesta los casos de uso...",
    "selected_candidate": null,
    "active_skill": "code-architect",
    "mcp_tool_calls": [],
    "created_at": "2026-10-19T10:25:08Z",
    "attachments": []
  }
}
```

---

### 3.4 Selección de Respuesta en Modo A/B y Preferencias

#### `POST /api/messages/{message_id}/select-candidate` (y alias `/api/messages/{message_id}/select-ab`)
Registra la elección del usuario entre la **Respuesta A** (concisa) y la **Respuesta B** (detallada) en un mensaje con `is_ab_test = true`.

- **Request Body (`application/json`)**:
```json
{
  "selected_candidate": "A"
}
```
*(Valores permitidos: `"A"` o `"B"`).*

- **Response `200 OK`**:
```json
{
  "message": {
    "id": "msg-ai-003",
    "chat_id": "550e8400-e29b-41d4-a716-446655440000",
    "role": "assistant",
    "content": "Usa una estructura de 4 capas...",
    "follow_up_options": [
      "¿Qué archivos van dentro de la carpeta domain?",
      "Dame un ejemplo de repositorio en infrastructure",
      "¿Cómo inyecto dependencias con FastAPI?"
    ],
    "is_ab_test": true,
    "candidate_a": "Usa una estructura de 4 capas...",
    "candidate_b": "Para estructurar un proyecto Python...",
    "selected_candidate": "A",
    "active_skill": "code-architect",
    "mcp_tool_calls": [],
    "created_at": "2026-10-19T10:25:08Z",
    "attachments": []
  },
  "preference_recorded": {
    "id": "pref-001",
    "preferred_style": "concise",
    "message_id": "msg-ai-003",
    "created_at": "2026-10-19T10:25:20Z"
  }
}
```

#### `GET /api/preferences/summary`
Devuelve el resumen estadístico de preferencias del usuario para mostrar en la UI y alimentar el prompt adaptativo.

- **Response `200 OK`**:
```json
{
  "total_ab_selections": 5,
  "concise_count": 3,
  "detailed_count": 2,
  "dominant_style": "concise"
}
```

---

### 3.5 Gestión de Skills (`SKILL.md`) y Herramientas MCP (v2.0)

#### `GET /api/skills`
Lista todas las Skills disponibles en `backend/skills/<skill_id>/SKILL.md`.

- **Response `200 OK`**:
```json
{
  "skills": [
    {
      "id": "code-architect",
      "name": "Arquitecto de Software",
      "description": "Experto en Clean Architecture, revisión de código, patrones de diseño y optimización.",
      "icon": "Code2",
      "category": "engineering",
      "triggers": ["arquitectura", "código", "refactoriza", "solid", "patrón", "fastapi", "react"],
      "instructions_preview": "Actúa como un Arquitecto de Software Principal..."
    }
  ]
}
```

#### `POST /api/skills`
Crea o actualiza un archivo `backend/skills/<skill_id>/SKILL.md` personalizado.

- **Request Body (`application/json`)**:
```json
{
  "id": "security-auditor",
  "name": "Auditor de Ciberseguridad",
  "description": "Analiza vulnerabilidades OWASP Top 10 y buenas prácticas de seguridad.",
  "icon": "ShieldCheck",
  "category": "security",
  "triggers": ["seguridad", "owasp", "vulnerabilidad", "xss", "sql injection"],
  "instructions": "Analiza el código o consulta desde la perspectiva de OWASP Top 10..."
}
```

#### `GET /api/mcp/tools`
Lista todas las herramientas registradas en el motor MCP local siguiendo el contrato estándar `tools/list` de Model Context Protocol.

- **Response `200 OK`**:
```json
{
  "tools": [
    {
      "name": "mcp_calculator",
      "description": "Evalúa expresiones matemáticas, financieras y estadísticas con precisión exacta.",
      "input_schema": {
        "type": "object",
        "properties": {
          "expression": { "type": "string", "description": "Expresión matemática a evaluar" }
        },
        "required": ["expression"]
      }
    }
  ]
}
```

#### `POST /api/mcp/call`
Ejecuta directamente una herramienta MCP (`tools/call`) con los argumentos proporcionados y devuelve su resultado estructurado y tiempo de ejecución.

- **Request Body (`application/json`)**:
```json
{
  "tool_name": "mcp_calculator",
  "arguments": {
    "expression": "sqrt(144) * 18.5"
  }
}
```

- **Response `200 OK`**:
```json
{
  "tool_name": "mcp_calculator",
  "arguments": { "expression": "sqrt(144) * 18.5" },
  "status": "success",
  "result": "222.0",
  "duration_ms": 4
}
```

---

### 3.6 Inspección de la Arquitectura Agéntica LangGraph (v2.1)

#### `GET /api/graph/schema`
Devuelve el esquema vivo del `StateGraph` de **LangGraph** (`backend/services/langgraph_service.py`), incluyendo los nodos del flujo agéntico y el código **Mermaid** para visualización interactiva.

- **Response `200 OK`**:
```json
{
  "engine": "LangGraph StateGraph",
  "version": "2.1.0",
  "state_schema": "LocalGemGraphState",
  "nodes": [
    {
      "id": "node_load_context",
      "label": "Carga de Contexto y Preferencias",
      "description": "Resuelve el modelo activo en Ollama, carga el estilo preferido del usuario y evalúa la condición de Test A/B."
    },
    {
      "id": "node_skill_router",
      "label": "Enrutador de Skills (SKILL.md)",
      "description": "Detecta e inyecta habilidades especializadas por selección manual, comando slash o triggers léxicos."
    },
    {
      "id": "node_mcp_executor",
      "label": "Ejecutor Híbrido MCP",
      "description": "Invoca herramientas locales del Model Context Protocol (Calculadora, SQLite, Reloj, Workspace, Wikipedia)."
    },
    {
      "id": "node_vision_bridge",
      "label": "Vision Bridge (2 Etapas)",
      "description": "Extrae descripciones visuales con moondream:latest y conmuta la síntesis en español a llama3.2."
    },
    {
      "id": "node_context_compactor",
      "label": "Compactador de Contexto",
      "description": "Resume historiales largos (>= 14 mensajes) para proteger la ventana de contexto y la memoria RAM."
    },
    {
      "id": "node_prompt_builder",
      "label": "Constructor de Prompt Multimodal",
      "description": "Ensambla el System Prompt adaptativo, adjuntos multimodales, resultados MCP y anclaje de intención."
    },
    {
      "id": "node_generate_standard",
      "label": "Generador Estándar Ollama",
      "description": "Ejecuta inferencia simple adaptada al estilo histórico del usuario (conciso o detallado)."
    },
    {
      "id": "node_generate_ab",
      "label": "Generador Dual A/B",
      "description": "Genera en paralelo controlado Candidata A (concisa, temp 0.3) y Candidata B (detallada, temp 0.8)."
    },
    {
      "id": "node_parse_and_fallback",
      "label": "Parser Resiliente de Opciones",
      "description": "Extrae ---FOLLOW_UP_OPTIONS--- con 3 niveles de fallback determinista garantizando 2 a 3 sugerencias."
    }
  ],
  "mermaid": "flowchart TD\n  START((START)) --> node_load_context..."
}
```

