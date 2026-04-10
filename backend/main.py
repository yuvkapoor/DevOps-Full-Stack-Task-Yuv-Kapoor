import logging
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

from database import execute_query, test_connection
from devops_agent import (
    DevOpsAgentError,
    diagnose_stack,
    explain_ci_failure,
    restart_services,
    summarize_logs,
    trigger_deploy,
)
from mcp_tools import SYSTEM_PROMPT, TOOLS
from settings import get_settings

logger = logging.getLogger("supachat")
handler = logging.StreamHandler()
handler.setFormatter(jsonlogger.JsonFormatter())
if not logger.handlers:
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False
uvicorn_logger = logging.getLogger("uvicorn.error")

settings = get_settings()
anthropic = None
if settings.anthropic_api_key:
    try:
        import anthropic  # type: ignore
    except ImportError:  # pragma: no cover
        anthropic = None

app = FastAPI(title="SupaChat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

claude = (
    anthropic.Anthropic(api_key=settings.anthropic_api_key)
    if anthropic and settings.anthropic_api_key
    else None
)

query_history: list[dict[str, Any]] = []


def _require_devops_token(x_devops_token: str | None) -> None:
    expected = settings.devops_agent_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="DevOps Agent is not configured. Set DEVOPS_AGENT_TOKEN in backend/.env.",
        )
    if x_devops_token != expected:
        raise HTTPException(status_code=401, detail="Invalid DevOps token.")


@app.on_event("startup")
async def log_startup_connectivity() -> None:
    db_ok = test_connection()
    if db_ok:
        uvicorn_logger.info("Database connected successfully")
    else:
        uvicorn_logger.error("Database connection failed during startup")


@app.on_event("shutdown")
async def log_shutdown_disconnect() -> None:
    uvicorn_logger.info("Database disconnected successfully")


@dataclass
class QueryPlan:
    sql: str
    chart_type: str = "none"
    x_key: Optional[str] = None
    y_key: Optional[str] = None
    source: str = "rules"


@dataclass
class GeminiDecision:
    mode: str
    plan: Optional[QueryPlan] = None
    answer: Optional[str] = None
    error: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    text: str
    sql: Optional[str] = None
    data: list[dict[str, Any]] = Field(default_factory=list)
    chart_type: str = "none"
    x_key: Optional[str] = None
    y_key: Optional[str] = None
    row_count: int = 0
    timestamp: str = ""


class DevOpsLogsRequest(BaseModel):
    service: str = "backend"
    tail: int = 120
    errors_only: bool = False


class DevOpsRestartRequest(BaseModel):
    services: list[str] = Field(default_factory=list)


class DevOpsDeployRequest(BaseModel):
    ref: Optional[str] = None


class DevOpsCiExplainRequest(BaseModel):
    log_text: str


MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_INFO = {"name": "supachat-mcp-server", "version": "1.0.0"}


def _mcp_tools_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for tool in TOOLS:
        catalog.append(
            {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "inputSchema": tool.get("input_schema", {}),
            }
        )
    return catalog


def _mcp_dispatch(method: str, params: dict[str, Any] | None) -> dict[str, Any]:
    params = params or {}

    if method == "initialize":
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": MCP_SERVER_INFO,
        }

    if method == "tools/list":
        return {"tools": _mcp_tools_catalog()}

    if method == "tools/call":
        name = (params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        if name != "execute_sql":
            raise ValueError(f"Unsupported tool '{name}'.")

        sql = (arguments.get("sql") or "").strip()
        if not sql:
            raise ValueError("Missing required argument: sql")

        rows = execute_query(sql)
        return {
            "content": [
                {"type": "text", "text": f"Returned {len(rows)} rows."},
                {"type": "json", "json": {"rows": rows, "row_count": len(rows)}},
            ],
            "isError": False,
        }

    if method == "ping":
        return {}

    raise KeyError(f"Unknown MCP method: {method}")


def _mcp_response_ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_response_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _execute_sql_via_mcp(sql: str) -> list[dict[str, Any]]:
    rpc_request = {
        "jsonrpc": "2.0",
        "id": "chat-exec",
        "method": "tools/call",
        "params": {"name": "execute_sql", "arguments": {"sql": sql}},
    }

    if settings.mcp_server_url:
        try:
            response = httpx.post(
                settings.mcp_server_url,
                json=rpc_request,
                timeout=settings.mcp_timeout_seconds,
            )
            response.raise_for_status()
            rpc_response = response.json()
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"MCP server request failed: {exc}") from exc
    else:
        try:
            result = _mcp_dispatch("tools/call", rpc_request["params"])
            rpc_response = _mcp_response_ok(rpc_request["id"], result)
        except Exception as exc:
            rpc_response = _mcp_response_error(rpc_request["id"], -32000, str(exc))

    if rpc_response.get("error"):
        error = rpc_response["error"]
        raise RuntimeError(f"MCP error {error.get('code')}: {error.get('message')}")

    result = rpc_response.get("result") or {}
    if result.get("isError"):
        content = result.get("content") or []
        reason = None
        for block in content:
            if block.get("type") == "text":
                reason = block.get("text")
                break
        raise RuntimeError(reason or "MCP tool returned isError=true")

    content = result.get("content") or []
    for block in content:
        if block.get("type") == "json":
            payload = block.get("json") or {}
            rows = payload.get("rows")
            if isinstance(rows, list):
                return rows

    raise RuntimeError("MCP response did not include rows payload")


@app.post("/mcp")
async def mcp_rpc(payload: dict[str, Any]):
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _mcp_response_error(request_id, -32600, "Invalid Request: jsonrpc must be '2.0'")

    method = (payload.get("method") or "").strip()
    if not method:
        return _mcp_response_error(request_id, -32600, "Invalid Request: method is required")

    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    try:
        result = _mcp_dispatch(method, params)
        return _mcp_response_ok(request_id, result)
    except KeyError as exc:
        return _mcp_response_error(request_id, -32601, str(exc))
    except ValueError as exc:
        return _mcp_response_error(request_id, -32602, str(exc))
    except Exception as exc:
        logger.error("mcp_dispatch_error", extra={"error": str(exc), "method": method})
        return _mcp_response_error(request_id, -32000, str(exc))


def _extract_window_days(message: str, default: int = 30) -> int:
    match = re.search(r"last\s+(\d+)\s+days?", message, re.IGNORECASE)
    return int(match.group(1)) if match else default


def _extract_top_limit(message: str, default: int = 10) -> int:
    match = re.search(r"\btop\s+(\d+)\b", message, re.IGNORECASE)
    return int(match.group(1)) if match else default


def _escape_like(value: str) -> str:
    return value.replace("'", "''").strip()


def _extract_topic_filter(message: str) -> Optional[str]:
    patterns = [
        r"for\s+(.+?)\s+articles",
        r"for\s+(.+?)\s+topic",
        r"about\s+(.+?)(?:\s+articles|\s+topic|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            topic = _escape_like(match.group(1))
            if topic:
                return topic
    return None


def _extract_views_subject(message: str) -> Optional[str]:
    patterns = [
        r"how\s+many\s+views?\s+did\s+(.+?)\s+get",
        r"views?\s+for\s+(.+?)(?:\s+in\s+last|\s*$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            subject = _escape_like(match.group(1))
            if subject:
                return subject
    return None


def _is_country_readership_query(message: str) -> bool:
    country_mentioned = bool(re.search(r"\bcountr(?:y|ies)\b", message, re.IGNORECASE))
    readership_metric_mentioned = bool(
        re.search(r"\b(reader|readers|reading|view|views|visitor|visitors)\b", message, re.IGNORECASE)
    )
    return country_mentioned and readership_metric_mentioned


def _is_db_analytics_query(message: str) -> bool:
    lowered = message.lower()
    has_entity = bool(
        re.search(
            r"\b(article|articles|topic|topics|author|authors|country|countries|post|posts|page\s*view|pageviews?)\b",
            lowered,
        )
    )
    has_metric = bool(
        re.search(
            r"\b(view|views|reader|readers|reading|visitor|visitors|like|likes|comment|comments|share|shares|engagement|session|sessions)\b",
            lowered,
        )
    )
    has_analytic_verb = bool(
        re.search(
            r"\b(top|most|least|count|trend|trends|plot|chart|compare|comparison|distribution|breakdown|daily|weekly|monthly|total|average|avg|sum|rank|group)\b",
            lowered,
        )
        or "how many" in lowered
    )
    has_time_window = bool(
        re.search(r"\blast\s+\d+\s+(day|days|week|weeks|month|months)\b", lowered)
    )

    return (has_metric and (has_entity or has_analytic_verb)) or (
        has_entity and has_analytic_verb
    ) or (has_time_window and (has_entity or has_metric))


def _is_greeting_or_smalltalk(message: str) -> bool:
    lowered = re.sub(r"\s+", " ", message.strip().lower())
    if not lowered:
        return False

    if re.search(
        r"\b(view|views|reader|readers|country|countries|topic|topics|article|articles|author|authors|engagement|like|likes|comment|comments|share|shares|trend|chart|plot|sql|database)\b",
        lowered,
    ):
        return False

    if re.search(r"\b(hi|hello|hey|yo|hola|namaste|good morning|good afternoon|good evening)\b", lowered):
        return True

    return bool(re.search(r"\b(how are you|how are you doing|what can you do|who are you|help)\b", lowered))


def _extract_json_object(raw_text: str) -> Optional[dict[str, Any]]:
    text = (raw_text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _sanitize_chart_type(value: Any) -> str:
    chart_type = str(value or "none").strip().lower()
    return chart_type if chart_type in {"bar", "line", "area", "pie", "none"} else "none"


def _decide_with_gemini(message: str) -> GeminiDecision:
    if not settings.gemini_api_key:
        return GeminiDecision(mode="unavailable", error="gemini_api_key_missing")

    planner_prompt = """
You are SupaChat's dynamic planner for a PostgreSQL blog analytics DB.

Schema:
- topics(id, name, created_at)
- articles(id, title, topic_id, author, published_at, created_at)
- page_views(id, article_id, viewed_at, country, session_id)
- engagements(id, article_id, likes, comments, shares, recorded_at)

Task:
Given the user's message, return STRICT JSON ONLY with one of two modes:

1) DB analytics question:
{
  "mode": "db",
  "sql": "SELECT ...",
  "chart_type": "bar|line|area|pie|none",
  "x_key": "column_or_null",
  "y_key": "column_or_null"
}

2) General/non-DB conversation:
{
  "mode": "general",
  "answer": "Natural helpful response for the user."
}

Rules:
- If answer should come from DB analytics, choose mode="db".
- SQL must be PostgreSQL, SELECT/CTE only, and use only schema tables above.
- Never invent metric values in text for db mode; db values will be computed after SQL execution.
- Prefer concise SQL with proper GROUP BY, ORDER BY, LIMIT where suitable.
- For time trends, use DATE_TRUNC.
- For country-specific reader questions, use page_views.country and COUNT(DISTINCT session_id).
- Output valid JSON only. No markdown, no extra commentary.
    """.strip()

    payload: dict[str, Any] | None = None
    for attempt in range(3):
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
                params={"key": settings.gemini_api_key},
                json={
                    "contents": [
                        {
                            "parts": [
                                {"text": planner_prompt},
                                {"text": f"User message: {message}"},
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 900,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=25.0,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else None
            retryable = status in {429, 500, 502, 503, 504}
            if retryable and attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            logger.warning(
                "gemini_planner_failed",
                extra={
                    "error": str(exc),
                    "model": settings.gemini_model,
                    "status_code": status,
                    "attempt": attempt + 1,
                },
            )
            return GeminiDecision(mode="error", error=str(exc))
        except Exception as exc:  # pragma: no cover
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            logger.warning(
                "gemini_planner_failed",
                extra={"error": str(exc), "model": settings.gemini_model, "attempt": attempt + 1},
            )
            return GeminiDecision(mode="error", error=str(exc))

    if payload is None:
        return GeminiDecision(mode="error", error="gemini_planner_no_payload")

    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []):
            text = (part.get("text") or "").strip()
            if text:
                texts.append(text)

    if not texts:
        return GeminiDecision(mode="error", error="gemini_empty_response")

    parsed = _extract_json_object(texts[0])
    if not parsed:
        return GeminiDecision(mode="error", error="gemini_invalid_json")

    mode = str(parsed.get("mode") or "").strip().lower()
    if mode == "db":
        sql = str(parsed.get("sql") or "").strip()
        if not sql:
            return GeminiDecision(mode="error", error="gemini_db_without_sql")

        plan = QueryPlan(
            sql=sql,
            chart_type=_sanitize_chart_type(parsed.get("chart_type")),
            x_key=parsed.get("x_key"),
            y_key=parsed.get("y_key"),
            source="gemini_dynamic",
        )
        return GeminiDecision(mode="db", plan=plan)

    if mode == "general":
        answer = (str(parsed.get("answer") or "")).strip()
        if answer:
            return GeminiDecision(mode="general", answer=answer)
        return GeminiDecision(mode="error", error="gemini_general_without_answer")

    return GeminiDecision(mode="error", error="gemini_unknown_mode")


def _generate_plan_with_rules(message: str) -> Optional[QueryPlan]:
    lowered = message.lower()
    days = _extract_window_days(message)
    limit = _extract_top_limit(message)
    topic_filter = _extract_topic_filter(message)
    views_subject = _extract_views_subject(message)

    if "trending" in lowered and "topic" in lowered:
        return QueryPlan(
            sql=f"""
SELECT t.name AS topic, COUNT(pv.id) AS views
FROM page_views pv
JOIN articles a ON a.id = pv.article_id
JOIN topics t ON t.id = a.topic_id
WHERE pv.viewed_at >= NOW() - INTERVAL '{days} days'
GROUP BY t.name
ORDER BY views DESC
LIMIT {limit};
            """.strip(),
            chart_type="bar",
            x_key="topic",
            y_key="views",
        )

    if "engagement" in lowered and "topic" in lowered:
        return QueryPlan(
            sql=f"""
SELECT
    t.name AS topic,
    COALESCE(SUM(e.likes), 0) AS likes,
    COALESCE(SUM(e.comments), 0) AS comments,
    COALESCE(SUM(e.shares), 0) AS shares,
    COALESCE(SUM(e.likes + e.comments + e.shares), 0) AS total_engagement
FROM topics t
LEFT JOIN articles a ON a.topic_id = t.id
LEFT JOIN engagements e ON e.article_id = a.id
GROUP BY t.name
ORDER BY total_engagement DESC
LIMIT {limit};
            """.strip(),
            chart_type="bar",
            x_key="topic",
            y_key="total_engagement",
        )

    if "daily" in lowered and "view" in lowered and ("trend" in lowered or "plot" in lowered):
        filters = [f"pv.viewed_at >= NOW() - INTERVAL '{days} days'"]
        if topic_filter:
            filters.append(
                f"(t.name ILIKE '%{topic_filter}%' OR a.title ILIKE '%{topic_filter}%')"
            )
        where_clause = " AND ".join(filters)
        return QueryPlan(
            sql=f"""
SELECT DATE_TRUNC('day', pv.viewed_at)::date AS day, COUNT(pv.id) AS views
FROM page_views pv
JOIN articles a ON a.id = pv.article_id
JOIN topics t ON t.id = a.topic_id
WHERE {where_clause}
GROUP BY day
ORDER BY day;
            """.strip(),
            chart_type="line",
            x_key="day",
            y_key="views",
        )

    if "author" in lowered and "view" in lowered:
        return QueryPlan(
            sql=f"""
SELECT a.author AS author, COUNT(pv.id) AS views
FROM page_views pv
JOIN articles a ON a.id = pv.article_id
WHERE pv.viewed_at >= NOW() - INTERVAL '{days} days'
GROUP BY a.author
ORDER BY views DESC
LIMIT {limit};
            """.strip(),
            chart_type="bar",
            x_key="author",
            y_key="views",
        )

    if "view" in lowered and views_subject:
        return QueryPlan(
            sql=f"""
SELECT '{views_subject}' AS subject, COUNT(pv.id) AS views
FROM page_views pv
JOIN articles a ON a.id = pv.article_id
JOIN topics t ON t.id = a.topic_id
WHERE pv.viewed_at >= NOW() - INTERVAL '{days} days'
  AND (
      t.name ILIKE '%{views_subject}%'
      OR a.title ILIKE '%{views_subject}%'
      OR a.author ILIKE '%{views_subject}%'
  );
            """.strip(),
            chart_type="none",
            x_key="subject",
            y_key="views",
        )

    if "article" in lowered and "like" in lowered:
        return QueryPlan(
            sql=f"""
SELECT a.title AS article, COALESCE(SUM(e.likes), 0) AS likes
FROM articles a
LEFT JOIN engagements e ON e.article_id = a.id
GROUP BY a.id, a.title
ORDER BY likes DESC
LIMIT {limit};
            """.strip(),
            chart_type="bar",
            x_key="article",
            y_key="likes",
        )

    if _is_country_readership_query(message):
        return QueryPlan(
            sql=f"""
SELECT pv.country AS country, COUNT(DISTINCT pv.session_id) AS readers
FROM page_views pv
WHERE pv.country IS NOT NULL AND TRIM(pv.country) <> ''
GROUP BY pv.country
ORDER BY readers DESC
LIMIT {limit};
            """.strip(),
            chart_type="pie",
            x_key="country",
            y_key="readers",
        )

    return None


def _generate_plan_with_anthropic(message: str) -> Optional[QueryPlan]:
    if not claude:
        return None

    try:
        response = claude.messages.create(
            model=settings.anthropic_model,
            max_tokens=900,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=[{"role": "user", "content": message}],
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("anthropic_translation_failed", extra={"error": str(exc)})
        return None

    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != "execute_sql":
            continue

        tool_input = getattr(block, "input", {}) or {}
        sql = (tool_input.get("sql") or "").strip()
        if not sql:
            return None

        chart_type = (tool_input.get("chart_type") or "none").strip().lower()
        if chart_type not in {"bar", "line", "area", "pie", "none"}:
            chart_type = "none"

        return QueryPlan(
            sql=sql,
            chart_type=chart_type,
            x_key=tool_input.get("x_key"),
            y_key=tool_input.get("y_key"),
            source="anthropic",
        )

    return None


def _answer_general_with_gemini(message: str) -> Optional[str]:
    if not settings.gemini_api_key:
        return None

    prompt = (
        "You are SupaChat's fallback assistant.\n"
        "Answer non-database questions clearly and briefly.\n"
        "If the user asks for analytics from the blog DB, tell them to ask with explicit metrics and dimensions.\n\n"
        f"User question: {message}"
    )

    payload: dict[str, Any] | None = None
    for attempt in range(3):
        try:
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
                params={"key": settings.gemini_api_key},
                json={
                    "contents": [
                        {
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 700,
                    },
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            break
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else None
            retryable = status in {429, 500, 502, 503, 504}
            if retryable and attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            logger.warning(
                "gemini_fallback_failed",
                extra={
                    "error": str(exc),
                    "model": settings.gemini_model,
                    "status_code": status,
                    "attempt": attempt + 1,
                },
            )
            return None
        except Exception as exc:  # pragma: no cover
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            logger.warning(
                "gemini_fallback_failed",
                extra={"error": str(exc), "model": settings.gemini_model, "attempt": attempt + 1},
            )
            return None

    if payload is None:
        return None

    texts: list[str] = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []):
            text = (part.get("text") or "").strip()
            if text:
                texts.append(text)

    if not texts:
        return None
    return "\n\n".join(texts)


def _answer_general_with_anthropic(message: str) -> Optional[str]:
    if not claude:
        return None

    try:
        response = claude.messages.create(
            model=settings.anthropic_model,
            max_tokens=700,
            system=(
                "You are SupaChat's fallback assistant. "
                "Answer non-database questions clearly and briefly. "
                "If the user asks for analytics from the blog DB, tell them to ask with explicit metrics and dimensions."
            ),
            messages=[{"role": "user", "content": message}],
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("anthropic_fallback_failed", extra={"error": str(exc)})
        return None

    chunks: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = (getattr(block, "text", "") or "").strip()
            if text:
                chunks.append(text)

    if not chunks:
        return None
    return "\n\n".join(chunks)


def _summarize_results(plan: QueryPlan, rows: list[dict[str, Any]], db_error: str | None) -> str:
    if db_error:
        return (
            "I translated your question into a database query, but the database rejected it. "
            f"Details: {db_error}"
        )

    if not rows:
        return (
            "I ran the query successfully, but it returned no rows. "
            "Try widening the date range or using a broader topic."
        )

    if plan.x_key and plan.y_key and plan.x_key in rows[0] and plan.y_key in rows[0]:
        leader = rows[0]
        return (
            f"I found {len(rows)} result rows. "
            f"The leading {plan.x_key.replace('_', ' ')} is {leader[plan.x_key]} "
            f"with {leader[plan.y_key]} {plan.y_key.replace('_', ' ')}."
        )

    preview = ", ".join(f"{key}={value}" for key, value in list(rows[0].items())[:3])
    return f"I found {len(rows)} result rows. The first row is {preview}."


@app.get("/health")
def health():
    db_ok = test_connection()
    providers: list[str] = []
    if settings.gemini_api_key:
        providers.append("gemini")
    if claude:
        providers.append("anthropic")
    provider_label = "/".join(providers) if providers else "none"
    mcp_mode = "external" if settings.mcp_server_url else "embedded"

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "translator": (
            f"{provider_label}_dynamic + db_execution"
            if providers
            else "rules_only"
        ),
        "mcp_mode": mcp_mode,
        "mcp_server_url": settings.mcp_server_url,
        "devops_agent": "enabled" if settings.devops_agent_token else "disabled",
        "project_id": settings.supabase_project_id,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/history")
def get_history():
    return {"history": query_history[-20:][::-1]}


@app.get("/api/devops/diagnose")
def api_devops_diagnose(x_devops_token: str | None = Header(default=None)):
    _require_devops_token(x_devops_token)
    try:
        return diagnose_stack(settings)
    except DevOpsAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/devops/logs")
def api_devops_logs(req: DevOpsLogsRequest, x_devops_token: str | None = Header(default=None)):
    _require_devops_token(x_devops_token)
    try:
        return summarize_logs(
            settings,
            service=req.service,
            tail=req.tail,
            errors_only=req.errors_only,
        )
    except DevOpsAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/devops/restart")
def api_devops_restart(req: DevOpsRestartRequest, x_devops_token: str | None = Header(default=None)):
    _require_devops_token(x_devops_token)
    try:
        return restart_services(settings, req.services)
    except DevOpsAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/devops/deploy")
def api_devops_deploy(req: DevOpsDeployRequest, x_devops_token: str | None = Header(default=None)):
    _require_devops_token(x_devops_token)
    try:
        return trigger_deploy(settings, req.ref)
    except DevOpsAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/devops/explain-ci")
def api_devops_explain_ci(
    req: DevOpsCiExplainRequest,
    x_devops_token: str | None = Header(default=None),
):
    _require_devops_token(x_devops_token)
    try:
        return explain_ci_failure(settings, req.log_text)
    except DevOpsAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    logger.info(
        "chat_request",
        extra={"user_query": req.message, "session_id": req.session_id},
    )

    try:
        if _is_greeting_or_smalltalk(req.message):
            text_response = (
                "Hi! I can help you explore your blog analytics. "
                "Try asking things like 'top countries by readers in last 30 days' "
                "or 'how many views did DevOps get'."
            )
            entry = {
                "id": len(query_history) + 1,
                "query": req.message,
                "sql": None,
                "row_count": 0,
                "chart_type": "none",
                "source": "builtin_smalltalk",
                "timestamp": datetime.utcnow().isoformat(),
            }
            query_history.append(entry)
            return ChatResponse(
                text=text_response,
                row_count=0,
                timestamp=datetime.utcnow().isoformat(),
            )

        decision = _decide_with_gemini(req.message)
        if decision.mode == "db" and decision.plan:
            plan = decision.plan
            data: list[dict[str, Any]] = []
            db_error = None
            logger.info(
                "executing_sql",
                extra={"sql": plan.sql, "translator": plan.source},
            )
            try:
                data = _execute_sql_via_mcp(plan.sql)
            except Exception as exc:
                db_error = str(exc)
                logger.error("sql_error", extra={"error": db_error, "sql": plan.sql})

            text_response = _summarize_results(plan, data, db_error)
            entry = {
                "id": len(query_history) + 1,
                "query": req.message,
                "sql": plan.sql,
                "row_count": len(data),
                "chart_type": plan.chart_type,
                "source": plan.source,
                "timestamp": datetime.utcnow().isoformat(),
            }
            query_history.append(entry)
            return ChatResponse(
                text=text_response,
                sql=plan.sql,
                data=data,
                chart_type=plan.chart_type,
                x_key=plan.x_key,
                y_key=plan.y_key,
                row_count=len(data),
                timestamp=datetime.utcnow().isoformat(),
            )

        if decision.mode == "general" and decision.answer:
            entry = {
                "id": len(query_history) + 1,
                "query": req.message,
                "sql": None,
                "row_count": 0,
                "chart_type": "none",
                "source": "gemini_general",
                "timestamp": datetime.utcnow().isoformat(),
            }
            query_history.append(entry)
            return ChatResponse(
                text=decision.answer,
                row_count=0,
                timestamp=datetime.utcnow().isoformat(),
            )

        if _is_db_analytics_query(req.message):
            text_response = (
                "I couldn't generate a valid dynamic SQL plan for this DB question right now. "
                "Please retry in a moment. If this continues, verify GEMINI_API_KEY, GEMINI_MODEL, and outbound network access."
            )
            entry = {
                "id": len(query_history) + 1,
                "query": req.message,
                "sql": None,
                "row_count": 0,
                "chart_type": "none",
                "source": "planner_unavailable_db",
                "timestamp": datetime.utcnow().isoformat(),
            }
            query_history.append(entry)
            return ChatResponse(
                text=text_response,
                row_count=0,
                timestamp=datetime.utcnow().isoformat(),
            )

        source = "gemini_fallback"
        fallback_text = _answer_general_with_gemini(req.message)
        if not fallback_text:
            source = "anthropic_fallback"
            fallback_text = _answer_general_with_anthropic(req.message)

        if fallback_text:
            text_response = fallback_text
        else:
            source = "no_fallback"
            if settings.gemini_api_key or claude:
                text_response = (
                    "AI fallback appears configured, but the provider call failed. "
                    "Please verify API key validity, model name, and outbound network access."
                )
            else:
                text_response = (
                    "This question is outside the blog analytics database, and AI fallback is not configured. "
                    "Set GEMINI_API_KEY (or ANTHROPIC_API_KEY) in backend/.env to enable non-database fallback answers."
                )

        entry = {
            "id": len(query_history) + 1,
            "query": req.message,
            "sql": None,
            "row_count": 0,
            "chart_type": "none",
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
        }
        query_history.append(entry)
        return ChatResponse(
            text=text_response,
            row_count=0,
            timestamp=datetime.utcnow().isoformat(),
        )

    except Exception as exc:
        logger.error("chat_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail=f"Error: {exc}") from exc


@app.get("/")
def root():
    return {"message": "SupaChat API is running", "docs": "/docs"}
