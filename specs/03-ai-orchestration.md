# 03 — Orquestación de IA con Ollama, Extracción de Opciones y Flujo Dual A/B

**Proyecto:** LocalGem Chat  
**Motor de IA:** Ollama Local (`http://localhost:11434/api/chat`)  
**Objetivo:** Garantizar respuestas de alta calidad, soporte multimodal, extracción infalible de 2-3 opciones de seguimiento (`---FOLLOW_UP_OPTIONS---`) y generación dual A/B incluso en modelos pequeños o antiguos.

---

## 1. Conexión Resiliente con Ollama (`http://localhost:11434/api/chat`)

### 1.1 Protocolo de Comunicación
El backend se comunica con Ollama mediante peticiones HTTP `POST` asíncronas (`httpx.AsyncClient(timeout=120.0)`) hacia el endpoint estándar:
- **URL de Chat:** `http://localhost:11434/api/chat`
- **URL de Modelos Instalados:** `http://localhost:11434/api/tags`

### 1.2 Compatibilidad con Modelos Antiguos o Pequeños
Muchos usuarios ejecutan modelos ligeros o antiguos en CPUs locales (ej. `llama3.2:1b`, `gemma:2b`, `phi3:mini`, `mistral:7b`, `tinyllama`, `qwen2:1.5b`). Estos modelos presentan tres limitaciones comunes que nuestra arquitectura resuelve por diseño:
1. **No soportan `tools` o `format: "json"` complejo sin degradar la respuesta**: Por ello, **NO** dependemos de llamadas a funciones (function calling) ni de JSON schemas forzados en Ollama. Utilizamos texto plano estructurado con el delimitador explícito `---FOLLOW_UP_OPTIONS---`.
2. **Ventana de contexto reducida**: El orquestador limita el historial enviado a Ollama a los últimos **10 mensajes** del chat actual (`MAX_HISTORY_MESSAGES = 10`) y trunca textos extraídos de documentos muy extensos a un máximo de **12,000 caracteres** por adjunto para evitar desbordar el contexto.
3. **Resolución Dinámica de Modelo (Auto-Discovery)**:
   - Antes de invocar `/api/chat`, si el modelo configurado por defecto (ej. `llama3.2`) no está instalado, el orquestador consulta `GET http://localhost:11434/api/tags` y selecciona automáticamente el primer modelo disponible en la máquina del usuario.
   - Si un mensaje incluye imágenes en Base64 (`images`) pero el modelo activo es solo de texto y Ollama devuelve un error HTTP `400` o `500`, el orquestador **reintenta automáticamente la petición sin el campo `images`**, utilizando únicamente los metadatos e información del archivo inyectados en `extracted_text`.

### 1.3 Estructura del Payload hacia Ollama
```json
{
  "model": "llama3.2:latest",
  "stream": false,
  "options": {
    "temperature": 0.7,
    "num_ctx": 4096
  },
  "messages": [
    {
      "role": "system",
      "content": "<SYSTEM_PROMPT_CON_REGLA_DE_SEPARADOR>"
    },
    {
      "role": "user",
      "content": "<MENSAJE_DEL_USUARIO_MAS_TEXTO_EXTRAIDO_DE_ADJUNTOS>",
      "images": ["<BASE64_STRING_OPCIONAL>"]
    }
  ]
}
```

---

## 2. Inyección de Contexto Multimodal en el Prompt

Cuando un mensaje de usuario tiene registros asociados en la tabla `attachments`, el orquestador construye un bloque de contexto enriquecido que se antepone al mensaje del usuario:

```text
[ARCHIVOS ADJUNTOS EN ESTE MENSAJE]
1. Archivo: "informe_ventas.csv" (Tipo: document | MIME: text/csv)
Contenido extraído:
---
mes,ventas,region
Enero,14500,Norte
...
---

2. Archivo: "nota_voz_reunion.wav" (Tipo: audio | MIME: audio/wav)
Transcripción / Información de audio:
---
"Necesitamos priorizar el módulo de reportes para el viernes..."
---

[MENSAJE DEL USUARIO]
Analiza las ventas y dime si coinciden con lo mencionado en el audio.
```

---

## 3. El Separador `---FOLLOW_UP_OPTIONS---` y Fallback Automático por Código

### 3.1 Instrucción en el System Prompt
Todo prompt enviado a Ollama incluye la siguiente directiva obligatoria al final del `system` prompt (y un recordatorio al final del último mensaje `user` para modelos pequeños con poca atención al system prompt):

```text
REGLA OBLIGATORIA DE FORMATO:
Responde siempre en español (a menos que el usuario pida otro idioma).
Al terminar tu respuesta principal, DEBES escribir exactamente el separador en una línea nueva:
---FOLLOW_UP_OPTIONS---
Debajo de ese separador, escribe entre 2 y 3 preguntas o acciones cortas (máximo 80 caracteres cada una, una por línea, sin numeración pesada) que el usuario podría hacer a continuación para profundizar en el tema.

Ejemplo de final de respuesta:
...espero que esta explicación te sea útil.

---FOLLOW_UP_OPTIONS---
¿Puedes darme un ejemplo práctico en código?
¿Cuáles son las ventajas principales de este enfoque?
¿Cómo puedo optimizar su rendimiento?
```

### 3.2 Algoritmo de Extracción y Fallback Determinista (`parse_response_and_options`)

Dado que los modelos antiguos o pequeños pueden:
- Olvidar por completo escribir `---FOLLOW_UP_OPTIONS---`,
- Escribir una variante ligeramente alterada (como `--- FOLLOW_UP_OPTIONS ---`, `FOLLOW_UP_OPTIONS:`, `***FOLLOW_UP_OPTIONS***`), o
- Escribir menos de 2 opciones válidas,

el backend implementa la función `parse_response_and_options(raw_text: str, user_prompt: str) -> tuple[str, list[str]]` con **3 capas de seguridad**:

```mermaid
flowchart TD
    A["Respuesta cruda de Ollama (raw_text)"] --> B{"¿Contiene '---FOLLOW_UP_OPTIONS---' o variante regex?"}
    B -- Sí --> C["Dividir en main_content y raw_options_block"]
    B -- No --> D["main_content = raw_text.strip()"]
    C --> E["Limpiar viñetas (-, *, 1., •) y filtrar líneas entre 5 y 110 chars"]
    D --> F["Ejecutar Fallback Determinista Contextual"]
    E --> G{"¿Se obtuvieron >= 2 opciones?"}
    G -- Sí --> H["Tomar máximo 3 opciones (options[:3])"]
    G -- No --> F
    F --> I["Rellenar hasta tener entre 2 y 3 opciones contextuales"]
    I --> H
    H --> J["Retornar (main_content, follow_up_options)"]
```

#### Reglas Exactas del Parser y Fallback por Código:
1. **Detección Flexible con Regex**:
   Se busca el patrón `r"(?i)[-_*]{0,3}\s*FOLLOW[_\s-]*UP[_\s-]*OPTIONS\s*[-_*:]{0,3}"`.
2. **Limpieza de Opciones Extraídas**:
   Si se encuentra el separador:
   - `main_content` es todo el texto anterior al separador (`.strip()`).
   - Se procesa el texto posterior línea por línea, eliminando prefijos como `- `, `* `, `• `, `1. `, `2) `, comillas envolventes y líneas vacías.
3. **Fallback Automático por Código (Si no hay separador o hay < 2 opciones)**:
   Si tras el parseo la lista tiene menos de 2 elementos, el código genera opciones contextuales basadas en el mensaje del usuario y el contenido generado:
   - Si el mensaje involucra código o programación:
     1. `"Muéstrame un ejemplo práctico de código paso a paso"`
     2. `"¿Cómo puedo probar y depurar esta implementación?"`
     3. `"¿Qué buenas prácticas o mejoras recomiendas aplicar aquí?"`
   - Si el mensaje incluye documentos, datos o imágenes adjuntas:
     1. `"Haz un resumen ejecutivo con los puntos clave del archivo"`
     2. `"¿Qué conclusiones o acciones recomiendas a partir de esto?"`
     3. `"Explícame con más detalle el punto más importante"`
   - Para cualquier otro tema general (extrae el tema clave del `user_prompt`):
     1. `"Explícame este tema con un ejemplo práctico"`
     2. `"Haz un resumen en puntos clave fáciles de recordar"`
     3. `"¿Cuáles son los aspectos más avanzados sobre esto?"`
4. **Garantía de Contrato**: La función **nunca** devuelve menos de 2 ni más de 3 strings en `follow_up_options`, y el separador `---FOLLOW_UP_OPTIONS---` **nunca** queda visible dentro de `main_content`.

---

## 4. Flujo de Generación Dual para el Modo de Satisfacción A/B

### 4.1 Condiciones de Disparo
El Modo de Satisfacción A/B se activa cuando se cumple cualquiera de estas dos condiciones al recibir un mensaje del usuario en `POST /api/chats/{chat_id}/messages`:
1. **Automático cada 3 mensajes del usuario**: `user_message_count % 3 == 0` (es decir, en el mensaje #3, #6, #9, #12... del usuario dentro de ese chat).
2. **Manual por el usuario**: El usuario activó el botón **"Comparar 2 respuestas"** en la UI (`force_ab_test == True`).

### 4.2 Arquitectura del Flujo Dual (Candidata A vs Candidata B)

```mermaid
sequenceDiagram
    participant U as Usuario (Frontend)
    participant API as FastAPI Backend
    participant DB as SQLite (localgem.db)
    participant OL as Ollama (localhost:11434)

    U->>API: POST /api/chats/{id}/messages (content, files, force_ab_test)
    API->>DB: Guarda mensaje User y cuenta mensajes de usuario en el chat
    Note over API: Detecta user_msg_count % 3 == 0 o force_ab_test == True
    API->>OL: Llamada 1 (Prompt Candidata A: Concisa y Directa, temp=0.4)
    OL-->>API: Respuesta cruda A
    API->>OL: Llamada 2 (Prompt Candidata B: Detallada y Explicativa, temp=0.7)
    OL-->>API: Respuesta cruda B + ---FOLLOW_UP_OPTIONS---
    Note over API: Aplica parse_response_and_options a A y B
    API->>DB: Guarda Message (is_ab_test=True, candidate_a, candidate_b, selected_candidate=NULL)
    API-->>U: Devuelve assistant_message con candidate_a, candidate_b y follow_up_options
    U->>API: POST /api/messages/{msg_id}/select-candidate {"selected_candidate": "A" | "B"}
    API->>DB: Actualiza selected_candidate, content y crea registro en user_preferences
    API-->>U: Confirmación y preferencia guardada
```

*(Nota de rendimiento para hardware local: Las llamadas para la Candidata A y la Candidata B se ejecutan de forma secuencial en el backend porque Ollama en equipos locales procesa una inferencia a la vez en GPU/CPU; esto evita timeouts por encolamiento y reduce el consumo pico de RAM).*

### 4.3 Prompts Especializados para Candidata A y Candidata B

#### Prompt para **Respuesta A (Concisa / Directa)**:
```text
MODO DE ESTILO: CONCISO Y DIRECTO (CANDIDATA A).
Instrucciones estrictas:
- Ve directamente al grano en el primer párrafo.
- Usa respuestas breves, ejecutivas y listas con viñetas cortas si es necesario.
- Evita introducciones largas, rellenos o explicaciones teóricas extensas.
- Limita tu respuesta a lo esencial y accionable.
```

#### Prompt para **Respuesta B (Detallada / Explicativa)**:
```text
MODO DE ESTILO: DETALLADO Y EXPLICATIVO (CANDIDATA B).
Instrucciones estrictas:
- Proporciona una explicación completa, didáctica y bien estructurada con subtítulos en Markdown.
- Incluye contexto, el "por qué" detrás de cada concepto y ejemplos prácticos o analogías.
- Desglosa la respuesta paso a paso para que no quede ninguna duda.
- Al final de tu respuesta incluye el bloque ---FOLLOW_UP_OPTIONS--- con 3 opciones de seguimiento.
```

### 4.4 Aprendizaje de Preferencias del Usuario (`user_preferences`)
Para las respuestas normales (cuando `is_ab_test == False`), el orquestador consulta la tabla `user_preferences`:
- Si el usuario tiene más selecciones de tipo `"concise"` que `"detailed"`, se inyecta automáticamente en el `system` prompt:
  `"Preferencia aprendida del usuario: El usuario prefiere respuestas CONCISAS, directas y al grano."`
- Si el usuario tiene más selecciones de tipo `"detailed"`, se inyecta:
  `"Preferencia aprendida del usuario: El usuario prefiere respuestas DETALLADAS, estructuradas y con ejemplos explicativos."`
- Si aún no hay registros en `user_preferences` (o hay empate), se utiliza un estilo equilibrado por defecto.

---

## 5. Context Compactor — Gestión Inteligente del Historial Largo

> **Versión:** 1.1.0 — Inspirado en el mecanismo de compactación de Claude Code.  
> **Problema resuelto:** El truncado ciego de `MAX_HISTORY_MESSAGES = 10` elimina contexto crítico en chats largos. El compactor preserva la esencia de toda la conversación en un resumen inyectado como contexto del sistema.

### 5.1 Cuándo se activa y Configuración vía `.env`

El Context Compactor se activa **antes de construir el payload hacia Ollama** cuando se cumplen AMBAS condiciones:

1. El chat tiene más de `COMPACTION_THRESHOLD` mensajes totales (usuario + asistente), Y
2. El tamaño estimado del historial en tokens supera `TOKEN_BUDGET` tokens (estimado como `total_chars / 4`).

Todos los parámetros son configurables libremente a través de variables de entorno en el archivo `.env`:

| Variable de Entorno | Valor por Defecto | Descripción |
| :--- | :--- | :--- |
| `COMPACTION_THRESHOLD` | `14` | Mensajes mínimos en el chat para evaluar la compactación |
| `TOKEN_BUDGET` | `3200` | Umbral de tokens estimados del historial antes de disparar el resumen |
| `RECENT_WINDOW_AFTER_COMPACTION` | `4` | Cantidad de turnos recientes que se preservan íntegros tras compactar |
| `COMPACTOR_TEMPERATURE` | `0.2` | Temperatura baja para resumen determinista y sin alucinaciones |
| `COMPACTOR_MODEL` | *(vacío)* | Modelo opcional exclusivo para compactar (ej. `llama3.2:1b`). Si se omite, usa el modelo activo |

> **Nota de compatibilidad con hardware local:** El umbral por defecto de 3200 tokens deja margen seguro para el system prompt (~400 tokens), el mensaje actual del usuario (~500 tokens) y la respuesta del modelo (~2000 tokens), considerando que la mayoría de modelos en Ollama local usa `num_ctx = 4096`.

### 5.2 Algoritmo de Compactación

```mermaid
flowchart TD
    A["generate_assistant_reply() llamado"] --> B{"¿Historial supera\nCOMPACTION_THRESHOLD\ny TOKEN_BUDGET?"}
    B -- No --> G["Flujo normal\n(últimos 10 mensajes)"]
    B -- Sí --> C["Seleccionar mensajes ANTIGUOS\npara compactar\n(todos excepto los últimos 4)"]
    C --> D["¿chat.context_summary ya existe?"]
    D -- Sí --> E["Combinar resumen previo\n+ mensajes nuevos a compactar"]
    D -- No --> E2["Usar solo mensajes a compactar"]
    E --> F["Llamar a Ollama con\nPROMPT_COMPACTOR\n(temp=0.2, modelo liviano)"]
    E2 --> F
    F --> H["Guardar nuevo resumen\nen chats.context_summary\ny actualizar compacted_up_to_index"]
    H --> I["Construir historial final:\n[RESUMEN como mensaje system]\n+ últimos 4 mensajes reales"]
    I --> G
```

### 5.3 Prompt de Compactación (`PROMPT_COMPACTOR`)

El prompt que se envía a Ollama para generar el resumen del historial antiguo:

```text
TAREA DE COMPACTACIÓN DE CONTEXTO:
Eres un asistente de resumen técnico. A continuación encontrarás el historial de una conversación entre un usuario y un asistente de IA.

Tu misión es generar un resumen compacto en español que preserve:
1. Los temas principales discutidos (máximo 5 bullets).
2. Cualquier dato técnico específico mencionado (nombres de archivos, errores concretos, decisiones tomadas).
3. El contexto acumulado que el asistente necesita para responder coherentemente en los próximos turnos.

IMPORTANTE:
- NO incluyas saludos, metadiálogos ni frases de cortesía.
- Máximo 400 palabras.
- Formato: texto plano estructurado (sin Markdown).
- NO incluyas ---FOLLOW_UP_OPTIONS--- en tu respuesta.

HISTORIAL A COMPACTAR:
{history_block}
```

### 5.4 Inyección del Resumen en el Historial

Cuando el compactor ha generado un `context_summary`, el historial enviado a Ollama se construye así:

```python
# Estructura del payload messages[] hacia Ollama tras compactación:
[
  {"role": "system", "content": "<SYSTEM_PROMPT_NORMAL>"},
  {"role": "system", "content": (
      "[RESUMEN DE CONVERSACIÓN PREVIA — generado automáticamente]\n"
      f"{chat.context_summary}\n"
      "[FIN DEL RESUMEN — los mensajes siguientes son los más recientes]"
  )},
  # últimos 4 mensajes reales (los más recientes, NO compactados)
  {"role": "user",      "content": "..."},
  {"role": "assistant", "content": "..."},
  {"role": "user",      "content": "..."},
  {"role": "assistant", "content": "..."},
  # mensaje actual del usuario:
  {"role": "user", "content": "<mensaje_actual_con_adjuntos>"}
]
```

### 5.5 Persistencia del Resumen en SQLite

El resumen se persiste en la tabla `chats` (campos añadidos en `specs/02-database-and-api.md`):

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `context_summary` | `TEXT DEFAULT NULL` | Texto del resumen generado por Ollama |
| `compacted_up_to_index` | `INTEGER DEFAULT NULL` | Posición del último mensaje incluido en el resumen (para re-compactaciones incrementales) |

**Migración de base de datos existente:** Al arrancar, `init_db()` ejecuta automáticamente `ALTER TABLE IF NOT EXISTS` para añadir las columnas si `localgem.db` ya existe, sin destruir datos.

### 5.6 Respuestas de la API afectadas

`GET /api/chats/{chat_id}` añade al response:
```json
{
  "id": "...",
  "title": "...",
  "context_summary": "El usuario discutió la arquitectura limpia con FastAPI...",
  "is_context_compacted": true,
  "messages": [...]
}
```

---

## 6. Prompt Enhancer — Enriquecimiento Determinista de Mensajes

> **Versión:** 1.1.0  
> **Objetivo:** Transformar el mensaje crudo del usuario en un prompt semánticamente enriquecido que mejore la calidad de las respuestas de modelos pequeños, **sin llamadas extra a Ollama** (100% determinista, cero latencia adicional).

### 6.1 Qué es y qué NO es

| ✅ Es | ❌ NO es |
|-------|---------|
| Análisis heurístico del texto del usuario | Llamada extra a un LLM para reformular |
| Inyección de contexto de sesión estructurado | JSON Schema forzado en Ollama (incompatible con modelos pequeños) |
| Enriquecimiento del mensaje antes de enviarlo a Ollama | Modificación visible del mensaje en la UI |
| Mejora de calidad sin overhead de latencia | Replacement completo del mensaje original |

### 6.2 Estructura del Mensaje Enriquecido

La función `enhance_user_prompt()` añade un bloque de contexto estructurado **antes** del mensaje del usuario, sin modificar el contenido original:

```text
[CONTEXTO DE SESIÓN]
Turno de usuario #7 en este chat | Estilo preferido aprendido: CONCISO | Adjuntos en este turno: 1 PDF
Intención detectada: ANÁLISIS DE DATOS
──────────────────────────────────────

Dame un resumen de las ventas del Q3 del archivo adjunto
```

### 6.3 Clasificador de Intención Determinista

La función `classify_intent(user_text: str, has_attachments: bool) -> str` clasifica el mensaje en una de estas 6 categorías usando regex y keywords sin IA:

| Intención | Keywords / Patrones detectados | Ejemplo de mensaje |
|-----------|-------------------------------|-------------------|
| `GENERACIÓN_DE_CÓDIGO` | `código`, `función`, `implementa`, `escribe`, `crea una clase`, `bug`, `error` | "Escríbeme una función que..." |
| `ANÁLISIS_DE_DATOS` | Adjunto CSV/PDF + `analiza`, `resume`, `compara`, `gráfico`, `estadística` | "Analiza este CSV de ventas" |
| `EXPLICACIÓN_CONCEPTUAL` | `qué es`, `explícame`, `cómo funciona`, `diferencia entre`, `define` | "¿Qué es Clean Architecture?" |
| `COMPARACIÓN` | `vs`, `versus`, `diferencias`, `ventajas`, `compara`, `elige entre` | "SQLite vs PostgreSQL para..." |
| `TRADUCCIÓN_O_IDIOMA` | `traduce`, `en inglés`, `en francés`, `idioma` | "Traduce esto al inglés" |
| `GENERAL` | Cualquier otro mensaje | Cualquier consulta libre |

### 6.4 Implementación de `enhance_user_prompt()`

```python
def enhance_user_prompt(
    user_text: str,
    user_message_count: int,
    has_attachments: bool,
    dominant_style: str,   # "concise" | "detailed" | "balanced"
) -> str:
    """
    Enriquece el mensaje del usuario con contexto de sesión estructurado
    para mejorar la coherencia y calidad de modelos locales pequeños.
    No realiza ninguna llamada a Ollama. Puramente determinista.
    """
    intent = classify_intent(user_text, has_attachments)
    style_label = {
        "concise": "CONCISO (preferencia aprendida)",
        "detailed": "DETALLADO (preferencia aprendida)",
        "balanced": "EQUILIBRADO (sin preferencia aún)",
    }.get(dominant_style, "EQUILIBRADO")

    attachment_note = f" | Adjuntos: {has_attachments and 'Sí' or 'No'}"

    context_block = (
        f"[CONTEXTO DE SESIÓN]\n"
        f"Turno de usuario #{user_message_count} | Estilo: {style_label}{attachment_note}\n"
        f"Intención detectada: {intent}\n"
        f"{'─' * 40}\n\n"
    )
    return context_block + user_text.strip()
```

### 6.5 Integración en el Orquestador Principal

`enhance_user_prompt()` se llama **dentro de `generate_assistant_reply()`** justo antes de construir `build_ollama_messages_history()`, reemplazando `user_content` por la versión enriquecida:

```python
# En generate_assistant_reply():
enriched_content = enhance_user_prompt(
    user_text=user_content,
    user_message_count=user_message_count,
    has_attachments=has_attachments,
    dominant_style=get_user_style_preference(db)["dominant_style"],
)
# Se usa enriched_content en lugar de user_content para construir el payload
```

> **Nota:** El mensaje que se guarda en SQLite (`messages.content`) sigue siendo el texto **original** del usuario, no la versión enriquecida. La UI siempre muestra el mensaje limpio; el enriquecimiento es solo para Ollama.

