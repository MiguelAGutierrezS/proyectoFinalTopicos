import base64
import csv
import io
import logging
import mimetypes
import os
import re
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Tuple

import httpx
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps

# Evitar errores de symlinks en Windows (WinError 1314) y conflictos OpenMP en CPU
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logger = logging.getLogger(__name__)

# Directorio base de subidas (backend/uploads/) y caché local de modelos
BACKEND_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BACKEND_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

WHISPER_CACHE_DIR = BACKEND_DIR / "models_cache" / "whisper"
WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")

# Límites de seguridad y compatibilidad con modelos locales pequeños/antiguos
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB según REQ-MULTI-07
MAX_IMAGE_DIMENSION = 1024  # Redimensionado máximo 1024px para no saturar modelos locales
MAX_DOCUMENT_CHARS = 12000  # Límite estricto de 12,000 caracteres por archivo

# Extensiones permitidas por categoría
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".csv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | AUDIO_EXTENSIONS

# Familias de modelos en Ollama con capacidad de visión real
VISION_MODEL_KEYWORDS = (
    "moondream",
    "llava",
    "bakllava",
    "minicpm-v",
    "llama3.2-vision",
    "qwen2.5vl",
    "qwen2-vl",
    "pixtral",
)

AttachmentCategory = Literal["image", "document", "audio"]

# Instancia singleton perezosa (lazy-loaded) para faster-whisper
_whisper_model_instance = None
_whisper_load_failed_reason: Optional[str] = None


@dataclass
class ProcessedAttachment:
    """Resultado estructurado tras procesar un archivo multimodal localmente."""

    id: str
    file_name: str
    file_type: AttachmentCategory
    mime_type: str
    local_path: str
    absolute_path: str
    extracted_text: str
    base64_image: Optional[str] = None


def sanitize_filename(filename: str) -> str:
    """Limpia el nombre de archivo conservando caracteres seguros y su extensión."""
    name = os.path.basename(filename or "archivo")
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return cleaned[:120] or "archivo"


def classify_extension(filename: str) -> Tuple[AttachmentCategory, str]:
    """
    Determina la categoría ('image', 'document', 'audio') y la extensión normalizada.
    Lanza HTTPException 400 si la extensión no está soportada (REQ-MULTI-07).
    """
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image", ext
    if ext in DOCUMENT_EXTENSIONS:
        return "document", ext
    if ext in AUDIO_EXTENSIONS:
        return "audio", ext

    allowed_list = ", ".join(sorted(ALLOWED_EXTENSIONS))
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"Formato de archivo no permitido ('{ext or 'sin extensión'}'). "
            f"Formatos soportados: {allowed_list}"
        ),
    )


def guess_mime_type(filename: str, fallback_content_type: Optional[str], ext: str) -> str:
    """Obtiene el MIME type confiable para un archivo subido."""
    if fallback_content_type and fallback_content_type != "application/octet-stream":
        return fallback_content_type

    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
    }
    return mime_map.get(ext, "application/octet-stream")


def truncate_text_safely(text: str, max_chars: int = MAX_DOCUMENT_CHARS) -> str:
    """Limita de forma segura el texto extraído a `max_chars` caracteres."""
    normalized = text.replace("\x00", "").strip()
    if len(normalized) <= max_chars:
        return normalized
    truncated = normalized[:max_chars]
    return (
        f"{truncated}\n\n"
        f"[... Texto truncado automáticamente a {max_chars:,} caracteres "
        f"(de {len(normalized):,} totales) para proteger la ventana de contexto del modelo local ...]"
    )


# =====================================================================
# 1. Procesamiento de Imágenes (.png, .jpg, .jpeg, .webp) + Vision Bridge
# =====================================================================


def is_vision_capable_model(model_name: str) -> bool:
    """Verifica si el nombre de un modelo en Ollama corresponde a un modelo con soporte de visión."""
    lower = (model_name or "").lower()
    return any(keyword in lower for keyword in VISION_MODEL_KEYWORDS)


async def find_best_installed_vision_model(preferred_model: Optional[str] = None) -> Optional[str]:
    """
    Busca en `GET http://localhost:11434/api/tags` el mejor modelo de visión instalado
    (ej. `moondream:latest`, `llava:latest`, `llama3.2-vision`, `minicpm-v`).
    Si `preferred_model` es un modelo de visión válido e instalado, lo prioriza.
    """
    url = f"{OLLAMA_BASE_URL}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            installed = [
                str(item.get("name") or item.get("model") or "")
                for item in data.get("models", [])
                if item.get("name") or item.get("model")
            ]

            if preferred_model and is_vision_capable_model(preferred_model):
                pref_clean = preferred_model.strip()
                if pref_clean in installed:
                    return pref_clean
                for name in installed:
                    if name.split(":")[0].lower() == pref_clean.split(":")[0].lower():
                        return name

            # Priorizar moondream o llava entre los instalados
            for name in installed:
                if is_vision_capable_model(name):
                    return name
    except Exception as exc:
        logger.warning("No fue posible consultar modelos de visión en Ollama: %s", exc)
    return None


async def analyze_image_with_vision_bridge(
    base64_image: str,
    original_name: str,
    preferred_model: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """
    Vision Bridge — Etapa 1 (specs/03-ai-orchestration.md §7):
    Invoca `/api/generate` en el modelo de visión instalado (`moondream`, `llava`, etc.)
    usando un prompt directo y limpio (sin system prompt largo ni ruido meta) para extraer
    una descripción visual precisa de objetos, personas, colores, textos (OCR) y diagramas.
    Retorna `(vision_model_used, visual_description)` o `None` si no hay modelo de visión.
    """
    if not base64_image:
        return None

    vision_model = await find_best_installed_vision_model(preferred_model)
    if not vision_model:
        return None

    url = f"{OLLAMA_BASE_URL}/api/generate"
    vision_prompt = (
        "Describe this image in detail. Clearly mention all visible objects, people, "
        "colors, setting, layout, diagrams, and transcribe any visible text or numbers."
    )
    payload = {
        "model": vision_model,
        "prompt": vision_prompt,
        "images": [base64_image],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_ctx": 2048,
        },
    }

    try:
        logger.info(
            "Vision Bridge Etapa 1: Analizando imagen '%s' con modelo de visión '%s'...",
            original_name,
            vision_model,
        )
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_desc = str(data.get("response") or "").strip()
            if raw_desc and len(raw_desc) >= 5:
                logger.info(
                    "Vision Bridge completado para '%s' (%d caracteres extraídos con '%s').",
                    original_name,
                    len(raw_desc),
                    vision_model,
                )
                return vision_model, raw_desc
    except Exception as exc:
        logger.warning(
            "Error en Vision Bridge al analizar '%s' con '%s': %s",
            original_name,
            vision_model,
            exc,
        )
    return None


def process_image_file(file_path: Path, original_name: str) -> Tuple[str, str]:
    """
    Procesa una imagen local con Pillow:
    - Corrige orientación EXIF si existe.
    - Si el ancho o alto supera 1024px, redimensiona manteniendo relación de aspecto
      y sobrescribe el archivo optimizado en disco para no saturar modelos locales.
    - Devuelve (base64_str, descriptive_note).
    """
    try:
        with Image.open(file_path) as img:
            original_format = img.format or file_path.suffix.lstrip(".").upper() or "PNG"
            img = ImageOps.exif_transpose(img)
            orig_width, orig_height = img.size
            orig_mode = img.mode

            resized = False
            if orig_width > MAX_IMAGE_DIMENSION or orig_height > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
                resized = True

            final_width, final_height = img.size

            save_format = original_format if original_format in {"PNG", "JPEG", "WEBP"} else "PNG"
            if save_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            buffer = io.BytesIO()
            save_kwargs = {"optimize": True}
            if save_format in {"JPEG", "WEBP"}:
                save_kwargs["quality"] = 88

            img.save(buffer, format=save_format, **save_kwargs)
            processed_bytes = buffer.getvalue()

            if resized:
                file_path.write_bytes(processed_bytes)

            b64_string = base64.b64encode(processed_bytes).decode("utf-8")

            size_kb = len(processed_bytes) / 1024.0
            resize_info = (
                f"redimensionada de {orig_width}x{orig_height}px a {final_width}x{final_height}px"
                if resized
                else f"dimensiones {final_width}x{final_height}px"
            )
            descriptive_note = (
                f"[Metadatos Técnicos de Imagen: '{original_name}' | Formato: {save_format} | "
                f"Modo: {orig_mode} | {resize_info} | Peso: {size_kb:.1f} KB]"
            )
            return b64_string, descriptive_note

    except Exception as exc:
        logger.warning("Error procesando imagen '%s' con Pillow: %s", original_name, exc)
        raw_bytes = file_path.read_bytes()
        b64_fallback = base64.b64encode(raw_bytes).decode("utf-8")
        fallback_note = (
            f"[Imagen adjunta: '{original_name}' | Tamaño: {len(raw_bytes) / 1024.0:.1f} KB | "
            f"Nota: No se pudieron leer metadatos detallados ({exc})]"
        )
        return b64_fallback, fallback_note


# =====================================================================
# 2. Procesamiento de Documentos (.pdf, .txt, .md, .csv)
# =====================================================================


async def extract_pdf_text_async(
    file_path: Path,
    original_name: str,
    preferred_model: Optional[str] = None,
) -> str:
    """
    Extrae texto de un archivo PDF usando PyMuPDF (fitz) con límite seguro de 12,000 caracteres.
    Si el PDF es escaneado (sin capa de texto seleccionable), renderiza la primera página como
    imagen y aplica el Vision Bridge (`moondream` / `llava`) como OCR visual automático.
    """
    try:
        import fitz  # PyMuPDF

        pages_text: List[str] = []
        collected_chars = 0
        first_page_b64: Optional[str] = None

        with fitz.open(file_path) as doc:
            total_pages = len(doc)
            for page_index in range(total_pages):
                page = doc.load_page(page_index)
                page_str = page.get_text("text").strip()
                if page_str:
                    header = f"--- Página {page_index + 1} de {total_pages} ---\n"
                    chunk = f"{header}{page_str}"
                    pages_text.append(chunk)
                    collected_chars += len(chunk)
                    if collected_chars >= MAX_DOCUMENT_CHARS + 1500:
                        break
                elif page_index == 0:
                    # Guardar imagen de la página 1 por si el PDF es escaneado
                    try:
                        pix = page.get_pixmap(dpi=150)
                        first_page_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
                    except Exception:
                        pass

        full_text = "\n\n".join(pages_text).strip()
        if not full_text:
            if first_page_b64:
                vision_res = await analyze_image_with_vision_bridge(
                    first_page_b64,
                    f"{original_name} (Página 1 escaneada)",
                    preferred_model=preferred_model,
                )
                if vision_res:
                    v_model, v_desc = vision_res
                    return (
                        f"[Documento PDF Escaneado '{original_name}' ({total_pages} páginas) — "
                        f"Analizado visualmente con {v_model}]:\n{v_desc}"
                    )

            return (
                f"[Documento PDF '{original_name}' ({total_pages} páginas): "
                "El PDF no contiene texto seleccionable y parece ser un documento escaneado.]"
            )

        summary_header = f"[Documento PDF: '{original_name}' | Total de páginas: {total_pages}]\n\n"
        return truncate_text_safely(summary_header + full_text, MAX_DOCUMENT_CHARS)

    except Exception as exc:
        logger.error("Error extrayendo texto del PDF '%s': %s", original_name, exc)
        return f"[Aviso: No se pudo extraer el texto del archivo PDF '{original_name}'. Detalle: {exc}]"


def extract_pdf_text(file_path: Path, original_name: str) -> str:
    """Versión síncrona de extracción de PDF para compatibilidad directa."""
    try:
        import fitz

        pages_text: List[str] = []
        collected_chars = 0
        with fitz.open(file_path) as doc:
            total_pages = len(doc)
            for page_index in range(total_pages):
                page = doc.load_page(page_index)
                page_str = page.get_text("text").strip()
                if page_str:
                    header = f"--- Página {page_index + 1} de {total_pages} ---\n"
                    chunk = f"{header}{page_str}"
                    pages_text.append(chunk)
                    collected_chars += len(chunk)
                    if collected_chars >= MAX_DOCUMENT_CHARS + 1500:
                        break
        full_text = "\n\n".join(pages_text).strip()
        if not full_text:
            return (
                f"[Documento PDF '{original_name}' ({total_pages} páginas): "
                "El PDF no contiene texto seleccionable.]"
            )
        return truncate_text_safely(full_text, MAX_DOCUMENT_CHARS)
    except Exception as exc:
        return f"[Aviso: No se pudo extraer el texto del archivo PDF '{original_name}'. Detalle: {exc}]"


def extract_plain_text_document(file_path: Path, original_name: str, ext: str = "") -> str:
    """
    Lee archivos .txt, .md o .csv con soporte multi-encoding y límite de 12,000 caracteres.
    Si es un archivo .csv, añade automáticamente un encabezado estructural con las columnas
    y el total de filas detectadas para mejorar el análisis en modelos locales pequeños.
    """
    raw_bytes = file_path.read_bytes()
    decoded_text: Optional[str] = None

    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            decoded_text = raw_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if decoded_text is None:
        decoded_text = raw_bytes.decode("utf-8", errors="replace")

    if not decoded_text.strip():
        return f"[El archivo '{original_name}' está vacío.]"

    effective_ext = ext or file_path.suffix.lower()
    if effective_ext == ".csv":
        try:
            reader = list(csv.reader(io.StringIO(decoded_text)))
            non_empty_rows = [row for row in reader if any(cell.strip() for cell in row)]
            if non_empty_rows:
                headers = non_empty_rows[0]
                data_rows_count = max(0, len(non_empty_rows) - 1)
                csv_meta = (
                    f"[Estructura de Tabla CSV '{original_name}': "
                    f"{data_rows_count} filas de datos | "
                    f"{len(headers)} columnas ({', '.join(headers[:15])})]\n\n"
                )
                return truncate_text_safely(csv_meta + decoded_text, MAX_DOCUMENT_CHARS)
        except Exception:
            pass

    return truncate_text_safely(decoded_text, MAX_DOCUMENT_CHARS)


def process_document_file(file_path: Path, original_name: str, ext: str) -> str:
    """Despacha la extracción de texto según la extensión del documento."""
    if ext == ".pdf":
        return extract_pdf_text(file_path, original_name)
    return extract_plain_text_document(file_path, original_name, ext=ext)


# =====================================================================
# 3. Procesamiento de Audios (.mp3, .wav, .m4a, .ogg, .webm) con faster-whisper
# =====================================================================


def _get_lazy_whisper_model():
    """
    Carga perezosamente (lazy-loading) el modelo ligero 'tiny' (o 'base') de faster-whisper
    en CPU con cuantización int8 y directorio de caché explícito sin symlinks (`WHISPER_CACHE_DIR`),
    evitando errores WinError 1314 en Windows sin privilegios de administrador.
    """
    global _whisper_model_instance, _whisper_load_failed_reason

    if _whisper_model_instance is not None:
        return _whisper_model_instance

    if _whisper_load_failed_reason is not None:
        return None

    model_size = os.getenv("WHISPER_MODEL_SIZE", "tiny")
    try:
        from faster_whisper import WhisperModel

        logger.info(
            "Cargando modelo faster-whisper '%s' en CPU (int8) desde caché '%s'...",
            model_size,
            WHISPER_CACHE_DIR,
        )
        _whisper_model_instance = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=str(WHISPER_CACHE_DIR),
        )
        return _whisper_model_instance
    except Exception as exc:
        _whisper_load_failed_reason = str(exc)
        logger.warning(
            "No fue posible inicializar faster-whisper ('%s'): %s",
            model_size,
            exc,
        )
        return None


def _get_wav_basic_info(file_path: Path) -> Optional[str]:
    """Si el archivo es WAV, obtiene su duración y frecuencia de muestreo con la librería estándar `wave`."""
    try:
        with wave.open(str(file_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            duration = frames / float(rate) if rate > 0 else 0.0
            return f"Duración: {duration:.1f}s | Canales: {channels} | Sample Rate: {rate} Hz"
    except Exception:
        return None


def process_audio_file(file_path: Path, original_name: str, ext: str) -> str:
    """
    Transcribe un archivo de audio (.mp3, .wav, .m4a, .ogg, .webm) usando faster-whisper en CPU (int8).
    Si el filtro VAD descarta una grabación muy corta, reintenta automáticamente con `vad_filter=False`.
    """
    file_size_kb = file_path.stat().st_size / 1024.0
    wav_meta = _get_wav_basic_info(file_path) if ext == ".wav" else None
    meta_suffix = f" | {wav_meta}" if wav_meta else ""

    model = _get_lazy_whisper_model()
    if model is None:
        reason = _whisper_load_failed_reason or "Modelo faster-whisper no disponible"
        return (
            f"[Archivo de audio adjunto: '{original_name}' ({file_size_kb:.1f} KB{meta_suffix})]\n"
            f"[Aviso de transcripción local: No se pudo cargar el motor faster-whisper ({reason}). "
            "Verifica tu conexión inicial para descargar el modelo 'tiny' o utiliza el dictado en vivo.]"
        )

    try:
        segments, info = model.transcribe(
            str(file_path),
            beam_size=2,
            vad_filter=True,
        )
        transcribed_parts: List[str] = [
            seg.text.strip() for seg in segments if seg.text and seg.text.strip()
        ]

        # Si el audio es corto y el filtro VAD eliminó la voz, reintentar sin VAD
        if not transcribed_parts:
            segments_retry, info = model.transcribe(
                str(file_path),
                beam_size=2,
                vad_filter=False,
            )
            transcribed_parts = [
                seg.text.strip() for seg in segments_retry if seg.text and seg.text.strip()
            ]

        transcript = " ".join(transcribed_parts).strip()
        detected_lang = getattr(info, "language", "es")
        duration = getattr(info, "duration", 0.0)

        if not transcript:
            return (
                f"[Archivo de audio: '{original_name}' | Duración: {duration:.1f}s | Idioma detectado: {detected_lang}]\n"
                "[Aviso: El archivo de audio fue procesado pero no se detectó voz clara en la grabación.]"
            )

        header = (
            f"[Transcripción de audio '{original_name}' "
            f"(Duración: {duration:.1f}s, Idioma detectado: {detected_lang})]:\n"
        )
        return truncate_text_safely(f"{header}\"{transcript}\"", MAX_DOCUMENT_CHARS)

    except Exception as exc:
        logger.warning(
            "Error al transcribir audio '%s' con faster-whisper: %s",
            original_name,
            exc,
        )
        return (
            f"[Archivo de audio adjunto: '{original_name}' ({file_size_kb:.1f} KB{meta_suffix})]\n"
            "[Aviso del procesador de audio local: No se pudo completar la transcripción automática "
            f"(detalle técnico: {exc}). Te recomendamos usar archivos .wav o el grabador de voz integrado.]"
        )


# =====================================================================
# 4. Función Principal de Procesamiento Multimodal
# =====================================================================


async def process_uploaded_file(
    upload_file: UploadFile,
    preferred_model: Optional[str] = None,
) -> ProcessedAttachment:
    """
    Recibe un `UploadFile` de FastAPI, valida su extensión y tamaño (máx 25 MB),
    lo guarda en `backend/uploads/` y ejecuta el procesador local correspondiente:
    - Imagen -> redimensiona <= 1024px con Pillow, genera Base64 + ejecuta el **Vision Bridge**
      (`moondream` / `llava` vía `/api/generate`) para guardar la descripción visual en `extracted_text`.
    - Documento -> extrae texto con PyMuPDF (con fallback OCR visual si es escaneado) o CSV enriquecido.
    - Audio -> transcribe con faster-whisper (lazy-loading CPU int8 sin symlinks).
    """
    original_name = upload_file.filename or "archivo"
    file_type, ext = classify_extension(original_name)
    mime_type = guess_mime_type(original_name, upload_file.content_type, ext)

    content_bytes = await upload_file.read()
    if len(content_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"El archivo '{original_name}' supera el límite máximo permitido de 25 MB "
                f"({len(content_bytes) / (1024 * 1024):.1f} MB)."
            ),
        )

    attachment_id = str(uuid.uuid4())
    safe_name = sanitize_filename(original_name)
    stored_filename = f"{attachment_id}_{safe_name}"

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    destination_path = UPLOADS_DIR / stored_filename
    destination_path.write_bytes(content_bytes)

    relative_local_path = f"uploads/{stored_filename}"
    base64_image: Optional[str] = None
    extracted_text: str = ""

    if file_type == "image":
        base64_image, meta_note = process_image_file(destination_path, original_name)
        vision_result = await analyze_image_with_vision_bridge(
            base64_image=base64_image,
            original_name=original_name,
            preferred_model=preferred_model,
        )
        if vision_result:
            v_model, v_description = vision_result
            extracted_text = (
                f"{meta_note}\n"
                f"[Análisis Visual IA (extraído de los píxeles de la imagen con '{v_model}')]:\n"
                f"{v_description}"
            )
        else:
            extracted_text = (
                f"{meta_note}\n"
                "[Aviso: No se encontró un modelo de visión activo en Ollama (ej. moondream o llava) "
                "para describir el contenido visual de la imagen.]"
            )
    elif file_type == "document":
        if ext == ".pdf":
            extracted_text = await extract_pdf_text_async(
                destination_path,
                original_name,
                preferred_model=preferred_model,
            )
        else:
            extracted_text = extract_plain_text_document(destination_path, original_name, ext=ext)
    elif file_type == "audio":
        extracted_text = process_audio_file(destination_path, original_name, ext)

    return ProcessedAttachment(
        id=attachment_id,
        file_name=original_name,
        file_type=file_type,
        mime_type=mime_type,
        local_path=relative_local_path,
        absolute_path=str(destination_path),
        extracted_text=extracted_text,
        base64_image=base64_image,
    )


def load_image_as_base64(local_path: str) -> Optional[str]:
    """
    Lee una imagen previamente guardada en `uploads/...` y devuelve su representación Base64.
    """
    try:
        candidate_path = Path(local_path)
        if not candidate_path.is_absolute():
            candidate_path = BACKEND_DIR / local_path
        if not candidate_path.exists():
            return None
        return base64.b64encode(candidate_path.read_bytes()).decode("utf-8")
    except Exception as exc:
        logger.warning("No se pudo recargar imagen en Base64 desde '%s': %s", local_path, exc)
        return None
