from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import stat
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_FILE = ROOT / "__init__.py"


def _load_plugin_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    hermes_constants = types.ModuleType("hermes_constants")
    hermes_constants.get_hermes_home = lambda: tmp_path
    monkeypatch.setitem(sys.modules, "hermes_constants", hermes_constants)

    module_name = f"telegram_business_history_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plugin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = _load_plugin_module(monkeypatch, tmp_path)
    for loaded in list(sys.modules.values()):
        history_support = getattr(loaded, "_history_support", None)
        if history_support is not None and hasattr(history_support, "reset_in_memory_caches"):
            history_support.reset_in_memory_caches()
    yield module
    for loaded in list(sys.modules.values()):
        history_support = getattr(loaded, "_history_support", None)
        if history_support is not None and hasattr(history_support, "reset_in_memory_caches"):
            history_support.reset_in_memory_caches()


@pytest.fixture
def enabled_history(monkeypatch: pytest.MonkeyPatch, plugin):
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "991")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")
    plugin._history_support.reset_in_memory_caches()
    return plugin


class FakeBot:
    def __init__(self, *, owner_id: int = 1000):
        self.owner_id = owner_id
        self.lookup_error: Exception | None = None
        self.calls: list[str] = []

    async def get_business_connection(self, business_connection_id: str):
        self.calls.append(business_connection_id)
        if self.lookup_error is not None:
            raise self.lookup_error
        return SimpleNamespace(user=SimpleNamespace(id=self.owner_id))


def make_business_text_update(
    *,
    text: str | None = "hello",
    caption: str | None = None,
    business_id: str = "business-123",
    chat_id: int = 991,
    message_id: int = 77,
    from_user_id: int | None = 2000,
    update_id: int = 42,
    date: datetime | None = None,
    reply_to_message_id: int | None = None,
    edited: bool = False,
    sender_business_bot_id: int | None = None,
):
    payload = SimpleNamespace(
        business_connection_id=business_id,
        chat=SimpleNamespace(id=chat_id),
        message_id=message_id,
        from_user=None if from_user_id is None else SimpleNamespace(id=from_user_id),
        date=date or datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        text=text,
        caption=caption,
        reply_to_message=None
        if reply_to_message_id is None
        else SimpleNamespace(message_id=reply_to_message_id),
        sender_business_bot=None
        if sender_business_bot_id is None
        else SimpleNamespace(id=sender_business_bot_id),
        api_kwargs={},
    )
    return SimpleNamespace(
        update_id=update_id,
        business_message=None if edited else payload,
        edited_business_message=payload if edited else None,
        deleted_business_messages=None,
    )


def make_business_media_update(
    *,
    caption: str = "caption-only",
    business_id: str = "business-123",
    chat_id: int = 991,
    message_id: int = 77,
    update_id: int = 42,
    date: datetime | None = None,
):
    payload = SimpleNamespace(
        business_connection_id=business_id,
        chat=SimpleNamespace(id=chat_id),
        message_id=message_id,
        from_user=SimpleNamespace(id=2000),
        date=date or datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
        text=None,
        caption=caption,
        voice=SimpleNamespace(file_id="voice-1"),
        reply_to_message=None,
        sender_business_bot=None,
        api_kwargs={},
    )
    return SimpleNamespace(
        update_id=update_id,
        business_message=payload,
        edited_business_message=None,
        deleted_business_messages=None,
    )


def make_deleted_update(
    *,
    business_id: str = "business-123",
    chat_id: int = 991,
    message_ids: tuple[int, ...] = (77,),
    update_id: int = 99,
):
    payload = SimpleNamespace(
        business_connection_id=business_id,
        chat=SimpleNamespace(id=chat_id),
        message_ids=list(message_ids),
        api_kwargs={},
    )
    return SimpleNamespace(
        update_id=update_id,
        business_message=None,
        edited_business_message=None,
        deleted_business_messages=payload,
    )


def load_records(plugin, *, business_id: str = "business-123", chat_id: int = 991):
    matches = plugin._history_support._iter_chat_matches(
        business_connection_id=business_id,
        chat_id=str(chat_id),
    )
    assert matches
    return matches[0][1]


def load_history_file(plugin, *, business_id: str = "business-123", chat_id: int = 991, month: str = "2026-07.jsonl") -> Path:
    root = plugin._history_support.history_root()
    chat_dirs = [path for path in root.glob("*/*") if path.is_dir()]
    assert chat_dirs
    for chat_dir in chat_dirs:
        records = plugin._history_support._load_chat_records_for_cli(chat_dir)
        if records and str(records[0].get("business_connection_id")) == business_id and str(records[0].get("chat_id")) == str(chat_id):
            return chat_dir / month
    raise AssertionError("history file not found")


class TimerHarness:
    class FakeTimer:
        def __init__(self, registry: list["TimerHarness.FakeTimer"], interval: float, function, args=None, kwargs=None):
            self._registry = registry
            self.interval = interval
            self.function = function
            self.args = tuple(args or ())
            self.kwargs = dict(kwargs or {})
            self.daemon = False
            self.cancelled = False
            self.started = False
            self.fired = False
            self._registry.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True

        def is_alive(self):
            return self.started and not self.cancelled and not self.fired

        def fire(self):
            if self.cancelled or self.fired:
                return
            self.fired = True
            self.function(*self.args, **self.kwargs)

    def __init__(self):
        self.timers: list[TimerHarness.FakeTimer] = []

    def timer(self, interval: float, function, args=None, kwargs=None):
        return self.FakeTimer(self.timers, interval, function, args=args, kwargs=kwargs)


@pytest.mark.asyncio
async def test_history_is_fail_closed_when_disabled_or_scope_is_missing(plugin, monkeypatch: pytest.MonkeyPatch):
    update = make_business_text_update()

    await plugin._history_support.observe_ptb_update(update, bot=FakeBot())
    assert not plugin._history_support._iter_chat_matches(chat_id="991")

    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    await plugin._history_support.observe_ptb_update(update, bot=FakeBot())
    assert not plugin._history_support._iter_chat_matches(chat_id="991")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connections", "chats", "matches"),
    [
        ("business-123", "991", True),
        ("other-connection", "991", False),
        ("*", "*", True),
    ],
)
async def test_history_scope_supports_exact_and_wildcard(
    plugin,
    monkeypatch: pytest.MonkeyPatch,
    connections: str,
    chats: str,
    matches: bool,
):
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", connections)
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", chats)

    await plugin._history_support.observe_ptb_update(make_business_text_update(), bot=FakeBot())

    found = bool(plugin._history_support._iter_chat_matches(chat_id="991"))
    assert found is matches


def test_history_config_defaults_disable_retention_and_parse_zero(plugin, monkeypatch: pytest.MonkeyPatch):
    config = plugin._history_support.history_config_from_env()
    assert config.retention_days == 0
    assert config.max_bytes == 1024 * 1024 * 1024

    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_RETENTION_DAYS", "0")
    config = plugin._history_support.history_config_from_env()
    assert config.retention_days == 0


@pytest.mark.asyncio
async def test_caption_only_media_update_creates_no_history_file(enabled_history):
    plugin = enabled_history

    wrote = await plugin._history_support.observe_ptb_update(
        make_business_media_update(),
        bot=FakeBot(),
    )

    assert wrote is False
    assert not plugin._history_support.history_root().exists()
    assert not plugin._history_support._iter_chat_matches(chat_id="991")


@pytest.mark.asyncio
async def test_raw_history_records_create_edit_delete_without_needing_gateway_dispatch(enabled_history, tmp_path: Path, monkeypatch):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    bot = FakeBot()

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="hello", message_id=77, update_id=1, date=base),
        bot=bot,
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="hello again", message_id=77, update_id=2, date=base, edited=True),
        bot=bot,
        now=base + timedelta(seconds=1),
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=3),
        bot=bot,
        now=base + timedelta(seconds=2),
    )

    records = load_records(plugin)
    assert [record["event_type"] for record in records] == [
        "message.created",
        "message.edited",
        "message.deleted",
    ]

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="hello", message_id=77, update_id=1, date=base),
        bot=bot,
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="hello again", message_id=77, update_id=2, date=base, edited=True),
        bot=bot,
        now=base + timedelta(seconds=1),
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=3),
        bot=bot,
        now=base + timedelta(seconds=2),
    )
    assert len(load_records(plugin)) == 3

    reloaded = _load_plugin_module(monkeypatch, tmp_path)
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "991")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")
    await reloaded._history_support.observe_ptb_update(
        make_business_text_update(text="hello", message_id=77, update_id=1, date=base),
        bot=bot,
        now=base,
    )
    await reloaded._history_support.observe_ptb_update(
        make_business_text_update(text="hello again", message_id=77, update_id=2, date=base, edited=True),
        bot=bot,
        now=base + timedelta(seconds=1),
    )
    await reloaded._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=3),
        bot=bot,
        now=base + timedelta(seconds=2),
    )
    matches = reloaded._history_support._iter_chat_matches(
        business_connection_id="business-123",
        chat_id="991",
    )
    assert len(matches[0][1]) == 3


@pytest.mark.asyncio
async def test_history_records_store_canonical_source_for_all_event_types(enabled_history):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    bot = FakeBot()

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="hello", message_id=77, update_id=1, date=base),
        bot=bot,
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="hello again", message_id=77, update_id=2, date=base, edited=True),
        bot=bot,
        now=base + timedelta(seconds=1),
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=3),
        bot=bot,
        now=base + timedelta(seconds=2),
    )
    result = plugin._history_support.maintain_history(now=base + timedelta(seconds=20))
    records = load_records(plugin)

    assert result.classified == 1
    assert {record["event_type"] for record in records} == {
        "message.created",
        "message.edited",
        "message.deleted",
        "deletion.classified",
    }
    assert {record["event_type"]: record["source"] for record in records} == {
        "message.created": "business_message",
        "message.edited": "edited_business_message",
        "message.deleted": "deleted_business_messages",
        "deletion.classified": "deleted_business_messages",
    }


@pytest.mark.asyncio
async def test_torn_tail_is_repaired_before_next_append_without_full_read_bytes(enabled_history, monkeypatch: pytest.MonkeyPatch):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="one", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    history_file = load_history_file(plugin)
    with history_file.open("ab") as handle:
        handle.write(b"{\"schema_version\":1")

    original_read_bytes = Path.read_bytes

    def _guarded_read_bytes(path: Path):
        if path == history_file:
            raise AssertionError("bounded torn-tail repair should not call Path.read_bytes()")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _guarded_read_bytes)
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="two", message_id=78, update_id=2, date=base),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )
    monkeypatch.setattr(Path, "read_bytes", original_read_bytes)

    lines = history_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["message_id"] for line in lines] == [77, 78]
    assert history_file.read_bytes().endswith(b"\n")


@pytest.mark.asyncio
async def test_second_append_uses_cached_chat_state_without_full_reload(enabled_history, monkeypatch: pytest.MonkeyPatch):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    original_loader = plugin._history_support._load_chat_state_from_disk
    loads = 0

    def _counting_loader(chat_dir: Path):
        nonlocal loads
        loads += 1
        return original_loader(chat_dir)

    monkeypatch.setattr(plugin._history_support, "_load_chat_state_from_disk", _counting_loader)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="one", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    assert loads == 1

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="two", message_id=78, update_id=2, date=base),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )
    assert loads == 1


@pytest.mark.asyncio
async def test_external_file_signature_change_invalidates_cached_chat_state(enabled_history, monkeypatch: pytest.MonkeyPatch):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    original_loader = plugin._history_support._load_chat_state_from_disk
    loads = 0

    def _counting_loader(chat_dir: Path):
        nonlocal loads
        loads += 1
        return original_loader(chat_dir)

    monkeypatch.setattr(plugin._history_support, "_load_chat_state_from_disk", _counting_loader)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="one", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    assert loads == 1

    history_file = load_history_file(plugin)
    external_record = plugin._history_support._build_event(
        event_type="message.created",
        source="business_message",
        observed_at=base + timedelta(seconds=2),
        telegram_update_id=200,
        business_connection_id="business-123",
        chat_id=991,
        message_id=700,
        message_at=base + timedelta(seconds=2),
        sender_id=999,
        direction="incoming",
        reply_to_message_id=None,
        text="external write",
    )
    with history_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(external_record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    stat_result = history_file.stat()
    os.utime(history_file, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1))

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="three", message_id=78, update_id=2, date=base),
        bot=FakeBot(),
        now=base + timedelta(seconds=3),
    )
    assert loads == 2
    assert [record["message_id"] for record in load_records(plugin)] == [77, 700, 78]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are required")
@pytest.mark.asyncio
async def test_history_permissions_are_private_on_posix(enabled_history):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="permissions", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )

    root = plugin._history_support.history_root()
    connection_dir = next(path for path in root.iterdir() if path.is_dir())
    chat_dir = next(path for path in connection_dir.iterdir() if path.is_dir())
    history_file = next(path for path in chat_dir.iterdir() if path.suffix == ".jsonl")
    lock_file = chat_dir / ".lock"

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(connection_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(chat_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(history_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_file.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_direction_resolution_accepts_sender_business_bot_and_owner_lookup(
    enabled_history,
    monkeypatch: pytest.MonkeyPatch,
):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "*")

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="bot", message_id=77, update_id=1, date=base, sender_business_bot_id=9),
        bot=FakeBot(owner_id=1234),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="owner", message_id=78, update_id=2, date=base, from_user_id=1000),
        bot=FakeBot(owner_id=1000),
        now=base + timedelta(seconds=1),
    )
    unknown_bot = FakeBot(owner_id=1000)
    unknown_bot.lookup_error = RuntimeError("lookup failed")
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(
            text="unknown",
            message_id=79,
            update_id=3,
            date=base,
            from_user_id=1000,
            business_id="business-999",
        ),
        bot=unknown_bot,
        now=base + timedelta(seconds=2),
    )

    directions = {record["message_id"]: record["direction"] for record in load_records(plugin)}
    assert directions[77] == "outgoing"
    assert directions[78] == "outgoing"
    unknown_records = load_records(plugin, business_id="business-999", chat_id=991)
    assert unknown_records[-1]["direction"] == "unknown"


async def _delete_and_classify(
    plugin,
    monkeypatch: pytest.MonkeyPatch,
    *,
    original_text: str | None,
    replacement_text: str | None,
    expected_status: str,
    replacement_message_id: int = 88,
    base: datetime | None = None,
    reload_after_delete: bool = False,
):
    base = base or datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "991")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")

    if original_text is not None:
        await plugin._history_support.observe_ptb_update(
            make_business_text_update(text=original_text, message_id=77, update_id=1, date=base),
            bot=FakeBot(),
            now=base,
        )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )
    if reload_after_delete:
        plugin = _load_plugin_module(monkeypatch, plugin._history_support.history_root().parents[3])
    if replacement_text is not None:
        await plugin._history_support.observe_ptb_update(
            make_business_text_update(text=replacement_text, message_id=replacement_message_id, update_id=3, date=base),
            bot=FakeBot(),
            now=base + timedelta(seconds=5),
        )
    result = plugin._history_support.maintain_history(now=base + timedelta(seconds=20))
    matches = plugin._history_support._iter_chat_matches(
        business_connection_id="business-123",
        chat_id="991",
    )
    records = matches[0][1]
    classifications = [record for record in records if record["event_type"] == "deletion.classified"]
    assert classifications
    assert classifications[-1]["classification"] == expected_status
    return classifications[-1], result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("original_text", "replacement_text", "expected_status", "expected_reason"),
    [
        ("Hello there", "hello   there", "likely_duplicate", "normalized_exact_duplicate"),
        ("Hello wrld", "Hello world", "likely_correction", "high_similarity_small_edit"),
        ("alpha beta gamma", "gamma beta alpha", "unexplained", "no_strong_match"),
        ("ok", "okay", "unexplained", "no_strong_match"),
        ("https://example.com 😄", "https://example.com 😄", "likely_duplicate", "normalized_exact_duplicate"),
    ],
)
async def test_deleted_message_classification_fixtures(
    plugin,
    monkeypatch: pytest.MonkeyPatch,
    original_text: str,
    replacement_text: str,
    expected_status: str,
    expected_reason: str,
):
    classification, _result = await _delete_and_classify(
        plugin,
        monkeypatch,
        original_text=original_text,
        replacement_text=replacement_text,
        expected_status=expected_status,
    )
    assert classification["classification_reason"] == expected_reason
    assert classification["classification_method"] == expected_reason


@pytest.mark.asyncio
async def test_deleted_message_without_original_is_unclassifiable(plugin, monkeypatch: pytest.MonkeyPatch):
    classification, result = await _delete_and_classify(
        plugin,
        monkeypatch,
        original_text=None,
        replacement_text="replacement",
        expected_status="unclassifiable",
    )
    assert classification["classification_reason"] == "missing_original"
    assert result.classified >= 1


@pytest.mark.asyncio
async def test_identical_pre_delete_message_is_not_classified_as_replacement(enabled_history):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    bot = FakeBot()

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="same text", message_id=77, update_id=1, date=base),
        bot=bot,
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="same text", message_id=88, update_id=2, date=base),
        bot=bot,
        now=base + timedelta(seconds=2),
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=3),
        bot=bot,
        now=base + timedelta(seconds=5),
    )
    plugin._history_support.maintain_history(now=base + timedelta(seconds=20))

    classifications = [record for record in load_records(plugin) if record["event_type"] == "deletion.classified"]

    assert classifications[-1]["classification"] == "unexplained"
    assert classifications[-1]["classification_reason"] == "no_strong_match"
    assert classifications[-1].get("replacement_message_id") is None


@pytest.mark.asyncio
async def test_deleted_message_classification_survives_restart(plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "991")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="Please call me back", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )

    reloaded = _load_plugin_module(monkeypatch, tmp_path)
    await reloaded._history_support.observe_ptb_update(
        make_business_text_update(text="Please call me back", message_id=88, update_id=3, date=base),
        bot=FakeBot(),
        now=base + timedelta(seconds=5),
    )
    result = reloaded._history_support.maintain_history(now=base + timedelta(seconds=20))
    records = load_records(reloaded)
    classifications = [record for record in records if record["event_type"] == "deletion.classified"]

    assert result.classified >= 1
    assert classifications[-1]["classification"] == "likely_duplicate"
    assert classifications[-1]["replacement_message_id"] == 88


@pytest.mark.asyncio
async def test_idle_deletion_is_classified_by_scheduler_without_manual_maintain(
    enabled_history,
    monkeypatch: pytest.MonkeyPatch,
):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    timers = TimerHarness()
    monkeypatch.setattr(plugin._history_support.threading, "Timer", timers.timer)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="Please call me back", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )

    assert len(timers.timers) == 1
    assert timers.timers[0].started is True
    assert not any(record["event_type"] == "deletion.classified" for record in load_records(plugin))

    timers.timers[0].fire()

    classifications = [record for record in load_records(plugin) if record["event_type"] == "deletion.classified"]
    assert classifications
    assert classifications[-1]["classification"] == "unexplained"


@pytest.mark.asyncio
async def test_startup_maintenance_classifies_overdue_deletions(plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "991")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    timers = TimerHarness()
    monkeypatch.setattr(plugin._history_support.threading, "Timer", timers.timer)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="Please call me back", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )

    plugin._history_support.reset_in_memory_caches()
    reloaded = _load_plugin_module(monkeypatch, tmp_path)
    result = reloaded._history_support.run_startup_maintenance(now=base + timedelta(seconds=20))
    records = load_records(reloaded)
    classifications = [record for record in records if record["event_type"] == "deletion.classified"]

    assert result.classified == 1
    assert classifications[-1]["classification"] == "unexplained"


@pytest.mark.asyncio
async def test_startup_maintenance_recovers_pending_timer_before_window(plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "991")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    first_timers = TimerHarness()
    monkeypatch.setattr(plugin._history_support.threading, "Timer", first_timers.timer)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="Please call me back", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )
    assert len(first_timers.timers) == 1

    plugin._history_support.reset_in_memory_caches()
    reloaded = _load_plugin_module(monkeypatch, tmp_path)
    second_timers = TimerHarness()
    monkeypatch.setattr(reloaded._history_support.threading, "Timer", second_timers.timer)
    result = reloaded._history_support.run_startup_maintenance(now=base + timedelta(seconds=5))

    assert result.classified == 0
    assert len(second_timers.timers) == 1
    assert second_timers.timers[0].interval == pytest.approx(6.0)

    second_timers.timers[0].fire()

    classifications = [record for record in load_records(reloaded) if record["event_type"] == "deletion.classified"]
    assert classifications
    assert classifications[-1]["classification"] == "unexplained"


@pytest.mark.asyncio
async def test_retention_and_size_prune_closed_partitions_but_preserve_active(enabled_history, monkeypatch: pytest.MonkeyPatch):
    plugin = enabled_history
    old_time = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    current_time = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="old month", message_id=77, update_id=1, date=old_time),
        bot=FakeBot(),
        now=old_time,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="current month", message_id=78, update_id=2, date=current_time),
        bot=FakeBot(),
        now=current_time,
    )

    old_file = load_history_file(plugin, month="2026-06.jsonl")
    current_file = load_history_file(plugin, month="2026-07.jsonl")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_RETENTION_DAYS", "20")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_MAX_BYTES", str(current_file.stat().st_size + 1))

    result = plugin._history_support.maintain_history(now=current_time)

    assert result.pruned_files >= 1
    assert not old_file.exists()
    assert current_file.exists()
    assert json.loads(current_file.read_text(encoding="utf-8").splitlines()[-1])["message_id"] == 78


@pytest.mark.asyncio
async def test_active_month_cap_failure_is_explicit(enabled_history, monkeypatch: pytest.MonkeyPatch):
    plugin = enabled_history
    current_time = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="x" * 1500, message_id=77, update_id=1, date=current_time),
        bot=FakeBot(),
        now=current_time,
    )
    current_file = load_history_file(plugin, month="2026-07.jsonl")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_MAX_BYTES", str(max(1, current_file.stat().st_size - 10)))

    result = plugin._history_support.maintain_history(now=current_time)

    assert result.cap_exceeded is True
    assert result.cap_shortfall_bytes > 0
    assert current_file.exists()
    assert plugin._history_support.verify_history().ok is True


@pytest.mark.asyncio
async def test_verify_warns_not_errors_when_retention_prunes_old_delete_tombstone(
    enabled_history,
    monkeypatch: pytest.MonkeyPatch,
):
    plugin = enabled_history
    original_time = datetime(2026, 6, 30, 23, 59, 40, tzinfo=timezone.utc)
    deleted_time = datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
    classified_time = datetime(2026, 7, 1, 0, 0, 20, tzinfo=timezone.utc)
    verify_time = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="carry forward", message_id=77, update_id=1, date=original_time),
        bot=FakeBot(),
        now=original_time,
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=deleted_time,
    )
    plugin._history_support.maintain_history(now=classified_time)

    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_RETENTION_DAYS", "10")
    result = plugin._history_support.maintain_history(now=verify_time)

    june_file = load_history_file(plugin, month="2026-06.jsonl")
    july_file = load_history_file(plugin, month="2026-07.jsonl")
    assert result.pruned_files >= 1
    assert not june_file.exists()
    assert july_file.exists()

    verification = plugin._history_support.verify_history(now=verify_time)
    assert verification.ok is True
    assert any("outside the retained archive" in warning for warning in verification.warnings)


def _build_history_parser(plugin):
    parser = argparse.ArgumentParser(prog="hermes telegram-business")
    plugin._history_support.setup_cli(parser)
    return parser


@pytest.mark.asyncio
async def test_history_cli_show_search_export_deletions_and_verify(enabled_history, capsys, monkeypatch: pytest.MonkeyPatch):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="first alpha", message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="second beta", message_id=78, update_id=2, date=base),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(message_ids=(78,), update_id=3),
        bot=FakeBot(),
        now=base + timedelta(seconds=2),
    )
    plugin._history_support.maintain_history(now=base + timedelta(seconds=20))

    parser = _build_history_parser(plugin)

    exit_code = plugin._history_support.handle_cli(parser.parse_args(["history", "show", "--chat", "991", "--limit", "1"]))
    output = capsys.readouterr().out.strip().splitlines()
    assert exit_code == 0
    assert len(output) == 1
    assert "deletion.classified" in output[0]
    assert "reason=no_strong_match" in output[0]

    exit_code = plugin._history_support.handle_cli(
        parser.parse_args(["history", "search", "--chat", "991", "--text", "alpha", "--limit", "5"])
    )
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert "first alpha" in output
    assert "second beta" not in output

    exit_code = plugin._history_support.handle_cli(
        parser.parse_args(["history", "export", "--chat", "991", "--format", "jsonl", "--limit", "1"])
    )
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert json.loads(output)["event_type"] in {"message.deleted", "deletion.classified"}

    exit_code = plugin._history_support.handle_cli(
        parser.parse_args(["history", "deletions", "--status", "unexplained", "--limit", "5"])
    )
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert "status=unexplained" in output

    history_file = load_history_file(plugin)
    with history_file.open("ab") as handle:
        handle.write(b"{\"event_id\":\"broken\"")
    exit_code = plugin._history_support.handle_cli(parser.parse_args(["history", "verify", "--repair-tails"]))
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "ok=True" in output


@pytest.mark.asyncio
async def test_history_cli_escapes_control_text_but_keeps_unicode_readable(enabled_history, capsys):
    plugin = enabled_history
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)
    text = "prefix\r\t\x1b[31mred\x00\x7f\x85\n🙂suffix"

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text=text, message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )

    parser = _build_history_parser(plugin)
    exit_code = plugin._history_support.handle_cli(parser.parse_args(["history", "show", "--chat", "991", "--limit", "1"]))
    output = capsys.readouterr().out.strip()

    assert exit_code == 0
    assert "\\r" in output
    assert "\\t" in output
    assert "\\x1b[31m" in output
    assert "\\x00" in output
    assert "\\x7f" in output
    assert "\\x85" in output
    assert "\\n" in output
    assert "🙂suffix" in output
    assert "\r" not in output
    assert "\t" not in output
    assert "\x1b" not in output
    assert "\x00" not in output
    assert "\x7f" not in output
    assert "\x85" not in output


@pytest.mark.asyncio
async def test_history_cli_deletions_builds_each_chat_independently_for_same_message_ids(
    plugin,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
):
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE", "1")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS", "business-123")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS", "*")
    monkeypatch.setenv("HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW", "10")
    base = datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc)

    await plugin._history_support.observe_ptb_update(
        make_business_text_update(text="chat one", chat_id=991, message_id=77, update_id=1, date=base),
        bot=FakeBot(),
        now=base,
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(chat_id=991, message_ids=(77,), update_id=2),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )
    await plugin._history_support.observe_ptb_update(
        make_deleted_update(chat_id=992, message_ids=(77,), update_id=3),
        bot=FakeBot(),
        now=base + timedelta(seconds=1),
    )

    original_build_state = plugin._history_support._build_chat_state
    built_chat_ids: list[set[int]] = []

    def _spy_build_chat_state(records):
        materialized = list(records)
        built_chat_ids.append({int(record["chat_id"]) for record in materialized})
        return original_build_state(materialized)

    monkeypatch.setattr(plugin._history_support, "_build_chat_state", _spy_build_chat_state)
    parser = _build_history_parser(plugin)
    exit_code = plugin._history_support.handle_cli(
        parser.parse_args(["history", "deletions", "--status", "pending", "--limit", "10"])
    )
    output = capsys.readouterr().out.strip().splitlines()

    assert exit_code == 0
    assert built_chat_ids == [{991}, {992}]
    assert any("chat=991" in line for line in output)
    assert any("chat=992" in line for line in output)


class FakeApplication:
    def __init__(self):
        self.handlers: list[tuple[int, Any]] = []

    def add_handler(self, handler, group=0):
        self.handlers.append((group, handler))
        return handler

    async def process_update(self, update, *, bot):
        seen_groups = []
        background_tasks = []
        for group in sorted({entry[0] for entry in self.handlers}):
            for handler_group, handler in [entry for entry in self.handlers if entry[0] == group]:
                checker = getattr(handler, "check_update", None)
                if callable(checker) and not checker(update):
                    continue
                seen_groups.append(handler_group)
                context = SimpleNamespace(bot=bot)
                if hasattr(handler, "handle_update"):
                    coroutine = handler.handle_update(update, self, True, context)
                else:
                    coroutine = handler.callback(update, context)
                if getattr(handler, "block", True):
                    await coroutine
                else:
                    background_tasks.append(asyncio.create_task(coroutine))
                break
        if background_tasks:
            await asyncio.gather(*background_tasks)
        return seen_groups


class FakeGroupZeroHandler:
    def __init__(self, callback):
        self.callback = callback

    def check_update(self, _update):
        return True

    async def handle_update(self, update, _application, _check_result, context):
        return await self.callback(update, context)


def _install_raw_handler_test_adapter(plugin, monkeypatch: pytest.MonkeyPatch):
    class FakeAdapter:
        def _is_user_authorized_from_message(self, _message):
            return False

        async def _handle_media_message(self, update, _context):
            return update

    telegram_adapter = types.SimpleNamespace(
        TelegramAdapter=FakeAdapter,
        TelegramMessageHandler=lambda handler_filter, callback, *args, **kwargs: (handler_filter, callback, args, kwargs),
        Application=FakeApplication,
        filters=SimpleNamespace(VIDEO_NOTE=16),
    )
    monkeypatch.setattr(plugin, "_resolve_telegram_adapter_module", lambda: telegram_adapter)
    return telegram_adapter


@pytest.mark.asyncio
async def test_raw_ptb_handler_installs_in_separate_group_and_does_not_block_group_zero(
    enabled_history,
    monkeypatch: pytest.MonkeyPatch,
):
    plugin = enabled_history
    telegram_adapter = _install_raw_handler_test_adapter(plugin, monkeypatch)
    plugin._install_telegram_adapter_compat()

    app = telegram_adapter.Application()
    called = []

    async def group_zero(update, _context):
        called.append(update.update_id)

    app.add_handler(FakeGroupZeroHandler(group_zero), group=0)
    groups = [group for group, _handler in app.handlers]
    assert plugin._RAW_HISTORY_HANDLER_GROUP in groups
    assert 0 in groups

    seen_groups = await app.process_update(
        make_business_text_update(text="group", message_id=77, update_id=1),
        bot=FakeBot(),
    )

    assert seen_groups[0] == plugin._RAW_HISTORY_HANDLER_GROUP
    assert seen_groups[1] == 0
    assert called == [1]
    assert load_records(plugin)[0]["text"] == "group"


@pytest.mark.asyncio
async def test_raw_ptb_history_handler_completes_before_group_zero_and_group_zero_still_runs(
    enabled_history,
):
    plugin = enabled_history
    raw_handler = plugin._build_raw_business_update_handler()
    assert bool(raw_handler.block) is True
    order: list[str] = []

    class LocalApplication:
        def __init__(self):
            self.handlers: list[tuple[int, Any]] = []

        def add_handler(self, handler, group=0):
            self.handlers.append((group, handler))
            return handler

        async def process_update(self, update, *, bot):
            seen_groups = []
            background_tasks = []
            for group in sorted({entry[0] for entry in self.handlers}):
                for handler_group, handler in [entry for entry in self.handlers if entry[0] == group]:
                    checker = getattr(handler, "check_update", None)
                    if callable(checker) and not checker(update):
                        continue
                    seen_groups.append(handler_group)
                    context = SimpleNamespace(bot=bot)
                    if hasattr(handler, "handle_update"):
                        coroutine = handler.handle_update(update, self, True, context)
                    else:
                        coroutine = handler.callback(update, context)
                    if getattr(handler, "block", True):
                        await coroutine
                    else:
                        background_tasks.append(asyncio.create_task(coroutine))
                    break
            if background_tasks:
                await asyncio.gather(*background_tasks)
            return seen_groups

    class BlockingHistoryHandler:
        block = raw_handler.block

        def check_update(self, _update):
            return True

        async def callback(self, update, _context):
            order.append(f"history-start:{update.update_id}")
            await asyncio.sleep(0)
            order.append(f"history-done:{update.update_id}")

    async def group_zero(update, _context):
        order.append(f"group-zero:{update.update_id}")

    app = LocalApplication()
    app.add_handler(BlockingHistoryHandler(), group=plugin._RAW_HISTORY_HANDLER_GROUP)
    app.add_handler(FakeGroupZeroHandler(group_zero), group=0)
    seen_groups = await app.process_update(
        make_business_text_update(text="group", message_id=77, update_id=1),
        bot=FakeBot(),
    )

    assert seen_groups == [plugin._RAW_HISTORY_HANDLER_GROUP, 0]
    assert order == ["history-start:1", "history-done:1", "group-zero:1"]


def test_real_ptb_raw_handler_is_blocking_when_ptb_is_importable(plugin):
    telegram_ext = pytest.importorskip("telegram.ext")

    raw_handler = plugin._build_raw_business_update_handler()

    assert isinstance(raw_handler, telegram_ext.BaseHandler)
    assert bool(raw_handler.block) is True


@pytest.mark.asyncio
async def test_raw_ptb_handler_failure_is_contained_and_group_zero_still_runs(
    enabled_history,
    monkeypatch: pytest.MonkeyPatch,
):
    plugin = enabled_history
    telegram_adapter = _install_raw_handler_test_adapter(plugin, monkeypatch)
    plugin._install_telegram_adapter_compat()
    monkeypatch.setattr(
        plugin._history_support,
        "observe_ptb_update",
        AsyncMock(side_effect=RuntimeError("history broken")),
    )

    app = telegram_adapter.Application()
    called = []

    async def group_zero(update, _context):
        called.append(update.update_id)

    app.add_handler(FakeGroupZeroHandler(group_zero), group=0)
    await app.process_update(
        make_business_text_update(text="still routed", message_id=77, update_id=2),
        bot=FakeBot(),
    )

    assert called == [2]
