import json
import re
from typing import Any

import httpx


class DevOpsAgentError(RuntimeError):
    pass


def _docker_client():
    try:
        import docker  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise DevOpsAgentError("Docker SDK is not installed in the backend container.") from exc

    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:  # pragma: no cover
        raise DevOpsAgentError(
            "Cannot connect to Docker. Mount /var/run/docker.sock into the backend service."
        ) from exc


def _service_order(service: str) -> tuple[int, str]:
    preferred = {
        "nginx": 0,
        "frontend": 1,
        "backend": 2,
        "mcp-server": 3,
        "prometheus": 4,
        "grafana": 5,
        "loki": 6,
        "promtail": 7,
        "cadvisor": 8,
        "node-exporter": 9,
    }
    return (preferred.get(service, 50), service)


def _find_supachat_containers() -> list[Any]:
    client = _docker_client()
    try:
        containers = client.containers.list(all=True)
    except Exception as exc:  # pragma: no cover
        raise DevOpsAgentError(f"Failed to list Docker containers: {exc}") from exc

    selected = []
    for container in containers:
        labels = container.labels or {}
        project = labels.get("com.docker.compose.project")
        if project == "supachat" or container.name.startswith("supachat"):
            selected.append(container)
    return sorted(
        selected,
        key=lambda item: _service_order(
            (item.labels or {}).get("com.docker.compose.service", item.name)
        ),
    )


def _container_health(container: Any) -> str:
    health = ((container.attrs.get("State") or {}).get("Health") or {}).get("Status")
    if health:
        return str(health)
    status = (container.attrs.get("State") or {}).get("Status")
    return str(status or "unknown")


def _container_payload(container: Any) -> dict[str, Any]:
    labels = container.labels or {}
    service = labels.get("com.docker.compose.service", container.name)
    state = container.attrs.get("State") or {}
    image = (container.image.tags or [container.image.short_id])[0]
    return {
        "service": service,
        "name": container.name,
        "status": state.get("Status", container.status),
        "health": _container_health(container),
        "image": image,
    }


def _http_check(name: str, url: str) -> dict[str, Any]:
    try:
        response = httpx.get(url, timeout=6.0)
        body = response.text.strip()
        return {
            "name": name,
            "url": url,
            "ok": response.is_success,
            "status_code": response.status_code,
            "detail": body[:200] if body else "",
        }
    except Exception as exc:
        return {
            "name": name,
            "url": url,
            "ok": False,
            "status_code": None,
            "detail": str(exc),
        }


def _fallback_summary(title: str, facts: list[str]) -> str:
    if not facts:
        return f"{title}: nothing noteworthy was detected."
    return f"{title}: " + " ".join(facts)


def _gemini_devops_summary(settings: Any, title: str, payload: dict[str, Any]) -> str | None:
    if not settings.gemini_api_key:
        return None

    prompt = (
        "You are a DevOps incident assistant.\n"
        "Summarize the operational state in plain English.\n"
        "Mention the likely issue, impact, and next action in 4 short bullet points max.\n"
        "Be concrete and concise.\n\n"
        f"Task: {title}\n"
        f"Payload: {json.dumps(payload)[:12000]}"
    )

    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            params={"key": settings.gemini_api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 600,
                },
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:  # pragma: no cover
        return None

    texts: list[str] = []
    for candidate in data.get("candidates", []):
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []):
            text = (part.get("text") or "").strip()
            if text:
                texts.append(text)
    return "\n\n".join(texts) if texts else None


def diagnose_stack(settings: Any) -> dict[str, Any]:
    containers = [_container_payload(container) for container in _find_supachat_containers()]

    checks = [
        _http_check("backend", "http://localhost:8000/health"),
        _http_check("mcp-server", "http://mcp-server:8000/health"),
        _http_check("frontend", "http://frontend/"),
        _http_check("nginx", "http://nginx/nginx-health"),
        _http_check("prometheus", "http://prometheus:9090/-/healthy"),
        _http_check("grafana", "http://grafana:3000/api/health"),
        _http_check("loki", "http://loki:3100/ready"),
    ]

    unhealthy_services = [
        item["service"] for item in containers if item["health"] not in {"healthy", "running"}
    ]
    failed_checks = [item["name"] for item in checks if not item["ok"]]
    overall_status = "healthy" if not unhealthy_services and not failed_checks else "degraded"

    facts = [
        f"{len(containers)} SupaChat containers discovered.",
        f"Unhealthy containers: {', '.join(unhealthy_services) or 'none'}.",
        f"Failed health checks: {', '.join(failed_checks) or 'none'}.",
    ]
    payload = {
        "overall_status": overall_status,
        "containers": containers,
        "checks": checks,
    }

    summary = _gemini_devops_summary(settings, "Diagnose current SupaChat stack", payload)
    if not summary:
        summary = _fallback_summary("Stack diagnosis", facts)

    return {
        "summary": summary,
        "overall_status": overall_status,
        "containers": containers,
        "checks": checks,
    }


def _match_service_container(service: str) -> Any:
    service = service.strip().lower()
    if not service:
        raise DevOpsAgentError("Service name is required.")

    candidates = []
    for container in _find_supachat_containers():
        payload = _container_payload(container)
        if payload["service"].lower() == service:
            return container
        if service in payload["service"].lower() or service in payload["name"].lower():
            candidates.append(container)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = ", ".join(_container_payload(item)["service"] for item in candidates)
        raise DevOpsAgentError(f"Service name '{service}' is ambiguous. Matches: {names}")
    raise DevOpsAgentError(f"Unknown service '{service}'.")


def summarize_logs(settings: Any, service: str, tail: int = 120, errors_only: bool = False) -> dict[str, Any]:
    container = _match_service_container(service)
    try:
        raw_logs = container.logs(tail=max(20, min(tail, 400))).decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover
        raise DevOpsAgentError(f"Unable to read logs for {service}: {exc}") from exc

    lines = [line for line in raw_logs.splitlines() if line.strip()]
    if errors_only:
        lines = [line for line in lines if re.search(r"error|exception|traceback|failed", line, re.IGNORECASE)]

    excerpt = "\n".join(lines[-80:]).strip()
    if not excerpt:
        excerpt = "No matching log lines were found."

    payload = {
        "service": service,
        "tail": tail,
        "errors_only": errors_only,
        "excerpt": excerpt,
    }
    summary = _gemini_devops_summary(
        settings,
        f"Summarize {'error ' if errors_only else ''}logs for service {service}",
        payload,
    )
    if not summary:
        summary = _fallback_summary(
            "Log summary",
            [
                f"Service: {service}.",
                f"Scanned last {tail} lines.",
                "Errors only filter is on." if errors_only else "Showing recent mixed logs.",
            ],
        )

    return {
        "summary": summary,
        "service": service,
        "tail": tail,
        "errors_only": errors_only,
        "log_excerpt": excerpt,
    }


def restart_services(settings: Any, services: list[str]) -> dict[str, Any]:
    if not services:
        raise DevOpsAgentError("At least one service must be provided.")

    restarted: list[str] = []
    for service in services:
        container = _match_service_container(service)
        try:
            container.restart(timeout=15)
        except Exception as exc:  # pragma: no cover
            raise DevOpsAgentError(f"Failed to restart service '{service}': {exc}") from exc
        restarted.append(_container_payload(container)["service"])

    payload = {"restarted_services": restarted}
    summary = _gemini_devops_summary(settings, "Summarize restart operation", payload)
    if not summary:
        summary = _fallback_summary(
            "Restart completed",
            [f"Restarted services: {', '.join(restarted)}."],
        )

    return {"summary": summary, "restarted_services": restarted}


def trigger_deploy(settings: Any, ref: str | None = None) -> dict[str, Any]:
    if not settings.github_repo or not settings.github_actions_token:
        raise DevOpsAgentError(
            "Deployment trigger is not configured. Set GITHUB_REPO and GITHUB_ACTIONS_TOKEN."
        )

    workflow_file = settings.github_workflow_file or "ci-cd.yml"
    ref_to_use = (ref or settings.github_workflow_ref or "main").strip()

    try:
        response = httpx.post(
            f"https://api.github.com/repos/{settings.github_repo}/actions/workflows/{workflow_file}/dispatches",
            headers={
                "Authorization": f"Bearer {settings.github_actions_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": ref_to_use},
            timeout=15.0,
        )
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover
        raise DevOpsAgentError(f"Failed to trigger deployment workflow: {exc}") from exc

    summary = (
        f"Deployment workflow '{workflow_file}' was triggered for repo "
        f"{settings.github_repo} on ref '{ref_to_use}'."
    )
    return {
        "summary": summary,
        "workflow_file": workflow_file,
        "repo": settings.github_repo,
        "ref": ref_to_use,
    }


def explain_ci_failure(settings: Any, log_text: str) -> dict[str, Any]:
    cleaned = (log_text or "").strip()
    if not cleaned:
        raise DevOpsAgentError("CI log text is required.")

    payload = {"log_excerpt": cleaned[-12000:]}
    summary = _gemini_devops_summary(settings, "Explain this CI/CD failure log", payload)
    if not summary:
        summary = _fallback_summary(
            "CI explanation",
            [
                "Gemini summary unavailable.",
                "Review the provided excerpt for the first explicit error line.",
            ],
        )

    return {
        "summary": summary,
        "log_excerpt": cleaned[-4000:],
    }
