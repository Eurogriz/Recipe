"""Webhook / alert notifications for drift and quality events.

The package intentionally exposes a *tiny* interface (``AlertNotifier``)
so that the drift detector, quality-benchmark job runner, and future
producers can stay decoupled from the transport (HTTP webhook, log,
Slack, PagerDuty).  The default implementation is
:class:`WebhookNotifier`, which POSTs a JSON payload to a configurable
URL and gracefully degrades to a structured log line when the URL is
empty or the request fails.
"""

from __future__ import annotations

from .notifier import (
    Alert,
    AlertNotifier,
    LoggingNotifier,
    NullNotifier,
    WebhookNotifier,
    build_notifier,
)

__all__ = [
    "Alert",
    "AlertNotifier",
    "LoggingNotifier",
    "NullNotifier",
    "WebhookNotifier",
    "build_notifier",
]
