import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BACKEND_DIR / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SkillDefinition:
    """Representación en memoria de un archivo `SKILL.md`."""

    id: str
    name: str
    description: str
    icon: str = "Sparkles"
    category: str = "general"
    triggers: List[str] = field(default_factory=list)
    instructions: str = ""

    @property
    def instructions_preview(self) -> str:
        cleaned = re.sub(r"\s+", " ", self.instructions).strip()
        if len(cleaned) <= 140:
            return cleaned
        return f"{cleaned[:137].rstrip()}..."


def _parse_skill_markdown(file_path: Path, folder_name: str) -> Optional[SkillDefinition]:
    """
    Parsea un archivo `SKILL.md` extrayendo su bloque YAML frontmatter (`--- ... ---`)
    y su cuerpo de instrucciones en Markdown.
    """
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("No se pudo leer '%s': %s", file_path, exc)
        return None

    frontmatter_match = re.match(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", raw_text, re.DOTALL)
    metadata = {}
    body = raw_text.strip()

    if frontmatter_match:
        yaml_block = frontmatter_match.group(1)
        body = frontmatter_match.group(2).strip()
        try:
            parsed_yaml = yaml.safe_load(yaml_block)
            if isinstance(parsed_yaml, dict):
                metadata = parsed_yaml
        except Exception as exc:
            logger.warning("Error parseando YAML frontmatter en '%s': %s", file_path, exc)

    skill_id = str(metadata.get("id") or folder_name).strip()
    name = str(metadata.get("name") or skill_id.replace("-", " ").title()).strip()
    description = str(
        metadata.get("description") or f"Habilidad especializada ({name})."
    ).strip()
    icon = str(metadata.get("icon") or "Sparkles").strip()
    category = str(metadata.get("category") or "general").strip()

    raw_triggers = metadata.get("triggers") or []
    triggers: List[str] = []
    if isinstance(raw_triggers, list):
        triggers = [str(t).strip().lower() for t in raw_triggers if str(t).strip()]
    elif isinstance(raw_triggers, str):
        triggers = [t.strip().lower() for t in raw_triggers.split(",") if t.strip()]

    return SkillDefinition(
        id=skill_id,
        name=name,
        description=description,
        icon=icon,
        category=category,
        triggers=triggers,
        instructions=body,
    )


def list_skills() -> List[SkillDefinition]:
    """
    Descubre todas las carpetas dentro de `backend/skills/<skill_id>/SKILL.md`
    y retorna sus definiciones ordenadas.
    """
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    preferred_order = ["code-architect", "data-analyst", "academic-tutor", "sql-specialist"]
    loaded: List[SkillDefinition] = []

    for child in sorted(SKILLS_DIR.iterdir()):
        if child.is_dir():
            skill_file = child / "SKILL.md"
            if skill_file.exists():
                parsed = _parse_skill_markdown(skill_file, child.name)
                if parsed:
                    loaded.append(parsed)

    def sort_key(s: SkillDefinition) -> tuple:
        if s.id in preferred_order:
            return (0, preferred_order.index(s.id), s.name)
        return (1, 99, s.name)

    loaded.sort(key=sort_key)
    return loaded


def get_skill_by_id(skill_id: str) -> Optional[SkillDefinition]:
    """Busca y devuelve una Skill específica por su `id`."""
    if not skill_id:
        return None
    cleaned = skill_id.strip().lower()
    for skill in list_skills():
        if skill.id.lower() == cleaned:
            return skill
    return None


def create_or_update_skill(
    skill_id: str,
    name: str,
    description: str,
    icon: str,
    category: str,
    triggers: List[str],
    instructions: str,
) -> SkillDefinition:
    """
    Crea o actualiza en disco el archivo `backend/skills/<skill_id>/SKILL.md` (REQ-SKILL-05).
    """
    safe_id = re.sub(r"[^a-z0-9_-]", "-", skill_id.strip().lower()).strip("-")
    if len(safe_id) < 2:
        safe_id = "custom-skill"

    target_dir = SKILLS_DIR / safe_id
    target_dir.mkdir(parents=True, exist_ok=True)
    skill_file = target_dir / "SKILL.md"

    clean_triggers = [t.strip().lower() for t in triggers if t and t.strip()]
    frontmatter_data = {
        "id": safe_id,
        "name": name.strip(),
        "description": description.strip(),
        "icon": (icon or "Sparkles").strip(),
        "category": (category or "custom").strip(),
        "triggers": clean_triggers,
    }
    yaml_str = yaml.safe_dump(
        frontmatter_data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()

    full_markdown = f"---\n{yaml_str}\n---\n{instructions.strip()}\n"
    skill_file.write_text(full_markdown, encoding="utf-8")

    parsed = _parse_skill_markdown(skill_file, safe_id)
    if parsed:
        return parsed

    return SkillDefinition(
        id=safe_id,
        name=name.strip(),
        description=description.strip(),
        icon=icon.strip(),
        category=category.strip(),
        triggers=clean_triggers,
        instructions=instructions.strip(),
    )


def resolve_skill_for_turn(
    requested_skill_id: Optional[str],
    user_text: str,
    has_attachments: bool = False,
    attachment_filenames: Optional[List[str]] = None,
) -> Optional[SkillDefinition]:
    """
    Determina qué Skill aplicar en el turno actual (REQ-SKILL-03 y REQ-SKILL-04):
    1. Si el usuario escribió un comando explícito al inicio (ej. `/code-architect ...`), lo activa.
    2. Si `requested_skill_id` es `'none'` o vacío, no activa ninguna Skill.
    3. Si `requested_skill_id` es un ID concreto (ej. `'code-architect'`), devuelve esa Skill.
    4. Si `requested_skill_id == 'auto'`, analiza los `triggers` de cada `SKILL.md` y los adjuntos.
    """
    text = (user_text or "").strip()
    text_lower = text.lower()
    all_skills = list_skills()
    if not all_skills:
        return None

    # 1. Detectar comando slash al inicio del mensaje (ej. "/code-architect" o "/sql-specialist")
    slash_match = re.match(r"^/([a-zA-Z0-9_-]+)(?:\s+|$)", text)
    if slash_match:
        cmd_slug = slash_match.group(1).lower()
        for s in all_skills:
            if s.id.lower() == cmd_slug or cmd_slug in s.id.lower():
                return s

    if not requested_skill_id:
        return None

    req_clean = requested_skill_id.strip().lower()
    if req_clean in ("none", "off", "disabled", ""):
        return None

    # 2. Selección manual explícita
    if req_clean != "auto":
        for s in all_skills:
            if s.id.lower() == req_clean:
                return s
        return None

    # 3. Modo Auto-Skill: evaluar archivos adjuntos (.csv / .pdf -> data-analyst) y triggers léxicos
    filenames_lower = " ".join((attachment_filenames or [])).lower()
    if has_attachments and any(ext in filenames_lower for ext in (".csv", ".pdf", ".txt")):
        analyst = get_skill_by_id("data-analyst")
        if analyst:
            return analyst

    best_skill: Optional[SkillDefinition] = None
    best_score = 0

    for skill in all_skills:
        score = sum(1 for trig in skill.triggers if trig and trig in text_lower)
        if score > best_score:
            best_score = score
            best_skill = skill

    return best_skill if best_score > 0 else None


def format_skill_system_block(skill: SkillDefinition) -> str:
    """Construye el bloque de System Prompt para inyectar las instrucciones de la Skill activa."""
    return (
        f"[SKILL ESPECIALIZADA ACTIVA: {skill.name} (ID: {skill.id})]\n"
        f"Descripción: {skill.description}\n"
        f"Directivas obligatorias de la Skill:\n"
        f"{skill.instructions}\n"
        f"[FIN DE SKILL ESPECIALIZADA]"
    )

