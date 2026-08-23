"""Pluggable alert notifiers (webhook + logging fallback).

We deliberately avoid a hard dependency on ``requests``/``httpx`` at
import time — the notifier lazily imports the transport it needs so
that installs without ``httpx`` still boot cleanly and fall through to
:class:`LoggingNotifier`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True, slots=True)
class Alert:
    """A single notification payload.

    ``kind`` identifies the producer (e.g. ``drift.severe``,
    ``training.failed``).  ``fields`` contains structured details that
    the receiver can render into a table or Slack block.
    """

    kind: str
    severity: Severity
    title: str
    summary: str
    fields: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""  # populated by the notifier if omitted

    def with_timestamp(self) -> Alert:
        if self.created_at:
            return self
        return Alert(
            kind=self.kind,
            severity=self.severity,
            title=self.title,
            summary=self.summary,
            fields=dict(self.fields),
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.with_timestamp())

    def to_slack_payload(self) -> dict[str, Any]:
        """Render the alert as a Slack-compatible ``blocks`` payload.

        Slack accepts an ``{"text": ..., "blocks": [...]}`` shape via
        both incoming-webhooks and the Web API.  Generic HTTP receivers
        can still parse ``text`` / ``kind`` / ``severity``.
        """
        icon = {"info": "🔵", "warning": "🟠", "critical": "🔴"}.get(self.severity, "⚪")
        stamped = self.with_timestamp()
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon} *{stamped.title}*\n{stamped.summary}",
                },
            }
        ]
        if stamped.fields:
            # Slack caps fields at 10 per section.
            field_items = list(stamped.fields.items())[:10]
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*{k}*\n{_stringify(v)}",
                        }
                        for k, v in field_items
                    ],
                }
            )
        return {
            "text": f"[{stamped.severity.upper()}] {stamped.title}",
            "kind": stamped.kind,
            "severity": stamped.severity,
            "created_at": stamped.created_at,
            "blocks": blocks,
            "fields": stamped.fields,
        }


@runtime_checkable
class AlertNotifier(Protocol):
    """Anything that can accept an :class:`Alert`."""

    async def notify(self, alert: Alert) -> bool:  # pragma: no cover — protocol
        ...


class NullNotifier:
    """Drop every alert on the floor (used when notifications are off)."""

    async def notify(self, alert: Alert) -> bool:
        return True


class LoggingNotifier:
    """Emit alerts as structured log lines only (no external I/O)."""

    async def notify(self, alert: Alert) -> bool:
        stamped = alert.with_timestamp()
        logger.log(
            _log_level_for(stamped.severity),
            "alert_emitted",
            extra={
                "alert_kind": stamped.kind,
                "alert_severity": stamped.severity,
                "alert_title": stamped.title,
                "alert_summary": stamped.summary,
                "alert_fields": stamped.fields,
                "alert_created_at": stamped.created_at,
            },
        )
        return True


class WebhookNotifier:
    """POST the alert as JSON to ``url`` (Slack-shaped by default).

    ``format`` = ``"slack"`` sends the block-kit payload; ``"generic"``
    sends the raw :meth:`Alert.to_dict` shape.  Failures are downgraded
    to a warning log and return ``False`` — the caller can decide
    whether to retry.
    """

    def __init__(
        self,
        url: str,
        *,
        format: Literal["slack", "generic"] = "slack",
        timeout_seconds: float = 5.0,
        min_severity: Severity = "info",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url.strip()
        self._format = format
        self._timeout = timeout_seconds
        self._min_severity = min_severity
        self._headers = {"Content-Type": "application/json", **(extra_headers or {})}

    async def notify(self, alert: Alert) -> bool:
        if not self._url:
            return False
        if _severity_rank(alert.severity) < _severity_rank(self._min_severity):
            return True  # filtered out but not a failure
        payload = alert.to_slack_payload() if self._format == "slack" else alert.to_dict()
        try:
            import httpx
        except ImportError:  # pragma: no cover — httpx is a hard dep already
            logger.warning(
                "webhook_notify_missing_httpx",
                extra={"alert_kind": alert.kind},
            )
            return False

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url,
                    content=json.dumps(payload, ensure_ascii=False, default=str),
                    headers=self._headers,
                )
        except Exception as exc:
            logger.warning(
                "webhook_notify_failed",
                extra={"alert_kind": alert.kind, "error": str(exc)},
            )
            return False

        if response.status_code >= 400:
            logger.warning(
                "webhook_notify_status_error",
                extra={
                    "alert_kind": alert.kind,
                    "status_code": response.status_code,
                    "body_preview": response.text[:200],
                },
            )
            return False
        return True


def build_notifier(
    *,
    webhook_url: str,
    format: Literal["slack", "generic"] = "slack",
    min_severity: Severity = "warning",
) -> AlertNotifier:
    """Convenience factory used by the DI container.

    Empty ``webhook_url`` → :class:`LoggingNotifier` (safe default —
    alerts still land in structured logs).
    """
    if not webhook_url.strip():
        return LoggingNotifier()
    return WebhookNotifier(webhook_url, format=format, min_severity=min_severity)


def _severity_rank(sev: Severity) -> int:
    return {"info": 0, "warning": 1, "critical": 2}.get(sev, 0)


def _log_level_for(sev: Severity) -> int:
    return {
        "info": logging.INFO,
        "warning": logging.WARNING,
        "critical": logging.ERROR,
    }.get(sev, logging.INFO)


def _stringify(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return ", ".join(_stringify(v) for v in value)
    return str(value)


__all__ = [
    "Alert",
    "AlertNotifier",
    "LoggingNotifier",
    "NullNotifier",
    "WebhookNotifier",
    "build_notifier",
]
