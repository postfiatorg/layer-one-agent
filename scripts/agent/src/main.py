from __future__ import annotations

import fcntl
import logging
import sys
import time

from .code_analyzer import CodeAnalyzer
from .config import LOCK_FILE_PATH, Config
from .github_ops import GitHubOps
from .log_analyzer import LogAnalyzer
from .loki_client import LokiClient
from .notifier import Notifier
from .openai_client import OpenAIClient
from .state import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _acquire_lock() -> object | None:
    LOCK_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_FILE_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except OSError:
        lock_file.close()
        return None


def run() -> None:
    lock = _acquire_lock()
    if lock is None:
        logger.info("Another run is in progress, exiting")
        return

    started_at = time.time()
    prs_created = 0
    errors = 0
    clusters_found = 0

    try:
        config = Config.from_env()
        state = StateManager()
        loki = LokiClient(config)
        openai = OpenAIClient(config)
        github = GitHubOps(config)
        analyzer = LogAnalyzer(openai)
        code_analyzer = CodeAnalyzer(config, openai)
        notifier = Notifier(config)

        github.pull_latest()

        # Fix agent PRs where the CI build ("PR Build Check") failed
        try:
            failed_prs = github.get_failed_build_prs()
            for pr_info in failed_prs:
                pr_number = pr_info["number"]
                branch = pr_info["branch"]
                logger.info("Fixing failed build for PR #%d (%s)", pr_number, branch)

                build_logs = github.get_build_error_logs(pr_number)
                changed_files = github.get_pr_changed_files(pr_number)

                if not build_logs or not changed_files:
                    logger.warning("Could not retrieve build logs or changed files for PR #%d", pr_number)
                    continue

                build_fix = code_analyzer.fix_build_errors(build_logs, changed_files)
                github.push_fix_commit(
                    branch=branch,
                    fixes=build_fix.fixes,
                    message=build_fix.commit_message,
                )
        except Exception:
            logger.error("Failed to process build fixes", exc_info=True)

        entries = loki.query_errors()
        if not entries:
            logger.info("No warning/error/fatal entries found, exiting")
            state.record_run(started_at, 0, 0, 0)
            return

        logger.info("Found %d log entries", len(entries))

        existing_patterns = state.get_open_patterns()
        clusters = analyzer.cluster_logs(entries, existing_patterns)
        clusters_found = len(clusters)

        existing_slugs = {p["slug"] for p in existing_patterns}
        fixable = [
            c for c in clusters
            if c.needs_fix and c.slug not in existing_slugs
        ]
        skipped = [c for c in clusters if not c.needs_fix]

        if skipped:
            logger.info("Sending skip notification for %d cluster(s)", len(skipped))
            try:
                notifier.send_skip_notification(skipped)
            except Exception:
                logger.error("Failed to send skip notification", exc_info=True)

        # Safety net: filter out clusters that already have branches or open PRs
        new_fixable = []
        for cluster in fixable:
            branch = f"agent-{config.environment}/{cluster.slug}"
            if github.branch_exists(branch):
                logger.info("Branch %s already exists, skipping", branch)
                continue
            if github.pr_exists_for_branch(branch):
                logger.info("Open PR for %s already exists, skipping", branch)
                continue
            new_fixable.append(cluster)

        for cluster in new_fixable[: config.max_prs_per_run]:
            try:
                logger.info("Processing cluster: %s", cluster.slug)

                proposal = code_analyzer.generate_fix(cluster)

                branch = proposal.branch_name
                github.create_branch_and_commit(
                    branch=branch,
                    fixes=proposal.fixes,
                    message=proposal.pr_title,
                )

                pr_url = github.create_pr(
                    branch=branch,
                    title=proposal.pr_title,
                    body=proposal.pr_body,
                )

                state.record_pattern(
                    slug=cluster.slug,
                    branch=branch,
                    pr_url=pr_url,
                    summary=cluster.summary,
                    sample_messages=cluster.sample_messages,
                )
                prs_created += 1

            except Exception:
                logger.error(
                    "Failed to process cluster %s", cluster.slug, exc_info=True
                )
                errors += 1

        run_id = state.record_run(started_at, clusters_found, prs_created, errors)

        for cluster in clusters:
            state.record_snapshot(
                run_id=run_id,
                cluster_slug=cluster.slug,
                sample_messages=cluster.sample_messages,
                occurrence_count=cluster.occurrence_count,
                module=cluster.module,
                severity=cluster.severity,
            )

        logger.info(
            "Run complete: clusters=%d, prs=%d, errors=%d",
            clusters_found,
            prs_created,
            errors,
        )

    except Exception:
        logger.critical("Fatal error in agent run", exc_info=True)
        try:
            StateManager().record_run(started_at, clusters_found, prs_created, errors + 1)
        except Exception:
            pass
        sys.exit(1)

    finally:
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()  # type: ignore[union-attr]
        except Exception:
            pass


if __name__ == "__main__":
    run()
