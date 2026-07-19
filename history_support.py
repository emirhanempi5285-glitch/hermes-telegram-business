"""Opt-in Telegram Business text history and maintenance helpers.

This module is stdlib-only by design so the history path never grows its own
dependency surface beyond Hermes/PTB at the integration boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

try:
    from hermes_constants import get_hermes_home
except ModuleNotFoundError as exc:
    if exc.name != "hermes_constants":
        raise

    def get_hermes_home() -> Path:
        configured = os.getenv("HERMES_HOME")
        return Path(configured).expanduser() if configured else Path.home() / ".hermes"


logger = logging.getLogger(__name__)

PLUGIN_NAME = "telegram-business-voice-transcriber"
HISTORY_ENABLE_ENV = "HERMES_TELEGRAM_BUSINESS_HISTORY_ENABLE"
HISTORY_CONNECTIONS_ENV = "HERMES_TELEGRAM_BUSINESS_HISTORY_CONNECTIONS"
HISTORY_CHATS_ENV = "HERMES_TELEGRAM_BUSINESS_HISTORY_CHATS"
HISTORY_CORRECTION_WINDOW_ENV = "HERMES_TELEGRAM_BUSINESS_HISTORY_CORRECTION_WINDOW"
HISTORY_RETENTION_DAYS_ENV = "HERMES_TELEGRAM_BUSINESS_HISTORY_RETENTION_DAYS"
HISTORY_MAX_BYTES_ENV = "HERMES_TELEGRAM_BUSINESS_HISTORY_MAX_BYTES"

DEFAULT_CORRECTION_WINDOW_SECONDS = 120
DEFAULT_RETENTION_DAYS = 0
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024
DEFAULT_READ_LIMIT = 200
DEFAULT_CHAT_LIMIT = 100
MAX_READ_LIMIT = 5000
MAINTENANCE_THROTTLE_SECONDS = 3600
TAIL_SCAN_CHUNK_BYTES = 64 * 1024
SCHEMA_VERSION = 1

_OWNER_CACHE: dict[str, str] = {}
_CACHE_LOCK = threading.RLock()
_CHAT_STATE_CACHE: dict[str, "ChatStateCacheEntry"] = {}
_DELETION_TIMERS: dict[tuple[str, str], "DeletionTimerEntry"] = {}
_LAST_MAINTENANCE_AT: datetime | None = None


@dataclass(frozen=True)
class Scope:
    wildcard: bool
    values: frozenset[str]

    def matches(self, value: Any) -> bool:
        if self.wildcard:
            return True
        return str(value) in self.values

    def render(self) -> str:
        if self.wildcard:
            return "*"
        return ",".join(sorted(self.values))


@dataclass(frozen=True)
class HistoryConfig:
    enabled: bool
    connections: Scope | None
    chats: Scope | None
    correction_window_seconds: int = DEFAULT_CORRECTION_WINDOW_SECONDS
    retention_days: int = DEFAULT_RETENTION_DAYS
    max_bytes: int = DEFAULT_MAX_BYTES

    @property
    def active(self) -> bool:
        return self.enabled and self.connections is not None and self.chats is not None

    def allows(self, business_connection_id: Any, chat_id: Any) -> bool:
        return bool(
            self.active
            and self.connections is not None
            and self.chats is not None
            and self.connections.matches(business_connection_id)
            and self.chats.matches(chat_id)
        )


@dataclass
class MessageState:
    message_id: Any
    sender_id: Any
    direction: str
    text: str | None
    message_at: str | None
    reply_to_message_id: Any
    last_event_id: str
    last_observed_at: datetime | None
    deleted: bool = False
    deleted_event_id: str | None = None


@dataclass
class PendingDeletion:
    deleted_event: dict[str, Any] | None
    original: MessageState | None
    classification: dict[str, Any] | None = None


@dataclass
class ChatState:
    seen_event_ids: set[str] = field(default_factory=set)
    messages: dict[str, MessageState] = field(default_factory=dict)
    pending_deletions: dict[str, PendingDeletion] = field(default_factory=dict)
    record_count: int = 0


@dataclass
class HistoryStats:
    chat_count: int
    file_count: int
    record_count: int
    total_bytes: int
    pending_count: int
    unexplained_count: int
    cap_exceeded: bool
    cap_shortfall_bytes: int


@dataclass
class MaintenanceResult:
    classified: int = 0
    pruned_files: int = 0
    pruned_bytes: int = 0
    cap_exceeded: bool = False
    cap_shortfall_bytes: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    ok: bool
    chat_count: int
    file_count: int
    record_count: int
    repaired_files: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChatFileSignature:
    files: tuple[tuple[str, int, int], ...]


@dataclass
class ChatStateCacheEntry:
    signature: ChatFileSignature
    state: ChatState


@dataclass
class DeletionTimerEntry:
    due_at: datetime
    timer: threading.Timer


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _safe_part(value: Any) -> str:
    text = str(value or "unknown")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._") or "unknown"


def _path_key(value: Any) -> str:
    raw = str(value or "unknown")
    safe = _safe_part(raw)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{safe}--{digest}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        if name in obj:
            return obj.get(name, default)
        api_kwargs = obj.get("api_kwargs")
        if isinstance(api_kwargs, dict) and name in api_kwargs:
            return api_kwargs.get(name, default)
        return default
    value = getattr(obj, name, default)
    if value is not default:
        return value
    api_kwargs = getattr(obj, "api_kwargs", None)
    if isinstance(api_kwargs, dict) and name in api_kwargs:
        return api_kwargs.get(name, default)
    return default


def _parse_scope(raw: str | None) -> Scope | None:
    if raw is None:
        return None
    values = [part.strip() for part in re.split(r"[\s,]+", raw) if part.strip()]
    if not values:
        return None
    if "*" in values:
        return Scope(wildcard=True, values=frozenset())
    return Scope(wildcard=False, values=frozenset(values))


def history_config_from_env() -> HistoryConfig:
    correction_window = max(1, _env_int(HISTORY_CORRECTION_WINDOW_ENV, DEFAULT_CORRECTION_WINDOW_SECONDS))
    retention_days = max(0, _env_int(HISTORY_RETENTION_DAYS_ENV, DEFAULT_RETENTION_DAYS))
    max_bytes = max(1, _env_int(HISTORY_MAX_BYTES_ENV, DEFAULT_MAX_BYTES))
    return HistoryConfig(
        enabled=_truthy_env(HISTORY_ENABLE_ENV),
        connections=_parse_scope(os.environ.get(HISTORY_CONNECTIONS_ENV)),
        chats=_parse_scope(os.environ.get(HISTORY_CHATS_ENV)),
        correction_window_seconds=correction_window,
        retention_days=retention_days,
        max_bytes=max_bytes,
    )


def history_root() -> Path:
    return get_hermes_home() / "data" / "telegram-business" / "history"


def skill_path() -> Path:
    return Path(__file__).resolve().parent / "skills" / "history" / "SKILL.md"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _ensure_private_file(path: Path) -> None:
    if not path.exists():
        path.touch(mode=0o600)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _history_chat_dir(business_connection_id: Any, chat_id: Any) -> Path:
    root = history_root()
    connection_dir = root / _path_key(business_connection_id)
    chat_dir = connection_dir / _safe_part(chat_id)
    _ensure_private_dir(root)
    _ensure_private_dir(connection_dir)
    _ensure_private_dir(chat_dir)
    return chat_dir


def _chat_lock_path(chat_dir: Path) -> Path:
    return chat_dir / ".lock"


def _root_lock_path() -> Path:
    root = history_root()
    _ensure_private_dir(root)
    return root / ".lock"


@contextmanager
def _locked_path(path: Path) -> Iterator[None]:
    _ensure_private_dir(path.parent)
    _ensure_private_file(path)
    with path.open("r+b") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _chat_lock(chat_dir: Path) -> Iterator[None]:
    with _locked_path(_chat_lock_path(chat_dir)):
        yield


@contextmanager
def _root_lock() -> Iterator[None]:
    with _locked_path(_root_lock_path()):
        yield


def _month_filename(observed_at: datetime) -> str:
    return observed_at.astimezone(timezone.utc).strftime("%Y-%m") + ".jsonl"


def _month_sort_key(path: Path) -> tuple[str, str]:
    return (path.stem, path.name)


def _iter_history_files(chat_dir: Path) -> list[Path]:
    return sorted(
        [path for path in chat_dir.iterdir() if path.is_file() and path.suffix == ".jsonl"],
        key=_month_sort_key,
    )


def _cache_key(chat_dir: Path) -> str:
    return str(chat_dir.resolve())


def _copy_message_state(message: MessageState) -> MessageState:
    return MessageState(
        message_id=message.message_id,
        sender_id=message.sender_id,
        direction=message.direction,
        text=message.text,
        message_at=message.message_at,
        reply_to_message_id=message.reply_to_message_id,
        last_event_id=message.last_event_id,
        last_observed_at=message.last_observed_at,
        deleted=message.deleted,
        deleted_event_id=message.deleted_event_id,
    )


def _chat_file_signature(chat_dir: Path) -> ChatFileSignature:
    if not chat_dir.exists():
        return ChatFileSignature(files=())
    files = []
    for path in _iter_history_files(chat_dir):
        try:
            stat_result = path.stat()
        except OSError:
            continue
        files.append((path.name, stat_result.st_size, stat_result.st_mtime_ns))
    return ChatFileSignature(files=tuple(files))


def _invalidate_chat_cache(chat_dir: Path) -> None:
    with _CACHE_LOCK:
        _CHAT_STATE_CACHE.pop(_cache_key(chat_dir), None)


def _store_chat_cache(chat_dir: Path, state: ChatState) -> None:
    with _CACHE_LOCK:
        _CHAT_STATE_CACHE[_cache_key(chat_dir)] = ChatStateCacheEntry(
            signature=_chat_file_signature(chat_dir),
            state=state,
        )


def _tail_scan_last_newline_offset(handle: Any) -> int:
    end = handle.seek(0, os.SEEK_END)
    position = end
    trailing = b""
    while position > 0:
        chunk_size = min(TAIL_SCAN_CHUNK_BYTES, position)
        position -= chunk_size
        handle.seek(position)
        chunk = handle.read(chunk_size)
        combined = chunk + trailing
        newline = combined.rfind(b"\n")
        if newline >= 0:
            return position + newline
        trailing = combined[: TAIL_SCAN_CHUNK_BYTES - 1]
    return -1


def _file_has_complete_final_line(path: Path) -> bool:
    if not path.exists():
        return True
    with path.open("rb") as handle:
        end = handle.seek(0, os.SEEK_END)
        if end == 0:
            return True
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) == b"\n"


def _repair_torn_tail(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("r+b") as handle:
        end = handle.seek(0, os.SEEK_END)
        if end == 0:
            return False
        handle.seek(-1, os.SEEK_END)
        if handle.read(1) == b"\n":
            return False
        last_newline = _tail_scan_last_newline_offset(handle)
        truncate_at = last_newline + 1 if last_newline >= 0 else 0
        handle.truncate(truncate_at)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _scan_records(
    chat_dir: Path,
    *,
    repair_tails: bool,
    on_record: Callable[[dict[str, Any]], None],
) -> int:
    repaired = 0
    for path in _iter_history_files(chat_dir):
        if repair_tails and _repair_torn_tail(path):
            repaired += 1
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON in {path.name}:{line_no}: {exc}") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"non-object record in {path.name}:{line_no}")
                on_record(record)
    return repaired


def _load_records(chat_dir: Path, *, repair_tails: bool = True) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    repaired = _scan_records(chat_dir, repair_tails=repair_tails, on_record=records.append)
    return records, repaired


def _record_signature(record: dict[str, Any]) -> dict[str, Any]:
    stable = {
        "schema_version": record["schema_version"],
        "event_type": record["event_type"],
        "source": record.get("source"),
        "telegram_update_id": record.get("telegram_update_id"),
        "business_connection_id": record["business_connection_id"],
        "chat_id": record["chat_id"],
        "message_id": record.get("message_id"),
        "message_at": record.get("message_at"),
        "sender_id": record.get("sender_id"),
        "direction": record.get("direction"),
        "reply_to_message_id": record.get("reply_to_message_id"),
        "text": record.get("text"),
        "deleted_event_id": record.get("deleted_event_id"),
        "classification": record.get("classification"),
        "replacement_message_id": record.get("replacement_message_id"),
        "classification_reason": record.get("classification_reason"),
        "classification_score": record.get("classification_score"),
    }
    return stable


def _event_id(record: dict[str, Any]) -> str:
    payload = json.dumps(_record_signature(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_event(
    *,
    event_type: str,
    source: str,
    observed_at: datetime,
    telegram_update_id: Any,
    business_connection_id: Any,
    chat_id: Any,
    message_id: Any,
    message_at: datetime | str | None,
    sender_id: Any,
    direction: str,
    reply_to_message_id: Any,
    text: str | None = None,
    deleted_event_id: str | None = None,
    classification: str | None = None,
    replacement_message_id: Any = None,
    classification_reason: str | None = None,
    classification_method: str | None = None,
    classification_score: float | None = None,
    evaluated_at: datetime | None = None,
    deleted_observed_at: datetime | str | None = None,
) -> dict[str, Any]:
    if classification_reason is None:
        classification_reason = classification_method
    if classification_method is None and classification_reason is not None:
        classification_method = classification_reason
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        "source": str(source),
        "observed_at": _isoformat_utc(observed_at),
        "telegram_update_id": telegram_update_id,
        "business_connection_id": str(business_connection_id),
        "chat_id": chat_id,
        "message_id": message_id,
        "message_at": _isoformat_utc(_normalize_timestamp(message_at) if not isinstance(message_at, str) else _parse_datetime(message_at)),
        "sender_id": sender_id,
        "direction": direction or "unknown",
        "reply_to_message_id": reply_to_message_id,
    }
    if text is not None:
        record["text"] = text
    if deleted_event_id is not None:
        record["deleted_event_id"] = deleted_event_id
    if classification is not None:
        record["classification"] = classification
    if replacement_message_id is not None:
        record["replacement_message_id"] = replacement_message_id
    if classification_reason is not None:
        record["classification_reason"] = classification_reason
    if classification_method is not None:
        record["classification_method"] = classification_method
    if classification_score is not None:
        record["classification_score"] = round(float(classification_score), 4)
    if evaluated_at is not None:
        record["evaluated_at"] = _isoformat_utc(evaluated_at)
    if deleted_observed_at is not None:
        record["deleted_observed_at"] = _isoformat_utc(
            _normalize_timestamp(deleted_observed_at)
            if not isinstance(deleted_observed_at, str)
            else _parse_datetime(deleted_observed_at)
        )
    record["event_id"] = _event_id(record)
    return record


def _append_record(chat_dir: Path, record: dict[str, Any]) -> bool:
    observed_at = _parse_datetime(record.get("observed_at")) or _utcnow()
    path = chat_dir / _month_filename(observed_at)
    _ensure_private_file(path)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return True


def _apply_record_to_state(state: ChatState, record: dict[str, Any]) -> None:
    event_id = str(record.get("event_id") or "")
    if event_id:
        state.seen_event_ids.add(event_id)
    state.record_count += 1
    event_type = str(record.get("event_type") or "")
    message_key = str(record.get("message_id"))
    observed_at = _parse_datetime(record.get("observed_at"))
    if event_type in {"message.created", "message.edited"}:
        state.messages[message_key] = MessageState(
            message_id=record.get("message_id"),
            sender_id=record.get("sender_id"),
            direction=str(record.get("direction") or "unknown"),
            text=record.get("text"),
            message_at=record.get("message_at"),
            reply_to_message_id=record.get("reply_to_message_id"),
            last_event_id=event_id,
            last_observed_at=observed_at,
            deleted=False,
            deleted_event_id=None,
        )
        return
    if event_type == "message.deleted":
        original = state.messages.get(message_key)
        state.pending_deletions[event_id] = PendingDeletion(
            deleted_event=record,
            original=None if original is None else _copy_message_state(original),
        )
        if original is not None:
            original.deleted = True
            original.deleted_event_id = event_id
        return
    if event_type == "deletion.classified":
        deleted_event_id = str(record.get("deleted_event_id") or "")
        if not deleted_event_id:
            return
        pending = state.pending_deletions.get(deleted_event_id)
        if pending is None:
            pending = PendingDeletion(deleted_event=None, original=None)
            state.pending_deletions[deleted_event_id] = pending
        pending.classification = record


def _build_chat_state(records: Iterable[dict[str, Any]]) -> ChatState:
    state = ChatState()
    for record in records:
        _apply_record_to_state(state, record)
    return state


def _load_chat_state_from_disk(chat_dir: Path) -> tuple[ChatState, int]:
    state = ChatState()
    repaired = _scan_records(chat_dir, repair_tails=True, on_record=lambda record: _apply_record_to_state(state, record))
    return state, repaired


def _load_chat_state(chat_dir: Path) -> tuple[ChatState, int]:
    signature = _chat_file_signature(chat_dir)
    with _CACHE_LOCK:
        cached = _CHAT_STATE_CACHE.get(_cache_key(chat_dir))
        if cached is not None and cached.signature == signature:
            return cached.state, 0
    state, repaired = _load_chat_state_from_disk(chat_dir)
    _store_chat_cache(chat_dir, state)
    return state, repaired


def _normalize_compare_text(text: str | None) -> str:
    compact = " ".join((text or "").strip().casefold().split())
    return compact


def _similarity_score(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _classify_one_deletion(
    *,
    chat_state: ChatState,
    pending: PendingDeletion,
    now: datetime,
    correction_window_seconds: int,
) -> dict[str, Any] | None:
    if pending.classification is not None:
        return None
    deleted_event = pending.deleted_event
    if deleted_event is None:
        return None
    deleted_at = _parse_datetime(deleted_event.get("observed_at"))
    if deleted_at is None or now < deleted_at + timedelta(seconds=correction_window_seconds):
        return None

    original = pending.original
    if original is None or original.text is None or original.sender_id is None:
        return _build_event(
            event_type="deletion.classified",
            source=str(deleted_event.get("source") or "deleted_business_messages"),
            observed_at=now,
            telegram_update_id=deleted_event.get("telegram_update_id"),
            business_connection_id=deleted_event["business_connection_id"],
            chat_id=deleted_event["chat_id"],
            message_id=deleted_event.get("message_id"),
            message_at=deleted_event.get("message_at"),
            sender_id=deleted_event.get("sender_id"),
            direction=str(deleted_event.get("direction") or "unknown"),
            reply_to_message_id=deleted_event.get("reply_to_message_id"),
            deleted_event_id=deleted_event["event_id"],
            classification="unclassifiable",
            classification_reason="missing_original",
            evaluated_at=now,
            deleted_observed_at=deleted_at,
        )

    original_text = _normalize_compare_text(original.text)
    if not original_text:
        return _build_event(
            event_type="deletion.classified",
            source=str(deleted_event.get("source") or "deleted_business_messages"),
            observed_at=now,
            telegram_update_id=deleted_event.get("telegram_update_id"),
            business_connection_id=deleted_event["business_connection_id"],
            chat_id=deleted_event["chat_id"],
            message_id=deleted_event.get("message_id"),
            message_at=deleted_event.get("message_at"),
            sender_id=deleted_event.get("sender_id"),
            direction=str(deleted_event.get("direction") or "unknown"),
            reply_to_message_id=deleted_event.get("reply_to_message_id"),
            deleted_event_id=deleted_event["event_id"],
            classification="unclassifiable",
            classification_reason="missing_text",
            evaluated_at=now,
            deleted_observed_at=deleted_at,
        )

    candidate_deadline = deleted_at + timedelta(seconds=correction_window_seconds)
    nearby_candidates: list[tuple[float, MessageState]] = []
    for candidate in chat_state.messages.values():
        if candidate.deleted:
            continue
        if str(candidate.message_id) == str(original.message_id):
            continue
        if candidate.sender_id is None or str(candidate.sender_id) != str(original.sender_id):
            continue
        if str(candidate.direction or "unknown") != str(original.direction or "unknown"):
            continue
        if candidate.text is None or candidate.last_observed_at is None:
            continue
        if candidate.last_observed_at < deleted_at or candidate.last_observed_at > candidate_deadline:
            continue
        delta = (candidate.last_observed_at - deleted_at).total_seconds()
        nearby_candidates.append((delta, candidate))

    if nearby_candidates:
        exact = sorted(
            (
                (delta, candidate)
                for delta, candidate in nearby_candidates
                if _normalize_compare_text(candidate.text) == original_text
            ),
            key=lambda item: (item[0], str(item[1].message_id)),
        )
        if exact:
            best_delta, best = exact[0]
            return _build_event(
                event_type="deletion.classified",
                source=str(deleted_event.get("source") or "deleted_business_messages"),
                observed_at=now,
                telegram_update_id=deleted_event.get("telegram_update_id"),
                business_connection_id=deleted_event["business_connection_id"],
                chat_id=deleted_event["chat_id"],
                message_id=deleted_event.get("message_id"),
                message_at=deleted_event.get("message_at"),
                sender_id=deleted_event.get("sender_id"),
                direction=str(deleted_event.get("direction") or "unknown"),
                reply_to_message_id=deleted_event.get("reply_to_message_id"),
                deleted_event_id=deleted_event["event_id"],
                classification="likely_duplicate",
                replacement_message_id=best.message_id,
                classification_reason="normalized_exact_duplicate",
                classification_score=1.0,
                evaluated_at=now,
                deleted_observed_at=deleted_at,
            )

        similarity_candidates: list[tuple[float, float, MessageState]] = []
        for delta, candidate in nearby_candidates:
            candidate_text = _normalize_compare_text(candidate.text)
            if len(original_text) < 8 or len(candidate_text) < 8:
                continue
            ratio = _similarity_score(original_text, candidate_text)
            length_gap = abs(len(original_text) - len(candidate_text))
            max_length_gap = max(3, min(12, int(max(len(original_text), len(candidate_text)) * 0.15)))
            if ratio >= 0.93 and length_gap <= max_length_gap:
                similarity_candidates.append((ratio, delta, candidate))
        if similarity_candidates:
            similarity_candidates.sort(key=lambda item: (-item[0], item[1], str(item[2].message_id)))
            best_ratio, _best_delta, best = similarity_candidates[0]
            return _build_event(
                event_type="deletion.classified",
                source=str(deleted_event.get("source") or "deleted_business_messages"),
                observed_at=now,
                telegram_update_id=deleted_event.get("telegram_update_id"),
                business_connection_id=deleted_event["business_connection_id"],
                chat_id=deleted_event["chat_id"],
                message_id=deleted_event.get("message_id"),
                message_at=deleted_event.get("message_at"),
                sender_id=deleted_event.get("sender_id"),
                direction=str(deleted_event.get("direction") or "unknown"),
                reply_to_message_id=deleted_event.get("reply_to_message_id"),
                deleted_event_id=deleted_event["event_id"],
                classification="likely_correction",
                replacement_message_id=best.message_id,
                classification_reason="high_similarity_small_edit",
                classification_score=best_ratio,
                evaluated_at=now,
                deleted_observed_at=deleted_at,
            )

    return _build_event(
        event_type="deletion.classified",
        source=str(deleted_event.get("source") or "deleted_business_messages"),
        observed_at=now,
        telegram_update_id=deleted_event.get("telegram_update_id"),
        business_connection_id=deleted_event["business_connection_id"],
        chat_id=deleted_event["chat_id"],
        message_id=deleted_event.get("message_id"),
        message_at=deleted_event.get("message_at"),
        sender_id=deleted_event.get("sender_id"),
        direction=str(deleted_event.get("direction") or "unknown"),
        reply_to_message_id=deleted_event.get("reply_to_message_id"),
        deleted_event_id=deleted_event["event_id"],
        classification="unexplained",
        classification_reason="no_strong_match",
        evaluated_at=now,
        deleted_observed_at=deleted_at,
    )


def _timer_key(chat_dir: Path, deleted_event_id: str) -> tuple[str, str]:
    return (_cache_key(chat_dir), deleted_event_id)


def _cancel_deletion_timer(chat_dir: Path, deleted_event_id: str) -> None:
    with _CACHE_LOCK:
        entry = _DELETION_TIMERS.pop(_timer_key(chat_dir, deleted_event_id), None)
    if entry is not None:
        entry.timer.cancel()


def _cancel_chat_timers(chat_dir: Path) -> None:
    chat_key = _cache_key(chat_dir)
    with _CACHE_LOCK:
        keys = [key for key in _DELETION_TIMERS if key[0] == chat_key]
        entries = [ _DELETION_TIMERS.pop(key) for key in keys ]
    for entry in entries:
        entry.timer.cancel()


def _run_scheduled_deletion_timer(chat_dir_text: str, deleted_event_id: str, due_at_text: str) -> None:
    chat_dir = Path(chat_dir_text)
    due_at = _parse_datetime(due_at_text) or _utcnow()
    key = (chat_dir_text, deleted_event_id)
    with _CACHE_LOCK:
        entry = _DELETION_TIMERS.get(key)
        if entry is None or entry.due_at != due_at:
            return
        _DELETION_TIMERS.pop(key, None)
    try:
        _classify_due_for_chat(chat_dir, history_config_from_env(), now=max(_utcnow(), due_at))
    except Exception as exc:  # noqa: BLE001 - background classification must stay contained
        logger.warning("%s: scheduled deletion classification failed: %s", PLUGIN_NAME, exc, exc_info=True)


def _ensure_deletion_timer(chat_dir: Path, deleted_event_id: str, *, due_at: datetime, now: datetime) -> None:
    if due_at <= now:
        return
    key = _timer_key(chat_dir, deleted_event_id)
    with _CACHE_LOCK:
        existing = _DELETION_TIMERS.get(key)
        if existing is not None and existing.due_at == due_at:
            return
        if existing is not None:
            existing.timer.cancel()
        delay = max(0.0, (due_at - now).total_seconds())
        timer = threading.Timer(
            delay,
            _run_scheduled_deletion_timer,
            args=(chat_dir.resolve().as_posix(), deleted_event_id, _isoformat_utc(due_at) or ""),
        )
        timer.daemon = True
        _DELETION_TIMERS[key] = DeletionTimerEntry(due_at=due_at, timer=timer)
    timer.start()


def _sync_pending_deletions_for_chat(
    chat_dir: Path,
    state: ChatState,
    config: HistoryConfig,
    *,
    now: datetime,
) -> int:
    appended = 0
    for deleted_event_id, pending in list(state.pending_deletions.items()):
        if pending.classification is not None:
            _cancel_deletion_timer(chat_dir, deleted_event_id)
            continue
        deleted_event = pending.deleted_event
        deleted_at = None if deleted_event is None else _parse_datetime(deleted_event.get("observed_at"))
        if deleted_at is None:
            continue
        due_at = deleted_at + timedelta(seconds=config.correction_window_seconds)
        if due_at > now:
            _ensure_deletion_timer(chat_dir, deleted_event_id, due_at=due_at, now=now)
            continue
        record = _classify_one_deletion(
            chat_state=state,
            pending=pending,
            now=now,
            correction_window_seconds=config.correction_window_seconds,
        )
        if record is None or record["event_id"] in state.seen_event_ids:
            continue
        _append_record(chat_dir, record)
        _apply_record_to_state(state, record)
        appended += 1
        _cancel_deletion_timer(chat_dir, deleted_event_id)
    if appended:
        _store_chat_cache(chat_dir, state)
    return appended


def _classify_due_for_chat(chat_dir: Path, config: HistoryConfig, *, now: datetime | None = None) -> int:
    current = now or _utcnow()
    with _chat_lock(chat_dir):
        state, _ = _load_chat_state(chat_dir)
        return _sync_pending_deletions_for_chat(chat_dir, state, config, now=current)


def _iter_chat_dirs() -> Iterator[Path]:
    root = history_root()
    if not root.exists():
        return
    for connection_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for chat_dir in sorted(path for path in connection_dir.iterdir() if path.is_dir()):
            yield chat_dir


def _file_month(path: Path) -> tuple[int, int] | None:
    match = re.fullmatch(r"(\d{4})-(\d{2})\.jsonl", path.name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _is_active_month_file(path: Path, now: datetime) -> bool:
    month = _file_month(path)
    if month is None:
        return True
    return month == (now.year, now.month)


def _prunable_history_files(now: datetime) -> list[Path]:
    files: list[Path] = []
    for chat_dir in _iter_chat_dirs():
        files.extend(
            path
            for path in _iter_history_files(chat_dir)
            if not _is_active_month_file(path, now)
        )
    return sorted(files, key=lambda path: (path.name, str(path.parent)))


def _history_file_bytes() -> list[Path]:
    files: list[Path] = []
    for chat_dir in _iter_chat_dirs():
        files.extend(_iter_history_files(chat_dir))
    return files


def collect_history_stats(*, now: datetime | None = None) -> HistoryStats:
    chat_count = 0
    record_count = 0
    pending_count = 0
    unexplained_count = 0
    files = _history_file_bytes()
    total_bytes = sum(path.stat().st_size for path in files if path.exists())
    for chat_dir in _iter_chat_dirs():
        chat_count += 1
        with _chat_lock(chat_dir):
            state, _ = _load_chat_state(chat_dir)
        record_count += state.record_count
        for pending in state.pending_deletions.values():
            if pending.classification is None:
                pending_count += 1
            elif pending.classification.get("classification") == "unexplained":
                unexplained_count += 1
    max_bytes = history_config_from_env().max_bytes
    cap_exceeded = total_bytes > max_bytes
    return HistoryStats(
        chat_count=chat_count,
        file_count=len(files),
        record_count=record_count,
        total_bytes=total_bytes,
        pending_count=pending_count,
        unexplained_count=unexplained_count,
        cap_exceeded=cap_exceeded,
        cap_shortfall_bytes=max(0, total_bytes - max_bytes),
    )


def _record_maintenance_run(now: datetime) -> None:
    global _LAST_MAINTENANCE_AT
    with _CACHE_LOCK:
        _LAST_MAINTENANCE_AT = now


def _should_run_throttled_maintenance(now: datetime) -> bool:
    with _CACHE_LOCK:
        last = _LAST_MAINTENANCE_AT
        return last is None or now >= last + timedelta(seconds=MAINTENANCE_THROTTLE_SECONDS)


def maintain_history(*, now: datetime | None = None) -> MaintenanceResult:
    config = history_config_from_env()
    current = now or _utcnow()
    result = MaintenanceResult()
    for chat_dir in _iter_chat_dirs():
        try:
            result.classified += _classify_due_for_chat(chat_dir, config, now=current)
        except Exception as exc:  # noqa: BLE001 - maintenance is best effort
            result.warnings.append(f"classification failed for {chat_dir}: {exc}")
    with _root_lock():
        if config.retention_days > 0:
            cutoff = current - timedelta(days=config.retention_days)
            retention_cutoff = datetime(cutoff.year, cutoff.month, 1, tzinfo=timezone.utc)
            for path in _prunable_history_files(current):
                month = _file_month(path)
                if month is None:
                    continue
                month_start = datetime(month[0], month[1], 1, tzinfo=timezone.utc)
                if month_start >= retention_cutoff:
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                    _invalidate_chat_cache(path.parent)
                    result.pruned_files += 1
                    result.pruned_bytes += size
                except OSError as exc:
                    result.warnings.append(f"retention prune failed for {path}: {exc}")

        files = sorted(
            _prunable_history_files(current),
            key=lambda path: (_file_month(path) or (9999, 99), str(path.parent)),
        )
        total_bytes = sum(path.stat().st_size for path in _history_file_bytes() if path.exists())
        while total_bytes > config.max_bytes and files:
            path = files.pop(0)
            try:
                size = path.stat().st_size
                path.unlink()
                _invalidate_chat_cache(path.parent)
                total_bytes -= size
                result.pruned_files += 1
                result.pruned_bytes += size
            except OSError as exc:
                result.warnings.append(f"size prune failed for {path}: {exc}")

        if total_bytes > config.max_bytes:
            result.cap_exceeded = True
            result.cap_shortfall_bytes = total_bytes - config.max_bytes
            result.warnings.append(
                "history size cap cannot be met without deleting an active month file"
            )
    _record_maintenance_run(current)
    return result


def verify_history(*, repair_tails: bool = False, now: datetime | None = None) -> VerificationResult:
    current = now or _utcnow()
    errors: list[str] = []
    warnings: list[str] = []
    chat_count = 0
    file_count = 0
    record_count = 0
    repaired_files = 0
    seen_global: set[str] = set()
    for chat_dir in _iter_chat_dirs():
        chat_count += 1
        with _chat_lock(chat_dir):
            try:
                records, repaired = _load_records(chat_dir, repair_tails=repair_tails)
            except Exception as exc:  # noqa: BLE001 - collect and continue
                errors.append(f"{chat_dir}: {exc}")
                continue
        repaired_files += repaired
        file_count += len(_iter_history_files(chat_dir))
        state = _build_chat_state(records)
        record_count += state.record_count
        for record in records:
            event_id = str(record.get("event_id") or "")
            if not event_id:
                errors.append(f"{chat_dir}: missing event_id")
                continue
            if event_id in seen_global:
                warnings.append(f"{chat_dir}: duplicate event_id {event_id}")
            seen_global.add(event_id)
            if record.get("schema_version") != SCHEMA_VERSION:
                warnings.append(f"{chat_dir}: unsupported schema_version {record.get('schema_version')}")
            if record.get("event_type") == "deletion.classified":
                deleted_event_id = str(record.get("deleted_event_id") or "")
                pending = state.pending_deletions.get(deleted_event_id)
                if pending is None or pending.deleted_event is None:
                    deleted_observed_at = _parse_datetime(record.get("deleted_observed_at"))
                    if deleted_observed_at is None:
                        warnings.append(
                            f"{chat_dir}: classification {event_id} refers to a missing tombstone"
                        )
                    else:
                        warnings.append(
                            f"{chat_dir}: classification {event_id} refers to tombstone {deleted_event_id} "
                            f"outside the retained archive"
                        )
        for path in _iter_history_files(chat_dir):
            if not _is_active_month_file(path, current):
                continue
            if not _file_has_complete_final_line(path):
                errors.append(f"{chat_dir}: torn tail remains in {path.name}")
    stats = collect_history_stats(now=current)
    if stats.cap_exceeded:
        warnings.append(
            f"history size cap exceeded by {stats.cap_shortfall_bytes} bytes"
        )
    return VerificationResult(
        ok=not errors,
        chat_count=chat_count,
        file_count=file_count,
        record_count=record_count,
        repaired_files=repaired_files,
        errors=errors,
        warnings=warnings,
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _resolve_direction(message: Any, *, bot: Any = None) -> str:
    if _get(message, "sender_business_bot") is not None:
        return "outgoing"
    business_connection_id = _get(message, "business_connection_id") or _get(message, "_hermes_business_connection_id")
    from_user_id = _get(_get(message, "from_user"), "id")
    if not business_connection_id or from_user_id is None or bot is None:
        return "unknown"
    connection_key = str(business_connection_id)
    owner_id = _OWNER_CACHE.get(connection_key)
    if owner_id is None:
        get_connection = getattr(bot, "get_business_connection", None)
        if not callable(get_connection):
            return "unknown"
        try:
            connection = await _maybe_await(get_connection(business_connection_id))
        except Exception:
            return "unknown"
        owner = _get(_get(connection, "user"), "id")
        if owner is None:
            return "unknown"
        owner_id = str(owner)
        _OWNER_CACHE[connection_key] = owner_id
    return "outgoing" if owner_id == str(from_user_id) else "incoming"


def _extract_history_text(message: Any) -> str | None:
    text = _get(message, "text")
    if isinstance(text, str) and text.strip():
        return text
    return None


async def observe_ptb_update(update: Any, *, bot: Any = None, now: datetime | None = None) -> bool:
    config = history_config_from_env()
    if not config.active:
        return False

    current = now or _utcnow()
    payload = None
    event_type = None
    source = None
    for attribute, normalized in (
        ("edited_business_message", "message.edited"),
        ("deleted_business_messages", "message.deleted"),
        ("business_message", "message.created"),
    ):
        candidate = getattr(update, attribute, None)
        if candidate is not None:
            payload = candidate
            event_type = normalized
            source = attribute
            break
    if payload is None or event_type is None or source is None:
        return False

    business_connection_id = _get(payload, "business_connection_id") or _get(payload, "_hermes_business_connection_id")
    chat_id = _get(_get(payload, "chat"), "id")
    if not business_connection_id or chat_id is None or not config.allows(business_connection_id, chat_id):
        return False

    chat_dir: Path | None = None
    wrote = False
    if event_type == "message.deleted":
        chat_dir = _history_chat_dir(business_connection_id, chat_id)
        with _chat_lock(chat_dir):
            state, _ = _load_chat_state(chat_dir)
            message_ids = tuple(_get(payload, "message_ids") or ())
            for message_id in message_ids:
                original = state.messages.get(str(message_id))
                record = _build_event(
                    event_type="message.deleted",
                    source=source,
                    observed_at=current,
                    telegram_update_id=getattr(update, "update_id", None),
                    business_connection_id=business_connection_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    message_at=None if original is None else original.message_at,
                    sender_id=None if original is None else original.sender_id,
                    direction="unknown" if original is None else original.direction,
                    reply_to_message_id=None if original is None else original.reply_to_message_id,
                )
                if record["event_id"] in state.seen_event_ids:
                    continue
                _append_record(chat_dir, record)
                _apply_record_to_state(state, record)
                wrote = True
            wrote_classifications = _sync_pending_deletions_for_chat(chat_dir, state, config, now=current)
            if wrote or wrote_classifications:
                _store_chat_cache(chat_dir, state)
            wrote = wrote or bool(wrote_classifications)
    else:
        text = _extract_history_text(payload)
        if text is None:
            return False
        chat_dir = _history_chat_dir(business_connection_id, chat_id)
        direction = await _resolve_direction(payload, bot=bot)
        message_date = _normalize_timestamp(_get(payload, "date"))
        with _chat_lock(chat_dir):
            state, _ = _load_chat_state(chat_dir)
            record = _build_event(
                event_type=event_type,
                source=source,
                observed_at=current,
                telegram_update_id=getattr(update, "update_id", None),
                business_connection_id=business_connection_id,
                chat_id=chat_id,
                message_id=_get(payload, "message_id"),
                message_at=message_date,
                sender_id=_get(_get(payload, "from_user"), "id"),
                direction=direction,
                reply_to_message_id=_get(_get(payload, "reply_to_message"), "message_id"),
                text=text,
            )
            if record["event_id"] not in state.seen_event_ids:
                _append_record(chat_dir, record)
                _apply_record_to_state(state, record)
                wrote = True
            wrote_classifications = _sync_pending_deletions_for_chat(chat_dir, state, config, now=current)
            if wrote or wrote_classifications:
                _store_chat_cache(chat_dir, state)
            wrote = wrote or bool(wrote_classifications)

    if _should_run_throttled_maintenance(current):
        maintenance = maintain_history(now=current)
        if maintenance.cap_exceeded:
            logger.warning(
                "%s: history size cap exceeded by %d bytes; active month files were preserved",
                PLUGIN_NAME,
                maintenance.cap_shortfall_bytes,
            )
        for warning in maintenance.warnings:
            logger.warning("%s: %s", PLUGIN_NAME, warning)
    return wrote


def run_startup_maintenance(*, now: datetime | None = None) -> MaintenanceResult:
    return maintain_history(now=now)


def _trim_records(records: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None or limit <= 0:
        return records
    return records[-limit:]


def _load_chat_records_for_cli(chat_dir: Path) -> list[dict[str, Any]]:
    with _chat_lock(chat_dir):
        records, _ = _load_records(chat_dir, repair_tails=True)
    return records


def _iter_chat_matches(*, business_connection_id: str | None = None, chat_id: str | None = None) -> list[tuple[Path, list[dict[str, Any]]]]:
    matches: list[tuple[Path, list[dict[str, Any]]]] = []
    for chat_dir in _iter_chat_dirs():
        records = _load_chat_records_for_cli(chat_dir)
        if not records:
            continue
        first = records[0]
        record_connection_id = str(first.get("business_connection_id"))
        record_chat_id = str(first.get("chat_id"))
        if business_connection_id is not None and record_connection_id != str(business_connection_id):
            continue
        if chat_id is not None and record_chat_id != str(chat_id):
            continue
        matches.append((chat_dir, records))
    return matches


def _require_single_chat(*, business_connection_id: str | None, chat_id: str) -> tuple[Path, list[dict[str, Any]]]:
    matches = _iter_chat_matches(business_connection_id=business_connection_id, chat_id=chat_id)
    if not matches:
        raise ValueError("no matching history chat found")
    if len(matches) > 1:
        raise ValueError("multiple history chats match; pass --connection explicitly")
    return matches[0]


def _parse_since(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if re.fullmatch(r"\d+[smhdw]", raw):
        amount = int(raw[:-1])
        unit = raw[-1]
        seconds = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 7 * 86400,
        }[unit]
        return _utcnow() - timedelta(seconds=amount * seconds)
    parsed = _parse_datetime(raw)
    if parsed is None:
        raise ValueError(f"unsupported --since value: {value}")
    return parsed


def _bounded_limit(raw: int | None, default: int) -> int:
    if raw is None:
        return default
    return max(1, min(int(raw), MAX_READ_LIMIT))


def _escape_terminal_text(text: str) -> str:
    escaped: list[str] = []
    for char in text:
        codepoint = ord(char)
        if char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif codepoint < 0x20 or codepoint == 0x7F or 0x80 <= codepoint <= 0x9F:
            escaped.append(f"\\x{codepoint:02x}")
        else:
            escaped.append(char)
    return "".join(escaped)


def _history_text_line(record: dict[str, Any]) -> str:
    business_connection_id = record.get("business_connection_id")
    chat_id = record.get("chat_id")
    observed_at = record.get("observed_at")
    message_id = record.get("message_id")
    event_type = record.get("event_type")
    source = record.get("source")
    direction = record.get("direction")
    sender_id = record.get("sender_id")
    text = record.get("text")
    if text is not None:
        text = _escape_terminal_text(text)
    suffix = ""
    if event_type == "deletion.classified":
        suffix = (
            f" status={record.get('classification')}"
            f" replacement={record.get('replacement_message_id')}"
            f" reason={record.get('classification_reason') or record.get('classification_method')}"
            f" score={record.get('classification_score')}"
        )
    elif text is not None:
        suffix = f" text={text}"
    return (
        f"{observed_at} {event_type} source={source} connection={business_connection_id} chat={chat_id} message={message_id} "
        f"direction={direction} sender={sender_id}{suffix}"
    )


def _chat_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {}
    chat_state = _build_chat_state(records)
    first = records[0]
    latest = records[-1]
    unexplained = sum(
        1
        for pending in chat_state.pending_deletions.values()
        if pending.classification is not None and pending.classification.get("classification") == "unexplained"
    )
    pending = sum(1 for pending in chat_state.pending_deletions.values() if pending.classification is None)
    return {
        "business_connection_id": first.get("business_connection_id"),
        "chat_id": first.get("chat_id"),
        "records": len(records),
        "first_observed_at": first.get("observed_at"),
        "last_observed_at": latest.get("observed_at"),
        "pending_deletions": pending,
        "unexplained_deletions": unexplained,
    }


def setup_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="telegram_business_command")
    history = subs.add_parser("history", help="Read and maintain Telegram Business history")
    history_subs = history.add_subparsers(dest="telegram_business_history_command")

    chats = history_subs.add_parser("chats", help="List chats with stored history")
    chats.add_argument("--limit", type=int, default=DEFAULT_CHAT_LIMIT)
    chats.set_defaults(_history_action="chats")

    stats = history_subs.add_parser("stats", help="Show aggregate history stats")
    stats.set_defaults(_history_action="stats")

    show = history_subs.add_parser("show", help="Show a bounded history timeline")
    show.add_argument("--connection")
    show.add_argument("--chat", required=True)
    show.add_argument("--since")
    show.add_argument("--limit", type=int, default=DEFAULT_READ_LIMIT)
    show.set_defaults(_history_action="show")

    search = history_subs.add_parser("search", help="Search chat history text")
    search.add_argument("--connection")
    search.add_argument("--chat", required=True)
    search.add_argument("--text", required=True)
    search.add_argument("--since")
    search.add_argument("--limit", type=int, default=DEFAULT_READ_LIMIT)
    search.set_defaults(_history_action="search")

    deletions = history_subs.add_parser("deletions", help="List deleted-message classifications")
    deletions.add_argument("--connection")
    deletions.add_argument("--chat")
    deletions.add_argument(
        "--status",
        choices=["pending", "likely_duplicate", "likely_correction", "unexplained", "unclassifiable"],
        default="unexplained",
    )
    deletions.add_argument("--limit", type=int, default=DEFAULT_READ_LIMIT)
    deletions.set_defaults(_history_action="deletions")

    export = history_subs.add_parser("export", help="Export bounded history records")
    export.add_argument("--connection")
    export.add_argument("--chat", required=True)
    export.add_argument("--format", choices=["jsonl", "text"], default="jsonl")
    export.add_argument("--limit", type=int, default=DEFAULT_READ_LIMIT)
    export.add_argument("--since")
    export.set_defaults(_history_action="export")

    verify = history_subs.add_parser("verify", help="Verify canonical history files")
    verify.add_argument("--repair-tails", action="store_true")
    verify.set_defaults(_history_action="verify")

    maintain = history_subs.add_parser("maintain", help="Run classification and retention/size maintenance")
    maintain.set_defaults(_history_action="maintain")


def handle_cli(args: argparse.Namespace) -> int:
    action = getattr(args, "_history_action", None)
    if action is None:
        print("Usage: hermes telegram-business history <chats|stats|show|search|deletions|export|verify|maintain>")
        return 1

    if action == "chats":
        matches = _iter_chat_matches()
        summaries = [_chat_summary(records) for _, records in matches]
        limit = _bounded_limit(getattr(args, "limit", None), DEFAULT_CHAT_LIMIT)
        for summary in summaries[:limit]:
            print(
                f"{summary['business_connection_id']} chat={summary['chat_id']} "
                f"records={summary['records']} pending={summary['pending_deletions']} "
                f"unexplained={summary['unexplained_deletions']} "
                f"range={summary['first_observed_at']}..{summary['last_observed_at']}"
            )
        if not summaries:
            print("No Telegram Business history found.")
        return 0

    if action == "stats":
        config = history_config_from_env()
        stats = collect_history_stats()
        print(
            " ".join(
                [
                    f"enabled={config.enabled}",
                    f"connections={config.connections.render() if config.connections else '<unset>'}",
                    f"chats={config.chats.render() if config.chats else '<unset>'}",
                    f"correction_window={config.correction_window_seconds}s",
                    f"retention_days={config.retention_days}",
                    f"max_bytes={config.max_bytes}",
                    f"chat_count={stats.chat_count}",
                    f"file_count={stats.file_count}",
                    f"record_count={stats.record_count}",
                    f"pending={stats.pending_count}",
                    f"unexplained={stats.unexplained_count}",
                    f"total_bytes={stats.total_bytes}",
                    f"cap_exceeded={stats.cap_exceeded}",
                ]
            )
        )
        return 0

    if action in {"show", "search", "export"}:
        _chat_dir, records = _require_single_chat(
            business_connection_id=getattr(args, "connection", None),
            chat_id=str(args.chat),
        )
        since = _parse_since(getattr(args, "since", None))
        if since is not None:
            records = [record for record in records if (_parse_datetime(record.get("observed_at")) or _utcnow()) >= since]
        if action == "search":
            query = str(args.text).casefold()
            records = [
                record
                for record in records
                if query in str(record.get("text") or "").casefold()
            ]
        limit = _bounded_limit(getattr(args, "limit", None), DEFAULT_READ_LIMIT)
        records = _trim_records(records, limit)
        if action == "export" and args.format == "jsonl":
            for record in records:
                print(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            return 0
        for record in records:
            print(_history_text_line(record))
        return 0

    if action == "deletions":
        rows: list[str] = []
        status = str(args.status)
        for _chat_dir, records in _iter_chat_matches(
            business_connection_id=getattr(args, "connection", None),
            chat_id=None if getattr(args, "chat", None) is None else str(args.chat),
        ):
            state = _build_chat_state(records)
            for deleted_event_id, pending in state.pending_deletions.items():
                if pending.classification is None:
                    if status == "pending" and pending.deleted_event is not None:
                        rows.append(
                            f"{pending.deleted_event.get('observed_at')} message.deleted "
                            f"connection={pending.deleted_event.get('business_connection_id')} "
                            f"chat={pending.deleted_event.get('chat_id')} "
                            f"message={pending.deleted_event.get('message_id')} status=pending"
                        )
                    continue
                if pending.classification.get("classification") != status:
                    continue
                rows.append(_history_text_line(pending.classification))
        limit = _bounded_limit(getattr(args, "limit", None), DEFAULT_READ_LIMIT)
        for row in rows[:limit]:
            print(row)
        if not rows:
            print("No matching deletions found.")
        return 0

    if action == "verify":
        result = verify_history(repair_tails=bool(getattr(args, "repair_tails", False)))
        print(
            f"ok={result.ok} chats={result.chat_count} files={result.file_count} "
            f"records={result.record_count} repaired_files={result.repaired_files}"
        )
        for warning in result.warnings:
            print(f"warning: {warning}")
        for error in result.errors:
            print(f"error: {error}")
        return 0 if result.ok else 1

    if action == "maintain":
        result = maintain_history()
        print(
            f"classified={result.classified} pruned_files={result.pruned_files} "
            f"pruned_bytes={result.pruned_bytes} cap_exceeded={result.cap_exceeded} "
            f"cap_shortfall_bytes={result.cap_shortfall_bytes}"
        )
        for warning in result.warnings:
            print(f"warning: {warning}")
        return 0

    print(f"Unknown history action: {action}")
    return 1


def reset_in_memory_caches() -> None:
    global _LAST_MAINTENANCE_AT
    with _CACHE_LOCK:
        timer_entries = list(_DELETION_TIMERS.values())
        _DELETION_TIMERS.clear()
        _CHAT_STATE_CACHE.clear()
        _LAST_MAINTENANCE_AT = None
    for entry in timer_entries:
        entry.timer.cancel()
    _OWNER_CACHE.clear()


def remove_history_tree() -> None:
    shutil.rmtree(history_root(), ignore_errors=True)


def file_modes(path: Path) -> dict[str, int]:
    modes = {}
    for child in [path, *path.parents]:
        if child.exists():
            modes[str(child)] = stat.S_IMODE(child.stat().st_mode)
    return modes
