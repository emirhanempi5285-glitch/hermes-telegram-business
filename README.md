# Hermes Telegram Business

[![test](https://github.com/neoromantic/hermes-telegram-business/actions/workflows/test.yml/badge.svg)](https://github.com/neoromantic/hermes-telegram-business/actions/workflows/test.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An extensible [Hermes Agent](https://github.com/NousResearch/hermes-agent) integration for Telegram Business. Its first and currently shipped module turns voice messages and round video notes into text without spending a full agent turn.

## Current module: voice transcription

1. Intercepts a Telegram `voice` or `video_note` update at `pre_gateway_dispatch`.
2. Requires a real Telegram Business connection and preserves its `business_connection_id`.
3. Returns `action: skip` so the ordinary auth/agent path does not process the media.
4. Downloads the media transiently and delegates speech recognition to Hermes's configured `transcribe_audio` backend.
5. Optionally asks the host-owned `ctx.llm` facade to correct punctuation, capitalization, paragraphing, and obvious ASR errors.
6. Rejects lossy cleanup or model failure and falls back to the raw transcript.
7. For a short outgoing Business message, appends the transcript to the original voice/video-note caption as an expandable blockquote, retrying the same caption as plain text when Telegram rejects the new entity type.
8. Uses expandable Business-scoped replies for incoming, long, expired, or uneditable messages, with the equivalent plain-text retry.

Handled updates are identified from stable Telegram Business connection, chat, update/message, and relationship data, then suppressed in memory for 24 hours. A successful caption edit suppresses the separate transcript reply, so the chat never receives both forms. PTB `BadRequest` is treated as a definite Telegram-side rejection unless it is the recognized `message is not modified` or unsupported-entity case. Failed entity requests are not treated as delivered before their targeted plain-text retry, and ambiguous post-send transport/backend failures suppress the reply fallback unless remote state is verified. The plugin never runs a separate model provider client and never needs its own credentials.

## Roadmap

The broader product direction includes operator or CRM integration adapters and opt-in automation modules. The small event/module boundary is now implemented; those product integrations are still planned extension points, not implemented features in `0.6.1`.

## Requirements

- Hermes Agent with plugin hooks, `pre_gateway_dispatch`, and `ctx.llm` support (current Hermes releases).
- Python 3.11 or newer.
- A configured Telegram gateway with a Telegram Business connection.
- A working Hermes STT provider. Configure it with `hermes setup` or the [`stt` settings](https://hermes-agent.nousresearch.com/docs/user-guide/configuration).

Telegram Business voice/video notes can originate from users outside the ordinary DM allowlist. Enable the plugin's narrowly scoped adapter bypass so those updates can reach its hook:

```bash
HERMES_TELEGRAM_BUSINESS_VOICE_BYPASS_AUTH=1
```

At registration time the plugin installs a small, idempotent compatibility shim around Hermes's bundled Telegram adapter. It recognizes Business `effective_message` updates, registers round video notes with the media handler, and applies the bypass only when both a real `business_connection_id` and a `voice`/`video_note` payload are present. It does not bypass auth for ordinary messages or other media. Because the shim belongs to this profile-scoped user plugin rather than the Hermes checkout, a normal `hermes update` neither removes it nor creates a core patch conflict.

The plugin itself intentionally handles every voice/video note delivered through the bot's Business connections; it has no separate sender allowlist.

## Compatibility and identity

- The public product and repository are **Hermes Telegram Business** / `hermes-telegram-business`.
- The Hermes runtime plugin ID remains `telegram-business-voice-transcriber`. It is a legacy-stable internal ID used by existing install directories, enablement/config keys, update/remove commands, and cache paths.
- Existing environment-variable namespaces remain unchanged.
- Existing Git installations that retain the [old repository URL](https://github.com/neoromantic/hermes-telegram-business-voice-transcriber) continue to update through GitHub's redirect. No reinstall or config migration is required for this rebrand.

## Install

```bash
hermes plugins install neoromantic/hermes-telegram-business --enable
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

`hermes plugins update` uses the Git remote retained by the installer. Both the old redirected source URL and the canonical repository URL remain supported; do not copy the directory manually if you want supported updates. Hermes core updates and this plugin's updates are independent: the installed plugin persists across a core update, while the command above advances the plugin itself.

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

## Current module architecture

The plugin registers one `pre_gateway_dispatch` hook and normalizes Telegram Business updates before any module sees them. The immutable event includes stable identity, Business connection, chat/user/message/update identifiers, known direction, message/edit timestamps, reply/edit/delete relationships, and provider-neutral media metadata. Direction remains `unknown` when Telegram supplies no outgoing marker; the voice module retains its existing asynchronous Business-owner lookup before editing a caption.

Modules are a small ordered tuple. Each module has its own enable check, declares whether it may receive the host-owned LLM facade, and explicitly returns `handled` or `pass_through`. A pass-through result leaves the ordinary Hermes path untouched. A handled result returns `action: skip` immediately and schedules any slow work outside gateway dispatch:

```text
Telegram gateway event
  -> normalize Telegram Business identity and relationships
  -> enabled modules in order
       -> pass_through: try next module / ordinary Hermes path
       -> handled: duplicate guard + action: skip (no agent turn)
  -> asynchronous module work
  -> voice module: transient download
  -> Hermes transcribe_audio (configured host STT)
  -> optional ctx.llm structured cleanup
  -> lexical conservatism guard / raw fallback
  -> short outgoing message: edit_message_caption(..., caption_entities=[expandable], business_connection_id=...)
  -> otherwise: send_message(..., entities=[expandable], business_connection_id=...)
```

Outgoing direction is checked against the owner returned by Telegram's `getBusinessConnection`; `sender_business_bot` is also accepted as an explicit outgoing signal. Caption text is plain text and limited conservatively to Telegram's 1024 UTF-16 code-unit ceiling. An existing caption is retained unchanged at the start, including its entities, then separated from the transcript by a blank line. A UTF-16-positioned `expandable_blockquote` entity covers only the appended transcript block.

Incoming messages, transcripts that do not fit in one caption, messages outside Telegram's 48-hour Business edit window, uncertain direction, and definite caption-edit rejection, including generic PTB `BadRequest`, use the existing reply path. The first response chunk replies to the original message; continuation chunks use the same Business connection. Caption and reply surfaces follow the same capability policy: use `expandable_blockquote` first, then retry the selected surface once as plain text only after a recognized unsupported-entity rejection. Ambiguous caption-edit transport/backend failures after Telegram may already have seen the request suppress the separate reply instead of risking duplicate transcript delivery.

## Privacy and security

- Voice/video data is written only to the active Hermes profile's cache while it is processed. The newly created file is deleted in a `finally` block after success or failure.
- The configured STT backend receives the media. Depending on your Hermes configuration, that backend may be local or external.
- When cleanup is enabled, the configured host LLM receives the transcript. The system prompt treats transcript contents as untrusted data and forbids following embedded instructions.
- The plugin does not log transcript text. Operational logs include media type, message/chat identifiers, character counts, and errors.
- Error replies are disabled by default. When enabled, the first line of an exception may be sent to the Business chat.
- The plugin stores only an in-process duplicate key for 24 hours. Its identity is deterministic across equivalent retry delivery, but the seen set intentionally resets with the process; no transcript/history database is created.
- Existing Hermes/Telegram media caches are outside this plugin's ownership and are never scanned or deleted.

## Failure behavior

- Non-Telegram, non-Business, and non-voice/video events pass through untouched.
- Disabled and pass-through modules do not consume the event's duplicate identity.
- A module enable/route exception is logged and contained, and later modules still receive the event.
- Background module exceptions are contained and cannot crash the gateway.
- Missing bot or Business connection data stops processing without invoking an agent.
- STT failure sends nothing unless error replies are enabled.
- Empty STT output sends nothing.
- Cleanup timeout, trust denial, malformed output, excessive deletion/addition, or broad paraphrasing falls back to raw STT text.
- Caption direction checks, length checks, edit-window checks, and definite caption-edit rejections fall back to a separate expandable transcript reply.
- A recognized unsupported-entity response retries the selected caption or reply surface once without the new entity; PTB `BadRequest` counts as a definite caption rejection unless it is the recognized not-modified or unsupported-entity case, while `TimedOut`, other `NetworkError` failures, and unrelated exceptions suppress the reply fallback to avoid duplicates.
- A successful caption edit never also sends a transcript reply.

## Testing

The unit suite uses fake Telegram objects and fake STT/LLM implementations. It needs no Telegram token, provider credential, network call, or running gateway.

```bash
python -m pip install pytest pytest-asyncio pyyaml
python -m pytest -q
```

Real Telegram Business chats are deliberately not contacted by the test suite.

## License

[MIT](LICENSE)
