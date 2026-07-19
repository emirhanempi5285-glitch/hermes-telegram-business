# Changelog

## Unreleased

- Normalize Telegram Business identifiers, direction, timestamps, relationships, and media before routing events through independently enabled modules.
- Add explicit handled/pass-through results, per-module LLM opt-in, stable retry identity, and failure isolation without adding persistence or provider clients.
- Run the existing voice/video-note transcriber as the first module on the shared non-agent pipeline while preserving its Business-scoped behavior.
- Attach fitting transcripts to outgoing Business voice/video-note captions without a duplicate reply.
- Preserve existing caption text and entities, and fall back to Business-scoped replies for incoming, long, expired, uncertain, or uneditable messages.
- Render transcript caption blocks and reply chunks with native `expandable_blockquote` entities using UTF-16 offsets.
- Keep long and emoji-heavy transcripts complete with UTF-16-safe chunking, and align caption/reply fallback by retrying the selected surface as plain text when Telegram rejects expandable entities.
- Add opt-in raw, no-agent Telegram Business text history captured from blocking PTB Business update observation.
- Persist immutable delete tombstones plus source-tagged `deletion.classified` records with canonical `classification_reason` codes.
- Keep history storage and CLI bounded with streamed JSONL scans, closed-partition pruning, and terminal-safe text rendering.
- Fix the raw Business observer path so Hermes startup handling with `Update.ALL_TYPES` also records deleted Business updates.

## 0.6.1 - 2026-07-18

- Resolve the active Telegram adapter through Hermes's platform registry.
- Support Hermes 0.18.2's isolated `hermes_plugins.telegram_platform` loader while retaining the legacy import fallback.
- Test that the shim patches the registered adapter class rather than a duplicate legacy module.

## 0.6.0 - 2026-07-18

- Move the Telegram Business adapter compatibility into the persistent user plugin.
- Handle Business updates exposed through `effective_message` without mutating PTB update objects.
- Register round video notes with Hermes's media handler.
- Keep the auth exception opt-in and limited to real Business voice/video-note media.
- Remove the need to patch Hermes core during or after normal updates.

All notable changes to this project are documented here.

## [0.5.0] - 2026-07-17

### Changed

- Rebranded the public product, repository, and package metadata as **Hermes Telegram Business** / `hermes-telegram-business`.
- Positioned voice and video-note transcription with Business-scoped replies as the first currently shipped module rather than the product boundary.
- Updated installation examples, badges, source/homepage links, and release references to the canonical repository URL.

### Compatibility

- Retained `telegram-business-voice-transcriber` as the legacy-stable Hermes runtime plugin ID, including existing config keys, update/remove commands, and cache paths.
- Retained all existing `TG_BUSINESS_VOICE_*` environment-variable namespaces.
- Existing installations that use the old GitHub URL continue through GitHub's repository redirect; no reinstall is required.

## [0.4.1] - 2026-07-17

### Fixed

- Made standalone source imports and credential-free tests portable outside a full Hermes installation.
- Added the missing `pytest-asyncio` CI dependency so async tests run across supported Python versions.

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

[0.5.0]: https://github.com/neoromantic/hermes-telegram-business/releases/tag/v0.5.0
[0.4.1]: https://github.com/neoromantic/hermes-telegram-business/releases/tag/v0.4.1
[0.4.0]: https://github.com/neoromantic/hermes-telegram-business/releases/tag/v0.4.0
