import base64
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

from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Directorio base de subidas (backend/uploads/) creado automáticamente al importar el módulo
BACKEND_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BACKEND_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# Límites de seguridad y compatibilidad con modelos locales pequeños/antiguos
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB según REQ-MULTI-07
MAX_IMAGE_DIMENSION = 1024  # Redimensionado máximo 1024px para no saturar modelos locales
MAX_DOCUMENT_CHARS = 12000  # Límite estricto de 12,000 caracteres por archivo

# Extensiones permitidas por categoría
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".csv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | AUDIO_EXTENSIONS

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
# 1. Procesamiento de Imágenes (.png, .jpg, .jpeg, .webp)
# =====================================================================


def process_image_file(file_path: Path, original_name: str) -> Tuple[str, str]:
    """
    Procesa una imagen local con Pillow:
    - Corrige orientación EXIF si existe.
    - Si el ancho o alto supera 1024px, redimensiona manteniendo relación de aspecto
      y sobrescribe el archivo optimizado en disco para no saturar modelos locales antiguos.
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

            # Preparar buffer para guardar y codificar en Base64
            save_format = original_format if original_format in {"PNG", "JPEG", "WEBP"} else "PNG"
            if save_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")

            buffer = io.BytesIO()
            save_kwargs = {"optimize": True}
            if save_format in {"JPEG", "WEBP"}:
                save_kwargs["quality"] = 88

            img.save(buffer, format=save_format, **save_kwargs)
            processed_bytes = buffer.getvalue()

            # Si fue redimensionada, actualizamos el archivo en disco con la versión optimizada
            if resized:
                file_path.write_bytes(processed_bytes)

            b64_string = base64.b64encode(processed_bytes).decode("utf-8")

            size_kb = len(processed_bytes) / 1024.0
            resize_info = (
                f"redimensionada de {orig_width}x{orig_height}px a {final_width}x{final_height}px"
                if resized
                else f"dimensiones {final_width}x{final_height}px (sin necesidad de redimensionar)"
            )
            descriptive_note = (
                f"[Imagen adjunta: '{original_name}' | Formato: {save_format} | "
                f"Modo de color: {orig_mode} | {resize_info} | Tamaño procesado: {size_kb:.1f} KB]"
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


def extract_pdf_text(file_path: Path, original_name: str) -> str:
    """Extrae texto de un archivo PDF usando PyMuPDF (fitz) con límite seguro de 12,000 caracteres."""
    try:
        import fitz  # PyMuPDF

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
                    # Si ya superamos ampliamente el límite de 12,000 chars, detenemos la lectura
                    if collected_chars >= MAX_DOCUMENT_CHARS + 1500:
                        break

        full_text = "\n\n".join(pages_text).strip()
        if not full_text:
            return (
                f"[Documento PDF '{original_name}' ({total_pages} páginas): "
                "El PDF no contiene texto seleccionable o parece ser un documento escaneado sin capa OCR.]"
            )

        return truncate_text_safely(full_text, MAX_DOCUMENT_CHARS)

    except Exception as exc:
        logger.error("Error extrayendo texto del PDF '%s': %s", original_name, exc)
        return f"[Aviso: No se pudo extraer el texto del archivo PDF '{original_name}'. Detalle: {exc}]"


def extract_plain_text_document(file_path: Path, original_name: str) -> str:
    """Lee archivos .txt, .md o .csv con soporte multi-encoding y límite de 12,000 caracteres."""
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

    return truncate_text_safely(decoded_text, MAX_DOCUMENT_CHARS)


def process_document_file(file_path: Path, original_name: str, ext: str) -> str:
    """Despacha la extracción de texto según la extensión del documento."""
    if ext == ".pdf":
        return extract_pdf_text(file_path, original_name)
    return extract_plain_text_document(file_path, original_name)


# =====================================================================
# 3. Procesamiento de Audios (.mp3, .wav, .m4a, .ogg) con faster-whisper
# =====================================================================


def _get_lazy_whisper_model():
    """
    Carga perezosamente (lazy-loading) el modelo ligero 'tiny' (o 'base') de faster-whisper
    en CPU con cuantización int8 para no bloquear el arranque del servidor si no se suben audios.
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
            "Cargando modelo faster-whisper '%s' en CPU (int8) bajo demanda...",
            model_size,
        )
        _whisper_model_instance = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
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
    Transcribe un archivo de audio (.mp3, .wav, .m4a, .ogg) usando faster-whisper en CPU (int8).
    Incluye manejo robusto de errores por si falta ffmpeg o librerías de decodificación,
    devolviendo un aviso claro sin tumbar el servidor.
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
            "Verifica que 'faster-whisper' y 'ffmpeg' estén instalados en el sistema o utiliza "
            "el botón de micrófono en tiempo real de la interfaz.]"
        )

    try:
        segments, info = model.transcribe(
            str(file_path),
            beam_size=2,
            vad_filter=True,
        )
        transcribed_parts: List[str] = []
        for segment in segments:
            text_piece = segment.text.strip()
            if text_piece:
                transcribed_parts.append(text_piece)

        transcript = " ".join(transcribed_parts).strip()
        detected_lang = getattr(info, "language", "es")
        duration = getattr(info, "duration", 0.0)

        if not transcript:
            return (
                f"[Archivo de audio: '{original_name}' | Duración: {duration:.1f}s | Idioma detectado: {detected_lang}]\n"
                "[Aviso: El audio fue procesado correctamente pero no se detectó voz audible en la grabación.]"
            )

        header = (
            f"[Transcripción de audio '{original_name}' "
            f"(Duración: {duration:.1f}s, Idioma: {detected_lang})]:\n"
        )
        return truncate_text_safely(f"{header}{transcript}", MAX_DOCUMENT_CHARS)

    except Exception as exc:
        logger.warning(
            "Error al transcribir audio '%s' con faster-whisper (posible falta de ffmpeg): %s",
            original_name,
            exc,
        )
        return (
            f"[Archivo de audio adjunto: '{original_name}' ({file_size_kb:.1f} KB{meta_suffix})]\n"
            "[Aviso del procesador de audio local: No se pudo completar la transcripción automática "
            f"(detalle técnico: {exc}). Si estás usando formatos comprimidos como .mp3/.m4a, "
            "asegúrate de tener 'ffmpeg' instalado en el PATH del sistema o usa el dictado por voz en tiempo real.]"
        )


# =====================================================================
# 4. Función Principal de Procesamiento Multimodal
# =====================================================================


async def process_uploaded_file(upload_file: UploadFile) -> ProcessedAttachment:
    """
    Recibe un `UploadFile` de FastAPI, valida su extensión y tamaño (máx 25 MB),
    lo guarda en `backend/uploads/` y ejecuta el procesador local correspondiente:
    - Imagen -> redimensiona <= 1024px con Pillow, genera Base64 + nota descriptiva.
    - Documento -> extrae texto con PyMuPDF / lectura estándar truncado a 12,000 caracteres.
    - Audio -> transcribe con faster-whisper (lazy-loading CPU int8) con fallback seguro.
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
        base64_image, extracted_text = process_image_file(destination_path, original_name)
    elif file_type == "document":
        extracted_text = process_document_file(destination_path, original_name, ext)
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
    Útil cuando se reenvía contexto de imágenes del historial a Ollama.
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
