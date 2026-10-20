from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# =====================================================================
# 1. Esquemas de Archivos Adjuntos Multimodales (`attachments`)
# =====================================================================

AttachmentFileType = Literal["image", "document", "audio"]


class AttachmentBase(BaseModel):
    file_name: str = Field(..., min_length=1, description="Nombre original del archivo")
    file_type: AttachmentFileType = Field(..., description="Categoría: image, document o audio")
    mime_type: str = Field(..., min_length=1, description="MIME type del archivo")
    local_path: str = Field(..., min_length=1, description="Ruta en disco local dentro de uploads/")
    extracted_text: Optional[str] = Field(
        default="",
        description="Texto extraído, transcripción de audio o metadatos de imagen",
    )


class AttachmentCreate(AttachmentBase):
    message_id: str = Field(..., description="ID del mensaje asociado")


class AttachmentResponse(AttachmentBase):
    id: str = Field(..., description="UUID v4 del archivo adjunto")
    message_id: str = Field(..., description="UUID v4 del mensaje al que pertenece")

    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# 2. Esquemas de Opciones de Seguimiento y Comparación A/B (`messages`)
# =====================================================================

MessageRole = Literal["user", "assistant", "system"]
CandidateChoice = Literal["A", "B"]
PreferredStyleType = Literal["concise", "detailed"]


class ABComparisonPair(BaseModel):
    """Estructura explícita para representar el par de candidatas del Modo de Satisfacción A/B."""

    is_ab_test: bool = Field(
        default=False,
        description="True cuando la respuesta contiene dos candidatas para comparar",
    )
    candidate_a: Optional[str] = Field(
        default=None,
        description="Respuesta Candidata A (estilo conciso y directo)",
    )
    candidate_b: Optional[str] = Field(
        default=None,
        description="Respuesta Candidata B (estilo detallado y explicativo)",
    )
    selected_candidate: Optional[CandidateChoice] = Field(
        default=None,
        description="Candidata elegida por el usuario ('A', 'B' o None si aún no ha elegido)",
    )


class MessageCreate(BaseModel):
    """Esquema de entrada para creación programática de mensajes."""

    content: str = Field(default="", description="Texto del mensaje enviado por el usuario")
    force_ab_test: bool = Field(
        default=False,
        description="Si es True, fuerza la generación de 2 respuestas candidatas (A y B)",
    )
    model: Optional[str] = Field(
        default=None,
        description="Modelo de Ollama a utilizar (opcional)",
    )


class MessageResponse(BaseModel):
    """Esquema de salida completo de un mensaje (usuario o asistente)."""

    id: str = Field(..., description="UUID v4 del mensaje")
    chat_id: str = Field(..., description="UUID v4 del chat al que pertenece")
    role: MessageRole = Field(..., description="Rol del autor: user, assistant o system")
    content: str = Field(..., description="Contenido principal o candidata ganadora")
    follow_up_options: List[str] = Field(
        default_factory=list,
        description="Lista de 2 a 3 opciones clicables de seguimiento al final de cada respuesta IA",
    )
    is_ab_test: bool = Field(
        default=False,
        description="Indica si este mensaje fue generado en Modo de Satisfacción A/B",
    )
    candidate_a: Optional[str] = Field(
        default=None,
        description="Texto de la Respuesta A (concisa/directa)",
    )
    candidate_b: Optional[str] = Field(
        default=None,
        description="Texto de la Respuesta B (detallada/explicativa)",
    )
    selected_candidate: Optional[CandidateChoice] = Field(
        default=None,
        description="Candidata seleccionada por el usuario ('A' o 'B')",
    )
    created_at: datetime = Field(..., description="Fecha y hora de creación UTC")
    attachments: List[AttachmentResponse] = Field(
        default_factory=list,
        description="Archivos multimodales adjuntos al mensaje",
    )

    model_config = ConfigDict(from_attributes=True)

    @field_validator("follow_up_options", mode="before")
    @classmethod
    def ensure_list_of_strings(cls, value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


# =====================================================================
# 3. Esquemas de Chats (`chats`)
# =====================================================================


class ChatCreate(BaseModel):
    title: Optional[str] = Field(
        default="Nuevo Chat",
        max_length=150,
        description="Título inicial del chat",
    )


class ChatUpdate(BaseModel):
    title: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Nuevo título para el chat",
    )


class ChatSummaryResponse(BaseModel):
    """Esquema resumido para listar chats en la barra lateral (`GET /api/chats`)."""

    id: str = Field(..., description="UUID v4 del chat")
    title: str = Field(..., description="Título del chat")
    created_at: datetime = Field(..., description="Fecha de creación UTC")
    updated_at: datetime = Field(..., description="Fecha de última actualización UTC")
    message_count: int = Field(default=0, description="Total de mensajes en el chat")

    model_config = ConfigDict(from_attributes=True)


class ChatDetailResponse(BaseModel):
    """Esquema detallado de un chat con su historial completo (`GET /api/chats/{chat_id}`)."""

    id: str = Field(..., description="UUID v4 del chat")
    title: str = Field(..., description="Título del chat")
    created_at: datetime = Field(..., description="Fecha de creación UTC")
    updated_at: datetime = Field(..., description="Fecha de última actualización UTC")
    user_message_count: int = Field(
        default=0,
        description="Total de mensajes enviados por el usuario en este chat",
    )
    messages: List[MessageResponse] = Field(
        default_factory=list,
        description="Lista cronológica de mensajes del chat",
    )

    model_config = ConfigDict(from_attributes=True)


class ChatDeleteResponse(BaseModel):
    deleted: bool = Field(default=True)
    chat_id: str = Field(..., description="ID del chat eliminado")


# =====================================================================
# 4. Esquemas de Respuesta de Envío de Mensaje y Selección A/B
# =====================================================================


class SendMessageResponse(BaseModel):
    """Respuesta del endpoint `POST /api/chats/{chat_id}/messages`."""

    chat_id: str = Field(..., description="UUID v4 del chat")
    chat_title: str = Field(..., description="Título actualizado del chat")
    user_message_count: int = Field(
        ...,
        description="Contador acumulado de mensajes del usuario en este chat",
    )
    user_message: MessageResponse = Field(
        ...,
        description="Mensaje del usuario persistido con sus adjuntos",
    )
    assistant_message: MessageResponse = Field(
        ...,
        description="Respuesta generada por la IA con opciones de seguimiento y datos A/B",
    )


class SelectCandidateRequest(BaseModel):
    """Payload de entrada para `POST /api/messages/{message_id}/select-ab` y `/select-candidate`."""

    selected: Optional[CandidateChoice] = Field(
        default=None,
        description="Candidata elegida por el usuario: 'A' (concisa) o 'B' (detallada)",
    )
    selected_candidate: Optional[CandidateChoice] = Field(
        default=None,
        description="Alias de selected: 'A' (concisa) o 'B' (detallada)",
    )

    @property
    def choice(self) -> CandidateChoice:
        val = self.selected or self.selected_candidate
        if val not in ("A", "B"):
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Debe especificar 'selected' o 'selected_candidate' con valor 'A' o 'B'.",
            )
        return val




class UserPreferenceResponse(BaseModel):
    """Registro de preferencia guardada en `user_preferences`."""

    id: str = Field(..., description="UUID v4 de la preferencia")
    preferred_style: PreferredStyleType = Field(
        ...,
        description="Estilo preferido registrado: 'concise' o 'detailed'",
    )
    message_id: str = Field(..., description="UUID v4 del mensaje A/B evaluado")
    created_at: datetime = Field(..., description="Fecha de registro UTC")

    model_config = ConfigDict(from_attributes=True)


class SelectCandidateResponse(BaseModel):
    """Respuesta al elegir la candidata A o B."""

    message: MessageResponse = Field(..., description="Mensaje actualizado con la candidata ganadora")
    preference_recorded: UserPreferenceResponse = Field(
        ...,
        description="Preferencia de estilo guardada en base de datos",
    )


class PreferenceSummaryResponse(BaseModel):
    """Resumen estadístico de preferencias del usuario (`GET /api/preferences/summary`)."""

    total_ab_selections: int = Field(default=0)
    concise_count: int = Field(default=0)
    detailed_count: int = Field(default=0)
    dominant_style: Optional[Literal["concise", "detailed", "balanced"]] = Field(
        default="balanced"
    )


# =====================================================================
# 5. Esquemas de Estado de Salud y Modelos de Ollama
# =====================================================================


class OllamaModelInfo(BaseModel):
    name: str = Field(..., description="Nombre del modelo en Ollama")
    size: Optional[int] = Field(default=None, description="Tamaño en bytes")
    modified_at: Optional[str] = Field(default=None, description="Fecha de modificación")


class ModelsListResponse(BaseModel):
    models: List[OllamaModelInfo] = Field(default_factory=list)
    default_model: str = Field(..., description="Modelo activo por defecto")


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    database: str = Field(default="connected")
    ollama_reachable: bool = Field(default=False)
    active_model: str = Field(default="llama3.2:latest")
    available_models: List[str] = Field(default_factory=list)
