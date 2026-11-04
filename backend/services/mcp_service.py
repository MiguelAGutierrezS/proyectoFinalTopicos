import ast
import logging
import math
import operator
import platform
import re
import sqlite3
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
SPECS_DIR = ROOT_DIR / "specs"
DB_PATH = BACKEND_DIR / "localgem.db"

DAYS_ES = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]
MONTHS_ES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


# =====================================================================
# 1. Catálogo Estándar de Herramientas MCP (`tools/list`)
# =====================================================================


def list_mcp_tools() -> List[Dict[str, Any]]:
    """
    Retorna el catálogo de herramientas MCP locales siguiendo el contrato estándar
    `tools/list` de Model Context Protocol (REQ-MCP-01 y REQ-MCP-02).
    """
    return [
        {
            "name": "mcp_system_time",
            "description": (
                "Obtiene la fecha, hora exacta del sistema local en español, zona horaria, "
                "sistema operativo y versión de Python."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "mcp_calculator",
            "description": (
                "Evalúa expresiones matemáticas, porcentajes, raíces, trigonometría, "
                "estadísticas y operaciones financieras con precisión exacta."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Expresión matemática a evaluar (ej. 'sqrt(144) * 18.5' o '18% de 45320')",
                    }
                },
                "required": ["expression"],
            },
        },
        {
            "name": "mcp_sqlite_inspector",
            "description": (
                "Inspecciona en tiempo real y en modo solo-lectura la base de datos SQLite local "
                "(`localgem.db`): conteo de chats, mensajes, adjuntos, preferencias A/B y consultas SELECT seguras."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "sql_query": {
                        "type": "string",
                        "description": "Consulta SQL SELECT opcional (solo lectura). Si se omite, devuelve el diagnóstico completo de localgem.db.",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "mcp_workspace_reader",
            "description": (
                "Explora y lee de forma segura los documentos de especificación SDD (`/specs`), "
                "`README.md`, `backend/skills/` y archivos subidos del proyecto."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Archivo o carpeta a consultar (ej. 'specs', '01-requirements-ears.md', 'README.md', 'skills')",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "mcp_wikipedia_search",
            "description": (
                "Consulta en vivo la API de Wikipedia en español para obtener un resumen "
                "verificado sobre un concepto, personaje histórico, país o tecnología."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Término o tema a buscar en Wikipedia",
                    }
                },
                "required": ["query"],
            },
        },
    ]


# =====================================================================
# 2. Implementación de las 5 Herramientas MCP Locales
# =====================================================================


def _exec_system_time() -> str:
    """Ejecuta `mcp_system_time`: devuelve fecha, hora y diagnóstico del sistema local."""
    now = datetime.now().astimezone()
    day_name = DAYS_ES[now.weekday()]
    month_name = MONTHS_ES[now.month]
    formatted_date = f"{day_name}, {now.day} de {month_name} de {now.year}"
    formatted_time = now.strftime("%H:%M:%S")
    tz_name = now.strftime("%Z (UTC%z)")

    return (
        f"Fecha local actual: {formatted_date}\n"
        f"Hora local exacta: {formatted_time} ({tz_name})\n"
        f"Timestamp ISO: {now.isoformat()}\n"
        f"Sistema Operativo: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"Motor Python: {sys.version.split()[0]}"
    )


_ALLOWED_MATH_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "pi": math.pi,
    "e": math.e,
    "mean": statistics.mean,
    "median": statistics.median,
    "stdev": statistics.stdev,
    "sum": sum,
    "min": min,
    "max": max,
    "pow": pow,
}

_ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Constante no numérica: {node.value}")
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_safe_eval_node(el) for el in node.elts]
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_MATH_FUNCS:
            return _ALLOWED_MATH_FUNCS[node.id]
        raise ValueError(f"Identificador no permitido: '{node.id}'")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BIN_OPS:
            raise ValueError(f"Operador binario no soportado: {op_type.__name__}")
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        return _ALLOWED_BIN_OPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_UNARY_OPS:
            raise ValueError(f"Operador unario no soportado: {op_type.__name__}")
        return _ALLOWED_UNARY_OPS[op_type](_safe_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_MATH_FUNCS:
            raise ValueError("Función matemática no permitida")
        func = _ALLOWED_MATH_FUNCS[node.func.id]
        args = [_safe_eval_node(arg) for arg in node.args]
        return func(*args)
    raise ValueError(f"Expresión AST no soportada: {type(node).__name__}")


def _normalize_math_expression(raw_expr: str) -> str:
    """Convierte expresiones en lenguaje natural (ej. '18% de 45,320' o 'raíz cuadrada de 144') a sintaxis matemática."""
    expr = (raw_expr or "").strip()
    # Convertir "X% de Y" -> "(X / 100) * Y"
    pct_match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*%\s*(?:de|of)\s*(\d[\d.,]*)",
        expr,
        flags=re.IGNORECASE,
    )
    if pct_match:
        pct_val = pct_match.group(1).replace(",", ".")
        base_val = pct_match.group(2).replace(",", "")
        return f"({pct_val} / 100.0) * {base_val}"

    # Reemplazar separadores de miles tipo 45,320 cuando hay 3 dígitos tras la coma
    expr = re.sub(r"(\d),(\d{3})\b", r"\1\2", expr)
    expr = expr.replace("^", "**").replace("×", "*").replace("÷", "/")
    expr = re.sub(r"(?i)ra[íi]z\s+cuadrada\s+de\s+(\d+(?:\.\d+)?)", r"sqrt(\1)", expr)
    return expr.strip()


def _exec_calculator(arguments: Dict[str, Any]) -> str:
    """Ejecuta `mcp_calculator` de forma 100% segura mediante AST."""
    raw_expr = str(arguments.get("expression") or "").strip()
    if not raw_expr:
        raise ValueError("Debes proporcionar 'expression' para calcular.")

    normalized = _normalize_math_expression(raw_expr)
    parsed = ast.parse(normalized, mode="eval")
    result = _safe_eval_node(parsed)

    if isinstance(result, float):
        formatted = f"{result:,.6f}".rstrip("0").rstrip(".")
    else:
        formatted = f"{result:,}" if isinstance(result, int) else str(result)

    return (
        f"Expresión original: {raw_expr}\n"
        f"Fórmula evaluada: {normalized}\n"
        f"Resultado exacto: {result} (Formateado: {formatted})"
    )


def _exec_sqlite_inspector(arguments: Dict[str, Any]) -> str:
    """Ejecuta `mcp_sqlite_inspector` en modo solo-lectura sobre `localgem.db`."""
    if not DB_PATH.exists():
        return "La base de datos SQLite (`localgem.db`) aún no tiene archivo en disco."

    custom_sql = str(arguments.get("sql_query") or "").strip()
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"

    with sqlite3.connect(uri, uri=True, timeout=5.0) as conn:
        cursor = conn.cursor()

        if custom_sql:
            if not re.match(r"^\s*(SELECT|PRAGMA)\b", custom_sql, flags=re.IGNORECASE):
                raise ValueError("Por seguridad, mcp_sqlite_inspector solo permite consultas SELECT o PRAGMA.")
            rows = cursor.execute(custom_sql). fetchmany(25)
            col_names = [desc[0] for desc in (cursor.description or [])]
            lines = [f"Consulta ejecutada: `{custom_sql}`", f"Columnas: {', '.join(col_names)}"]
            for idx, r in enumerate(rows, start=1):
                lines.append(f"  {idx}. {dict(zip(col_names, r))}")
            return "\n".join(lines)

        chats_count = cursor.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
        msgs_count = cursor.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        user_msgs = cursor.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
        ai_msgs = cursor.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]
        att_count = cursor.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
        concise_prefs = cursor.execute(
            "SELECT COUNT(*) FROM user_preferences WHERE preferred_style='concise'"
        ).fetchone()[0]
        detailed_prefs = cursor.execute(
            "SELECT COUNT(*) FROM user_preferences WHERE preferred_style='detailed'"
        ).fetchone()[0]

        recent_chats = cursor.execute(
            "SELECT title, updated_at FROM chats ORDER BY updated_at DESC LIMIT 5"
        ).fetchall()

        recent_str = "\n".join(
            f"  - \"{row[0]}\" (actualizado: {row[1]})" for row in recent_chats
        ) or "  (Sin chats registrados)"

        return (
            " Diagnóstico en Vivo de SQLite (`localgem.db`):\n"
            f"- Total de conversaciones (`chats`): {chats_count}\n"
            f"- Total de mensajes (`messages`): {msgs_count} ({user_msgs} de usuario, {ai_msgs} de asistente)\n"
            f"- Total de archivos multimodales (`attachments`): {att_count}\n"
            f"- Preferencias A/B aprendidas (`user_preferences`): {concise_prefs} concisas (A) vs {detailed_prefs} detalladas (B)\n"
            f"- Últimos chats activos:\n{recent_str}"
        )


def _exec_workspace_reader(arguments: Dict[str, Any]) -> str:
    """Ejecuta `mcp_workspace_reader` para leer especificaciones SDD, Skills o estructura del proyecto."""
    target = str(arguments.get("target") or "specs").strip()
    target_lower = target.lower()

    # Si pide un archivo específico de /specs o README.md
    candidate_files = [
        SPECS_DIR / "01-requirements-ears.md",
        SPECS_DIR / "02-database-and-api.md",
        SPECS_DIR / "03-ai-orchestration.md",
        ROOT_DIR / "README.md",
        ROOT_DIR / "GEMINI.md",
    ]
    for fpath in candidate_files:
        if fpath.exists() and (fpath.name.lower() in target_lower or target_lower in fpath.name.lower()):
            content = fpath.read_text(encoding="utf-8")
            snippet = content[:3500]
            return f"Contenido de `{fpath.name}` (primeros 3,500 caracteres):\n\n{snippet}"

    spec_files = [f.name for f in sorted(SPECS_DIR.glob("*.md"))] if SPECS_DIR.exists() else []
    skills_dir = BACKEND_DIR / "skills"
    skill_folders = [d.name for d in sorted(skills_dir.iterdir()) if d.is_dir()] if skills_dir.exists() else []
    uploads_dir = BACKEND_DIR / "uploads"
    upload_count = len(list(uploads_dir.iterdir())) if uploads_dir.exists() else 0

    return (
        "Estructura verificada del Workspace (LocalGem Chat SDD):\n"
        f"- Especificaciones SDD en `/specs`: {', '.join(spec_files)}\n"
        f"- Skills modulares en `backend/skills/`: {', '.join(skill_folders)}\n"
        f"- Archivos subidos en `backend/uploads/`: {upload_count} archivos\n"
        "- Módulos Backend: `main.py`, `database.py`, `models.py`, `schemas.py`, "
        "`services/ollama_service.py`, `services/multimodal_processor.py`, `services/skills_service.py`, `services/mcp_service.py`"
    )


async def _exec_wikipedia_search(arguments: Dict[str, Any]) -> str:
    """Ejecuta `mcp_wikipedia_search` consultando la API de Wikipedia en español."""
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("Debes proporcionar un término 'query' para buscar en Wikipedia.")

    headers = {"User-Agent": "LocalGemChatMCP/2.0 (https://localhost:3000; local-academic-project)"}
    async with httpx.AsyncClient(timeout=6.0, headers=headers, follow_redirects=True) as client:
        # 1. Buscar el título exacto mediante opensearch
        search_url = (
            f"https://es.wikipedia.org/w/api.php?action=opensearch&search={quote(query)}&limit=1&namespace=0&format=json"
        )
        search_resp = await client.get(search_url)
        search_resp.raise_for_status()
        search_data = search_resp.json()

        titles = search_data[1] if isinstance(search_data, list) and len(search_data) > 1 else []
        best_title = titles[0] if titles else query

        summary_url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{quote(best_title)}"
        sum_resp = await client.get(summary_url)
        if sum_resp.status_code == 200:
            data = sum_resp.json()
            title = data.get("title", best_title)
            extract = data.get("extract", "")
            page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            if extract:
                return (
                    f"Fuente verificada Wikipedia ES — Artículo: '{title}'\n"
                    f"URL: {page_url}\n"
                    f"Resumen: {extract}"
                )

    return f"No se encontró un artículo exacto en Wikipedia para '{query}'."


# =====================================================================
# 3. Ejecutor Estándar MCP (`tools/call`) y Router Híbrido
# =====================================================================


async def call_mcp_tool(tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Ejecuta una herramienta MCP por nombre (`tools/call`), mide su tiempo de respuesta
    en milisegundos y captura cualquier error sin colapsar el flujo (REQ-MCP-05).
    """
    args = arguments or {}
    start_time = time.perf_counter()
    status: Literal["success", "error"] = "success"

    try:
        if tool_name == "mcp_system_time":
            result_str = _exec_system_time()
        elif tool_name == "mcp_calculator":
            result_str = _exec_calculator(args)
        elif tool_name == "mcp_sqlite_inspector":
            result_str = _exec_sqlite_inspector(args)
        elif tool_name == "mcp_workspace_reader":
            result_str = _exec_workspace_reader(args)
        elif tool_name == "mcp_wikipedia_search":
            result_str = await _exec_wikipedia_search(args)
        else:
            status = "error"
            result_str = f"Herramienta MCP '{tool_name}' no registrada en el servidor."
    except Exception as exc:
        status = "error"
        result_str = f"Error ejecutando {tool_name}: {exc}"
        logger.warning("Fallo controlado en herramienta MCP '%s': %s", tool_name, exc)

    duration_ms = max(1, int((time.perf_counter() - start_time) * 1000))
    return {
        "tool_name": tool_name,
        "arguments": args,
        "status": status,
        "result": result_str,
        "result_preview": result_str[:500],
        "duration_ms": duration_ms,
    }


def _extract_math_expression_from_text(user_text: str) -> Optional[str]:
    """Extrae una expresión matemática o de porcentaje si el mensaje del usuario la contiene."""
    text = (user_text or "").strip()

    # Caso 1: "18% de 45320"
    pct_match = re.search(
        r"(\d+(?:[.,]\d+)?\s*%\s*(?:de|of)\s*\d[\d.,]*)",
        text,
        flags=re.IGNORECASE,
    )
    if pct_match:
        return pct_match.group(1)

    # Caso 2: "raíz cuadrada de 144"
    sqrt_match = re.search(
        r"(ra[íi]z\s+cuadrada\s+de\s+\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if sqrt_match:
        return sqrt_match.group(1)

    # Caso 3: Expresión numérica con operadores aritméticos (ej. "450 * 12 + 300" o "sqrt(144) * 5")
    math_match = re.search(
        r"((?:sqrt|sin|cos|tan|log|log10|abs|pow)?\s*\(?\s*\d[\d.,]*\s*\)?\s*(?:[\+\-\*\/\^×÷]\s*\(?\s*(?:sqrt|sin|cos|tan|log)?\s*\(?\s*\d[\d.,]*\s*\)?\s*)+)",
        text,
    )
    if math_match:
        candidate = math_match.group(1).strip()
        # Evitar falsos positivos con fechas tipo 2026-11-03 o rangos simples 1-2
        if not re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", candidate) and any(
            op in candidate for op in ("+", "*", "/", "^", "×", "÷", "sqrt")
        ):
            return candidate
        if "-" in candidate and any(
            kw in text.lower() for kw in ("calcula", "cuánto es", "cuanto es", "resta", "resultado")
        ):
            return candidate

    return None


async def run_mcp_router_for_message(
    user_text: str,
    enable_mcp: bool = True,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Router Híbrido MCP (specs/03-ai-orchestration.md §9):
    Detecta de forma determinista qué herramientas MCP locales necesita la consulta del usuario,
    las ejecuta antes de llamar a Ollama y retorna `(lista_trazas_mcp, bloque_contexto_mcp)`.
    """
    if not enable_mcp or not user_text or not user_text.strip():
        return [], ""

    text = user_text.strip()
    text_lower = text.lower()
    planned_calls: List[Tuple[str, Dict[str, Any]]] = []

    # 1. Detectar solicitud de Fecha / Hora / Reloj / Estado del Sistema (`mcp_system_time`)
    if any(
        kw in text_lower
        for kw in (
            "qué hora es",
            "que hora es",
            "hora actual",
            "hora exacta",
            "qué día es hoy",
            "que dia es hoy",
            "fecha de hoy",
            "fecha actual",
            "en qué fecha estamos",
            "sistema operativo",
            "mcp_system_time",
        )
    ):
        planned_calls.append(("mcp_system_time", {}))

    # 2. Detectar solicitud de Cálculo Matemático / Porcentaje (`mcp_calculator`)
    math_expr = _extract_math_expression_from_text(text)
    if math_expr:
        planned_calls.append(("mcp_calculator", {"expression": math_expr}))

    # 3. Detectar solicitud de Inspección de Base de Datos SQLite (`mcp_sqlite_inspector`)
    if any(
        kw in text_lower
        for kw in (
            "cuántos chats",
            "cuantos chats",
            "cuántos mensajes",
            "cuantos mensajes",
            "estadísticas de la base de datos",
            "estadisticas de la base de datos",
            "inspecciona la base de datos",
            "localgem.db",
            "preferencias guardadas",
            "preferencias a/b",
            "mcp_sqlite_inspector",
        )
    ):
        planned_calls.append(("mcp_sqlite_inspector", {}))

    # 4. Detectar solicitud de Lectura del Workspace / Especificaciones SDD (`mcp_workspace_reader`)
    if any(
        kw in text_lower
        for kw in (
            "especificaciones del proyecto",
            "archivos en specs",
            "carpeta specs",
            "estructura del proyecto",
            "01-requirements",
            "02-database",
            "03-ai-orchestration",
            "mcp_workspace_reader",
        )
    ):
        target = "specs"
        for doc_name in ("01-requirements-ears.md", "02-database-and-api.md", "03-ai-orchestration.md", "readme.md"):
            if doc_name.split("-")[0] in text_lower or doc_name in text_lower:
                target = doc_name
                break
        planned_calls.append(("mcp_workspace_reader", {"target": target}))

    # 5. Detectar solicitud de Búsqueda en Wikipedia (`mcp_wikipedia_search`)
    wiki_match = re.search(
        r"(?:busca\s+en\s+wikipedia(?:\s+sobre)?|seg[úu]n\s+wikipedia|biograf[íi]a\s+de|qui[ée]n\s+fue)\s+([^\?\.\!\n]+)",
        text,
        flags=re.IGNORECASE,
    )
    if wiki_match:
        topic = wiki_match.group(1).strip(" '\",.:;¿?¡!")
        if len(topic) >= 2:
            planned_calls.append(("mcp_wikipedia_search", {"query": topic}))

    if not planned_calls:
        return [], ""

    traces: List[Dict[str, Any]] = []
    context_lines: List[str] = [
        "[RESULTADOS VERIFICADOS DE HERRAMIENTAS MCP (Model Context Protocol Local)]",
        "Utiliza obligatoriamente estos datos reales obtenidos en tiempo real por las herramientas MCP para responder al usuario:",
    ]

    for tool_name, tool_args in planned_calls:
        exec_res = await call_mcp_tool(tool_name, tool_args)
        traces.append(
            {
                "tool_name": exec_res["tool_name"],
                "arguments": exec_res["arguments"],
                "status": exec_res["status"],
                "result_preview": exec_res["result_preview"],
                "duration_ms": exec_res["duration_ms"],
            }
        )
        context_lines.append(
            f"\n--- Herramienta MCP: `{tool_name}` (Estado: {exec_res['status']}, {exec_res['duration_ms']} ms) ---\n"
            f"{exec_res['result']}\n---"
        )

    context_lines.append("[FIN DE RESULTADOS MCP]\n")
    return traces, "\n".join(context_lines)

