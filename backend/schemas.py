from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
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
        description="Texto extraído, transcripción de audio o análisis visual Vision Bridge",
    )


class AttachmentCreate(AttachmentBase):
    message_id: str = Field(..., description="ID del mensaje asociado")


class AttachmentResponse(AttachmentBase):
    id: str = Field(..., description="UUID v4 del archivo adjunto")
    message_id: str = Field(..., description="UUID v4 del mensaje al que pertenece")

    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# 2. Esquemas de Opciones de Seguimiento, Comparación A/B, Skills y MCP (`messages`)
# =====================================================================

MessageRole = Literal["user", "assistant", "system"]
CandidateChoice = Literal["A", "B"]
PreferredStyleType = Literal["concise", "detailed"]


class MCPToolCallTrace(BaseModel):
    """Traza de ejecución de una herramienta MCP durante un turno de conversación."""

    tool_name: str = Field(..., description="Nombre de la herramienta MCP ejecutada")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Argumentos enviados a la herramienta MCP",
    )
    status: Literal["success", "error"] = Field(
        default="success",
        description="Estado de la ejecución MCP",
    )
    result_preview: str = Field(
        default="",
        description="Resultado o resumen devuelto por la herramienta MCP",
    )
    duration_ms: int = Field(
        default=0,
        description="Tiempo de ejecución de la herramienta en milisegundos",
    )


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
    skill_id: Optional[str] = Field(
        default=None,
        description="ID de la Skill modular a activar ('auto', 'code-architect', etc.)",
    )
    enable_mcp: bool = Field(
        default=True,
        description="Si es True, habilita la ejecución de herramientas MCP locales",
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
    active_skill: Optional[str] = Field(
        default=None,
        description="ID de la Skill aplicada en este mensaje (ej. 'code-architect')",
    )
    mcp_tool_calls: List[MCPToolCallTrace] = Field(
        default_factory=list,
        description="Lista de herramientas MCP ejecutadas en este turno",
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

    @field_validator("mcp_tool_calls", mode="before")
    @classmethod
    def ensure_mcp_calls_list(cls, value: object) -> List[Dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, list):
            return [item if isinstance(item, dict) else item.model_dump() for item in value]
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
    is_context_compacted: bool = Field(
        default=False,
        description="True si el chat posee memoria histórica compactada",
    )

    model_config = ConfigDict(from_attributes=True)


class ChatDetailResponse(BaseModel):
    """Esquema detallado de un chat con su historial completo (`GET /api/chats/{chat_id}`)."""

    id: str = Field(..., description="UUID v4 del chat")
    title: str = Field(..., description="Título del chat")
    context_summary: Optional[str] = Field(
        default=None,
        description="Resumen técnico compactado del historial antiguo (estilo Claude Code)",
    )
    compacted_up_to_index: Optional[int] = Field(
        default=None,
        description="Índice del último mensaje compactado",
    )
    is_context_compacted: bool = Field(
        default=False,
        description="True si este chat ha sido compactado",
    )
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
        description="Respuesta generada por la IA con opciones de seguimiento, datos A/B, Skill y trazas MCP",
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


# =====================================================================
# 6. Esquemas de Skills Modulares (`SKILL.md`) y Herramientas MCP (v2.0)
# =====================================================================


class SkillInfo(BaseModel):
    """Información estructurada de una Skill modular cargada desde `backend/skills/<id>/SKILL.md`."""

    id: str = Field(..., description="Identificador único de la Skill (ej. 'code-architect')")
    name: str = Field(..., description="Nombre visible de la Skill")
    description: str = Field(..., description="Descripción corta del propósito de la Skill")
    icon: str = Field(default="Sparkles", description="Nombre del icono Lucide")
    category: str = Field(default="general", description="Categoría de la Skill")
    triggers: List[str] = Field(
        default_factory=list,
        description="Palabras clave para activación automática en modo Auto-Skill",
    )
    instructions: str = Field(
        default="",
        description="Cuerpo completo en Markdown con las directivas expertas de la Skill",
    )
    instructions_preview: str = Field(
        default="",
        description="Extracto resumido de las instrucciones de la Skill",
    )


class SkillCreateRequest(BaseModel):
    """Payload para crear o actualizar una nueva Skill modular (`POST /api/skills`)."""

    id: str = Field(..., min_length=2, max_length=60, description="Slug de la Skill (ej. 'security-auditor')")
    name: str = Field(..., min_length=2, max_length=80, description="Nombre visible")
    description: str = Field(..., min_length=5, max_length=250, description="Descripción corta")
    icon: str = Field(default="Sparkles", description="Nombre del icono Lucide")
    category: str = Field(default="custom", description="Categoría")
    triggers: List[str] = Field(default_factory=list, description="Palabras clave disparadoras")
    instructions: str = Field(..., min_length=10, description="Instrucciones Markdown de la Skill")


class SkillsListResponse(BaseModel):
    skills: List[SkillInfo] = Field(default_factory=list)


class MCPToolDefinition(BaseModel):
    """Definición estándar de una herramienta en el catálogo Model Context Protocol (`tools/list`)."""

    name: str = Field(..., description="Nombre único de la herramienta MCP")
    description: str = Field(..., description="Descripción de la funcionalidad de la herramienta")
    input_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema de los argumentos de entrada",
    )


class MCPToolsListResponse(BaseModel):
    tools: List[MCPToolDefinition] = Field(default_factory=list)


class MCPCallRequest(BaseModel):
    """Payload para invocar manualmente una herramienta MCP (`POST /api/mcp/call`)."""

    tool_name: str = Field(..., min_length=1, description="Nombre de la herramienta MCP a ejecutar")
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Diccionario de argumentos para la herramienta",
    )


class MCPCallResponse(BaseModel):
    """Respuesta de la ejecución directa de una herramienta MCP (`tools/call`)."""

    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error"]
    result: str
    duration_ms: int


# =====================================================================
# 7. Esquemas de Inspección de la Arquitectura LangGraph (`GET /api/graph/schema`)
# =====================================================================


class GraphNodeSchema(BaseModel):
    """Metadatos de un nodo del StateGraph de LangGraph."""

    id: str = Field(..., description="Identificador del nodo en el StateGraph")
    label: str = Field(..., description="Nombre legible del nodo")
    description: str = Field(..., description="Responsabilidad única del nodo")


class GraphSchemaResponse(BaseModel):
    """Esquema de respuesta de `GET /api/graph/schema` (`specs/04-langgraph-architecture.md` §5)."""

    engine: str = Field(default="LangGraph StateGraph")
    version: str = Field(default="2.1.0")
    state_schema: str = Field(default="LocalGemGraphState")
    nodes: List[GraphNodeSchema] = Field(default_factory=list)
    mermaid: str = Field(..., description="Definición Mermaid flowchart TD del StateGraph")

