# Contributing

## Local Setup

This repository is a Python `>=3.11` Hermes plugin with a minimal `pyproject.toml` and a `uv.lock` that currently contains only project metadata. There is no declared development dependency group yet.

Use `uv` to run tools with explicit test dependencies:

```bash
uv run --frozen --with pytest --with pytest-asyncio --with pyyaml python -m pytest -q
```

The GitHub Actions workflow currently uses the equivalent pip path:

```bash
python -m pip install --upgrade pytest pytest-asyncio pyyaml
python -m pytest -q
```

Ruff configuration exists in `pyproject.toml`, but Ruff is not currently declared as a project dependency. Run it explicitly when checking a change:

```bash
uv run --frozen --with ruff ruff check .
```

Contributors may format only the Python files they actually change.

## Scope Discipline

Keep changes focused on the plugin behavior or documentation under review. Avoid unrelated refactors, metadata churn, version bumps, release notes, deploy steps, and changes to Hermes core.

The public package is `hermes-telegram-business`, but the runtime plugin ID remains `telegram-business-voice-transcriber`. That legacy ID is used by existing Hermes install directories, enablement/config keys, update/remove commands, and cache paths. Do not rename it casually.

Existing environment-variable namespaces are also legacy-stable. Preserve them unless a breaking change is explicitly planned, tested, and documented.

Do not test against live Telegram chats, production gateways, real provider accounts, or customer systems for ordinary PRs. Use synthetic fixtures and fake adapters/STT/LLM objects.

## Privacy Requirements

Never commit real Telegram content or provider data. Fixtures, logs, and screenshots must be synthetic or heavily sanitized.

Do not include:

- Bot tokens, API keys, credentials, cookies, or session strings.
- Telegram Business connection IDs.
- Chat IDs, user IDs, message IDs, update IDs, or relationship IDs from real systems.
- Transcript text, message bodies, captions, prompts, audio, video, or screenshots from real conversations.
- STT/LLM provider logs, gateway logs with private data, cache files, or full environment dumps.

Use placeholders such as `business-demo`, `chat-123`, `message-456`, and short synthetic transcripts.

## Pull Requests

Expected PR shape:

- Focused diff with a clear behavior, test, or documentation purpose.
- Tests updated for behavior changes and static safety checks when useful.
- `uv run --frozen --with pytest --with pytest-asyncio --with pyyaml python -m pytest -q` run locally when possible.
- Ruff checks run with `uv run --frozen --with ruff ruff check .` when possible; format only Python files changed by the PR.
- A local diff review for accidental secrets, live IDs, unrelated files, release/deploy changes, and misleading product claims.
- Behavior and privacy documentation updated when the user-visible trust boundary changes.

Do not bundle releases, deployments, public announcements, or live-system validation into an ordinary code PR unless maintainers explicitly request that scope.
