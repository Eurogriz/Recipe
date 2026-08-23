"""Unit tests for the alert notifier stack."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from formulation_workbench.infrastructure.notifications import (
    Alert,
    LoggingNotifier,
    NullNotifier,
    WebhookNotifier,
    build_notifier,
)

pytestmark = [pytest.mark.unit]


def _alert(severity: str = "warning") -> Alert:
    return Alert(
        kind="ml.drift",
        severity=severity,  # type: ignore[arg-type]
        title="Drift",
        summary="Feature drift detected",
        fields={"a": 1, "b": [1, 2]},
    )


async def test_null_notifier_returns_true_and_drops() -> None:
    n = NullNotifier()
    assert await n.notify(_alert()) is True


async def test_logging_notifier_emits_structured_log(caplog: Any) -> None:
    n = LoggingNotifier()
    with caplog.at_level(logging.WARNING):
        assert await n.notify(_alert("warning")) is True
    # At least one log record with the expected message.
    assert any("alert_emitted" in r.message for r in caplog.records)


def test_alert_to_slack_payload_has_blocks() -> None:
    payload = _alert("critical").to_slack_payload()
    assert payload["kind"] == "ml.drift"
    assert payload["severity"] == "critical"
    assert payload["blocks"], "must produce at least one Slack block"
    assert payload["blocks"][0]["type"] == "section"


async def test_webhook_notifier_posts_to_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["client_args"] = (args, kwargs)

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return httpx.Response(200)

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    n = WebhookNotifier("https://example.com/hook", format="slack")
    assert await n.notify(_alert("warning")) is True

    assert captured["url"] == "https://example.com/hook"
    payload = json.loads(captured["content"])
    assert payload["kind"] == "ml.drift"
    assert payload["severity"] == "warning"


async def test_webhook_notifier_reports_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, *, content: str, headers: dict[str, str]) -> Any:
            return httpx.Response(503, text="upstream down")

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    n = WebhookNotifier("https://example.com/hook")
    assert await n.notify(_alert()) is False


async def test_webhook_notifier_filters_by_min_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"n": 0}

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> Any:
            called["n"] += 1
            return httpx.Response(200)

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    n = WebhookNotifier("https://x/y", min_severity="critical")
    # A warning-level alert must be filtered out (no HTTP call).
    assert await n.notify(_alert("warning")) is True
    assert called["n"] == 0
    # A critical alert must make it through.
    assert await n.notify(_alert("critical")) is True
    assert called["n"] == 1


async def test_webhook_notifier_no_url_returns_false() -> None:
    n = WebhookNotifier("")
    assert await n.notify(_alert()) is False


def test_build_notifier_defaults_to_logging_when_url_missing() -> None:
    n = build_notifier(webhook_url="")
    assert isinstance(n, LoggingNotifier)


def test_build_notifier_returns_webhook_when_url_set() -> None:
    n = build_notifier(webhook_url="https://example.com/hook", format="generic")
    assert isinstance(n, WebhookNotifier)


async def test_webhook_notifier_swallows_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BoomClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: ...
        async def __aenter__(self) -> BoomClient:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, *args: Any, **kwargs: Any) -> Any:
            raise httpx.ConnectError("no route")

    monkeypatch.setattr("httpx.AsyncClient", BoomClient)
    n = WebhookNotifier("https://example.com/hook")
    assert await n.notify(_alert()) is False
