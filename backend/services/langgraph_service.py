import logging
import re
import time
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from models import Chat, Message
from services.mcp_service import run_mcp_router_for_message
from services.multimodal_processor import ProcessedAttachment
from services.ollama_service import (
    COMPACTION_THRESHOLD,
    DEFAULT_FALLBACK_MODEL,
    OrchestrationResult,
    TOKEN_BUDGET,
    build_ollama_messages_history,
    build_ollama_offline_message,
    build_session_context_directive,
    build_style_instruction_from_preferences,
    build_system_prompt,
    call_ollama_chat,
    compact_chat_history,
    enhance_user_prompt,
    ensure_vision_bridge_on_attachments,
    estimate_history_tokens,
    get_user_style_preference,
    is_caption_only_vision_model,
    parse_response_and_options,
    resolve_active_model,
    resolve_synthesis_model,
)
from services.skills_service import format_skill_system_block, resolve_skill_for_turn

logger = logging.getLogger("localgem.langgraph")


# =====================================================================
# 1. Definición de Estado Tipado (`LocalGemGraphState`) — specs/04 §2
# =====================================================================


class GraphNodeTrace(TypedDict):
    node: str
    status: str          # "ok" | "skipped" | "fallback" | "error"
    duration_ms: int
    detail: Optional[str]


class LocalGemGraphState(TypedDict, total=False):
    # --- 1. Entradas del Turno (Inputs) ---
    db: Session
    chat_obj: Optional[Chat]
    chat_id: str
    user_message_id: str
    user_content: str
    requested_model: Optional[str]
    skill_id: Optional[str]
    enable_mcp: bool
    force_ab_test: bool
    user_message_count: int
    history_messages: List[Message]
    current_attachments: List[ProcessedAttachment]

    # --- 2. Estado Enriquecido por Nodos Intermedios ---
    ollama_reachable: bool
    installed_models: List[str]
    active_model: str
    synthesis_model: str
    preferred_style: Optional[str]       # "concise" | "detailed" | "balanced"
    learned_style_directive: str
    session_directive: str
    active_skill_meta: Optional[Dict[str, Any]]
    active_skill_id: Optional[str]
    skill_system_block: Optional[str]
    skill_cleaned_user_text: str
    mcp_tool_calls: List[Dict[str, Any]]
    mcp_context_block: str
    vision_bridge_applied: bool
    compacted_summary: Optional[str]
    ollama_messages: List[Dict[str, Any]]
    ollama_messages_b: List[Dict[str, Any]]
    is_ab_test: bool

    # --- 3. Salidas de Generación y Post-Procesamiento (Outputs) ---
    raw_response_main: str
    raw_response_b: Optional[str]
    final_content: str
    candidate_a: Optional[str]
    candidate_b: Optional[str]
    follow_up_options: List[str]

    # --- 4. Telemetría y Manejo de Errores del Grafo ---
    graph_trace: List[GraphNodeTrace]
    error: Optional[str]


def _append_trace(
    state: LocalGemGraphState,
    node: str,
    status: str,
    started_at: float,
    detail: Optional[str] = None,
) -> List[GraphNodeTrace]:
    duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    existing = list(state.get("graph_trace") or [])
    existing.append(
        {
            "node": node,
            "status": status,
            "duration_ms": duration_ms,
            "detail": detail,
        }
    )
    return existing


# =====================================================================
# 2. Nodos del Grafo (`StateGraph`) — specs/04-langgraph-architecture.md §4
# =====================================================================


async def node_load_context(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 1: Carga de Contexto, Resolución de Modelo en Ollama, Preferencia de Estilo y Regla A/B.
    """
    t0 = time.perf_counter()
    requested_model = state.get("requested_model")
    force_ab = bool(state.get("force_ab_test", False))
    msg_count = int(state.get("user_message_count", 1))
    db = state.get("db")

    is_ab_test = bool(force_ab or (msg_count > 0 and msg_count % 3 == 0))

    active_model, reachable, installed_names = await resolve_active_model(requested_model)
    effective_active = active_model or requested_model or DEFAULT_FALLBACK_MODEL
    synthesis_model = (
        resolve_synthesis_model(effective_active, installed_names)
        if reachable and active_model
        else effective_active
    )

    preferred_style = "balanced"
    learned_directive = (
        "PREFERENCIA DE ESTILO: Utiliza un estilo equilibrado, claro, amigable y bien estructurado en Markdown."
    )
    if db is not None:
        try:
            pref_summary = get_user_style_preference(db)
            preferred_style = pref_summary.get("dominant_style", "balanced")
            learned_directive = build_style_instruction_from_preferences(db)
        except Exception as exc:
            logger.warning("No se pudo leer user_preferences en node_load_context: %s", exc)

    detail = (
        f"model={effective_active}, synthesis={synthesis_model}, "
        f"style={preferred_style}, is_ab_test={is_ab_test}, ollama_reachable={reachable}"
    )
    return {
        "ollama_reachable": reachable,
        "installed_models": installed_names,
        "active_model": effective_active,
        "synthesis_model": synthesis_model,
        "preferred_style": preferred_style,
        "learned_style_directive": learned_directive,
        "is_ab_test": is_ab_test,
        "graph_trace": _append_trace(state, "node_load_context", "ok", t0, detail),
    }


async def node_skill_router(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 2: Resolución de la Skill activa (`SKILL.md`) por selección manual, comando slash o auto-detección.
    """
    t0 = time.perf_counter()
    user_content = state.get("user_content") or ""
    skill_id = state.get("skill_id")
    attachments = state.get("current_attachments") or []
    has_attachments = len(attachments) > 0

    try:
        active_skill_obj = resolve_skill_for_turn(
            requested_skill_id=skill_id,
            user_text=user_content,
            has_attachments=has_attachments,
            attachment_filenames=[a.file_name for a in attachments],
        )
        active_skill_id = active_skill_obj.id if active_skill_obj else None
        skill_block = format_skill_system_block(active_skill_obj) if active_skill_obj else None
        cleaned_text = (
            re.sub(r"^/[a-zA-Z0-9_-]+\s*", "", user_content.strip())
            or user_content.strip()
        )
        skill_meta = (
            {
                "id": active_skill_obj.id,
                "name": active_skill_obj.name,
                "category": active_skill_obj.category,
            }
            if active_skill_obj
            else None
        )
        detail = f"active_skill={active_skill_id or 'none'}"
        return {
            "active_skill_meta": skill_meta,
            "active_skill_id": active_skill_id,
            "skill_system_block": skill_block,
            "skill_cleaned_user_text": cleaned_text,
            "graph_trace": _append_trace(state, "node_skill_router", "ok", t0, detail),
        }
    except Exception as exc:
        logger.warning("Fallback en node_skill_router: %s", exc)
        return {
            "active_skill_meta": None,
            "active_skill_id": None,
            "skill_system_block": None,
            "skill_cleaned_user_text": user_content.strip(),
            "graph_trace": _append_trace(state, "node_skill_router", "fallback", t0, str(exc)),
        }


async def node_mcp_executor(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 3: Ejecutor Híbrido MCP (`tools/call`) con degradación elegante (REQ-GRAPH-06).
    """
    t0 = time.perf_counter()
    cleaned_text = (state.get("skill_cleaned_user_text") or state.get("user_content") or "").strip()
    if not cleaned_text:
        return {
            "mcp_tool_calls": [],
            "mcp_context_block": "",
            "graph_trace": _append_trace(state, "node_mcp_executor", "skipped", t0, "Sin texto para MCP"),
        }

    try:
        mcp_calls, mcp_block = await run_mcp_router_for_message(cleaned_text)
        tools_names = [c.get("tool_name", "") for c in mcp_calls]
        detail = f"tools_called={tools_names}" if tools_names else "no_tools_needed"
        return {
            "mcp_tool_calls": mcp_calls,
            "mcp_context_block": mcp_block,
            "graph_trace": _append_trace(state, "node_mcp_executor", "ok", t0, detail),
        }
    except Exception as exc:
        logger.warning("Fallback en node_mcp_executor: %s", exc)
        return {
            "mcp_tool_calls": [],
            "mcp_context_block": "",
            "graph_trace": _append_trace(state, "node_mcp_executor", "fallback", t0, str(exc)),
        }


async def node_vision_bridge(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 4: Vision Bridge en 2 Etapas (`moondream:latest` -> `llama3.2`).
    Garantiza que toda imagen adjunta tenga su `[Análisis Visual IA]` y que la síntesis final sea en español.
    """
    t0 = time.perf_counter()
    db = state.get("db")
    attachments = state.get("current_attachments") or []
    active_model = state.get("active_model") or DEFAULT_FALLBACK_MODEL
    installed_models = state.get("installed_models") or []

    try:
        if db is not None and attachments:
            await ensure_vision_bridge_on_attachments(
                db=db,
                processed_attachments=attachments,
                preferred_model=active_model,
            )
        synthesis_model = resolve_synthesis_model(active_model, installed_models)
        detail = f"vision_model={active_model}, synthesis_model={synthesis_model}"
        return {
            "current_attachments": attachments,
            "synthesis_model": synthesis_model,
            "vision_bridge_applied": True,
            "graph_trace": _append_trace(state, "node_vision_bridge", "ok", t0, detail),
        }
    except Exception as exc:
        logger.warning("Fallback en node_vision_bridge: %s", exc)
        return {
            "vision_bridge_applied": False,
            "graph_trace": _append_trace(state, "node_vision_bridge", "fallback", t0, str(exc)),
        }


async def node_context_compactor(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 5: Compactación ejecutiva de historiales extensos (>= 14 mensajes o >= 3200 tokens).
    """
    t0 = time.perf_counter()
    db = state.get("db")
    chat_obj = state.get("chat_obj")
    history_messages = state.get("history_messages") or []
    synthesis_model = state.get("synthesis_model") or DEFAULT_FALLBACK_MODEL

    if not state.get("ollama_reachable", False) or db is None or chat_obj is None:
        existing_summary = chat_obj.context_summary if chat_obj else None
        return {
            "compacted_summary": existing_summary,
            "graph_trace": _append_trace(
                state, "node_context_compactor", "skipped", t0, "Ollama offline o sin sesión"
            ),
        }

    try:
        summary = await compact_chat_history(
            db=db,
            chat=chat_obj,
            history_messages=history_messages,
            active_model=synthesis_model,
        )
        detail = f"compacted_chars={len(summary or '')}"
        return {
            "compacted_summary": summary,
            "graph_trace": _append_trace(state, "node_context_compactor", "ok", t0, detail),
        }
    except Exception as exc:
        logger.warning("Fallback en node_context_compactor: %s", exc)
        return {
            "compacted_summary": chat_obj.context_summary if chat_obj else None,
            "graph_trace": _append_trace(state, "node_context_compactor", "fallback", t0, str(exc)),
        }


async def node_prompt_builder(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 6: Ensamblaje del System Prompt adaptativo, payload multimodal, bloque MCP y mensajes para Ollama.
    """
    t0 = time.perf_counter()
    cleaned_text = state.get("skill_cleaned_user_text") or state.get("user_content") or ""
    msg_count = int(state.get("user_message_count", 1))
    attachments = state.get("current_attachments") or []
    has_attachments = len(attachments) > 0
    preferred_style = state.get("preferred_style") or "balanced"
    learned_directive = state.get("learned_style_directive") or ""
    skill_block = state.get("skill_system_block")
    mcp_block = state.get("mcp_context_block") or ""
    history_messages = state.get("history_messages") or []
    chat_obj = state.get("chat_obj")
    compacted_summary = state.get("compacted_summary")
    if compacted_summary is None and chat_obj is not None:
        compacted_summary = chat_obj.context_summary
    synthesis_model = state.get("synthesis_model") or DEFAULT_FALLBACK_MODEL
    is_ab_test = bool(state.get("is_ab_test", False))

    session_directive = build_session_context_directive(
        user_text=cleaned_text,
        user_message_count=msg_count,
        has_attachments=has_attachments,
        dominant_style=preferred_style,
    )
    enhanced_user = enhance_user_prompt(
        user_text=cleaned_text,
        user_message_count=msg_count,
        has_attachments=has_attachments,
        dominant_style=preferred_style,
    )
    if mcp_block:
        enhanced_user = f"{mcp_block}\n\n{enhanced_user}".strip()

    if is_ab_test:
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
            current_user_content=enhanced_user,
            current_attachments=attachments,
            system_prompt=build_system_prompt(
                directive_a,
                session_directive=session_directive,
                skill_block=skill_block,
            ),
            context_summary=compacted_summary,
            synthesis_model=synthesis_model,
        )
        messages_b = build_ollama_messages_history(
            history_messages=history_messages,
            current_user_content=enhanced_user,
            current_attachments=attachments,
            system_prompt=build_system_prompt(
                directive_b,
                session_directive=session_directive,
                skill_block=skill_block,
            ),
            context_summary=compacted_summary,
            synthesis_model=synthesis_model,
        )
        detail = f"mode=AB, messages_count={len(messages_a)}"
        return {
            "session_directive": session_directive,
            "ollama_messages": messages_a,
            "ollama_messages_b": messages_b,
            "graph_trace": _append_trace(state, "node_prompt_builder", "ok", t0, detail),
        }

    system_prompt = build_system_prompt(
        learned_directive,
        session_directive=session_directive,
        skill_block=skill_block,
    )
    ollama_messages = build_ollama_messages_history(
        history_messages=history_messages,
        current_user_content=enhanced_user,
        current_attachments=attachments,
        system_prompt=system_prompt,
        context_summary=compacted_summary,
        synthesis_model=synthesis_model,
    )
    detail = f"mode=standard, messages_count={len(ollama_messages)}"
    return {
        "session_directive": session_directive,
        "ollama_messages": ollama_messages,
        "ollama_messages_b": [],
        "graph_trace": _append_trace(state, "node_prompt_builder", "ok", t0, detail),
    }


async def node_generate_standard(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 7A: Generación Estándar en Ollama adaptada al estilo preferido del usuario.
    """
    t0 = time.perf_counter()
    reachable = bool(state.get("ollama_reachable", False))
    user_content = state.get("user_content") or ""
    synthesis_model = state.get("synthesis_model") or DEFAULT_FALLBACK_MODEL
    preferred_style = state.get("preferred_style") or "balanced"
    ollama_messages = state.get("ollama_messages") or []

    if not reachable or not state.get("installed_models"):
        offline_msg = build_ollama_offline_message(user_content, reachable, style="detailed")
        return {
            "raw_response_main": offline_msg,
            "raw_response_b": None,
            "graph_trace": _append_trace(
                state, "node_generate_standard", "fallback", t0, "Ollama offline"
            ),
        }

    temp = 0.4 if preferred_style == "concise" else 0.7
    raw_reply = await call_ollama_chat(
        model_name=synthesis_model,
        messages=ollama_messages,
        temperature=temp,
    )
    detail = f"model={synthesis_model}, temp={temp}, chars={len(raw_reply)}"
    return {
        "raw_response_main": raw_reply,
        "raw_response_b": None,
        "graph_trace": _append_trace(state, "node_generate_standard", "ok", t0, detail),
    }


async def node_generate_ab(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 7B: Generación Dual A/B (Candidata A concisa temp=0.3 vs. Candidata B detallada temp=0.8).
    """
    t0 = time.perf_counter()
    reachable = bool(state.get("ollama_reachable", False))
    user_content = state.get("user_content") or ""
    synthesis_model = state.get("synthesis_model") or DEFAULT_FALLBACK_MODEL
    messages_a = state.get("ollama_messages") or []
    messages_b = state.get("ollama_messages_b") or messages_a

    if not reachable or not state.get("installed_models"):
        cand_a = build_ollama_offline_message(user_content, reachable, style="concise")
        cand_b = build_ollama_offline_message(user_content, reachable, style="detailed")
        return {
            "raw_response_main": cand_a,
            "raw_response_b": cand_b,
            "graph_trace": _append_trace(state, "node_generate_ab", "fallback", t0, "Ollama offline"),
        }

    raw_a = await call_ollama_chat(model_name=synthesis_model, messages=messages_a, temperature=0.3)
    raw_b = await call_ollama_chat(model_name=synthesis_model, messages=messages_b, temperature=0.8)
    detail = f"model={synthesis_model}, chars_a={len(raw_a)}, chars_b={len(raw_b)}"
    return {
        "raw_response_main": raw_a,
        "raw_response_b": raw_b,
        "graph_trace": _append_trace(state, "node_generate_ab", "ok", t0, detail),
    }


async def node_parse_and_fallback(state: LocalGemGraphState) -> Dict[str, Any]:
    """
    Nodo 8: Extracción tolerante a fallos de `---FOLLOW_UP_OPTIONS---` y garantía de 2-3 opciones válidas.
    """
    t0 = time.perf_counter()
    user_content = state.get("user_content") or ""
    attachments = state.get("current_attachments") or []
    has_attachments = len(attachments) > 0
    is_ab_test = bool(state.get("is_ab_test", False))
    reachable = bool(state.get("ollama_reachable", False))
    installed_models = state.get("installed_models") or []

    raw_main = state.get("raw_response_main") or ""
    raw_b = state.get("raw_response_b")

    if not reachable or not installed_models:
        fallback_options = [
            "¿Cómo instalo Ollama y descargo mi primer modelo?",
            "¿Qué modelos ligeros recomiendas para poca RAM?",
            "Reintentar mi consulta ahora",
        ]
        return {
            "final_content": raw_main,
            "candidate_a": raw_main if is_ab_test else None,
            "candidate_b": raw_b if is_ab_test else None,
            "follow_up_options": fallback_options,
            "graph_trace": _append_trace(
                state, "node_parse_and_fallback", "fallback", t0, "Opciones offline"
            ),
        }

    if is_ab_test:
        clean_a, options_a = parse_response_and_options(
            raw_text=raw_main,
            user_prompt=user_content,
            has_attachments=has_attachments,
        )
        clean_b, options_b = parse_response_and_options(
            raw_text=raw_b or raw_main,
            user_prompt=user_content,
            has_attachments=has_attachments,
        )
        if clean_a.strip() == clean_b.strip():
            clean_b = f"### Explicación Detallada\n\n{clean_b}"

        merged_options = options_b if len(options_b) >= 2 else options_a
        final_options = merged_options[:3]
        detail = f"options_count={len(final_options)}, is_ab=True"
        return {
            "final_content": clean_a,
            "candidate_a": clean_a,
            "candidate_b": clean_b,
            "follow_up_options": final_options,
            "graph_trace": _append_trace(state, "node_parse_and_fallback", "ok", t0, detail),
        }

    clean_reply, follow_up_options = parse_response_and_options(
        raw_text=raw_main,
        user_prompt=user_content,
        has_attachments=has_attachments,
    )
    final_options = follow_up_options[:3]
    detail = f"options_count={len(final_options)}, is_ab=False"
    return {
        "final_content": clean_reply,
        "candidate_a": None,
        "candidate_b": None,
        "follow_up_options": final_options,
        "graph_trace": _append_trace(state, "node_parse_and_fallback", "ok", t0, detail),
    }


# =====================================================================
# 3. Aristas Condicionales (`add_conditional_edges`) — specs/04 §4
# =====================================================================


def _needs_vision_bridge(state: LocalGemGraphState) -> bool:
    attachments = state.get("current_attachments") or []
    active_model = state.get("active_model") or ""
    has_unprocessed_image = any(
        att.file_type == "image" and "[Análisis Visual IA" not in (att.extracted_text or "")
        for att in attachments
    )
    return bool(has_unprocessed_image or is_caption_only_vision_model(active_model) or attachments)


def _needs_compaction(state: LocalGemGraphState) -> bool:
    history_messages = state.get("history_messages") or []
    if len(history_messages) >= COMPACTION_THRESHOLD:
        return True
    est_tokens = estimate_history_tokens(history_messages)
    return est_tokens >= TOKEN_BUDGET


def route_mcp_check(state: LocalGemGraphState) -> str:
    """Arista Condicional 1: ¿Se debe ejecutar el nodo MCP?"""
    if state.get("enable_mcp", True):
        return "node_mcp_executor"
    return route_vision_check(state)


def route_vision_check(state: LocalGemGraphState) -> str:
    """Arista Condicional 2: ¿Se requiere Vision Bridge en este turno?"""
    if _needs_vision_bridge(state):
        return "node_vision_bridge"
    return route_compaction_check(state)


def route_compaction_check(state: LocalGemGraphState) -> str:
    """Arista Condicional 3: ¿El historial supera el umbral de compactación?"""
    if _needs_compaction(state):
        return "node_context_compactor"
    return "node_prompt_builder"


def route_generation_mode(state: LocalGemGraphState) -> str:
    """Arista Condicional 4: ¿Generación Estándar o Generación Dual A/B?"""
    if state.get("is_ab_test", False):
        return "node_generate_ab"
    return "node_generate_standard"


# =====================================================================
# 4. Construcción y Compilación del `StateGraph` de LangGraph
# =====================================================================


def build_localgem_state_graph() -> StateGraph:
    """Construye la máquina de estados `StateGraph(LocalGemGraphState)` según specs/04-langgraph-architecture.md."""
    workflow = StateGraph(LocalGemGraphState)

    # Registrar los 9 nodos oficiales
    workflow.add_node("node_load_context", node_load_context)
    workflow.add_node("node_skill_router", node_skill_router)
    workflow.add_node("node_mcp_executor", node_mcp_executor)
    workflow.add_node("node_vision_bridge", node_vision_bridge)
    workflow.add_node("node_context_compactor", node_context_compactor)
    workflow.add_node("node_prompt_builder", node_prompt_builder)
    workflow.add_node("node_generate_standard", node_generate_standard)
    workflow.add_node("node_generate_ab", node_generate_ab)
    workflow.add_node("node_parse_and_fallback", node_parse_and_fallback)

    # Flujo inicial
    workflow.add_edge(START, "node_load_context")
    workflow.add_edge("node_load_context", "node_skill_router")

    # Arista Condicional 1: Tras node_skill_router -> MCP, Vision, Compactor o Prompt Builder
    workflow.add_conditional_edges(
        "node_skill_router",
        route_mcp_check,
        {
            "node_mcp_executor": "node_mcp_executor",
            "node_vision_bridge": "node_vision_bridge",
            "node_context_compactor": "node_context_compactor",
            "node_prompt_builder": "node_prompt_builder",
        },
    )

    # Arista Condicional 2: Tras node_mcp_executor -> Vision, Compactor o Prompt Builder
    workflow.add_conditional_edges(
        "node_mcp_executor",
        route_vision_check,
        {
            "node_vision_bridge": "node_vision_bridge",
            "node_context_compactor": "node_context_compactor",
            "node_prompt_builder": "node_prompt_builder",
        },
    )

    # Arista Condicional 3: Tras node_vision_bridge -> Compactor o Prompt Builder
    workflow.add_conditional_edges(
        "node_vision_bridge",
        route_compaction_check,
        {
            "node_context_compactor": "node_context_compactor",
            "node_prompt_builder": "node_prompt_builder",
        },
    )

    # Tras compactar -> siempre construir prompt
    workflow.add_edge("node_context_compactor", "node_prompt_builder")

    # Arista Condicional 4: Tras construir prompt -> Generación Estándar (7A) o Dual A/B (7B)
    workflow.add_conditional_edges(
        "node_prompt_builder",
        route_generation_mode,
        {
            "node_generate_standard": "node_generate_standard",
            "node_generate_ab": "node_generate_ab",
        },
    )

    # Ambos generadores convergen en el Parser Resiliente (Nodo 8)
    workflow.add_edge("node_generate_standard", "node_parse_and_fallback")
    workflow.add_edge("node_generate_ab", "node_parse_and_fallback")

    # Cierre del grafo
    workflow.add_edge("node_parse_and_fallback", END)

    return workflow


# Instancia compilada singleton lista para ejecución asíncrona
localgem_compiled_graph = build_localgem_state_graph().compile()


# =====================================================================
# 5. Ejecutor Principal e Inspección de Esquema (`GET /api/graph/schema`)
# =====================================================================


OFFICIAL_MERMAID_DIAGRAM = """flowchart TD
    START((START)) --> N1["1. node_load_context\\n(Modelo + Preferencia Estilo + Modo A/B)"]
    N1 --> N2["2. node_skill_router\\n(Resolución SKILL.md Manual / Auto)"]
    
    N2 --> C_MCP{"¿enable_mcp == True?"}
    C_MCP -- "Sí" --> N3["3. node_mcp_executor\\n(Router Híbrido MCP + tools/call)"]
    C_MCP -- "No" --> C_VIS{"¿Hay imágenes\\nsin Análisis Visual?"}
    N3 --> C_VIS
    
    C_VIS -- "Sí" --> N4["4. node_vision_bridge\\n(Etapa 1: moondream -> Etapa 2: llama3.2)"]
    C_VIS -- "No" --> C_COMP{"¿Historial >= 14 msgs\\no >= 3200 tokens?"}
    N4 --> C_COMP
    
    C_COMP -- "Sí" --> N5["5. node_context_compactor\\n(Resumen Ejecutivo de Mensajes Antiguos)"]
    C_COMP -- "No" --> N6["6. node_prompt_builder\\n(Ensamblaje System Prompt + Payload Multimodal + MCP)"]
    N5 --> N6
    
    N6 --> C_AB{"¿is_ab_test == True?\\n(force_ab o msg_count % 3 == 0)"}
    C_AB -- "No (Estándar)" --> N7A["7A. node_generate_standard\\n(Inferencia Adaptativa con Ollama)"]
    C_AB -- "Sí (Modo A/B)" --> N7B["7B. node_generate_ab\\n(Inferencia Dual: Candidata A temp=0.3 / B temp=0.8)"]
    
    N7A --> N8["8. node_parse_and_fallback\\n(Parser ---FOLLOW_UP_OPTIONS--- + Fallback Determinista)"]
    N7B --> N8
    
    N8 --> END((END))"""


def get_graph_schema() -> Dict[str, Any]:
    """
    Devuelve la estructura viva del `StateGraph` compilado en LangGraph (`GET /api/graph/schema`)
    cumpliendo exactamente con `specs/04-langgraph-architecture.md` §5 y `specs/02-database-and-api.md` §3.6.
    """
    return {
        "engine": "LangGraph StateGraph",
        "version": "2.1.0",
        "state_schema": "LocalGemGraphState",
        "nodes": [
            {
                "id": "node_load_context",
                "label": "Carga de Contexto y Preferencias",
                "description": "Resuelve el modelo activo en Ollama, carga el estilo preferido del usuario y evalúa la condición de Test A/B.",
            },
            {
                "id": "node_skill_router",
                "label": "Enrutador de Skills (SKILL.md)",
                "description": "Detecta e inyecta habilidades especializadas por selección manual, comando slash o triggers léxicos.",
            },
            {
                "id": "node_mcp_executor",
                "label": "Ejecutor Híbrido MCP",
                "description": "Invoca herramientas locales del Model Context Protocol (Calculadora, SQLite, Reloj, Workspace, Wikipedia).",
            },
            {
                "id": "node_vision_bridge",
                "label": "Vision Bridge (2 Etapas)",
                "description": "Extrae descripciones visuales con moondream:latest y conmuta la síntesis en español a llama3.2.",
            },
            {
                "id": "node_context_compactor",
                "label": "Compactador de Contexto",
                "description": "Resume historiales largos (>= 14 mensajes) para proteger la ventana de contexto y la memoria RAM.",
            },
            {
                "id": "node_prompt_builder",
                "label": "Constructor de Prompt Multimodal",
                "description": "Ensambla el System Prompt adaptativo, adjuntos multimodales, resultados MCP y anclaje de intención.",
            },
            {
                "id": "node_generate_standard",
                "label": "Generador Estándar Ollama",
                "description": "Ejecuta inferencia simple adaptada al estilo histórico del usuario (conciso o detallado).",
            },
            {
                "id": "node_generate_ab",
                "label": "Generador Dual A/B",
                "description": "Genera en paralelo controlado Candidata A (concisa, temp 0.3) y Candidata B (detallada, temp 0.8).",
            },
            {
                "id": "node_parse_and_fallback",
                "label": "Parser Resiliente de Opciones",
                "description": "Extrae ---FOLLOW_UP_OPTIONS--- con 3 niveles de fallback determinista garantizando 2 a 3 sugerencias.",
            },
        ],
        "mermaid": OFFICIAL_MERMAID_DIAGRAM,
    }


async def run_localgem_graph(
    db: Session,
    history_messages: List[Message],
    user_content: str,
    processed_attachments: List[ProcessedAttachment],
    user_message_count: int,
    requested_model: Optional[str] = None,
    compare_mode: bool = False,
    chat: Optional[Chat] = None,
    skill_id: Optional[str] = "auto",
    enable_mcp: bool = True,
) -> OrchestrationResult:
    """
    Ejecuta una invocación completa del `StateGraph` de LangGraph y devuelve el `OrchestrationResult`.
    """
    initial_state: LocalGemGraphState = {
        "db": db,
        "chat_obj": chat,
        "chat_id": chat.id if chat else "",
        "user_content": user_content,
        "requested_model": requested_model,
        "skill_id": skill_id,
        "enable_mcp": enable_mcp,
        "force_ab_test": compare_mode,
        "user_message_count": user_message_count,
        "history_messages": history_messages,
        "current_attachments": processed_attachments,
        "graph_trace": [],
    }

    final_state: LocalGemGraphState = await localgem_compiled_graph.ainvoke(initial_state)

    trace = final_state.get("graph_trace") or []
    visited_summary = " -> ".join(
        f"{t['node']}({t['status']}:{t['duration_ms']}ms)" for t in trace
    )
    logger.info("LangGraph StateGraph ejecutado: %s", visited_summary)

    return OrchestrationResult(
        content=final_state.get("final_content") or "",
        follow_up_options=final_state.get("follow_up_options") or [],
        is_ab_test=bool(final_state.get("is_ab_test", False)),
        candidate_a=final_state.get("candidate_a"),
        candidate_b=final_state.get("candidate_b"),
        model_used=final_state.get("active_model") or requested_model or DEFAULT_FALLBACK_MODEL,
        active_skill=final_state.get("active_skill_id"),
        mcp_tool_calls=final_state.get("mcp_tool_calls") or [],
    )

