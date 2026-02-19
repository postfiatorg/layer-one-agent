from __future__ import annotations

import logging
import time

import httpx

from .config import SERVICE_TYPES, LOG_LEVELS, Config
from .models import LogEntry

logger = logging.getLogger(__name__)

QUERY_TIMEOUT_SECONDS = 30
MAX_ENTRIES = 5000


def _build_logql() -> str:
    services = "|".join(SERVICE_TYPES)
    levels = "|".join(LOG_LEVELS)
    return f'{{service_type=~"{services}", level=~"{levels}"}}'


class LokiClient:
    def __init__(self, config: Config) -> None:
        self._base_url = config.loki_url.rstrip("/")
        self._window_minutes = config.query_window_minutes

    def query_errors(self) -> list[LogEntry]:
        now_ns = int(time.time() * 1e9)
        start_ns = now_ns - (self._window_minutes * 60 * int(1e9))

        params = {
            "query": _build_logql(),
            "start": str(start_ns),
            "end": str(now_ns),
            "limit": str(MAX_ENTRIES),
            "direction": "backward",
        }

        url = f"{self._base_url}/loki/api/v1/query_range"
        logger.info("Querying Loki: %s", url)

        response = httpx.get(url, params=params, timeout=QUERY_TIMEOUT_SECONDS)
        response.raise_for_status()

        data = response.json()
        return self._parse_streams(data)

    def _parse_streams(self, data: dict) -> list[LogEntry]:
        entries: list[LogEntry] = []
        streams = data.get("data", {}).get("result", [])

        for stream in streams:
            labels = stream.get("stream", {})
            hostname = labels.get("hostname", "unknown")
            service_type = labels.get("service_type", "unknown")
            module = labels.get("module", "unknown")
            level = labels.get("level", "unknown")

            for ts, message in stream.get("values", []):
                entries.append(
                    LogEntry(
                        timestamp=ts,
                        hostname=hostname,
                        service_type=service_type,
                        module=module,
                        level=level,
                        message=message,
                    )
                )

        logger.info("Parsed %d log entries from Loki", len(entries))
        return entries
