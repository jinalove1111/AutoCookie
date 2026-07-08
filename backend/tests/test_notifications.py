"""Tests for app.notifications.{telegram,discord}: clean no-op when
disabled/unconfigured, and that a simulated network failure never raises
out of the notify function (both must be safe to call from the paper
trading loop unconditionally).

Settings are mutated via `telegram.settings` / `discord.settings` (the
exact `settings` object each module holds a reference to internally),
not a fresh `from app.config import settings`, so these tests are
correct regardless of whether some other test in the same session has
since re-imported `app.config` into a different object (e.g. via the DB
fixtures' module purging in test_db_bootstrap.py / conftest.py).
"""

from __future__ import annotations

import httpx

from app.notifications import discord, telegram


# --------------------------------------------------------------------------
# telegram
# --------------------------------------------------------------------------


def test_telegram_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(telegram.settings, "ENABLE_TELEGRAM_ALERTS", False)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when disabled")

    monkeypatch.setattr(httpx, "post", _fail_if_called)

    telegram.send_telegram_alert("should not send")  # must not raise


def test_telegram_noop_when_enabled_but_unconfigured(monkeypatch):
    monkeypatch.setattr(telegram.settings, "ENABLE_TELEGRAM_ALERTS", True)
    monkeypatch.setattr(telegram.settings, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(telegram.settings, "TELEGRAM_CHAT_ID", "")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when unconfigured")

    monkeypatch.setattr(httpx, "post", _fail_if_called)

    telegram.send_telegram_alert("should not send")  # must not raise


def test_telegram_sends_when_enabled_and_configured(monkeypatch):
    monkeypatch.setattr(telegram.settings, "ENABLE_TELEGRAM_ALERTS", True)
    monkeypatch.setattr(telegram.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(telegram.settings, "TELEGRAM_CHAT_ID", "fake-chat-id")

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    telegram.send_telegram_alert("hello")

    assert len(calls) == 1
    url, payload = calls[0]
    assert "fake-token" in url
    assert payload["chat_id"] == "fake-chat-id"
    assert payload["text"] == "hello"


def test_telegram_network_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(telegram.settings, "ENABLE_TELEGRAM_ALERTS", True)
    monkeypatch.setattr(telegram.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(telegram.settings, "TELEGRAM_CHAT_ID", "fake-chat-id")

    def raise_network_error(*args, **kwargs):
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(httpx, "post", raise_network_error)

    telegram.send_telegram_alert("this will fail to send")  # must not raise


def test_telegram_unexpected_exception_does_not_raise(monkeypatch):
    monkeypatch.setattr(telegram.settings, "ENABLE_TELEGRAM_ALERTS", True)
    monkeypatch.setattr(telegram.settings, "TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setattr(telegram.settings, "TELEGRAM_CHAT_ID", "fake-chat-id")

    def raise_unexpected(*args, **kwargs):
        raise RuntimeError("something totally unexpected")

    monkeypatch.setattr(httpx, "post", raise_unexpected)

    telegram.send_telegram_alert("this will also fail")  # must not raise


# --------------------------------------------------------------------------
# discord
# --------------------------------------------------------------------------


def test_discord_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(discord.settings, "ENABLE_DISCORD_ALERTS", False)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when disabled")

    monkeypatch.setattr(httpx, "post", _fail_if_called)

    discord.send_discord_alert("should not send")  # must not raise


def test_discord_noop_when_enabled_but_unconfigured(monkeypatch):
    monkeypatch.setattr(discord.settings, "ENABLE_DISCORD_ALERTS", True)
    monkeypatch.setattr(discord.settings, "DISCORD_WEBHOOK_URL", "")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when unconfigured")

    monkeypatch.setattr(httpx, "post", _fail_if_called)

    discord.send_discord_alert("should not send")  # must not raise


def test_discord_network_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(discord.settings, "ENABLE_DISCORD_ALERTS", True)
    monkeypatch.setattr(discord.settings, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    def raise_network_error(*args, **kwargs):
        raise httpx.ConnectError("simulated network failure")

    monkeypatch.setattr(httpx, "post", raise_network_error)

    discord.send_discord_alert("this will fail to send")  # must not raise


def test_discord_sends_when_enabled_and_configured(monkeypatch):
    monkeypatch.setattr(discord.settings, "ENABLE_DISCORD_ALERTS", True)
    monkeypatch.setattr(discord.settings, "DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)

    discord.send_discord_alert("hello discord")

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://discord.example/webhook"
    assert payload["content"] == "hello discord"
