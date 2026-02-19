from __future__ import annotations

import logging
import time
from typing import Any

from openai import OpenAI
from pydantic import BaseModel

from .config import Config

logger = logging.getLogger(__name__)

MODEL = "gpt-5.2-codex"
RETRY_DELAYS = (2, 5, 15)


def _enforce_strict_schema(schema: dict) -> dict:
    """Add additionalProperties: false to all object types for OpenAI strict mode."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
    for key in ("properties", "$defs"):
        if key in schema:
            for value in schema[key].values():
                if isinstance(value, dict):
                    _enforce_strict_schema(value)
    if "items" in schema and isinstance(schema["items"], dict):
        _enforce_strict_schema(schema["items"])
    return schema


class OpenAIClient:
    def __init__(self, config: Config) -> None:
        self._client = OpenAI(api_key=config.openai_api_key)

    def create(
        self,
        prompt: str,
        developer_message: str,
        schema: type[BaseModel],
        reasoning_effort: str = "medium",
    ) -> Any:
        json_schema = _enforce_strict_schema(schema.model_json_schema())

        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            try:
                response = self._client.responses.create(
                    model=MODEL,
                    input=[
                        {"role": "developer", "content": developer_message},
                        {"role": "user", "content": prompt},
                    ],
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": schema.__name__,
                            "schema": json_schema,
                            "strict": True,
                        }
                    },
                    reasoning={"effort": reasoning_effort},
                )

                text = response.output_text
                return schema.model_validate_json(text)

            except Exception:
                if attempt == len(RETRY_DELAYS):
                    raise
                logger.warning(
                    "OpenAI request failed (attempt %d/%d), retrying in %ds",
                    attempt,
                    len(RETRY_DELAYS),
                    delay,
                    exc_info=True,
                )
                time.sleep(delay)
