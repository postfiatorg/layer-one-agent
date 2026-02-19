from __future__ import annotations

import logging
import re
from collections import Counter

from .models import ClusterAnalysis, LogCluster, LogEntry
from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

MAX_CLUSTERS = 3
MAX_SAMPLES_PER_PATTERN = 5

HEX_PATTERN = re.compile(r"0x[0-9a-fA-F]+")
SEQ_PATTERN = re.compile(r"seq=\d+")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
HASH_PATTERN = re.compile(r"\b[0-9a-fA-F]{40,64}\b")
NUMBER_PATTERN = re.compile(r"\b\d{6,}\b")

DEVELOPER_MESSAGE = """\
You are a log analysis expert for PostFiat blockchain nodes (postfiatd, an XRPL fork).

Your task:
1. Group the provided log entries into distinct problem clusters.
2. Compare each cluster against the list of existing open patterns. If a new cluster \
describes the same root cause as an existing pattern (even with different wording), \
set its slug to match the existing pattern's slug to mark it as a duplicate.
3. For each cluster, evaluate whether it warrants a code fix:
   - Set needs_fix=true for genuine bugs, persistent errors, or recurring issues \
that indicate code problems.
   - Set needs_fix=false for transient/benign issues: one-time startup noise, \
expected warnings during provisioning, infrequent non-actionable warnings, \
network-level issues outside the codebase (peer disconnects from remote side, etc.).
   - When needs_fix=false, provide a clear skip_reason.
4. Assign severity: fatal > error > warning.
5. Return at most 3 clusters, prioritized by severity and frequency.

Slug format: lowercase, hyphens, URL-safe (e.g., "shamap-missing-node").
"""


def _normalize_message(message: str) -> str:
    normalized = HEX_PATTERN.sub("<hex>", message)
    normalized = SEQ_PATTERN.sub("seq=<N>", normalized)
    normalized = TIMESTAMP_PATTERN.sub("<timestamp>", normalized)
    normalized = HASH_PATTERN.sub("<hash>", normalized)
    normalized = NUMBER_PATTERN.sub("<N>", normalized)
    return normalized.strip()


def _deduplicate_messages(entries: list[LogEntry]) -> list[dict]:
    counter: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}

    for entry in entries:
        key = _normalize_message(entry.message)
        counter[key] += 1
        if key not in samples:
            samples[key] = []
        if len(samples[key]) < MAX_SAMPLES_PER_PATTERN:
            samples[key].append(entry.message)

    deduped = []
    for key, count in counter.most_common():
        deduped.append(
            {
                "normalized": key,
                "count": count,
                "samples": samples[key],
                "module": next(
                    (e.module for e in entries if _normalize_message(e.message) == key),
                    "unknown",
                ),
                "level": next(
                    (e.level for e in entries if _normalize_message(e.message) == key),
                    "unknown",
                ),
            }
        )

    return deduped


def _format_log_block(deduped: list[dict]) -> str:
    lines = []
    for item in deduped:
        lines.append(
            f"[{item['level'].upper()}] module={item['module']} "
            f"occurrences={item['count']}"
        )
        for sample in item["samples"]:
            lines.append(f"  | {sample}")
        lines.append("")
    return "\n".join(lines)


def _format_existing_patterns(patterns: list[dict]) -> str:
    if not patterns:
        return "No existing open patterns."

    lines = ["Existing open patterns (do not create duplicates):"]
    for p in patterns:
        lines.append(f"- slug={p['slug']}: {p['summary']}")
        for msg in p["sample_messages"][:3]:
            lines.append(f"    sample: {msg}")
    return "\n".join(lines)


class LogAnalyzer:
    def __init__(self, openai: OpenAIClient) -> None:
        self._openai = openai

    def cluster_logs(
        self,
        entries: list[LogEntry],
        existing_patterns: list[dict],
    ) -> list[LogCluster]:
        deduped = _deduplicate_messages(entries)
        if not deduped:
            return []

        log_block = _format_log_block(deduped)
        pattern_block = _format_existing_patterns(existing_patterns)

        prompt = f"Analyze these postfiatd log entries:\n\n{log_block}\n\n{pattern_block}"

        logger.info(
            "Clustering %d deduplicated patterns from %d entries",
            len(deduped),
            len(entries),
        )

        result: ClusterAnalysis = self._openai.create(
            prompt=prompt,
            developer_message=DEVELOPER_MESSAGE,
            schema=ClusterAnalysis,
            reasoning_effort="medium",
        )

        clusters = sorted(
            result.clusters,
            key=lambda c: (
                {"fatal": 0, "error": 1, "warning": 2}.get(c.severity, 3),
                -c.occurrence_count,
            ),
        )

        return clusters[:MAX_CLUSTERS]
