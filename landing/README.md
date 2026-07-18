# Hermes Telegram Business

Voice and round video notes for Telegram Business chats, transcribed by Hermes before they become a full agent turn.

[Install from source](../README.md) · [20-second synthetic demo brief](ASSETS.md#20-second-synthetic-demo)

## The Event-Path Problem

Telegram Business voice and video-note updates can arrive through a Business connection owned by a Telegram account, not through the ordinary direct-message path most bot workflows expect. Generic Telegram Business or CRM automation is a broader problem; this plugin targets the narrow event path where a Business-connected media note should become readable text without handing the media to a full Hermes agent turn.

## What It Does

- Intercepts Telegram Business `voice` and `video_note` updates at `pre_gateway_dispatch`.
- Requires and preserves the Telegram `business_connection_id`.
- Returns `action: skip` for handled media so the passive path avoids starting a full Hermes agent turn.
- Downloads the media transiently and sends it to the STT backend configured in Hermes.
- Optionally asks the host-configured `ctx.llm` to clean punctuation, capitalization, paragraphing, and obvious ASR errors.
- Falls back to the raw transcript when cleanup is unavailable, denied, malformed, or too lossy.
- Edits a short outgoing Business voice/video-note caption with the transcript when Telegram allows it.
- Uses the same Business connection for the safe separate-reply fallback when the message is incoming, too long, expired, uncertain, or uneditable.

## 20-Second Synthetic Demo

The launch asset should be a synthetic demo, not a live Telegram client recording and not a fake production screenshot. The storyboard is specified in [ASSETS.md](ASSETS.md#20-second-synthetic-demo): an incoming Business-chat voice note with the synthetic spoken request `Please move tomorrow's delivery to 2 PM and confirm the new time.`, a short `business_message -> Hermes plugin -> configured STT` overlay, the transcript reply in the same Business chat, and an end card that says `Same Business connection. No full agent turn.` plus the GitHub install command.

## Prerequisites, Install, Verify

Prerequisites:

- Hermes Agent with plugin hooks, `pre_gateway_dispatch`, and `ctx.llm` support.
- Python `>=3.11`.
- A configured Telegram gateway with a Telegram Business connection.
- A configured Hermes STT backend, local or external.
- Gateway-visible `HERMES_TELEGRAM_BUSINESS_VOICE_BYPASS_AUTH=1`.

Install the plugin into the Hermes profile used by the gateway:

```bash
hermes plugins install neoromantic/hermes-telegram-business --enable
hermes gateway restart
```

Verify the install:

```bash
hermes plugins list --user
```

The public package is `hermes-telegram-business`. The runtime plugin ID remains `telegram-business-voice-transcriber` for existing Hermes install paths, config keys, update/remove commands, and cache paths.

## Privacy and Trust Boundary

The plugin does not own provider credentials and does not run a separate model provider client. STT uses the Hermes-configured backend, which may be local or external depending on the host setup.

When transcript cleanup is enabled, the host-configured `ctx.llm` may receive the transcript. Set `TG_BUSINESS_VOICE_CLEANUP_DISABLE=1` to skip cleanup and post raw STT text.

Voice/video files are written only while processing and are deleted by the plugin after success or failure. The plugin does not log transcript text, create a transcript database, or scan unrelated Hermes/Telegram media caches.

## Current Scope And Non-Goals

Current scope:

- Telegram Business voice messages.
- Telegram Business round video notes.
- Business-scoped caption edit for short outgoing media.
- Business-scoped separate reply fallback for incoming, long, expired, uncertain, or uneditable media.
- Version/package truth: `0.6.1`.

Current non-goals:

- Generic Telegram Business automation.
- CRM/operator adapters.
- A separate allowlist inside the plugin.
- A separate STT or LLM credential store.
- A hosted marketing site, released demo asset, PyPI availability claim, or clean-profile production proof.

## Feedback And Source

Use the repository source, install, testing, privacy, and failure-behavior details in the [root README](../README.md). File only sanitized public issues unless maintainers advertise a private security channel.
