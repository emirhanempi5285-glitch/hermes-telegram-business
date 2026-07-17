# Telegram Business Voice Transcriber for Hermes Agent

[![test](https://github.com/neoromantic/hermes-telegram-business-voice-transcriber/actions/workflows/test.yml/badge.svg)](https://github.com/neoromantic/hermes-telegram-business-voice-transcriber/actions/workflows/test.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A focused [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that turns Telegram Business voice messages and round video notes into text without spending a full agent turn.

## What it does

1. Intercepts a Telegram `voice` or `video_note` update at `pre_gateway_dispatch`.
2. Requires a real Telegram Business connection and preserves its `business_connection_id`.
3. Returns `action: skip` so the ordinary auth/agent path does not process the media.
4. Downloads the media transiently and delegates speech recognition to Hermes's configured `transcribe_audio` backend.
5. Optionally asks the host-owned `ctx.llm` facade to correct punctuation, capitalization, paragraphing, and obvious ASR errors.
6. Rejects lossy cleanup or model failure and falls back to the raw transcript.
7. Replies through the same Business connection, splitting long text into Telegram-safe chunks.

Duplicate updates are suppressed in memory for 24 hours. The plugin never runs a separate model provider client and never needs its own credentials.

## Requirements

- Hermes Agent with plugin hooks, `pre_gateway_dispatch`, and `ctx.llm` support (current Hermes releases).
- Python 3.11 or newer.
- A configured Telegram gateway with a Telegram Business connection.
- A working Hermes STT provider. Configure it with `hermes setup` or the [`stt` settings](https://hermes-agent.nousresearch.com/docs/user-guide/configuration).

Telegram Business voice/video notes can originate from users outside the ordinary DM allowlist. Current Hermes Telegram adapters require the narrowly scoped adapter bypass below for those updates to reach this plugin:

```bash
HERMES_TELEGRAM_BUSINESS_VOICE_BYPASS_AUTH=1
```

The adapter applies that bypass only when both a real `business_connection_id` and a `voice`/`video_note` payload are present. It does not bypass auth for ordinary messages or other media. The plugin itself intentionally handles every voice/video note delivered through the bot's Business connections; it has no separate sender allowlist.

## Install

```bash
hermes plugins install neoromantic/hermes-telegram-business-voice-transcriber --enable
hermes gateway restart
```

Inspect the installation:

```bash
hermes plugins list --user
```

Plugins are profile-scoped. Set `HERMES_HOME` or use the appropriate Hermes profile before installing when the gateway does not use the default profile.

## Update and remove

```bash
hermes plugins update telegram-business-voice-transcriber
hermes gateway restart
```

```bash
hermes plugins remove telegram-business-voice-transcriber
hermes gateway restart
```

`hermes plugins update` uses the Git remote retained by the installer, so do not copy the directory manually if you want supported updates.

## Configuration

All plugin variables are optional.

| Variable | Default | Meaning |
|---|---:|---|
| `TG_BUSINESS_VOICE_TRANSCRIBER_DISABLE` | false | Disable interception entirely. |
| `TG_BUSINESS_VOICE_TRANSCRIBER_SEND_ERRORS` | false | Reply with a short STT error notice. |
| `TG_BUSINESS_VOICE_CLEANUP_DISABLE` | false | Skip LLM cleanup and post raw STT text. |
| `TG_BUSINESS_VOICE_CLEANUP_PROVIDER` | `gemini` | Host provider requested for cleanup. |
| `TG_BUSINESS_VOICE_CLEANUP_MODEL` | `gemini-3.5-flash` | Host model requested for cleanup. |
| `TG_BUSINESS_VOICE_CLEANUP_TIMEOUT` | `45` | Cleanup timeout in seconds. |
| `TG_BUSINESS_VOICE_CLEANUP_MIN_CHARS` | `81` | Minimum transcript length for cleanup. |
| `TG_BUSINESS_VOICE_CLEANUP_MIN_WORDS` | `1` | Minimum word count for cleanup. |

Boolean values accept `1`, `true`, `yes`, or `on` (case-insensitive).

### LLM trust gate

Cleanup uses Hermes's host-owned `ctx.llm`; no provider key belongs in this repository or in plugin-specific files. Explicit provider/model overrides are fail-closed in Hermes. Permit only the provider and model you intend to use:

```yaml
plugins:
  entries:
    telegram-business-voice-transcriber:
      llm:
        allow_provider_override: true
        allowed_providers: [gemini]
        allow_model_override: true
        allowed_models: [gemini-3.5-flash]
```

If the trust gate, provider, or model is unavailable, the plugin logs the cleanup failure and posts the raw STT transcript. To use different environment values, update the allowlists to match. To avoid any LLM call, set `TG_BUSINESS_VOICE_CLEANUP_DISABLE=1`.

## Architecture

The plugin registers one `pre_gateway_dispatch` hook. Matching updates are marked as handled immediately and processing continues in an asynchronous task:

```text
Telegram Business voice/video note
  -> pre_gateway_dispatch filter + duplicate guard
  -> action: skip (no agent turn)
  -> transient download
  -> Hermes transcribe_audio (configured host STT)
  -> optional ctx.llm structured cleanup
  -> lexical conservatism guard / raw fallback
  -> Telegram send_message(..., business_connection_id=...)
```

The first response chunk replies to the original message; continuation chunks use the same Business connection.

## Privacy and security

- Voice/video data is written only to the active Hermes profile's cache while it is processed. The newly created file is deleted in a `finally` block after success or failure.
- The configured STT backend receives the media. Depending on your Hermes configuration, that backend may be local or external.
- When cleanup is enabled, the configured host LLM receives the transcript. The system prompt treats transcript contents as untrusted data and forbids following embedded instructions.
- The plugin does not log transcript text. Operational logs include media type, message/chat identifiers, character counts, and errors.
- Error replies are disabled by default. When enabled, the first line of an exception may be sent to the Business chat.
- The plugin stores only an in-process duplicate key for 24 hours; no transcript database is created.
- Existing Hermes/Telegram media caches are outside this plugin's ownership and are never scanned or deleted.

## Failure behavior

- Non-Telegram, non-Business, and non-voice/video events pass through untouched.
- Missing bot or Business connection data stops processing without invoking an agent.
- STT failure sends nothing unless error replies are enabled.
- Empty STT output sends nothing.
- Cleanup timeout, trust denial, malformed output, excessive deletion/addition, or broad paraphrasing falls back to raw STT text.
- Hook-task exceptions are contained and cannot crash the gateway.

## Testing

The unit suite uses fake Telegram objects and fake STT/LLM implementations. It needs no Telegram token, provider credential, network call, or running gateway.

```bash
python -m pip install pytest pytest-asyncio pyyaml
python -m pytest -q
```

Real Telegram Business chats are deliberately not contacted by the test suite.

## License

[MIT](LICENSE)
