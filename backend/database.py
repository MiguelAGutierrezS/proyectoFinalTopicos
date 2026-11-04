import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Cargar automáticamente .env si existe en backend/ o en la raíz
_backend_env = Path(__file__).resolve().parent / ".env"
_root_env = Path(__file__).resolve().parent.parent / ".env"
try:
    from dotenv import load_dotenv
    if _backend_env.exists():
        load_dotenv(dotenv_path=_backend_env)
    elif _root_env.exists():
        load_dotenv(dotenv_path=_root_env)
    else:
        load_dotenv()
except ImportError:
    for candidate in (_backend_env, _root_env):
        if candidate.exists():
            with open(candidate, "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k, _v = _k.strip(), _v.strip().strip("\"'")
                        if _k and _k not in os.environ:
                            os.environ[_k] = _v

# Configuración apuntando al archivo local sqlite:///./localgem.db
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./localgem.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """Activa PRAGMA foreign_keys = ON en cada conexión SQLite para asegurar ON DELETE CASCADE."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI que provee una sesión de base de datos por petición."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Importa los modelos ORM y crea automáticamente todas las tablas en localgem.db si no existen,
    aplicando migración idempotente para columnas nuevas (Context Compactor, Skills y MCP) si la BD ya existía."""
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    try:
        with engine.connect() as conn:
            # 1. Migración de tabla chats
            chat_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chats)").fetchall()}
            if "context_summary" not in chat_cols:
                conn.exec_driver_sql("ALTER TABLE chats ADD COLUMN context_summary TEXT DEFAULT NULL")
            if "compacted_up_to_index" not in chat_cols:
                conn.exec_driver_sql("ALTER TABLE chats ADD COLUMN compacted_up_to_index INTEGER DEFAULT NULL")

            # 2. Migración de tabla messages (Skills v2.0 y trazas MCP v2.0)
            msg_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(messages)").fetchall()}
            if "active_skill" not in msg_cols:
                conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN active_skill TEXT DEFAULT NULL")
            if "mcp_calls_json" not in msg_cols:
                conn.exec_driver_sql("ALTER TABLE messages ADD COLUMN mcp_calls_json TEXT NOT NULL DEFAULT '[]'")

            conn.commit()
    except Exception as exc:
        import logging
        logging.getLogger("localgem.db").warning("Aviso durante migración de base de datos: %s", exc)
