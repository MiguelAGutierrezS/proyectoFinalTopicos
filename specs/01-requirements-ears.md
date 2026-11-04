# 01 — Requisitos del Sistema en Formato EARS (Easy Approach to Requirements Syntax)

**Proyecto:** LocalGem Chat (Clon de Google Gemini 100% Local y Gratuito)  
**Versión:** 2.1.0  
**Estado:** Aprobado — Fuente Única de Verdad (Incluye Vision Bridge Multimodal, Skills `SKILL.md`, MCP Local y Orquestación Agéntica con LangGraph)  

---

## 1. Introducción y Glosario EARS

Este documento define los requisitos funcionales y no funcionales de **LocalGem Chat** utilizando la sintaxis **EARS (Easy Approach to Requirements Syntax)** para eliminar ambigüedades:

- **Ubiquitous (Ubicuos):** `El sistema deberá <respuesta del sistema>.` (Siempre activos).
- **Event-Driven (Dirigidos por Eventos):** `CUANDO <evento desencadenante>, el sistema deberá <respuesta del sistema>.`
- **State-Driven (Dirigidos por Estado):** `MIENTRAS <estado activo>, el sistema deberá <respuesta del sistema>.`
- **Unwanted Behavior (Comportamiento No Deseado / Excepciones):** `SI <condición de fallo>, ENTONCES el sistema deberá <respuesta de mitigación>.`
- **Complex (Complejos):** Combinación de `MIENTRAS` + `CUANDO`.

---

## 2. Requisitos de Gestión y Persistencia de Chats (`REQ-CHAT`)

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-CHAT-01** | Ubiquitous | El sistema deberá almacenar de forma persistente todas las sesiones de conversación, mensajes, adjuntos y preferencias en una base de datos SQLite local llamada `localgem.db`. |
| **REQ-CHAT-02** | Event-Driven | **CUANDO** el usuario haga clic en el botón "Nuevo Chat" (o envíe un mensaje sin tener un chat activo), el sistema deberá crear un nuevo registro en la tabla `chats`, limpiar el área de conversación principal y seleccionarlo como chat activo. |
| **REQ-CHAT-03** | Event-Driven | **CUANDO** se envíe el primer mensaje de usuario en un chat cuyo título sea el valor por defecto (`"Nuevo Chat"`), el sistema deberá actualizar automáticamente el `title` del chat utilizando los primeros 45 caracteres significativos del mensaje (o un resumen corto) y actualizar `updated_at`. |
| **REQ-CHAT-04** | Event-Driven | **CUANDO** el usuario inicie o recargue la aplicación, el sistema deberá consultar el historial de chats ordenados por `updated_at` descendente y mostrarlos en la barra lateral izquierda. |
| **REQ-CHAT-05** | Event-Driven | **CUANDO** el usuario seleccione un chat anterior en la barra lateral, el sistema deberá recuperar y renderizar todos sus mensajes en orden cronológico (`created_at` ascendente), incluyendo sus archivos adjuntos, opciones de seguimiento y estado de pruebas A/B. |
| **REQ-CHAT-06** | Event-Driven | **CUANDO** el usuario solicite eliminar un chat del historial, el sistema deberá eliminar el registro de `chats`, sus `messages`, sus `attachments` asociados en cascada y borrar los archivos físicos correspondientes del disco local. |

---

## 3. Requisitos de Entrada Multimodal (`REQ-MULTI`)

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-MULTI-01** | Ubiquitous | El sistema deberá permitir adjuntar múltiples archivos por mensaje soportando tres categorías: **Fotos** (`.png`, `.jpg`, `.jpeg`, `.webp`), **Documentos** (`.pdf`, `.txt`, `.csv`, `.md`) y **Audios** (`.mp3`, `.wav`, `.m4a`, `.ogg`). |
| **REQ-MULTI-02** | Event-Driven | **CUANDO** el usuario seleccione o arrastre archivos válidos al compositor de mensajes, el sistema deberá mostrar chips de previsualización (miniatura para imágenes, icono y nombre para documentos/audios) con la opción de quitarlos antes de enviar. |
| **REQ-MULTI-03** | Event-Driven | **CUANDO** el backend reciba archivos adjuntos junto a un mensaje, el sistema deberá guardar cada archivo físico en el directorio local `backend/uploads/`, registrar su ruta en `attachments.local_path` y extraer su contenido textual o representación en `attachments.extracted_text`. |
| **REQ-MULTI-04** | Event-Driven | **CUANDO** se adjunte un documento `.pdf`, `.txt`, `.csv` o `.md`, el sistema deberá extraer su texto completo localmente y almacenarlo en `extracted_text` para inyectarlo en el contexto del prompt enviado a Ollama. |
| **REQ-MULTI-05** | Event-Driven | **CUANDO** se adjunte una foto (`.png`, `.jpg`, `.jpeg`, `.webp`), el sistema deberá redimensionarla de forma segura ($\le 1024\text{px}$), codificarla en Base64 y ejecutar automáticamente el **Vision Bridge (Pipeline de Visión en 2 Etapas)**: invocar un modelo de visión instalado en Ollama (`moondream`, `llava`, `minicpm-v`, etc.) mediante un prompt limpio en `/api/generate` para extraer la descripción visual completa y texto visible (OCR), persistiendo tanto los metadatos técnicos de Pillow como el análisis visual en `attachments.extracted_text`. |
| **REQ-MULTI-06** | Event-Driven | **CUANDO** se adjunte un archivo de audio (`.mp3`, `.wav`, `.m4a`, `.ogg`), el sistema deberá transcribir su contenido a texto localmente usando `faster-whisper` configurado con caché local libre de symlinks (`backend/models_cache/whisper`) para evitar errores de privilegios en Windows (`WinError 1314`), guardando la transcripción en `extracted_text`. |
| **REQ-MULTI-07** | Unwanted Behavior | **SI** el usuario intenta subir un archivo con extensión no permitida o que supere el límite de 25 MB, **ENTONCES** el sistema deberá rechazar el archivo y mostrar una notificación clara indicando los formatos permitidos. |
| **REQ-MULTI-08** | Complex | **MIENTRAS** una consulta incluya imágenes adjuntas (o el usuario seleccione un modelo de visión ligero como `moondream` que no sigue instrucciones complejas en español), **CUANDO** se genere la respuesta del asistente, el orquestador deberá utilizar el análisis visual extraído por el modelo de visión y delegar la redacción final en español, el formato Markdown, el Modo A/B y el bloque `---FOLLOW_UP_OPTIONS---` al modelo de lenguaje principal (`llama3.2` / `llama3.2:1b`), garantizando respuestas fluidas sin importar qué modelo esté seleccionado en la UI. |
| **REQ-MULTI-09** | Event-Driven | **CUANDO** el usuario pegue una imagen desde el portapapeles (`Ctrl+V`) o pulse el botón de grabación de nota de voz `.wav` en el compositor, el sistema deberá capturar el recurso en el navegador y adjuntarlo como un archivo multimodal estándar listo para ser procesado por el backend. |

---

## 4. Requisitos de Voz Bidireccional (`REQ-VOICE`)

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-VOICE-01** | Event-Driven | **CUANDO** el usuario pulse el botón de micrófono ("Dictar por voz"), el sistema deberá iniciar el reconocimiento de voz en tiempo real en español (configurable al idioma del navegador) e insertar progresivamente la transcripción parcial y final en el campo de texto del mensaje. |
| **REQ-VOICE-02** | State-Driven | **MIENTRAS** el dictado por voz esté activo, el sistema deberá mostrar un indicador visual pulsante (estilo onda/pulso rojo) en el botón de micrófono permitiendo detener la captura con un clic adicional. |
| **REQ-VOICE-03** | Unwanted Behavior | **SI** el navegador no soporta Web Speech API (`SpeechRecognition`/`webkitSpeechRecognition`) o el permiso de micrófono es denegado, **ENTONCES** el sistema deberá mostrar un aviso amigable al usuario sin bloquear el resto de la interfaz, permitiendo usar el grabador de notas de voz `.wav` nativo. |
| **REQ-VOICE-04** | Ubiquitous | El sistema deberá incluir un botón de lectura en voz alta ("Escuchar respuesta" / TTS) en cada mensaje generado por la IA (incluyendo ambas tarjetas candidatas A y B en el modo A/B). |
| **REQ-VOICE-05** | Event-Driven | **CUANDO** el usuario pulse el botón de lectura en voz alta (TTS) en una respuesta de la IA, el sistema deberá limpiar la sintaxis Markdown decorativa y leer el contenido utilizando `window.speechSynthesis` con una voz en español natural. |
| **REQ-VOICE-06** | State-Driven | **MIENTRAS** una respuesta se esté leyendo en voz alta, el sistema deberá cambiar el icono del botón a "Detener lectura" y permitir cancelar o pausar la síntesis de voz inmediatamente al hacer clic. |

---

## 5. Requisitos de Opciones de Seguimiento (`REQ-FOLLOW`)

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-FOLLOW-01** | Ubiquitous | Al final de **CADA** respuesta de la IA, el sistema deberá generar, almacenar en `messages.follow_up_options_json` y mostrar en la interfaz entre **2 y 3 opciones clicables** de continuación relevantes al contexto. |
| **REQ-FOLLOW-02** | Event-Driven | **CUANDO** el backend construya el prompt hacia Ollama, el sistema deberá instruir al modelo para que incluya el separador exacto `---FOLLOW_UP_OPTIONS---` al final de su respuesta seguido de 2 o 3 sugerencias en líneas separadas. |
| **REQ-FOLLOW-03** | Unwanted Behavior | **SI** un modelo pequeño o antiguo de Ollama olvida incluir el separador `---FOLLOW_UP_OPTIONS---` o genera menos de 2 opciones válidas, **ENTONCES** el sistema deberá ejecutar automáticamente un generador de fallback determinista en el backend que produzca entre 2 y 3 opciones contextuales sin fallar. |
| **REQ-FOLLOW-04** | Event-Driven | **CUANDO** el usuario haga clic en cualquiera de las opciones de seguimiento mostradas debajo de un mensaje de la IA, el sistema deberá enviar inmediatamente el texto de esa opción como un nuevo mensaje del usuario en el chat actual. |

---

## 6. Requisitos del Modo de Satisfacción A/B (`REQ-AB`)

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-AB-01** | Event-Driven | **CUANDO** el número total de mensajes enviados por el usuario en el chat actual sea múltiplo exacto de 3 (`conteo_mensajes_usuario % 3 == 0`), el sistema deberá activar automáticamente el **Modo de Satisfacción A/B** para esa respuesta (`is_ab_test = true`). |
| **REQ-AB-02** | Event-Driven | **CUANDO** el usuario active manualmente el botón **"Comparar 2 respuestas"** en la barra de entrada antes de enviar un mensaje, el sistema deberá forzar la activación del **Modo de Satisfacción A/B** (`is_ab_test = true`) independientemente del contador de mensajes. |
| **REQ-AB-03** | State-Driven | **MIENTRAS** una petición se procese en **Modo de Satisfacción A/B**, el sistema deberá generar 2 respuestas candidatas distintas desde Ollama: **Respuesta A** (estilo conciso, directo y ejecutivo) y **Respuesta B** (estilo detallado, explicativo, con ejemplos y desglose paso a paso), guardándolas en `messages.candidate_a` y `messages.candidate_b`. |
| **REQ-AB-04** | State-Driven | **MIENTRAS** un mensaje con `is_ab_test = true` no tenga un `selected_candidate` elegido (`NULL`), el sistema deberá mostrar en el frontend una vista comparativa lado a lado (en escritorio) o apilada (en móvil) con ambas tarjetas (**Respuesta A — Concisa** vs **Respuesta B — Detallada**) y un botón **"Prefiero esta respuesta"** en cada una. |
| **REQ-AB-05** | Event-Driven | **CUANDO** el usuario seleccione su candidata preferida (`"A"` o `"B"`), el sistema deberá: (1) actualizar `messages.selected_candidate` con `"A"` o `"B"`, (2) establecer `messages.content` con el texto de la candidata ganadora, (3) registrar la preferencia en la tabla `user_preferences` (`preferred_style = "concise"` para A o `"detailed"` para B, vinculada a `message_id`), y (4) mostrar las opciones de seguimiento correspondientes. |
| **REQ-AB-06** | Ubiquitous | El sistema deberá consultar las preferencias históricas de `user_preferences` para adaptar el tono por defecto de las respuestas estándar (no A/B) al estilo favorito del usuario (`concise` o `detailed`). |

---

## 7. Nuevos Requisitos de Interfaz y Experiencia (`REQ-UI`)

> **Versión:** 1.1.0 — Añadidos tras análisis de brechas entre especificación e implementación (2026-10-27).

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-UI-01** | Event-Driven | **CUANDO** el usuario haga doble clic sobre el título de un chat en la barra lateral izquierda, el sistema deberá convertir el texto en un campo de texto editable (`<input>`) inline, permitiendo modificar el título y confirmarlo con `Enter` o perder el foco (`blur`), invocando `PATCH /api/chats/{chat_id}` con el nuevo título. |
| **REQ-UI-02** | Unwanted Behavior | **SI** el usuario deja el campo de edición de título vacío o con solo espacios en blanco y confirma, **ENTONCES** el sistema deberá revertir el título al valor anterior sin llamar al backend. |
| **REQ-UI-03** | Event-Driven | **CUANDO** el usuario arrastre y suelte (`drag-and-drop`) uno o más archivos válidos sobre el área del compositor de mensajes (`MultimodalInputBar`), el sistema deberá comportarse exactamente igual que si hubiera seleccionado esos archivos mediante el botón `+`, mostrando los chips de previsualización y rechazando los archivos no permitidos o que superen 25 MB. |
| **REQ-UI-04** | State-Driven | **MIENTRAS** el usuario arrastra archivos sobre el compositor, el sistema deberá mostrar un indicador visual de zona de destino activa (borde resaltado en azul/púrpura con mensaje "Suelta aquí tus archivos") que desaparece al soltar o al alejar el cursor. |
| **REQ-UI-05** | Ubiquitous | El sistema deberá aplicar **syntax highlighting** a todos los bloques de código ` ``` ` dentro de las respuestas de la IA, usando la librería `react-syntax-highlighter` con un tema oscuro compatible con el diseño (ej. `oneDark` o `atomDark`), diferenciando visualmente el lenguaje del bloque cuando el modelo lo especifique. |
| **REQ-UI-06** | Event-Driven | **CUANDO** el usuario haga clic en el botón **"Copiar"** que aparece al hacer hover sobre cualquier bloque de código en una respuesta de la IA, el sistema deberá copiar el contenido del bloque al portapapeles (`navigator.clipboard.writeText`) y mostrar un estado visual de confirmación ("¡Copiado!") durante 2 segundos. |
| **REQ-UI-07** | Ubiquitous | El sistema deberá incluir un archivo `README.md` en la raíz del repositorio con instrucciones claras de instalación, prerrequisitos (Python 3.10+, Node.js 18+, Ollama, ffmpeg) y cómo arrancar el proyecto con `start-localgem.bat` (Windows) o `start-localgem.sh` (Unix). |

---

## 8. Requisitos del Sistema de Skills Modulares (`REQ-SKILL`)

> **Versión:** 2.0.0 — Sistema de habilidades modulares basado en archivos `SKILL.md` con frontmatter YAML.

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-SKILL-01** | Ubiquitous | El sistema deberá descubrir y cargar automáticamente las habilidades modulares (*Skills*) almacenadas en `backend/skills/<skill_id>/SKILL.md`, parseando su frontmatter YAML (`id`, `name`, `description`, `icon`, `triggers`, `category`) y su cuerpo de instrucciones Markdown. |
| **REQ-SKILL-02** | Ubiquitous | El sistema deberá incluir al menos 4 Skills preinstaladas listas para producción: `code-architect` (Arquitecto de Software), `data-analyst` (Analista de Datos CSV/PDF), `academic-tutor` (Tutor Universitario) y `sql-specialist` (Especialista en SQL y Bases de Datos). |
| **REQ-SKILL-03** | Event-Driven | **CUANDO** el usuario seleccione manualmente una Skill en la interfaz (o escriba un comando `/skill`) antes de enviar un mensaje, el orquestador deberá inyectar las directivas expertas del `SKILL.md` correspondiente en el System Prompt y registrar el identificador de la Skill en `messages.active_skill`. |
| **REQ-SKILL-04** | Event-Driven | **CUANDO** el usuario envíe un mensaje con el modo de **Auto-Skill** activado (sin haber forzado una Skill específica) y el texto o adjuntos coincidan con los `triggers` léxicos de una Skill, el sistema deberá activar automáticamente dicha Skill e indicarlo visualmente en la tarjeta de respuesta de la IA. |
| **REQ-SKILL-05** | Event-Driven | **CUANDO** el usuario cree o guarde una nueva Skill personalizada desde la API (`POST /api/skills`), el sistema deberá generar el archivo `backend/skills/<skill_id>/SKILL.md` en disco y dejarla inmediatamente disponible en el catálogo. |

---

## 9. Requisitos de Integración con Model Context Protocol (`REQ-MCP`)

> **Versión:** 2.0.0 — Soporte nativo para herramientas MCP locales y servidores MCP externos con enrutamiento híbrido resiliente para modelos pequeños en Ollama.

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-MCP-01** | Ubiquitous | El sistema deberá contar con un motor **MCP (Model Context Protocol)** local (`backend/services/mcp_service.py`) que exponga un catálogo estandarizado de herramientas (`tools/list`) y un ejecutor seguro (`tools/call`), soportando tanto herramientas MCP nativas como servidores MCP externos configurables. |
| **REQ-MCP-02** | Ubiquitous | El sistema deberá proveer de serie 5 herramientas MCP locales verificables sin requerir claves de API de pago: `mcp_system_time` (fecha, hora y diagnóstico de entorno), `mcp_calculator` (evaluador matemático y estadístico exacto), `mcp_sqlite_inspector` (consulta de métricas reales e inspección solo-lectura de `localgem.db`), `mcp_workspace_reader` (exploración y lectura segura de archivos del proyecto/subidas) y `mcp_wikipedia_search` (búsqueda enciclopédica verificada). |
| **REQ-MCP-03** | Event-Driven | **CUANDO** el usuario envíe un mensaje con MCP habilitado (`enable_mcp = true`), el **Router Híbrido MCP** deberá detectar si la consulta requiere datos en tiempo real, cálculo exacto, inspección de base de datos, lectura de archivos o búsqueda externa, ejecutar las herramientas MCP correspondientes e inyectar sus resultados estructurados en el bloque `[RESULTADOS VERIFICADOS DE HERRAMIENTAS MCP]` del prompt enviado a Ollama. |
| **REQ-MCP-04** | Ubiquitous | El sistema deberá persistir las trazas de todas las herramientas MCP invocadas en cada turno dentro de `messages.mcp_calls_json` (incluyendo `tool_name`, `arguments`, `result_preview`, `status` y `duration_ms`) y mostrarlas como insignias (*badges*) interactivas en el mensaje del asistente en el frontend. |
| **REQ-MCP-05** | Unwanted Behavior | **SI** la ejecución de una herramienta MCP falla o excede el tiempo máximo de espera (8 segundos), **ENTONCES** el sistema deberá capturar la excepción, registrar el estado de error en la traza MCP y permitir que el modelo de Ollama responda normalmente sin interrumpir la conversación. |

---

## 10. Requisitos de Orquestación Agéntica con LangGraph (`REQ-GRAPH`)

> **Versión:** 2.1.0 — Orquestación basada en máquina de estados finitos (`StateGraph`) mediante LangGraph (`specs/04-langgraph-architecture.md`).

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-GRAPH-01** | Ubiquitous | El sistema deberá orquestar todo el flujo de generación de respuestas del asistente mediante un grafo de estados compilado con **LangGraph** (`StateGraph(LocalGemGraphState)`) definido en `backend/services/langgraph_service.py`. |
| **REQ-GRAPH-02** | Ubiquitous | El grafo `StateGraph` deberá estructurarse en nodos modulares con responsabilidad única: `node_load_context`, `node_skill_router`, `node_mcp_executor`, `node_vision_bridge`, `node_context_compactor`, `node_prompt_builder`, `node_generate_standard`, `node_generate_ab` y `node_parse_and_fallback`. |
| **REQ-GRAPH-03** | Event-Driven | **CUANDO** el grafo evalúe las aristas condicionales de un turno (`route_mcp_check`, `route_vision_check`, `route_compaction_check` y `route_generation_mode`), el sistema deberá decidir dinámicamente qué nodos especializados ejecutar sin invocar pasos innecesarios. |
| **REQ-GRAPH-04** | Ubiquitous | Cada nodo ejecutado dentro del `StateGraph` deberá registrar en `state["graph_trace"]` su nombre (`node`), estado (`ok`, `skipped`, `fallback` o `error`), duración en milisegundos (`duration_ms`) y detalle operativo para fines de auditoría y observabilidad. |
| **REQ-GRAPH-05** | Event-Driven | **CUANDO** el cliente consulte `GET /api/graph/schema`, el sistema deberá devolver la topología completa del `StateGraph` de LangGraph, incluyendo la lista de nodos y su definición en formato **Mermaid** (`flowchart TD`) para su inspección visual. |
| **REQ-GRAPH-06** | Unwanted Behavior | **SI** cualquier nodo intermedio del grafo (`node_mcp_executor`, `node_vision_bridge` o `node_context_compactor`) sufre una excepción en tiempo de ejecución, **ENTONCES** el nodo deberá capturar el fallo, registrar `status = "fallback"` en `graph_trace` y permitir que el grafo continúe hacia la generación y el parser final sin abortar la respuesta al usuario. |

