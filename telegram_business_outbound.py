"""Small Telegram Business send CLI for Hermes profiles."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from hermes_constants import get_hermes_home
except ModuleNotFoundError as exc:
    if exc.name != "hermes_constants":
        raise

    def get_hermes_home() -> Path:
        configured = os.getenv("HERMES_HOME")
        return Path(configured).expanduser() if configured else Path.home() / ".hermes"


_TARGETS_FILE_NAME = "telegram-business-targets.json"


class TelegramBusinessCliError(RuntimeError):
    """User-facing CLI failure."""


@dataclass(frozen=True)
class TelegramBusinessTarget:
    alias: str
    business_connection_id: str
    chat_id: str


class PtbTelegramBusinessClient:
    def __init__(self, token: str):
        from telegram import Bot

        self._bot = Bot(token=token)

    async def get_business_connection(self, business_connection_id: str) -> Any:
        return await self._bot.get_business_connection(business_connection_id=business_connection_id)

    async def send_message(self, **kwargs: Any) -> Any:
        return await self._bot.send_message(**kwargs)


def _targets_path(home: Path | None = None) -> Path:
    return (home or get_hermes_home()) / _TARGETS_FILE_NAME


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _load_targets(path: Path | None = None) -> dict[str, TelegramBusinessTarget]:
    path = path or _targets_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise TelegramBusinessCliError(f"Target store is not valid JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise TelegramBusinessCliError(f"Target store has unexpected format: {path}")

    targets: dict[str, TelegramBusinessTarget] = {}
    for alias, data in raw.items():
        if not isinstance(alias, str) or not isinstance(data, dict):
            raise TelegramBusinessCliError(f"Target store has unexpected format: {path}")
        try:
            targets[alias] = TelegramBusinessTarget(
                alias=alias,
                business_connection_id=str(data["business_connection_id"]),
                chat_id=str(data["chat_id"]),
            )
        except KeyError as exc:
            raise TelegramBusinessCliError(f"Target {alias!r} is missing {exc.args[0]}") from exc
    return targets


def _save_targets(targets: dict[str, TelegramBusinessTarget], path: Path | None = None) -> None:
    path = path or _targets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        alias: {
            "business_connection_id": target.business_connection_id,
            "chat_id": target.chat_id,
        }
        for alias, target in sorted(targets.items())
    }
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _resolve_telegram_bot_token() -> str:
    try:
        from gateway.config import Platform, load_gateway_config

        cfg = load_gateway_config()
        telegram_cfg = cfg.platforms.get(Platform.TELEGRAM)
        token = str(getattr(telegram_cfg, "token", "") or "").strip()
        if token:
            return token
    except Exception:
        pass

    try:
        from hermes_cli.config import get_env_value

        token = str(get_env_value("TELEGRAM_BOT_TOKEN") or "").strip()
    except Exception:
        token = str(os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
    if not token:
        raise TelegramBusinessCliError("Telegram bot token is not configured for the active Hermes profile")
    return token


async def _require_business_reply_right(client: Any, business_connection_id: str) -> None:
    try:
        connection = await client.get_business_connection(business_connection_id=business_connection_id)
    except Exception as exc:
        raise TelegramBusinessCliError(f"Telegram Business connection check failed: {exc}") from exc

    if not _field(connection, "is_enabled"):
        raise TelegramBusinessCliError("Telegram Business connection is disabled")
    if not _field(_field(connection, "rights"), "can_reply"):
        raise TelegramBusinessCliError("Telegram Business connection does not have can_reply")


async def add_target(
    alias: str,
    *,
    business_connection_id: str,
    chat_id: str,
    client: Any,
    path: Path | None = None,
) -> TelegramBusinessTarget:
    targets = _load_targets(path)
    if alias in targets:
        raise TelegramBusinessCliError(f"Target alias already exists: {alias}")
    await _require_business_reply_right(client, business_connection_id)
    target = TelegramBusinessTarget(alias=alias, business_connection_id=business_connection_id, chat_id=str(chat_id))
    targets[alias] = target
    _save_targets(targets, path)
    return target


def list_targets(*, path: Path | None = None) -> list[TelegramBusinessTarget]:
    targets = _load_targets(path)
    return [targets[alias] for alias in sorted(targets)]


def remove_target(alias: str, *, path: Path | None = None) -> TelegramBusinessTarget:
    targets = _load_targets(path)
    try:
        removed = targets.pop(alias)
    except KeyError as exc:
        raise TelegramBusinessCliError(f"Target alias not found: {alias}") from exc
    _save_targets(targets, path)
    return removed


async def send_target(
    alias: str,
    *,
    text: str,
    reply_to_message_id: int | None = None,
    client: Any,
    path: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    targets = _load_targets(path)
    try:
        target = targets[alias]
    except KeyError as exc:
        raise TelegramBusinessCliError(f"Target alias not found: {alias}") from exc

    await _require_business_reply_right(client, target.business_connection_id)

    kwargs: dict[str, Any] = {
        "business_connection_id": target.business_connection_id,
        "chat_id": target.chat_id,
        "text": text,
    }
    if reply_to_message_id is not None:
        kwargs["reply_to_message_id"] = reply_to_message_id

    try:
        message = await client.send_message(**kwargs)
    except Exception as exc:
        raise TelegramBusinessCliError(f"Telegram Business send failed: {exc}") from exc

    delivered_at = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    return {
        "business_connection_id": target.business_connection_id,
        "chat_id": target.chat_id,
        "delivered_at": delivered_at.isoformat().replace("+00:00", "Z"),
        "reply_to_message_id": reply_to_message_id,
        "status": "sent",
        "target_alias": target.alias,
        "telegram_message_id": _field(message, "message_id"),
    }


def _client_from_profile() -> PtbTelegramBusinessClient:
    return PtbTelegramBusinessClient(_resolve_telegram_bot_token())


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def telegram_business_command(args: argparse.Namespace) -> int:
    action = getattr(args, "telegram_business_action", None)
    try:
        if action == "target_add":
            target = _run(
                add_target(
                    args.alias,
                    business_connection_id=args.business_connection_id,
                    chat_id=args.chat_id,
                    client=_client_from_profile(),
                )
            )
            _print_json({"status": "added", "target_alias": target.alias})
            return 0
        if action == "target_list":
            _print_json([asdict(target) for target in list_targets()])
            return 0
        if action == "target_remove":
            target = remove_target(args.alias)
            _print_json({"status": "removed", "target_alias": target.alias})
            return 0
        if action == "send":
            text = Path(args.text_file).read_text(encoding="utf-8")
            audit = _run(
                send_target(
                    args.target,
                    text=text,
                    reply_to_message_id=args.reply_to_message_id,
                    client=_client_from_profile(),
                )
            )
            if not args.quiet:
                _print_json(audit)
            return 0
    except (OSError, TelegramBusinessCliError) as exc:
        print(f"telegram-business: {exc}", file=sys.stderr)
        raise SystemExit(1)

    print("telegram-business: no action selected", file=sys.stderr)
    raise SystemExit(2)


def register_cli(parser: argparse.ArgumentParser) -> None:
    subparsers = parser.add_subparsers(dest="telegram_business_group")

    target_parser = subparsers.add_parser("target", help="Manage Telegram Business send targets")
    target_subparsers = target_parser.add_subparsers(dest="telegram_business_target_action")

    target_add = target_subparsers.add_parser("add", help="Add a Telegram Business target")
    target_add.add_argument("alias")
    target_add.add_argument("--business-connection-id", required=True)
    target_add.add_argument("--chat-id", required=True)
    target_add.set_defaults(func=telegram_business_command, telegram_business_action="target_add")

    target_list = target_subparsers.add_parser("list", help="List Telegram Business targets")
    target_list.set_defaults(func=telegram_business_command, telegram_business_action="target_list")

    target_remove = target_subparsers.add_parser("remove", help="Remove a Telegram Business target")
    target_remove.add_argument("alias")
    target_remove.set_defaults(func=telegram_business_command, telegram_business_action="target_remove")

    send_parser = subparsers.add_parser("send", help="Send static text through Telegram Business")
    send_parser.add_argument("--target", required=True)
    send_parser.add_argument("--text-file", required=True)
    send_parser.add_argument("--reply-to-message-id", type=int)
    send_parser.add_argument("--quiet", action="store_true")
    send_parser.set_defaults(func=telegram_business_command, telegram_business_action="send")
