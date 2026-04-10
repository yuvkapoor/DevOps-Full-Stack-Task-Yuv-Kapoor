import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    anthropic_api_key: str | None
    anthropic_model: str
    gemini_api_key: str | None
    gemini_model: str
    devops_agent_token: str | None
    github_repo: str | None
    github_actions_token: str | None
    github_workflow_file: str
    github_workflow_ref: str
    mcp_server_url: str | None
    mcp_timeout_seconds: float
    supabase_project_id: str | None
    supabase_project_url: str | None
    supabase_api_key: str | None
    supabase_anon_key: str | None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=_first_env(
            "DATABASE_URL",
            "SUPABASE_DB_URL",
            "connection_string",
            "CONNECTION_STRING",
        ),
        anthropic_api_key=_first_env(
            "ANTHROPIC_API_KEY",
            "CLAUDE_API_KEY",
            "ANTHROPIC_KEY",
        ),
        anthropic_model=_first_env("ANTHROPIC_MODEL", "CLAUDE_MODEL")
        or "claude-3-5-sonnet-latest",
        gemini_api_key=_first_env("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        gemini_model=_first_env("GEMINI_MODEL", "GOOGLE_MODEL")
        or "gemini-2.5-flash",
        devops_agent_token=_first_env("DEVOPS_AGENT_TOKEN"),
        github_repo=_first_env("GITHUB_REPO"),
        github_actions_token=_first_env("GITHUB_ACTIONS_TOKEN"),
        github_workflow_file=_first_env("GITHUB_WORKFLOW_FILE") or "ci-cd.yml",
        github_workflow_ref=_first_env("GITHUB_WORKFLOW_REF") or "main",
        mcp_server_url=_first_env("MCP_SERVER_URL"),
        mcp_timeout_seconds=float(_first_env("MCP_TIMEOUT_SECONDS") or "12"),
        supabase_project_id=_first_env("SUPABASE_PROJECT_ID", "project_id", "PROJECT_ID"),
        supabase_project_url=_first_env("SUPABASE_PROJECT_URL", "project_url", "PROJECT_URL"),
        supabase_api_key=_first_env(
            "SUPABASE_API_KEY",
            "SUPABASE_PUBLISHABLE_KEY",
            "API_key",
            "API_KEY",
        ),
        supabase_anon_key=_first_env(
            "SUPABASE_ANON_KEY",
            "anon_public_key",
            "ANON_PUBLIC_KEY",
        ),
    )
