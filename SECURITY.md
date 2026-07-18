# Security Policy

## Supported Versions

Hermes Telegram Business is an early public Hermes plugin. Security fixes are scoped to the current public package line, currently `0.6.1`, and the legacy-stable runtime plugin ID `telegram-business-voice-transcriber`.

The maintained security scope is:

- Telegram Business `voice` and `video_note` updates delivered through a real Business connection.
- The plugin's `pre_gateway_dispatch` hook, Business-scoped reply/caption paths, adapter compatibility shim, duplicate guard, transient media handling, STT delegation, and optional transcript cleanup through the host-owned `ctx.llm`.
- Documentation, tests, and packaging for this plugin.

Unsupported or out-of-scope reports may include unrelated Hermes core behavior, Telegram account configuration issues, provider outages, generic CRM automation, or live-system incidents caused by custom local modifications outside this repository.

## Reporting a Vulnerability

GitHub private vulnerability reporting is currently disabled for this repository (`enabled: false`). Until maintainers advertise a private channel, use only a sanitized public issue.

Do not post secrets or private content. If a report appears sensitive, file the smallest sanitized public issue that describes the affected behavior without exposing private data. Maintainers may then move the discussion to a private channel if needed.

Never include:

- Bot tokens, API keys, credentials, cookies, session strings, or authentication headers.
- Telegram Business connection IDs.
- Chat IDs, user IDs, message IDs, update IDs, or relationship IDs.
- Transcript text, message bodies, correspondence, captions, or prompts copied from real chats.
- Audio, video notes, voice files, screenshots of real conversations, or exported chat data.
- STT/LLM provider logs, gateway logs containing private data, trace dumps, cache files, or environment dumps.
- Any other data that could identify a person, account, business, provider credential, or private conversation.

Safe reports should use synthetic identifiers such as `business-demo`, `chat-123`, and `message-456`, plus a minimal reproduction using fake Telegram objects or clearly redacted logs.

## Expected Handling

Maintainers will triage sanitized public reports as project capacity allows. For confirmed vulnerabilities, fixes should preserve the legacy runtime plugin ID and environment-variable namespace unless a breaking change is explicitly justified and documented.

Security fixes should avoid contacting live Telegram chats, providers, or user accounts during tests. Use synthetic fixtures and fake STT/LLM implementations.
