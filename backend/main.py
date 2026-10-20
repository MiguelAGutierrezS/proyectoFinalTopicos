import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Attachment, Chat, Message, UserPreference
from schemas import (
    ChatCreate,
    ChatDeleteResponse,
    ChatDetailResponse,
    ChatSummaryResponse,
    ChatUpdate,
    HealthResponse,
    MessageResponse,
    ModelsListResponse,
    OllamaModelInfo,
    PreferenceSummaryResponse,
    SelectCandidateRequest,
    SelectCandidateResponse,
    SendMessageResponse,
    UserPreferenceResponse,
)
from services.multimodal_processor import (
    BACKEND_DIR as PROCESSOR_BACKEND_DIR,
    UPLOADS_DIR,
    ProcessedAttachment,
    process_uploaded_file,
)
from services.ollama_service import (
    DEFAULT_FALLBACK_MODEL,
    generate_assistant_reply,
    generate_fallback_follow_up_options,
    get_user_style_preference,
    list_ollama_models,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("localgem.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos SQLite (`localgem.db`) y la carpeta `uploads/` al arrancar."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("Base de datos SQLite inicializada y carpeta '%s' lista.", UPLOADS_DIR)
    yield


app = FastAPI(
    title="LocalGem Chat API",
    description="Backend 100% local y gratuito para LocalGem Chat con FastAPI, SQLite y Ollama.",
    version="1.0.0",
    lifespan=lifespan,
)

# Habilitar CORS para * según especificación
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir archivos multimodales subidos en /uploads
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


def generate_chat_title_from_first_message(
    content: str,
    attachments: List[ProcessedAttachment],
) -> str:
    """
    Genera automáticamente un título conciso (máximo 45 caracteres) para el chat
    a partir del primer mensaje del usuario o del nombre del primer archivo adjunto (REQ-CHAT-03).
    """
    cleaned = re.sub(r"\s+", " ", (content or "").strip())
    if cleaned:
        if len(cleaned) <= 45:
            return cleaned
        return f"{cleaned[:42].rstrip()}..."

    if attachments:
        first_file = attachments[0].file_name
        return f"Análisis de {first_file}"[:45]

    return "Nuevo Chat"


# =====================================================================
# 1. Endpoints de Salud y Modelos de Ollama
# =====================================================================


@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Verifica la conexión con SQLite y el estado de Ollama en localhost:11434."""
    models_raw, reachable = await list_ollama_models()
    available_names = [m["name"] for m in models_raw]
    active_model = available_names[0] if available_names else DEFAULT_FALLBACK_MODEL
    return HealthResponse(
        status="ok",
        database="connected",
        ollama_reachable=reachable,
        active_model=active_model,
        available_models=available_names,
    )


@app.get("/api/models", response_model=ModelsListResponse, tags=["Models"])
async def get_models() -> ModelsListResponse:
    """Lista los modelos instalados localmente en Ollama (`/api/tags`)."""
    models_raw, _ = await list_ollama_models()
    models_list = [OllamaModelInfo(**m) for m in models_raw]
    default_model = models_list[0].name if models_list else DEFAULT_FALLBACK_MODEL
    return ModelsListResponse(
        models=models_list,
        default_model=default_model,
    )


# =====================================================================
# 2. Endpoints de Gestión de Chats (`chats`)
# =====================================================================


@app.get("/api/chats", response_model=List[ChatSummaryResponse], tags=["Chats"])
def list_chats(db: Session = Depends(get_db)) -> List[Chat]:
    """Lista todos los chats guardados ordenados por fecha de actualización descendente."""
    chats = db.query(Chat).order_by(Chat.updated_at.desc()).all()
    return chats


@app.post(
    "/api/chats",
    response_model=ChatDetailResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Chats"],
)
def create_chat(
    payload: Optional[ChatCreate] = None,
    db: Session = Depends(get_db),
) -> Chat:
    """Crea un nuevo chat vacío en SQLite."""
    initial_title = (
        payload.title.strip()
        if payload and payload.title and payload.title.strip()
        else "Nuevo Chat"
    )
    new_chat = Chat(title=initial_title)
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)
    return new_chat


@app.get("/api/chats/{chat_id}", response_model=ChatDetailResponse, tags=["Chats"])
def get_chat_detail(chat_id: str, db: Session = Depends(get_db)) -> Chat:
    """Devuelve el chat con todos sus mensajes, archivos adjuntos, opciones de seguimiento y estado A/B."""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El chat con ID '{chat_id}' no existe.",
        )
    return chat


@app.patch("/api/chats/{chat_id}", response_model=ChatDetailResponse, tags=["Chats"])
def update_chat_title(
    chat_id: str,
    payload: ChatUpdate,
    db: Session = Depends(get_db),
) -> Chat:
    """Actualiza el título de un chat existente."""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El chat con ID '{chat_id}' no existe.",
        )
    chat.title = payload.title.strip()
    chat.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(chat)
    return chat


@app.delete("/api/chats/{chat_id}", response_model=ChatDeleteResponse, tags=["Chats"])
def delete_chat(chat_id: str, db: Session = Depends(get_db)) -> ChatDeleteResponse:
    """
    Borra un chat, todo su historial de mensajes y preferencias en cascada,
    y elimina los archivos físicos correspondientes en `backend/uploads/`.
    """
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El chat con ID '{chat_id}' no existe.",
        )

    # Recolectar rutas de archivos físicos para borrarlos del disco
    file_paths_to_remove: List[Path] = []
    for msg in chat.messages:
        for att in msg.attachments:
            if att.local_path:
                file_path = PROCESSOR_BACKEND_DIR / att.local_path
                file_paths_to_remove.append(file_path)

    db.delete(chat)
    db.commit()

    for path in file_paths_to_remove:
        try:
            if path.exists() and path.is_file():
                path.unlink()
        except Exception as exc:
            logger.warning("No se pudo eliminar el archivo físico '%s': %s", path, exc)

    return ChatDeleteResponse(deleted=True, chat_id=chat_id)


# =====================================================================
# 3. Envío de Mensajes Multimodales y Orquestación con Ollama
# =====================================================================


@app.post(
    "/api/chats/{chat_id}/messages",
    response_model=SendMessageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Messages"],
)
async def send_message(
    chat_id: str,
    content: str = Form(default=""),
    model: Optional[str] = Form(default=None),
    compare_mode: bool = Form(default=False),
    force_ab_test: bool = Form(default=False),
    files: Optional[List[UploadFile]] = File(default=None),
    db: Session = Depends(get_db),
) -> SendMessageResponse:
    """
    Recibe `FormData` con `content`, `model`, `compare_mode` (o `force_ab_test`) y `files`.
    1. Procesa localmente los archivos subidos (imágenes, PDFs/documentos, audios).
    2. Guarda el mensaje del usuario y sus registros `Attachment` en SQLite.
    3. Autogenera el título del chat si es el primer mensaje.
    4. Llama a `ollama_service.generate_assistant_reply` (activando el modo A/B cada 3 mensajes o si `compare_mode=True`).
    5. Persiste y devuelve el mensaje del usuario y la respuesta del asistente con sus `follow_up_options`.
    """
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El chat con ID '{chat_id}' no existe.",
        )

    valid_uploads = [f for f in (files or []) if f and f.filename]
    if not content.strip() and not valid_uploads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes enviar un mensaje de texto o al menos un archivo adjunto.",
        )

    # Historial previo antes de insertar el nuevo mensaje
    previous_messages: List[Message] = list(chat.messages)

    # 1. Procesar archivos multimodales subidos
    processed_attachments: List[ProcessedAttachment] = []
    for upload in valid_uploads:
        processed = await process_uploaded_file(upload)
        processed_attachments.append(processed)

    # 2. Crear y guardar el mensaje del usuario
    effective_user_content = content.strip()
    if not effective_user_content and processed_attachments:
        names = ", ".join(att.file_name for att in processed_attachments)
        effective_user_content = f"[Archivo adjunto: {names}]"

    user_msg = Message(
        chat_id=chat.id,
        role="user",
        content=effective_user_content,
        follow_up_options=[],
        is_ab_test=False,
    )
    db.add(user_msg)
    db.flush()

    for proc in processed_attachments:
        att_record = Attachment(
            id=proc.id,
            message_id=user_msg.id,
            file_name=proc.file_name,
            file_type=proc.file_type,
            mime_type=proc.mime_type,
            local_path=proc.local_path,
            extracted_text=proc.extracted_text,
        )
        db.add(att_record)

    db.flush()

    # 3. Contar mensajes del usuario en este chat y actualizar título si es el primer turno
    user_msg_count = (
        db.query(Message)
        .filter(Message.chat_id == chat.id, Message.role == "user")
        .count()
    )
    if user_msg_count == 1 or chat.title == "Nuevo Chat":
        chat.title = generate_chat_title_from_first_message(
            content=content,
            attachments=processed_attachments,
        )

    chat.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user_msg)

    # 4. Invocar al orquestador de Ollama (Modo normal o Modo de Satisfacción A/B)
    should_compare = bool(compare_mode or force_ab_test)
    orchestration = await generate_assistant_reply(
        db=db,
        history_messages=previous_messages,
        user_content=content.strip(),
        processed_attachments=processed_attachments,
        user_message_count=user_msg_count,
        requested_model=model,
        compare_mode=should_compare,
    )

    # 5. Guardar la respuesta del asistente en SQLite
    assistant_msg = Message(
        chat_id=chat.id,
        role="assistant",
        content=orchestration.content,
        is_ab_test=orchestration.is_ab_test,
        candidate_a=orchestration.candidate_a,
        candidate_b=orchestration.candidate_b,
        selected_candidate=None,
    )
    assistant_msg.follow_up_options = orchestration.follow_up_options

    chat.updated_at = datetime.now(timezone.utc)
    db.add(assistant_msg)
    db.commit()
    db.refresh(user_msg)
    db.refresh(assistant_msg)
    db.refresh(chat)

    return SendMessageResponse(
        chat_id=chat.id,
        chat_title=chat.title,
        user_message_count=user_msg_count,
        user_message=MessageResponse.model_validate(user_msg),
        assistant_message=MessageResponse.model_validate(assistant_msg),
    )


# =====================================================================
# 4. Selección de Respuesta en Modo A/B y Preferencias del Usuario
# =====================================================================


def _handle_ab_selection(
    message_id: str,
    payload: SelectCandidateRequest,
    db: Session,
) -> SelectCandidateResponse:
    """
    Lógica compartida para fijar la respuesta ganadora ('A' o 'B') como `content` definitivo,
    asegurar sus opciones de seguimiento y guardar la preferencia en `user_preferences`.
    """
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"El mensaje con ID '{message_id}' no existe.",
        )

    if not msg.is_ab_test:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este mensaje no pertenece a una prueba de comparación A/B.",
        )

    chosen = payload.choice
    winning_text = msg.candidate_a if chosen == "A" else msg.candidate_b
    if not winning_text:
        winning_text = msg.content

    msg.selected_candidate = chosen
    msg.content = winning_text

    # Asegurar que el mensaje tenga siempre sus 3 opciones de seguimiento listas
    if len(msg.follow_up_options) < 2:
        msg.follow_up_options = generate_fallback_follow_up_options(
            user_prompt=winning_text[:200],
            clean_response=winning_text,
            has_attachments=False,
        )

    preferred_style = "concise" if chosen == "A" else "detailed"
    preference = UserPreference(
        preferred_style=preferred_style,
        message_id=msg.id,
    )
    db.add(preference)

    if msg.chat:
        msg.chat.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(msg)
    db.refresh(preference)

    return SelectCandidateResponse(
        message=MessageResponse.model_validate(msg),
        preference_recorded=UserPreferenceResponse.model_validate(preference),
    )


@app.post(
    "/api/messages/{message_id}/select-ab",
    response_model=SelectCandidateResponse,
    tags=["A/B Satisfaction"],
)
def select_ab_response(
    message_id: str,
    payload: SelectCandidateRequest,
    db: Session = Depends(get_db),
) -> SelectCandidateResponse:
    """
    Recibe `{"selected": "A" | "B"}`, fija esa respuesta como el `content` definitivo del mensaje,
    asegura sus opciones de seguimiento y guarda la preferencia en `user_preferences`.
    """
    return _handle_ab_selection(message_id=message_id, payload=payload, db=db)


@app.post(
    "/api/messages/{message_id}/select-candidate",
    response_model=SelectCandidateResponse,
    tags=["A/B Satisfaction"],
)
def select_candidate_alias(
    message_id: str,
    payload: SelectCandidateRequest,
    db: Session = Depends(get_db),
) -> SelectCandidateResponse:
    """Alias compatible con `specs/02-database-and-api.md` para selección A/B."""
    return _handle_ab_selection(message_id=message_id, payload=payload, db=db)


@app.get(
    "/api/preferences/summary",
    response_model=PreferenceSummaryResponse,
    tags=["A/B Satisfaction"],
)
def get_preferences_summary(db: Session = Depends(get_db)) -> PreferenceSummaryResponse:
    """Devuelve el resumen estadístico de preferencias A/B del usuario."""
    summary = get_user_style_preference(db)
    return PreferenceSummaryResponse(**summary)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
