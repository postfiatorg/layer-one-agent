from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_CLONE_PATH = Path("/data/postfiatd")
STATE_DB_PATH = Path("/data/state.db")
LOCK_FILE_PATH = Path("/data/agent.lock")

SERVICE_TYPES = ("validator", "rpc", "archive")
LOG_LEVELS = ("warning", "error", "fatal")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Config:
    loki_url: str
    openai_api_key: str
    github_token: str
    environment: str
    target_repo: str
    reviewer: str
    max_prs_per_run: int
    query_window_minutes: int
    resend_api_key: str
    notification_email: str
    from_email: str

    @classmethod
    def from_env(cls) -> Config:
        environment = _require("ENVIRONMENT")
        return cls(
            loki_url=_require("LOKI_URL"),
            openai_api_key=_require("OPENAI_API_KEY"),
            github_token=_require("GITHUB_TOKEN"),
            environment=environment,
            target_repo=os.environ.get("TARGET_REPO", "postfiatorg/postfiatd"),
            reviewer=os.environ.get("REVIEWER", "DRavlic"),
            max_prs_per_run=int(os.environ.get("MAX_PRS_PER_RUN", "3")),
            query_window_minutes=int(os.environ.get("QUERY_WINDOW_MINUTES", "30")),
            resend_api_key=_require("RESEND_API_KEY"),
            notification_email=os.environ.get(
                "NOTIFICATION_EMAIL", "domagoj@deltahash.net"
            ),
            from_email=f"agent-{environment}@postfiat.org",
        )
