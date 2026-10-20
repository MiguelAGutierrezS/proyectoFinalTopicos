# 01 — Requisitos del Sistema en Formato EARS (Easy Approach to Requirements Syntax)

**Proyecto:** LocalGem Chat (Clon de Google Gemini 100% Local y Gratuito)  
**Versión:** 1.0.0  
**Estado:** Aprobado — Fuente Única de Verdad  

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
| **REQ-MULTI-01** | Ubiquitous | El sistema deberá permitir adjuntar múltiples archivos por mensaje soportando tres categorías: **Fotos** (`.png`, `.jpg`, `.jpeg`, `.webp`), **Documentos** (`.pdf`, `.txt`, `.csv`, `.md`) y **Audios** (`.mp3`, `.wav`, `.m4a`). |
| **REQ-MULTI-02** | Event-Driven | **CUANDO** el usuario seleccione o arrastre archivos válidos al compositor de mensajes, el sistema deberá mostrar chips de previsualización (miniatura para imágenes, icono y nombre para documentos/audios) con la opción de quitarlos antes de enviar. |
| **REQ-MULTI-03** | Event-Driven | **CUANDO** el backend reciba archivos adjuntos junto a un mensaje, el sistema deberá guardar cada archivo físico en el directorio local `backend/uploads/`, registrar su ruta en `attachments.local_path` y extraer su contenido textual o representación en `attachments.extracted_text`. |
| **REQ-MULTI-04** | Event-Driven | **CUANDO** se adjunte un documento `.pdf`, `.txt`, `.csv` o `.md`, el sistema deberá extraer su texto completo localmente y almacenarlo en `extracted_text` para inyectarlo en el contexto del prompt enviado a Ollama. |
| **REQ-MULTI-05** | Event-Driven | **CUANDO** se adjunte una foto (`.png`, `.jpg`, `.webp`), el sistema deberá codificar la imagen en Base64 para enviarla en el campo `images` de Ollama (si el modelo soporta visión) y además registrar los metadatos de la imagen (dimensiones, formato y nombre) en `extracted_text` como contexto de respaldo para modelos solo-texto. |
| **REQ-MULTI-06** | Event-Driven | **CUANDO** se adjunte un archivo de audio (`.mp3`, `.wav`, `.m4a`), el sistema deberá transcribir su contenido a texto localmente (o extraer metadatos acústicos/duración como fallback si el motor STT local no está instalado) y guardar el resultado en `extracted_text` para que la IA pueda responder sobre el audio. |
| **REQ-MULTI-07** | Unwanted Behavior | **SI** el usuario intenta subir un archivo con extensión no permitida o que supere el límite de 25 MB, **ENTONCES** el sistema deberá rechazar el archivo y mostrar una notificación clara indicando los formatos permitidos. |

---

## 4. Requisitos de Voz Bidireccional (`REQ-VOICE`)

| ID | Tipo EARS | Especificación del Requisito |
| :--- | :--- | :--- |
| **REQ-VOICE-01** | Event-Driven | **CUANDO** el usuario pulse el botón de micrófono ("Dictar por voz"), el sistema deberá iniciar el reconocimiento de voz en tiempo real en español (configurable al idioma del navegador) e insertar progresivamente la transcripción parcial y final en el campo de texto del mensaje. |
| **REQ-VOICE-02** | State-Driven | **MIENTRAS** el dictado por voz esté activo, el sistema deberá mostrar un indicador visual pulsante (estilo onda/pulso rojo) en el botón de micrófono permitiendo detener la captura con un clic adicional. |
| **REQ-VOICE-03** | Unwanted Behavior | **SI** el navegador no soporta Web Speech API (`SpeechRecognition`/`webkitSpeechRecognition`) o el permiso de micrófono es denegado, **ENTONCES** el sistema deberá mostrar un aviso amigable al usuario sin bloquear el resto de la interfaz. |
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
