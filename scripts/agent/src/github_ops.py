from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import REPO_CLONE_PATH, Config
from .models import CodeFix

logger = logging.getLogger(__name__)


def _run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
    return result.stdout.strip()


class GitHubOps:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._repo_path = REPO_CLONE_PATH

    def pull_latest(self) -> None:
        logger.info("Pulling latest main branch")
        _run(["git", "fetch", "origin", "main"], cwd=self._repo_path)
        _run(["git", "checkout", "main"], cwd=self._repo_path)
        _run(["git", "reset", "--hard", "origin/main"], cwd=self._repo_path)

    def branch_exists(self, branch: str) -> bool:
        output = _run(
            ["git", "ls-remote", "--heads", "origin", branch],
            cwd=self._repo_path,
            check=False,
        )
        return bool(output.strip())

    def pr_exists_for_branch(self, branch: str) -> bool:
        output = _run(
            [
                "gh", "pr", "list",
                "--repo", self._config.target_repo,
                "--head", branch,
                "--state", "open",
                "--json", "number",
            ],
            cwd=self._repo_path,
            check=False,
        )
        return output.strip() not in ("", "[]")

    def create_branch_and_commit(
        self,
        branch: str,
        fixes: list[CodeFix],
        message: str,
    ) -> None:
        logger.info("Creating branch %s with %d file changes", branch, len(fixes))

        _run(["git", "checkout", "-b", branch], cwd=self._repo_path)

        for fix in fixes:
            file_path = self._repo_path / fix.path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(fix.modified_content)

        _run(
            ["git", "add"] + [fix.path for fix in fixes],
            cwd=self._repo_path,
        )
        _run(["git", "commit", "-m", message], cwd=self._repo_path)
        _run(["git", "push", "-u", "origin", branch], cwd=self._repo_path)

        _run(["git", "checkout", "main"], cwd=self._repo_path)

    def create_pr(self, branch: str, title: str, body: str) -> str:
        logger.info("Creating PR: %s", title)

        output = _run(
            [
                "gh", "pr", "create",
                "--repo", self._config.target_repo,
                "--base", "main",
                "--head", branch,
                "--title", title,
                "--body", body,
                "--reviewer", self._config.reviewer,
            ],
            cwd=self._repo_path,
        )

        pr_url = output.strip().splitlines()[-1]
        logger.info("Created PR: %s", pr_url)
        return pr_url
