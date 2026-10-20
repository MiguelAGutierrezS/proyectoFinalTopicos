import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def utc_now() -> datetime:
    """Retorna la fecha y hora actual en UTC."""
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """Genera un identificador único UUID v4 en formato texto."""
    return str(uuid.uuid4())


class Chat(Base):
    """
    Tabla `chats`: Almacena las sesiones de conversación.
    Campos exactos según specs/02-database-and-api.md:
    - id, title, created_at, updated_at
    """

    __tablename__ = "chats"

    id = Column(Text, primary_key=True, default=generate_uuid)
    title = Column(Text, nullable=False, default="Nuevo Chat")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    messages = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
        passive_deletes=True,
    )

    @property
    def message_count(self) -> int:
        """Cantidad total de mensajes en el chat."""
        return len(self.messages) if self.messages is not None else 0

    @property
    def user_message_count(self) -> int:
        """Cantidad de mensajes enviados por el usuario en el chat (para el disparo A/B cada 3 mensajes)."""
        if not self.messages:
            return 0
        return sum(1 for msg in self.messages if msg.role == "user")


class Message(Base):
    """
    Tabla `messages`: Almacena todos los mensajes del usuario y respuestas de la IA.
    Campos exactos según specs/02-database-and-api.md:
    - id, chat_id, role, content, follow_up_options_json, is_ab_test,
      candidate_a, candidate_b, selected_candidate, created_at
    """

    __tablename__ = "messages"

    id = Column(Text, primary_key=True, default=generate_uuid)
    chat_id = Column(
        Text,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(Text, nullable=False)
    content = Column(Text, nullable=False, default="")
    follow_up_options_json = Column(Text, nullable=True, default="[]")
    is_ab_test = Column(Boolean, nullable=False, default=False)
    candidate_a = Column(Text, nullable=True, default=None)
    candidate_b = Column(Text, nullable=True, default=None)
    selected_candidate = Column(Text, nullable=True, default=None)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="check_message_role",
        ),
        CheckConstraint(
            "selected_candidate IN ('A', 'B') OR selected_candidate IS NULL",
            name="check_selected_candidate",
        ),
        Index("idx_messages_chat_id", "chat_id"),
    )

    chat = relationship("Chat", back_populates="messages")
    attachments = relationship(
        "Attachment",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    preferences = relationship(
        "UserPreference",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def follow_up_options(self) -> List[str]:
        """Deserializa `follow_up_options_json` a una lista de strings de Python."""
        if not self.follow_up_options_json:
            return []
        try:
            parsed = json.loads(self.follow_up_options_json)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            return []
        except (ValueError, TypeError):
            return []

    @follow_up_options.setter
    def follow_up_options(self, options: Optional[List[str]]) -> None:
        """Serializa una lista de strings a formato JSON en `follow_up_options_json`."""
        if not options:
            self.follow_up_options_json = "[]"
        else:
            cleaned = [str(item).strip() for item in options if str(item).strip()]
            self.follow_up_options_json = json.dumps(cleaned, ensure_ascii=False)


class Attachment(Base):
    """
    Tabla `attachments`: Almacena los archivos multimodales adjuntos a un mensaje.
    Campos exactos según specs/02-database-and-api.md:
    - id, message_id, file_name, file_type, mime_type, local_path, extracted_text
    """

    __tablename__ = "attachments"

    id = Column(Text, primary_key=True, default=generate_uuid)
    message_id = Column(
        Text,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name = Column(Text, nullable=False)
    file_type = Column(Text, nullable=False)
    mime_type = Column(Text, nullable=False)
    local_path = Column(Text, nullable=False)
    extracted_text = Column(Text, nullable=True, default="")

    __table_args__ = (
        CheckConstraint(
            "file_type IN ('image', 'document', 'audio')",
            name="check_attachment_file_type",
        ),
        Index("idx_attachments_message_id", "message_id"),
    )

    message = relationship("Message", back_populates="attachments")


class UserPreference(Base):
    """
    Tabla `user_preferences`: Registra el historial de elecciones del usuario en el Modo A/B.
    Campos exactos según specs/02-database-and-api.md:
    - id, preferred_style, message_id, created_at
    """

    __tablename__ = "user_preferences"

    id = Column(Text, primary_key=True, default=generate_uuid)
    preferred_style = Column(Text, nullable=False)
    message_id = Column(
        Text,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        CheckConstraint(
            "preferred_style IN ('concise', 'detailed')",
            name="check_user_preference_style",
        ),
        Index("idx_user_preferences_message_id", "message_id"),
    )

    message = relationship("Message", back_populates="preferences")
