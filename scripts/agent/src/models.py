from __future__ import annotations

from pydantic import BaseModel


class LogEntry(BaseModel):
    timestamp: str
    hostname: str
    service_type: str
    module: str
    level: str
    message: str


class LogCluster(BaseModel):
    slug: str
    title: str
    summary: str
    module: str
    severity: str
    sample_messages: list[str]
    occurrence_count: int
    needs_fix: bool
    skip_reason: str | None = None


class ClusterAnalysis(BaseModel):
    clusters: list[LogCluster]


class FileRelevance(BaseModel):
    path: str
    reason: str


class FileSelection(BaseModel):
    files: list[FileRelevance]


class CodeFix(BaseModel):
    path: str
    original_content: str
    modified_content: str
    explanation: str


class FixProposal(BaseModel):
    cluster_slug: str
    branch_name: str
    pr_title: str
    pr_body: str
    fixes: list[CodeFix]
    relevant_files: list[FileRelevance]
