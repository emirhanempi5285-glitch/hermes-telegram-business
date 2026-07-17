# Changelog

All notable changes to this project are documented here.

## [0.4.0] - 2026-07-17

### Added

- Public, Git-installable Hermes Agent plugin distribution.
- Telegram Business voice-message and round-video-note interception through `pre_gateway_dispatch`.
- Host-configured STT delegation and optional host-owned LLM copy editing.
- Conservative cleanup validation with raw-transcript fallback.
- Duplicate-update suppression, Telegram-safe chunking, and `business_connection_id`-aware replies.
- Credential-free unit tests and multi-version Python CI.

### Security

- Treat transcript text as untrusted LLM input and instruct cleanup models not to follow embedded commands.
- Delete each transiently downloaded media file after the transcription attempt.
- Keep cleanup failures fail-safe: the raw transcript is posted rather than dropped.

[0.4.0]: https://github.com/neoromantic/hermes-telegram-business-voice-transcriber/releases/tag/v0.4.0
