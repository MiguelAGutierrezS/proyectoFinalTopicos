import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Message, UserPreference
from services.multimodal_processor import ProcessedAttachment, load_image_as_base64

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_FALLBACK_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.2:latest")
MAX_HISTORY_MESSAGES = 10
FOLLOW_UP_SEPARATOR = "---FOLLOW_UP_OPTIONS---"

# Regex tolerante a variaciones que suelen producir modelos pequeños o antiguos
SEPARATOR_REGEX = re.compile(
    r"(?i)(?:^|\n)\s*[-_*=#]{0,4}\s*FOLLOW[_\s-]*UP[_\s-]*OPTIONS\s*[-_*=#]{0,4}\s*:?\s*(?:\n|$)"
)


@dataclass
class OrchestrationResult:
    """Resultado completo generado por el orquestador de IA local."""

    content: str
    follow_up_options: List[str]
    is_ab_test: bool = False
    candidate_a: Optional[str] = None
    candidate_b: Optional[str] = None
    model_used: str = DEFAULT_FALLBACK_MODEL


# =====================================================================
# 1. Descubrimiento y Listado de Modelos Locales en Ollama (/api/tags)
# =====================================================================


async def list_ollama_models() -> Tuple[List[Dict[str, Any]], bool]:
    """
    Consulta `GET http://localhost:11434/api/tags` para obtener los modelos instalados localmente.
    Retorna `(lista_de_modelos, ollama_reachable)`.
    """
    url = f"{OLLAMA_BASE_URL}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            raw_models = data.get("models", [])
            models: List[Dict[str, Any]] = []
            for item in raw_models:
                name = item.get("name") or item.get("model")
                if name:
                    models.append(
                        {
                            "name": str(name),
                            "size": item.get("size"),
                            "modified_at": item.get("modified_at"),
                        }
                    )
            return models, True
    except Exception as exc:
        logger.warning("No se pudo conectar con Ollama en %s: %s", url, exc)
        return [], False


async def resolve_active_model(requested_model: Optional[str] = None) -> Tuple[Optional[str], bool]:
    """
    Determina qué modelo usar en Ollama:
    - Si el usuario especificó un modelo válido instalado, lo usa.
    - Si no especificó ninguno (o el especificado no está instalado), selecciona el primero disponible en `/api/tags`.
    - Retorna `(nombre_modelo_o_None, ollama_reachable)`.
    """
    models, reachable = await list_ollama_models()
    if not reachable:
        return None, False

    installed_names = [m["name"] for m in models]
    if not installed_names:
        return None, True

    if requested_model:
        cleaned = requested_model.strip()
        if cleaned in installed_names:
            return cleaned, True
        # Coincidencia parcial sin tag (ej. "llama3.2" coincide con "llama3.2:latest")
        for name in installed_names:
            if name.split(":")[0].lower() == cleaned.split(":")[0].lower():
                return name, True

    return installed_names[0], True


# =====================================================================
# 2. Preferencias Aprendidas del Usuario (`user_preferences`)
# =====================================================================


def get_user_style_preference(db: Session) -> Dict[str, Any]:
    """
    Consulta la tabla `user_preferences` para determinar si el usuario prefiere
    históricamente respuestas concisas ('concise' / A) o detalladas ('detailed' / B).
    """
    concise_count = (
        db.query(func.count(UserPreference.id))
        .filter(UserPreference.preferred_style == "concise")
        .scalar()
        or 0
    )
    detailed_count = (
        db.query(func.count(UserPreference.id))
        .filter(UserPreference.preferred_style == "detailed")
        .scalar()
        or 0
    )
    total = concise_count + detailed_count

    if concise_count > detailed_count:
        dominant = "concise"
    elif detailed_count > concise_count:
        dominant = "detailed"
    else:
        dominant = "balanced"

    return {
        "total_ab_selections": total,
        "concise_count": concise_count,
        "detailed_count": detailed_count,
        "dominant_style": dominant,
    }


def build_style_instruction_from_preferences(db: Session) -> str:
    """Construye la instrucción de estilo adaptativo basada en el historial de `user_preferences`."""
    summary = get_user_style_preference(db)
    dominant = summary["dominant_style"]

    if dominant == "concise":
        return (
            "PREFERENCIA APRENDIDA DEL USUARIO: El usuario ha demostrado preferir respuestas "
            "CONCISAS, directas, ejecutivas y al grano (Estilo A). Prioriza la brevedad y claridad."
        )
    if dominant == "detailed":
        return (
            "PREFERENCIA APRENDIDA DEL USUARIO: El usuario ha demostrado preferir respuestas "
            "DETALLADAS, profundas, bien estructuradas con ejemplos prácticos y explicaciones paso a paso (Estilo B)."
        )
    return (
        "PREFERENCIA DE ESTILO: Utiliza un estilo equilibrado, claro, amigable y bien estructurado en Markdown."
    )


# =====================================================================
# 3. Extracción de `---FOLLOW_UP_OPTIONS---` y Fallback Automático
# =====================================================================


def extract_topic_snippet(user_prompt: str) -> str:
    """Extrae una frase corta representativa del mensaje del usuario para personalizar opciones fallback."""
    cleaned = re.sub(r"\s+", " ", (user_prompt or "").strip())
    # Eliminar signos iniciales o comandos comunes
    cleaned = re.sub(r"^(?:por favor|puedes|podrías|dime|explícame|explicame|qué es|que es)\s+", "", cleaned, flags=re.I)
    cleaned = cleaned.strip("¿?¡!.,:;\"' ")
    if not cleaned:
        return "este tema"
    words = cleaned.split()
    snippet = " ".join(words[:5])
    if len(snippet) > 38:
        snippet = snippet[:38].rstrip()
    return snippet


def generate_fallback_follow_up_options(
    user_prompt: str,
    clean_response: str = "",
    has_attachments: bool = False,
) -> List[str]:
    """
    Generador determinista de 3 opciones contextuales cuando un modelo antiguo o pequeño
    olvida incluir `---FOLLOW_UP_OPTIONS---` o devuelve menos de 2 opciones válidas.
    Garantiza que la interfaz SIEMPRE muestre 3 opciones clicables relevantes.
    """
    combined_lower = f"{user_prompt} {clean_response[:400]}".lower()

    if has_attachments or any(
        kw in combined_lower
        for kw in ("archivo", "documento", "pdf", "csv", "imagen", "foto", "audio", "adjunto", "tabla")
    ):
        return [
            "Haz un resumen ejecutivo con los puntos clave",
            "¿Qué conclusiones o acciones prácticas recomiendas?",
            "Explícame paso a paso el detalle más importante",
        ]

    if any(
        kw in combined_lower
        for kw in (
            "código",
            "codigo",
            "python",
            "javascript",
            "typescript",
            "react",
            "fastapi",
            "sql",
            "función",
            "error",
            "bug",
            "api",
            "algoritmo",
        )
    ):
        return [
            "Explícame esto paso a paso con un ejemplo práctico",
            "¿Cómo puedo optimizar o probar este código?",
            "¿Qué alternativas o buenas prácticas existen?",
        ]

    topic = extract_topic_snippet(user_prompt)
    if topic and topic != "este tema" and len(topic) >= 3:
        return [
            f"Explícame {topic} paso a paso",
            f"Dame un ejemplo práctico sobre {topic}",
            "¿Qué alternativas o enfoques existen?",
        ]

    return [
        "Explícame esto paso a paso",
        "Dame un ejemplo práctico",
        "¿Qué alternativas existen?",
    ]


def _clean_option_line(line: str) -> str:
    """Limpia numeración, viñetas, guiones y comillas de una línea de opción de seguimiento."""
    cleaned = line.strip()
    cleaned = re.sub(r"^(?:[-*•‣⁃]|\d+[.)]|\[[0-9a-zA-Z]\]|Opción\s*\d+\s*:?)\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.strip("\"'`«» ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def parse_response_and_options(
    raw_text: str,
    user_prompt: str,
    has_attachments: bool = False,
) -> Tuple[str, List[str]]:
    """
    Separa la respuesta limpia de las opciones de seguimiento ubicadas tras `---FOLLOW_UP_OPTIONS---`.
    Si el modelo local olvida el separador o genera menos de 2 opciones válidas,
    completa automáticamente hasta tener exactamente 3 opciones contextuales.
    """
    if not raw_text or not raw_text.strip():
        fallback = generate_fallback_follow_up_options(user_prompt, "", has_attachments)
        return "No se recibió texto del modelo local.", fallback

    text = raw_text.strip()
    extracted_options: List[str] = []
    main_content = text

    if FOLLOW_UP_SEPARATOR in text:
        parts = text.split(FOLLOW_UP_SEPARATOR, 1)
        main_content = parts[0].strip()
        raw_options_block = parts[1].strip()
    else:
        match = SEPARATOR_REGEX.search(text)
        if match:
            main_content = text[: match.start()].strip()
            raw_options_block = text[match.end() :].strip()
        else:
            raw_options_block = ""

    if raw_options_block:
        for raw_line in raw_options_block.splitlines():
            candidate = _clean_option_line(raw_line)
            # Filtramos líneas demasiado cortas, demasiado largas o que sean encabezados vacíos
            if 5 <= len(candidate) <= 110 and not candidate.lower().startswith("aquí tienes"):
                if candidate not in extracted_options:
                    extracted_options.append(candidate)

    # Si el modelo olvidó el separador o generó menos de 3 opciones, rellenamos con el fallback contextual
    if len(extracted_options) < 3:
        fallback_options = generate_fallback_follow_up_options(
            user_prompt=user_prompt,
            clean_response=main_content,
            has_attachments=has_attachments,
        )
        for fb in fallback_options:
            if len(extracted_options) >= 3:
                break
            if fb.lower() not in {opt.lower() for opt in extracted_options}:
                extracted_options.append(fb)

    return main_content, extracted_options[:3]


# =====================================================================
# 4. Construcción de Prompts y Contexto Multimodal
# =====================================================================


def build_system_prompt(style_directive: str) -> str:
    """Construye el System Prompt completo incluyendo la regla obligatoria de `---FOLLOW_UP_OPTIONS---`."""
    return (
        "Eres LocalGem, un asistente de inteligencia artificial multimodal 100% local, "
        "inspirado en Google Gemini. Respondes siempre en español claro, preciso y bien formateado en Markdown.\n\n"
        f"{style_directive}\n\n"
        "REGLA OBLIGATORIA DE OPCIONES DE SEGUIMIENTO:\n"
        "Al final de CADA respuesta, después de terminar tu explicación principal, DEBES escribir "
        f"en una línea nueva exactamente el separador:\n{FOLLOW_UP_SEPARATOR}\n"
        "Y justo debajo escribe 3 opciones cortas (una por línea, sin viñetas ni numeración, máximo 75 caracteres) "
        "que el usuario pueda hacer clic para continuar la conversación.\n\n"
        "Ejemplo del formato final obligatorio:\n"
        "Espero que esta información te sea de utilidad.\n\n"
        f"{FOLLOW_UP_SEPARATOR}\n"
        "Explícame esto paso a paso\n"
        "Dame un ejemplo práctico\n"
        "¿Qué alternativas existen?"
    )


def format_user_message_with_attachments(
    content: str,
    attachments_info: List[Dict[str, str]],
    include_separator_reminder: bool = True,
) -> str:
    """
    Combina el texto del usuario con el texto extraído/transcrito de sus archivos adjuntos
    y añade un recordatorio ligero del separador para modelos pequeños.
    """
    blocks: List[str] = []

    if attachments_info:
        blocks.append("[ARCHIVOS MULTIMODALES ADJUNTOS EN ESTE MENSAJE]")
        for idx, att in enumerate(attachments_info, start=1):
            blocks.append(
                f"{idx}. Archivo: \"{att.get('file_name', 'adjunto')}\" "
                f"(Categoría: {att.get('file_type', 'document')} | MIME: {att.get('mime_type', '')})\n"
                f"Contenido / Contexto extraído:\n---\n{att.get('extracted_text', '')}\n---"
            )
        blocks.append("")

    user_text = (content or "").strip()
    if not user_text and attachments_info:
        user_text = "Analiza los archivos adjuntos, explica su contenido y destaca los puntos más importantes."

    blocks.append(user_text)

    if include_separator_reminder:
        blocks.append(
            f"\n\n(Recuerda incluir al final de tu respuesta una línea con {FOLLOW_UP_SEPARATOR} "
            "seguida de 3 opciones cortas de continuación en líneas separadas)."
        )

    return "\n".join(blocks).strip()


def build_ollama_messages_history(
    history_messages: List[Message],
    current_user_content: str,
    current_attachments: List[ProcessedAttachment],
    system_prompt: str,
) -> List[Dict[str, Any]]:
    """
    Construye la lista de mensajes para el payload `/api/chat` de Ollama,
    incluyendo hasta `MAX_HISTORY_MESSAGES` mensajes previos del chat.
    """
    ollama_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]

    # Tomar los últimos mensajes previos (excluyendo el recién insertado si ya viene en la lista)
    recent_history = history_messages[-MAX_HISTORY_MESSAGES:]
    for msg in recent_history:
        msg_text = (msg.content or "").strip()
        if msg.role == "user" and msg.attachments:
            att_list = [
                {
                    "file_name": a.file_name,
                    "file_type": a.file_type,
                    "mime_type": a.mime_type,
                    "extracted_text": a.extracted_text or "",
                }
                for a in msg.attachments
            ]
            msg_text = format_user_message_with_attachments(
                msg_text, att_list, include_separator_reminder=False
            )

        if msg_text:
            ollama_messages.append({"role": msg.role, "content": msg_text})

    # Mensaje actual del usuario con adjuntos e imágenes en Base64
    current_att_dicts = [
        {
            "file_name": att.file_name,
            "file_type": att.file_type,
            "mime_type": att.mime_type,
            "extracted_text": att.extracted_text,
        }
        for att in current_attachments
    ]
    formatted_current_user = format_user_message_with_attachments(
        current_user_content,
        current_att_dicts,
        include_separator_reminder=True,
    )

    user_payload: Dict[str, Any] = {
        "role": "user",
        "content": formatted_current_user,
    }

    images_b64: List[str] = []
    for att in current_attachments:
        if att.file_type == "image":
            b64_val = att.base64_image or load_image_as_base64(att.local_path)
            if b64_val:
                images_b64.append(b64_val)

    if images_b64:
        user_payload["images"] = images_b64

    ollama_messages.append(user_payload)
    return ollama_messages


# =====================================================================
# 5. Invocación a Ollama con Reintento Automático y Mensajes Amigables
# =====================================================================


def build_ollama_offline_message(
    user_prompt: str,
    ollama_reachable: bool,
    style: str = "standard",
) -> str:
    """
    Devuelve una respuesta amigable y detallada cuando Ollama no está corriendo
    o no tiene ningún modelo descargado localmente.
    """
    if not ollama_reachable:
        if style == "concise":
            return (
                "⚠️ **Ollama no está en ejecución en `http://localhost:11434`.**\n\n"
                "Ejecuta estos comandos en tu terminal para activarlo:\n"
                "```bash\n"
                "ollama serve\n"
                "ollama pull llama3.2\n"
                "```\n"
                f"Una vez iniciado, vuelve a enviar tu consulta: *\"{user_prompt[:80]}\"*."
            )
        return (
            "⚠️ **No se pudo conectar con el servidor local de Ollama (`http://localhost:11434`).**\n\n"
            "LocalGem Chat funciona 100% gratis y en privado usando tus propios modelos locales. "
            "Para comenzar a generar respuestas con IA, sigue estos pasos rápidos en tu terminal:\n\n"
            "### 1. Inicia el servicio de Ollama\n"
            "```bash\n"
            "ollama serve\n"
            "```\n\n"
            "### 2. Descarga un modelo ligero (si aún no tienes uno)\n"
            "```bash\n"
            "# Modelo recomendado rápido y ligero:\n"
            "ollama pull llama3.2\n\n"
            "# O para soporte de visión de imágenes:\n"
            "ollama pull llava\n"
            "```\n\n"
            "Tu mensaje y tus archivos adjuntos ya quedaron guardados en **SQLite (`localgem.db`)**."
        )

    # Ollama está corriendo pero la lista de modelos (/api/tags) está vacía
    if style == "concise":
        return (
            "⚠️ **Ollama está activo, pero no tienes ningún modelo descargado.**\n\n"
            "Ejecuta en tu terminal:\n"
            "```bash\n"
            "ollama pull llama3.2\n"
            "```"
        )
    return (
        "⚠️ **Ollama está corriendo correctamente, pero aún no hay modelos instalados.**\n\n"
        "Abre una terminal y descarga al menos un modelo gratuito ejecutando:\n\n"
        "```bash\n"
        "ollama pull llama3.2\n"
        "```\n\n"
        "Si tu equipo tiene pocos recursos, puedes instalar un modelo ultraligero:\n"
        "```bash\n"
        "ollama pull llama3.2:1b\n"
        "```\n"
        "En cuanto termine la descarga, podrás conversar de inmediato."
    )


async def call_ollama_chat(
    model_name: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.6,
) -> str:
    """
    Realiza la petición `POST http://localhost:11434/api/chat` con `stream=False`.
    Si el modelo no soporta imágenes (`images`) y devuelve HTTP 400/500, reintenta
    automáticamente quitando el array `images` y conservando el contexto descriptivo.
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload: Dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": 4096,
        },
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(url, json=payload)
            if response.status_code >= 400 and any("images" in m for m in messages):
                logger.info(
                    "El modelo '%s' devolvió HTTP %s con imágenes; reintentando solo con texto/metadatos...",
                    model_name,
                    response.status_code,
                )
                sanitized_messages = [
                    {k: v for k, v in m.items() if k != "images"} for m in messages
                ]
                payload["messages"] = sanitized_messages
                response = await client.post(url, json=payload)

            response.raise_for_status()
            data = response.json()
            message_obj = data.get("message") or {}
            content = message_obj.get("content") or data.get("response") or ""
            return str(content).strip()

        except Exception as exc:
            logger.error("Error al invocar Ollama /api/chat con modelo '%s': %s", model_name, exc)
            return (
                f"⚠️ **Ocurrió un error al consultar el modelo local `{model_name}` en Ollama:**\n\n"
                f"`{exc}`\n\n"
                "Verifica que Ollama esté ejecutándose con `ollama serve` y que el modelo esté disponible con `ollama list`."
            )


# =====================================================================
# 6. Orquestación Principal (Modo Estándar y Modo de Comparación A/B)
# =====================================================================


async def generate_assistant_reply(
    db: Session,
    history_messages: List[Message],
    user_content: str,
    processed_attachments: List[ProcessedAttachment],
    user_message_count: int,
    requested_model: Optional[str] = None,
    compare_mode: bool = False,
) -> OrchestrationResult:
    """
    Orquesta la generación de la respuesta de la IA local:
    - Determina si debe activarse el Modo de Satisfacción A/B:
      `should_run_ab = compare_mode or (user_message_count > 0 and user_message_count % 3 == 0)`
    - En modo normal: Inyecta la preferencia histórica del usuario (`user_preferences`) y genera 1 respuesta + 3 opciones.
    - En modo A/B: Genera DOS respuestas candidatas:
      * `candidate_a`: Directa, concisa y estructurada (`temperature=0.3`).
      * `candidate_b`: Profunda, detallada y con ejemplos (`temperature=0.8`).
    """
    has_attachments = len(processed_attachments) > 0
    should_run_ab = bool(compare_mode or (user_message_count > 0 and user_message_count % 3 == 0))

    active_model, ollama_reachable = await resolve_active_model(requested_model)

    # Caso 1: Ollama apagado o sin modelos instalados
    if not ollama_reachable or not active_model:
        fallback_options = [
            "¿Cómo instalo Ollama y descargo mi primer modelo?",
            "¿Qué modelos ligeros recomiendas para poca RAM?",
            "Reintentar mi consulta ahora",
        ]
        if should_run_ab:
            cand_a = build_ollama_offline_message(user_content, ollama_reachable, style="concise")
            cand_b = build_ollama_offline_message(user_content, ollama_reachable, style="detailed")
            return OrchestrationResult(
                content=cand_a,
                follow_up_options=fallback_options,
                is_ab_test=True,
                candidate_a=cand_a,
                candidate_b=cand_b,
                model_used=requested_model or DEFAULT_FALLBACK_MODEL,
            )

        offline_msg = build_ollama_offline_message(user_content, ollama_reachable, style="detailed")
        return OrchestrationResult(
            content=offline_msg,
            follow_up_options=fallback_options,
            is_ab_test=False,
            candidate_a=None,
            candidate_b=None,
            model_used=requested_model or DEFAULT_FALLBACK_MODEL,
        )

    # Caso 2: Modo de Comparación A/B (cada 3 mensajes del usuario o compare_mode=True)
    if should_run_ab:
        directive_a = (
            "MODO DE ESTILO: RESPUESTA CANDIDATA A (DIRECTA, CONCISA Y ESTRUCTURADA).\n"
            "Instrucciones estrictas:\n"
            "- Ve directamente al grano desde la primera oración.\n"
            "- Sé conciso, ejecutivo y estructurado con puntos clave breves.\n"
            "- Evita introducciones largas o explicaciones redundantes."
        )
        directive_b = (
            "MODO DE ESTILO: RESPUESTA CANDIDATA B (PROFUNDA, DETALLADA Y CON EJEMPLOS).\n"
            "Instrucciones estrictas:\n"
            "- Desarrolla una explicación profunda, didáctica, completa y paso a paso.\n"
            "- Usa subtítulos en Markdown, explica el contexto y añade ejemplos prácticos.\n"
            "- Cubre casos de uso y matices importantes para que el usuario comprenda todo en detalle."
        )

        messages_a = build_ollama_messages_history(
            history_messages=history_messages,
            current_user_content=user_content,
            current_attachments=processed_attachments,
            system_prompt=build_system_prompt(directive_a),
        )
        messages_b = build_ollama_messages_history(
            history_messages=history_messages,
            current_user_content=user_content,
            current_attachments=processed_attachments,
            system_prompt=build_system_prompt(directive_b),
        )

        # Llamadas secuenciales para no saturar la CPU/GPU local en Ollama
        raw_a = await call_ollama_chat(model_name=active_model, messages=messages_a, temperature=0.3)
        raw_b = await call_ollama_chat(model_name=active_model, messages=messages_b, temperature=0.8)

        clean_a, options_a = parse_response_and_options(
            raw_text=raw_a,
            user_prompt=user_content,
            has_attachments=has_attachments,
        )
        clean_b, options_b = parse_response_and_options(
            raw_text=raw_b,
            user_prompt=user_content,
            has_attachments=has_attachments,
        )

        # Garantizar que candidate_a y candidate_b sean visualmente distinguibles incluso en modelos diminutos
        if clean_a.strip() == clean_b.strip():
            clean_b = f"### Explicación Detallada\n\n{clean_b}"

        merged_options = options_b if len(options_b) >= 2 else options_a

        return OrchestrationResult(
            content=clean_a,
            follow_up_options=merged_options[:3],
            is_ab_test=True,
            candidate_a=clean_a,
            candidate_b=clean_b,
            model_used=active_model,
        )

    # Caso 3: Respuesta Estándar adaptada al historial `user_preferences`
    learned_style_directive = build_style_instruction_from_preferences(db)
    system_prompt = build_system_prompt(learned_style_directive)
    ollama_messages = build_ollama_messages_history(
        history_messages=history_messages,
        current_user_content=user_content,
        current_attachments=processed_attachments,
        system_prompt=system_prompt,
    )

    user_pref = get_user_style_preference(db)
    temp = 0.4 if user_pref["dominant_style"] == "concise" else 0.7

    raw_reply = await call_ollama_chat(
        model_name=active_model,
        messages=ollama_messages,
        temperature=temp,
    )
    clean_reply, follow_up_options = parse_response_and_options(
        raw_text=raw_reply,
        user_prompt=user_content,
        has_attachments=has_attachments,
    )

    return OrchestrationResult(
        content=clean_reply,
        follow_up_options=follow_up_options[:3],
        is_ab_test=False,
        candidate_a=None,
        candidate_b=None,
        model_used=active_model,
    )
