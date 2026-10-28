import logging
import os
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

# Cargar automáticamente .env si existe
_env_backend = Path(__file__).resolve().parent.parent / ".env"
_env_root = Path(__file__).resolve().parent.parent.parent / ".env"
try:
    from dotenv import load_dotenv
    if _env_backend.exists():
        load_dotenv(dotenv_path=_env_backend)
    elif _env_root.exists():
        load_dotenv(dotenv_path=_env_root)
    else:
        load_dotenv()
except ImportError:
    for _cand in (_env_backend, _env_root):
        if _cand.exists():
            with open(_cand, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k, _v = _k.strip(), _v.strip().strip("\"'")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v

from models import Chat, Message, UserPreference
from services.multimodal_processor import ProcessedAttachment, load_image_as_base64

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_FALLBACK_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.2:latest")
MAX_HISTORY_MESSAGES = 10
FOLLOW_UP_SEPARATOR = "---FOLLOW_UP_OPTIONS---"

# Parámetros del Context Compactor (estilo Claude Code, configurables vía .env)
COMPACTION_THRESHOLD = int(os.getenv("COMPACTION_THRESHOLD", "14"))
TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET", "3200"))
RECENT_WINDOW_AFTER_COMPACTION = int(os.getenv("RECENT_WINDOW_AFTER_COMPACTION", "4"))
COMPACTOR_TEMPERATURE = float(os.getenv("COMPACTOR_TEMPERATURE", "0.2"))
COMPACTOR_MODEL = os.getenv("COMPACTOR_MODEL", "").strip() or None

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
# 2.1. Prompt Enhancer Determinista (specs/03-ai-orchestration.md §6)
# =====================================================================


def classify_intent(user_text: str, has_attachments: bool) -> str:
    """
    Clasifica la intención del usuario de forma 100% determinista (sin llamadas a LLM),
    utilizando análisis léxico y contexto multimodal según specs/03-ai-orchestration.md §6.3.
    """
    text_lower = (user_text or "").lower()

    if any(
        kw in text_lower
        for kw in (
            "código",
            "codigo",
            "función",
            "funcion",
            "implementa",
            "escribe",
            "crea una clase",
            "bug",
            "error",
            "script",
            "algoritmo",
            "sql",
            "query",
            "endpoint",
            "fastapi",
            "react",
            "typescript",
            "python",
        )
    ):
        return "GENERACIÓN_DE_CÓDIGO"

    if has_attachments or any(
        kw in text_lower
        for kw in (
            "archivo",
            "documento",
            "pdf",
            "csv",
            "tabla",
            "datos",
            "analiza",
            "resume",
            "estadística",
            "estadistica",
            "reporte",
            "ventas",
        )
    ):
        return "ANÁLISIS_DE_DATOS"

    if any(
        kw in text_lower
        for kw in (
            "vs",
            "versus",
            "diferencias",
            "ventajas",
            "compara",
            "elige entre",
            "cuál es mejor",
            "cual es mejor",
        )
    ):
        return "COMPARACIÓN"

    if any(
        kw in text_lower
        for kw in (
            "qué es",
            "que es",
            "explícame",
            "explicame",
            "cómo funciona",
            "como funciona",
            "diferencia entre",
            "define",
            "por qué",
            "por que",
        )
    ):
        return "EXPLICACIÓN_CONCEPTUAL"

    if any(
        kw in text_lower
        for kw in (
            "traduce",
            "en inglés",
            "en ingles",
            "en francés",
            "en frances",
            "idioma",
            "traducción",
            "traduccion",
        )
    ):
        return "TRADUCCIÓN_O_IDIOMA"

    return "GENERAL"


def build_session_context_directive(
    user_text: str,
    user_message_count: int,
    has_attachments: bool,
    dominant_style: str,
) -> str:
    """
    Construye una directiva técnica de sesión para inyectar en el System Prompt
    (specs/03-ai-orchestration.md §6). Evita alterar el contenido directo del usuario.
    """
    clean_text = (user_text or "").strip()
    intent = classify_intent(clean_text, has_attachments)
    style_label = {
        "concise": "CONCISO (preferencia aprendida)",
        "detailed": "DETALLADO (preferencia aprendida)",
        "balanced": "EQUILIBRADO",
    }.get(dominant_style, "EQUILIBRADO")

    attachment_note = " (con archivos adjuntos)" if has_attachments else ""
    return (
        f"CONTEXTO DE SESIÓN:\n"
        f"- Turno del usuario en este chat: #{user_message_count}\n"
        f"- Estilo preferido del usuario: {style_label}{attachment_note}\n"
        f"- Intención detectada en la consulta: {intent}"
    )


def enhance_user_prompt(
    user_text: str,
    user_message_count: int,
    has_attachments: bool,
    dominant_style: str,
) -> str:
    """
    Retorna el texto limpio del usuario sin decoradores que confundan a modelos pequeños o de código.
    """
    clean_text = (user_text or "").strip()
    if not clean_text and has_attachments:
        return "Analiza los archivos adjuntos y explica su contenido en detalle."
    return clean_text


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
    Utiliza rsplit para evitar cortes prematuros si el modelo repite texto meta.
    Si el modelo local olvida el separador o genera menos de 2 opciones válidas,
    completa automáticamente hasta tener exactamente 3 opciones contextuales.
    """
    if not raw_text or not raw_text.strip():
        fallback = generate_fallback_follow_up_options(user_prompt, "", has_attachments)
        return "No se recibió texto del modelo local.", fallback

    text = raw_text.strip()
    extracted_options: List[str] = []
    main_content = text
    raw_options_block = ""

    # Usar rsplit para partir en la ÚLTIMA ocurrencia del separador
    if FOLLOW_UP_SEPARATOR in text:
        parts = text.rsplit(FOLLOW_UP_SEPARATOR, 1)
        cand_main = parts[0].strip()
        cand_opts = parts[1].strip()

        # Si lo que hay antes del separador es trivial o una repetición de recordatorio
        # y lo que hay después tiene contenido sustancial, el separador estaba al inicio
        if len(cand_main) < 25 and len(cand_opts) > 40:
            main_content = cand_opts
            raw_options_block = ""
        else:
            main_content = cand_main
            raw_options_block = cand_opts
    else:
        matches = list(SEPARATOR_REGEX.finditer(text))
        if matches:
            last_match = matches[-1]
            cand_main = text[: last_match.start()].strip()
            cand_opts = text[last_match.end() :].strip()
            if len(cand_main) < 25 and len(cand_opts) > 40:
                main_content = cand_opts
                raw_options_block = ""
            else:
                main_content = cand_main
                raw_options_block = cand_opts

    # Limpiar posibles regurgitaciones de frases meta en main_content
    main_content = re.sub(
        r"\(?\s*Recuerda incluir al final de tu respuesta.*?seguida de 3 opciones.*?\)?",
        "",
        main_content,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()

    # Si main_content sigue empezando con variantes truncadas del recordatorio, removerlas
    main_content = re.sub(
        r"^\(?\s*Recuerda incluir al final de tu respuesta[^\n]*\n?",
        "",
        main_content,
        flags=re.IGNORECASE,
    ).strip()

    # Si tras la limpieza el contenido quedó vacío o truncado (< 15 caracteres),
    # generar una respuesta contextual para que la UI nunca muestre texto roto
    if len(main_content) < 15:
        topic = extract_topic_snippet(user_prompt)
        main_content = (
            f"### Análisis sobre: {topic.capitalize()}\n\n"
            f"El modelo ha procesado tu consulta sobre **{topic}**. "
            "A continuación puedes profundizar en los detalles utilizando las opciones de seguimiento."
        )

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


def build_system_prompt(style_directive: str, session_directive: Optional[str] = None) -> str:
    """Construye el System Prompt completo incluyendo la directiva de sesión y la regla obligatoria de `---FOLLOW_UP_OPTIONS---`."""
    parts = [
        "Eres LocalGem, un asistente de inteligencia artificial multimodal 100% local, "
        "inspirado en Google Gemini. Respondes siempre en español claro, preciso y bien formateado en Markdown."
    ]
    if session_directive:
        parts.append(session_directive)
    parts.append(style_directive)
    parts.append(
        "REGLA OBLIGATORIA DE OPCIONES DE SEGUIMIENTO:\n"
        "Primero desarrolla tu respuesta completa y natural a la consulta del usuario.\n"
        "Únicamente al final de tu respuesta, en una línea nueva separada, escribe exactamente:\n"
        f"{FOLLOW_UP_SEPARATOR}\n"
        "Y justo debajo escribe 3 opciones cortas (una por línea, sin viñetas ni numeración, máximo 75 caracteres) "
        "que el usuario pueda hacer clic para continuar la conversación."
    )
    return "\n\n".join(parts)


def format_user_message_with_attachments(
    content: str,
    attachments_info: List[Dict[str, str]],
    include_separator_reminder: bool = False,
) -> str:
    """
    Combina el texto del usuario con el texto extraído/transcrito de sus archivos adjuntos.
    El texto del usuario permanece limpio sin instrucciones meta para evitar que modelos
    pequeños o de código las repitan.
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

    return "\n".join(blocks).strip()


def estimate_history_tokens(messages: List[Message]) -> int:
    """Estima la cantidad de tokens acumulados en el historial (heurística: ~4 caracteres por token)."""
    total_chars = sum(len(m.content or "") for m in messages)
    for m in messages:
        if m.attachments:
            total_chars += sum(len(a.extracted_text or "") for a in m.attachments)
    return total_chars // 4


async def compact_chat_history(
    db: Session,
    chat: Optional[Chat],
    history_messages: List[Message],
    active_model: str,
) -> Optional[str]:
    """
    Context Compactor inspirado en Claude Code (specs/03-ai-orchestration.md §5).
    Si el historial supera COMPACTION_THRESHOLD o TOKEN_BUDGET, resume los turnos
    antiguos con Ollama y persiste el resumen técnico en chats.context_summary.
    """
    if not chat:
        return None

    if len(history_messages) < COMPACTION_THRESHOLD:
        return chat.context_summary

    est_tokens = estimate_history_tokens(history_messages)
    if len(history_messages) < COMPACTION_THRESHOLD and est_tokens < TOKEN_BUDGET:
        return chat.context_summary

    cutoff_index = max(0, len(history_messages) - RECENT_WINDOW_AFTER_COMPACTION)
    messages_to_compact = history_messages[:cutoff_index]
    if not messages_to_compact:
        return chat.context_summary

    history_lines: List[str] = []
    if chat.context_summary:
        history_lines.append(f"[Resumen previo acumulado]:\n{chat.context_summary}\n")

    history_lines.append("[Turnos a compactar]:")
    for msg in messages_to_compact:
        role_label = "Usuario" if msg.role == "user" else "Asistente"
        snippet = (msg.content or "").strip()
        if len(snippet) > 600:
            snippet = f"{snippet[:600]}..."
        history_lines.append(f"- {role_label}: {snippet}")

    history_block = "\n".join(history_lines)

    compactor_system = (
        "Eres un asistente de resumen técnico para compactación de contexto en LLMs locales.\n"
        "Tu misión es resumir la conversación en español preservando:\n"
        "1. Temas principales discutidos (máximo 5 puntos clave concisos).\n"
        "2. Datos técnicos concretos (nombres de archivos, tecnologías, decisiones tomadas).\n"
        "3. El contexto acumulado necesario para los próximos turnos.\n\n"
        "Reglas estrictas:\n"
        "- Máximo 300 palabras.\n"
        "- NO incluyas saludos ni frases de cortesía.\n"
        "- NO incluyas el separador ---FOLLOW_UP_OPTIONS---.\n"
        "- Responde únicamente con el resumen técnico estructurado."
    )

    payload_messages = [
        {"role": "system", "content": compactor_system},
        {
            "role": "user",
            "content": f"Compacta el siguiente historial de conversación:\n\n{history_block}",
        },
    ]

    try:
        logger.info(
            "Ejecutando Context Compactor para el chat '%s' (%d mensajes a compactar, ~%d tokens estimados)...",
            chat.id,
            len(messages_to_compact),
            est_tokens,
        )
        model_to_use = COMPACTOR_MODEL or active_model
        compacted_summary = await call_ollama_chat(
            model_name=model_to_use,
            messages=payload_messages,
            temperature=COMPACTOR_TEMPERATURE,
        )
        cleaned_summary, _ = parse_response_and_options(compacted_summary, "resumen")
        cleaned_summary = cleaned_summary.strip()

        if cleaned_summary and not cleaned_summary.startswith("⚠️"):
            chat.context_summary = cleaned_summary
            chat.compacted_up_to_index = cutoff_index
            db.commit()
            db.refresh(chat)
            logger.info("Context Compactor guardado exitosamente para el chat '%s'.", chat.id)
            return cleaned_summary

    except Exception as exc:
        logger.warning("Error en Context Compactor para el chat '%s': %s", chat.id, exc)

    return chat.context_summary


def build_ollama_messages_history(
    history_messages: List[Message],
    current_user_content: str,
    current_attachments: List[ProcessedAttachment],
    system_prompt: str,
    context_summary: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Construye la lista de mensajes para el payload `/api/chat` de Ollama.
    Si context_summary está presente, inyecta la memoria compactada en el rol system
    y conserva solo los turnos recientes (RECENT_WINDOW_AFTER_COMPACTION).
    """
    ollama_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]

    if context_summary and context_summary.strip():
        ollama_messages.append({
            "role": "system",
            "content": (
                "[MEMORIA COMPACTADA DE CONVERSACIÓN PREVIA — Claude Code style]\n"
                f"{context_summary.strip()}\n"
                "[FIN DE MEMORIA COMPACTADA — los mensajes siguientes corresponden a los turnos recientes]"
            ),
        })
        recent_history = history_messages[-RECENT_WINDOW_AFTER_COMPACTION:]
    else:
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
    chat: Optional[Chat] = None,
) -> OrchestrationResult:
    """
    Orquesta la generación de la respuesta de la IA local:
    - Activa Context Compactor si la conversación supera COMPACTION_THRESHOLD / TOKEN_BUDGET (Claude Code style).
    - Aplica Prompt Enhancer determinista con detección de intención y perfil de sesión.
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

    # 1. Context Compactor (estilo Claude Code): resumir turnos antiguos si se supera el presupuesto
    context_summary = None
    if ollama_reachable and active_model and chat:
        context_summary = await compact_chat_history(
            db=db,
            chat=chat,
            history_messages=history_messages,
            active_model=active_model,
        )
    elif chat and chat.context_summary:
        context_summary = chat.context_summary

    # 2. Prompt Enhancer Determinista (specs/03-ai-orchestration.md §6):
    user_pref = get_user_style_preference(db)
    session_directive = build_session_context_directive(
        user_text=user_content,
        user_message_count=user_message_count,
        has_attachments=has_attachments,
        dominant_style=user_pref["dominant_style"],
    )
    clean_user_content = enhance_user_prompt(
        user_text=user_content,
        user_message_count=user_message_count,
        has_attachments=has_attachments,
        dominant_style=user_pref["dominant_style"],
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
            current_user_content=clean_user_content,
            current_attachments=processed_attachments,
            system_prompt=build_system_prompt(directive_a, session_directive=session_directive),
            context_summary=context_summary,
        )
        messages_b = build_ollama_messages_history(
            history_messages=history_messages,
            current_user_content=clean_user_content,
            current_attachments=processed_attachments,
            system_prompt=build_system_prompt(directive_b, session_directive=session_directive),
            context_summary=context_summary,
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
    system_prompt = build_system_prompt(learned_style_directive, session_directive=session_directive)
    ollama_messages = build_ollama_messages_history(
        history_messages=history_messages,
        current_user_content=clean_user_content,
        current_attachments=processed_attachments,
        system_prompt=system_prompt,
        context_summary=context_summary,
    )

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
