from __future__ import annotations

import logging

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Email, Mail, To

from .config import Config
from .models import LogCluster

logger = logging.getLogger(__name__)


def _build_html_body(clusters: list[LogCluster], environment: str) -> str:
    sections = []
    for cluster in clusters:
        samples_html = "".join(
            f"<li><code>{msg}</code></li>" for msg in cluster.sample_messages[:5]
        )
        sections.append(f"""
        <div style="margin-bottom: 24px; padding: 16px; border: 1px solid #ddd; border-radius: 8px;">
            <h3 style="margin-top: 0;">{cluster.title}</h3>
            <table style="margin-bottom: 12px;">
                <tr><td><strong>Module:</strong></td><td>{cluster.module}</td></tr>
                <tr><td><strong>Severity:</strong></td><td>{cluster.severity}</td></tr>
                <tr><td><strong>Occurrences:</strong></td><td>{cluster.occurrence_count}</td></tr>
            </table>
            <p><strong>Sample messages:</strong></p>
            <ul>{samples_html}</ul>
            <p><strong>Why no PR was created:</strong></p>
            <p>{cluster.skip_reason or "No reason provided."}</p>
        </div>""")

    body = "\n".join(sections)
    return f"""
    <html>
    <body style="font-family: -apple-system, sans-serif; max-width: 720px; margin: 0 auto;">
        <h2>PostFiat Agent Report — {environment}</h2>
        <p>The agent analyzed {len(clusters)} issue(s) and determined none warrant a code fix.</p>
        {body}
        <hr style="margin-top: 32px;">
        <p style="color: #666; font-size: 12px;">
            This is an automated report from the PostFiat Layer-One Agent ({environment}).
        </p>
    </body>
    </html>"""


class Notifier:
    def __init__(self, config: Config) -> None:
        self._client = SendGridAPIClient(api_key=config.sendgrid_api_key)
        self._from_email = config.from_email
        self._to_email = config.notification_email
        self._environment = config.environment

    def send_skip_notification(self, skipped_clusters: list[LogCluster]) -> None:
        if not skipped_clusters:
            return

        subject = (
            f"[PostFiat Agent] {self._environment}: "
            f"{len(skipped_clusters)} issue(s) analyzed — no fix needed"
        )

        html_body = _build_html_body(skipped_clusters, self._environment)

        message = Mail(
            from_email=Email(self._from_email),
            to_emails=To(self._to_email),
            subject=subject,
            html_content=Content("text/html", html_body),
        )

        try:
            response = self._client.send(message)
            logger.info(
                "Skip notification sent (status=%d, clusters=%d)",
                response.status_code,
                len(skipped_clusters),
            )
        except Exception:
            logger.error("Failed to send skip notification", exc_info=True)
