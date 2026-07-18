# Launch Asset Briefs

All assets must be synthetic, privacy-safe, and clearly labeled as mockups or schematics where applicable. Do not create fake Telegram client screenshots or imply live Telegram rendering. Do not use real Telegram chats, Business connection IDs, chat/user/message IDs, names, avatars, credentials, logs, audio, video, correspondence, transcripts, provider data, or customer data.

Use synthetic names such as `Mira Chen`, `Northstar Studio`, and `Alex Demo`. Use schematic interface shapes, not copied Telegram UI. Keep all visible identifiers fictional and generic.

## hero-social.webp

- Dimensions: `1280x640`.
- Format: WebP.
- Alt text: `Schematic Hermes Telegram Business flow showing a voice note becoming a transcript through a Business connection.`
- Brief: A clean product-social image with the title `Hermes Telegram Business`, a schematic Business connection line, a voice-note symbol, a transcript panel, and a small `0.6.1` label. Include a visible `Mockup` label. Avoid Telegram client chrome, fake chat screenshots, real logos, and real IDs.
- Production constraints: readable at social-card size, no external brand marks, no live-chat content, no secrets, no provider names unless generic `Configured STT` is used.

## flow.webp

- Dimensions: `1600x900`.
- Format: WebP.
- Alt text: `Schematic event path from Telegram Business voice or video note to Hermes STT and Business-scoped caption or reply.`
- Brief: A schematic architecture diagram: `Telegram Business update` -> `pre_gateway_dispatch` -> `transient download` -> `Hermes configured STT` -> optional `ctx.llm cleanup` -> `edit caption with business_connection_id` or `send separate reply with business_connection_id`. Show the passive handler returning `action: skip` without claiming there is no LLM. Mark `ctx.llm cleanup` as optional.
- Production constraints: diagram only, no real logs, no real identifiers, no network/provider logos, no fake app screenshot.

## demo.gif

- Dimensions: `1200x750`.
- Maximum size: `8 MB`.
- Format: GIF or optimized animated WebP if the publishing target supports it.
- Alt text: `Synthetic demo of an incoming Business-chat voice note becoming a transcript reply through Hermes configured STT.`
- Brief: A schematic, synthetic product demo with a visible `Synthetic mockup` label. Show an incoming Business-chat voice note with the synthetic spoken request `Please move tomorrow's delivery to 2 PM and confirm the new time.`, a short `business_message -> Hermes plugin -> configured STT` overlay, the transcript reply appearing in the same Business chat, and an end card with `Same Business connection. No full agent turn.` plus `hermes plugins install neoromantic/hermes-telegram-business --enable`. Use abstract chat rows and fictional names only. Do not mimic exact Telegram client rendering.
- Production constraints: no real audio waveform, no captured client UI, no real correspondence, no provider logs, no credentials, no IDs, no production timestamps.

## 20-Second Synthetic Demo

Target length: `18-22` seconds.

Sequence:

| Time | Scene | Copy |
| --- | --- | --- |
| `0-3s` | Owner has already configured a Telegram Business connection and Hermes STT. | `Business connection configured by the account owner` |
| `3-6s` | Synthetic incoming voice note appears in a schematic Business chat. | `Incoming Business-chat voice note` |
| `6-9s` | The voice note expands to the exact synthetic spoken request. | `Please move tomorrow's delivery to 2 PM and confirm the new time.` |
| `9-12s` | Short processing overlay shows the event path. | `business_message -> Hermes plugin -> configured STT` |
| `12-15s` | Transcript reply appears in the same Business chat. | `Please move tomorrow's delivery to 2 PM and confirm the new time.` |
| `15-18s` | Privacy boundary panel. | `Configured STT receives media; optional ctx.llm cleanup may receive transcript` |
| `18-22s` | End card with install command. | `Same Business connection. No full agent turn.` and `hermes plugins install neoromantic/hermes-telegram-business --enable` |

Use the exact synthetic spoken request `Please move tomorrow's delivery to 2 PM and confirm the new time.` for the main demo transcript. Keep all visible content fictional.

## Outgoing Caption/Fallback Demo

- Dimensions: can reuse `1200x750` for video/GIF or `1600x900` for a still schematic.
- Alt text: `Schematic comparison of outgoing caption edit and safe separate-reply fallback for Telegram Business voice notes.`
- Brief: Two-panel schematic. Left: short outgoing media note inside the Telegram Business edit window receives appended caption text. Right: incoming, expired, uncertain, or over-limit media receives a separate transcript reply. Both panels explicitly show `business_connection_id preserved`.
- Production constraints: label as `Schematic`, avoid fake Telegram screenshots, use only synthetic transcript text, and do not show IDs, logs, tokens, audio, video, or real users.

## story-01.webp

- Dimensions: `1080x1920`.
- Format: WebP.
- Alt text: `Story frame showing the Telegram Business voice-note event-path problem as a schematic.`
- Brief: Vertical story frame introducing the narrow problem: Business-connected voice/video notes need transcription before a full Hermes agent turn. Use schematic bubbles and a visible `Synthetic schematic` label.
- Production constraints: no real client UI, no real names, no IDs, no screenshots.

## story-02.webp

- Dimensions: `1080x1920`.
- Format: WebP.
- Alt text: `Story frame showing Hermes configured STT and optional ctx.llm cleanup in the transcript path.`
- Brief: Vertical story frame showing transient media processing, Hermes-configured STT, optional `ctx.llm` cleanup, and raw transcript fallback. Do not claim cleanup always runs.
- Production constraints: no provider logos, credentials, provider logs, real audio, or real transcript content.

## story-03.webp

- Dimensions: `1080x1920`.
- Format: WebP.
- Alt text: `Story frame showing Business-scoped caption edit and separate reply fallback.`
- Brief: Vertical story frame showing the result paths: short outgoing note caption edit and separate Business-scoped reply fallback. Include `same Business connection` as a visible label.
- Production constraints: synthetic mockup only, no fake Telegram screenshot, no real message content, no IDs, no logs.
