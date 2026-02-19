from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import REPO_CLONE_PATH, Config
from .models import BuildFixResult, FileRelevance, FileSelection, FixProposal, LogCluster
from .openai_client import OpenAIClient

logger = logging.getLogger(__name__)

MAX_RELEVANT_FILES = 5
ARCHITECTURE_DOC_MAX_CHARS = 8000

MODULE_DIR_HINTS: dict[str, list[str]] = {
    "LedgerConsensus": ["src/xrpld/consensus/", "src/xrpld/app/consensus/"],
    "ConsensusTransacting": ["src/xrpld/consensus/", "src/xrpld/app/consensus/"],
    "NetworkOPs": ["src/xrpld/app/misc/"],
    "Application": ["src/xrpld/app/main/"],
    "Overlay": ["src/xrpld/overlay/"],
    "Peer": ["src/xrpld/overlay/"],
    "NodeStore": ["src/xrpld/nodestore/"],
    "SHAMap": ["src/xrpld/shamap/"],
    "SHAMapStore": ["src/xrpld/shamap/"],
    "Amendments": ["src/xrpld/app/misc/"],
    "Transactor": ["src/xrpld/app/tx/"],
    "ValidatorList": ["src/xrpld/app/misc/"],
    "ValidatorSite": ["src/xrpld/app/misc/"],
    "LedgerMaster": ["src/xrpld/app/ledger/"],
    "LedgerCleaner": ["src/xrpld/app/ledger/"],
    "InboundLedger": ["src/xrpld/app/ledger/"],
    "OrderBookDB": ["src/xrpld/app/misc/"],
    "LoadManager": ["src/xrpld/app/misc/"],
    "Resource": ["src/libxrpl/resource/"],
    "Server": ["src/libxrpl/server/"],
    "PeerFinder": ["src/xrpld/peerfinder/"],
    "TaggedCache": ["include/xrpl/basics/"],
    "JobQueue": ["src/xrpld/core/"],
    "RPCHandler": ["src/xrpld/rpc/"],
    "Exclusions": ["src/xrpld/app/misc/"],
    "Loans": ["src/xrpld/app/tx/"],
    "Vaults": ["src/xrpld/app/tx/"],
    "PermissionedDEX": ["src/xrpld/app/tx/"],
}

SOURCE_EXTENSIONS = {".cpp", ".h", ".ipp"}

IDENTIFY_FILES_DEVELOPER_MSG = """\
You are a C++ source code expert for postfiatd (an XRPL fork).

Given a log error cluster and a list of candidate source files, select the {max_files} \
most relevant files for diagnosing and fixing the issue.

Consider: which files emit the log messages, which files contain the logic \
that could cause the error, and which files would need modification to fix it."""

GENERATE_FIX_DEVELOPER_MSG = """\
You are an expert C++20 developer working on postfiatd (an XRPL fork).

Generate a minimal, safe fix for the described problem. Guidelines:
- Make the smallest change necessary to fix the root cause.
- Preserve existing code style (JLOG macros for logging, RAII patterns, C++20 features).
- Do not introduce new dependencies.
- Do not change unrelated code.
- The fix must compile and not break existing behavior.
- Do NOT attempt to compile, build, or run any code. Only generate source file changes.
- Provide clear explanations of what changed and why.

Branch naming: agent-{{environment}}/{{cluster_slug}}
PR title: concise, imperative sentence describing the fix."""

FIX_BUILD_ERRORS_DEVELOPER_MSG = """\
You are an expert C++20 developer working on postfiatd (an XRPL fork).

A previous code change failed to compile. You are given:
- The build error logs from CI
- The current content of the files that were changed

Fix the compilation errors. Guidelines:
- Only modify files that have build errors.
- Make the minimal changes needed to fix the compilation.
- Do NOT attempt to compile, build, or run any code. Only generate source file changes.
- Preserve existing code style.
- The commit message should describe what build errors were fixed."""


class CodeAnalyzer:
    def __init__(self, config: Config, openai: OpenAIClient) -> None:
        self._config = config
        self._openai = openai
        self._repo_path = REPO_CLONE_PATH

    def fix_build_errors(
        self, build_logs: str, changed_files: list[str]
    ) -> BuildFixResult:
        file_contents = self._read_files_by_path(changed_files)

        prompt = (
            f"Build error logs:\n{build_logs}\n\n"
            f"Current file contents:\n{file_contents}"
        )

        return self._openai.create(
            prompt=prompt,
            developer_message=FIX_BUILD_ERRORS_DEVELOPER_MSG,
            schema=BuildFixResult,
            reasoning_effort="xhigh",
        )

    def generate_fix(self, cluster: LogCluster) -> FixProposal:
        relevant_files = self._identify_relevant_files(cluster)
        return self._generate_fix_proposal(cluster, relevant_files)

    def _identify_relevant_files(self, cluster: LogCluster) -> list[FileRelevance]:
        candidates = self._collect_candidate_files(cluster.module)
        candidate_list = "\n".join(str(f) for f in candidates[:200])

        prompt = (
            f"Problem: {cluster.title}\n"
            f"Module: {cluster.module}\n"
            f"Summary: {cluster.summary}\n"
            f"Sample messages:\n"
            + "\n".join(f"  - {m}" for m in cluster.sample_messages)
            + f"\n\nCandidate source files:\n{candidate_list}"
        )

        developer_msg = IDENTIFY_FILES_DEVELOPER_MSG.format(max_files=MAX_RELEVANT_FILES)

        result: FileSelection = self._openai.create(
            prompt=prompt,
            developer_message=developer_msg,
            schema=FileSelection,
            reasoning_effort="xhigh",
        )

        return result.files[:MAX_RELEVANT_FILES]

    def _generate_fix_proposal(
        self,
        cluster: LogCluster,
        relevant_files: list[FileRelevance],
    ) -> FixProposal:
        architecture_context = self._read_architecture_doc()
        file_contents = self._read_source_files(relevant_files)
        branch_name = f"agent-{self._config.environment}/{cluster.slug}"

        prompt = (
            f"Environment: {self._config.environment}\n"
            f"Branch: {branch_name}\n"
            f"Target repo: {self._config.target_repo}\n\n"
            f"Architecture context:\n{architecture_context}\n\n"
            f"Problem cluster:\n"
            f"  Slug: {cluster.slug}\n"
            f"  Title: {cluster.title}\n"
            f"  Module: {cluster.module}\n"
            f"  Severity: {cluster.severity}\n"
            f"  Summary: {cluster.summary}\n"
            f"  Occurrences: {cluster.occurrence_count}\n"
            f"  Sample messages:\n"
            + "\n".join(f"    - {m}" for m in cluster.sample_messages)
            + "\n\nSource files:\n"
            + file_contents
        )

        result: FixProposal = self._openai.create(
            prompt=prompt,
            developer_message=GENERATE_FIX_DEVELOPER_MSG,
            schema=FixProposal,
            reasoning_effort="xhigh",
        )

        return result

    def _collect_candidate_files(self, module: str) -> list[Path]:
        candidates: list[Path] = []

        hint_dirs = MODULE_DIR_HINTS.get(module, [])
        for hint in hint_dirs:
            hint_path = self._repo_path / hint
            if hint_path.is_dir():
                for f in hint_path.rglob("*"):
                    if f.suffix in SOURCE_EXTENSIONS:
                        candidates.append(f.relative_to(self._repo_path))

        if not candidates:
            candidates = self._grep_fallback(module)

        return candidates

    def _grep_fallback(self, module: str) -> list[Path]:
        try:
            result = subprocess.run(
                ["grep", "-rl", module, str(self._repo_path / "src")],
                capture_output=True,
                text=True,
                timeout=30,
            )
            paths = []
            for line in result.stdout.strip().splitlines():
                p = Path(line)
                if p.suffix in SOURCE_EXTENSIONS:
                    paths.append(p.relative_to(self._repo_path))
            return paths[:100]
        except (subprocess.TimeoutExpired, Exception):
            logger.warning("grep fallback failed for module %s", module)
            return []

    def _read_architecture_doc(self) -> str:
        doc_path = self._repo_path / "docs" / "Architecture.md"
        if not doc_path.exists():
            return "(Architecture document not found)"
        content = doc_path.read_text()
        if len(content) > ARCHITECTURE_DOC_MAX_CHARS:
            return content[:ARCHITECTURE_DOC_MAX_CHARS] + "\n... (truncated)"
        return content

    def _read_files_by_path(self, paths: list[str]) -> str:
        sections = []
        for path in paths:
            file_path = self._repo_path / path
            if not file_path.exists():
                sections.append(f"--- {path} ---\n(file not found)\n")
                continue
            try:
                content = file_path.read_text()
                sections.append(f"--- {path} ---\n{content}\n")
            except Exception:
                sections.append(f"--- {path} ---\n(read error)\n")
        return "\n".join(sections)

    def _read_source_files(self, files: list[FileRelevance]) -> str:
        sections = []
        for fr in files:
            file_path = self._repo_path / fr.path
            if not file_path.exists():
                sections.append(f"--- {fr.path} ---\n(file not found)\n")
                continue
            try:
                content = file_path.read_text()
                sections.append(f"--- {fr.path} ---\n{content}\n")
            except Exception:
                sections.append(f"--- {fr.path} ---\n(read error)\n")
        return "\n".join(sections)
