## Final Launch Preparation Package: Hermes Telegram Business Plugin

This package contains the final, polished copy and structured asset requirements for launching the `hermes-telegram-business` plugin across all designated channels. All drafts are optimized for maximum clarity, technical relevance, and actionable installation instructions, following the principle of providing concrete demos and one-line commands.

---

### 🚀 I. Core Assets & Installation (Must be Ready)

**A. Demo Asset:**
*   **Type:** Video/GIF (15–30 seconds).
*   **Content Focus:** Showing a Business-initiated voice note arriving $\rightarrow$ The Hermes system detecting it and transcribing it via STT $\rightarrow$ A response being drafted/sent *through the same apparent Business channel*.
*   **Key Visual Requirement:** Highlight that no "Agent Turn" counter increases for passive transcription.

**B. Installation Command (The universal call-to-action):**
```bash
hermes plugins install neoromantic/hermes-telegram-business --enable
```

---

### 🌐 II. Channel-Specific Copy & Strategy Drafts

#### **1. X (Twitter)**

*(Goal: Broad developer visibility; focus on the "magic" fix.)*

**A. Main Launch Post (T0):**
> Built a public Hermes Agent plugin to solve a niche Telegram Business problem: Voice/video notes arrive outside standard bot message paths.
>
> This plugin transcribes and replies through the *same* Business connection, critically **without spending an agent turn**. 🤯
>
> Install + Source:
> `hermes plugins install neoromantic/hermes-telegram-business --enable`
> [Link to GitHub Repo]
> *(Attach 15–30 second demo video)*

**B. Contextual Reply (Use ONLY if initial post traffic is slow and needs a technical hook):**
> This is the Telegram Business edge case I hit: voice notes arrive outside the ordinary bot message path (`business_message`). Extracting this fix into Hermes preserves the crucial Business connection and runs STT efficiently: [Link to GitHub Repo].

#### **2. Nous Discord (Official Plugin Channel)**

*(Goal: Direct, technical announcement for existing power users.)*

> **✨ Release v0.5.0: Telegram Business Connector ✨**
>
> We're excited to announce `hermes-telegram-business`, a standalone Hermes plugin designed to solve the challenging event routing within Telegram Business API contexts.
>
> This module allows your agent to seamlessly transcribe and reply to authorized Business voice/video notes using the dedicated Business connection, critically *without consuming an additional LLM turn.*
>
> **Install:**
> `hermes plugins install neoromantic/hermes-telegram-business --enable`
>
> We welcome feedback on the routing model itself and which other complex Telegram Business events (e.g., scheduled sends, opt-in history) need tackling next!
> [Link to GitHub Repo]

#### **3. Reddit**

*(Strategy: Treat as a high-value deep dive. Requires drafting two separate versions depending on the chosen subreddit focus.)*

**A. Target Subreddit 1 (r/Developer / r/Automation): Focus on API pain points.**
> **Title:** I open-sourced a Hermes Agent plugin for Telegram Business's complex message routing.
>
> **Body:**
> Hey all, most standard bots only see messages through the primary handler path. However, within Telegram Business, voice and video notes can arrive via distinct `business_message` payloads, requiring specific context preservation to reply correctly.
>
> I solved this in my own Hermes setup and wrapped it into a standalone plugin: `hermes-telegram-business`.
>
> **What it does:**
> 1. Detects authorized Business voice/video notes (`business_message` path).
> 2. Routes media through your configured STT provider.
> 3. Replies by maintaining the original Business connection context.
> 4. *Crucially:* It handles passive transcription without costing an agent LLM turn.
> 5. Keeps standard unauthorized DMs blocked.
>
> **Installation:**
> ```bash
> hermes plugins install neoromantic/hermes-telegram-business --enable
> ```
> Source, threat model, and deeper compatibility notes: [Link to GitHub Repo]
>
> I'm the author—I'd be grateful for input on real-world pain points in Business APIs. What event type is next? (e.g., outgoing transcript processing, etc.)

**B. Target Subreddit 2 (r/Telegram): Focus on Platform Integration/Feature Gaps.**
> **Title:** Bridging the gap between Telegram Business Notes and Automated Agents using Hermes.
>
> **Body:**
> As many of you know, while bots are great, the specific message flow for voice/video notes in a formal Business context often bypasses standard bot handlers, making full automation tricky.
>
> I wrote `hermes-telegram-business`—a plugin that explicitly intercepts and manages these `business_message` events. It allows an agent to reliably transcribe media from the dedicated Business channel *and* reply within that conversation thread, all without wasting an expensive LLM turn on simple transcription.
>
> **Details:** [Include bulleted technical breakdown as above.]
> **Install:** `hermes plugins install neoromantic/hermes-telegram-business --enable`
> Source: [Link to GitHub Repo]

#### **4. Telegram Story (Visual Asset)**

*(Goal: High visual impact, minimal text. Requires graphic design approval.)*

**Format:** 1080x1920 pixels. All real correspondent identities must be redacted/blurred.

| Frame | Title/Theme | Text Content (Russian) | Required Visual Elements |
| :--- | :--- | :--- | :--- |
| **1. Проблема** | The Edge Case | «В Telegram Business голосовые сообщения идут отдельным event path — обычный bot handler их не видит.» | Flowchart visualization showing the "standard" message line, with a dashed arrow pointing to an unseen 'Business Note' path. |
| **2. Что сделал** | The Solution | «Я вынес решение из своего Hermes в open-source plugin: voice/video $\rightarrow$ transcript $\rightarrow$ reply в тот же Business-чат. Без отдельного LLM-turn.» | Clean UI mockup showing the media input, a transparent "Transcription Engine" block (Hermes), and the context-preserving outgoing message. |
| **3. CTA** | Get Started | `github.com/neoromantic/hermes-telegram-business` / QR Code | Bright background with the plugin name and GitHub link/QR code dominating the space. |

#### **5. awesome-hermes-agent Submission**

*(Goal: Catalog listing for deep technical discoverability.)*

| Field | Value |
| :--- | :--- |
| **Name:** | Hermes Telegram Business |
| **URL:** | `https://github.com/neoromantic/hermes-telegram-business` |
| **Author:** | neoromantic |
| **Category:** | Plugins (Messaging Integration) |
| **Description:** | Specialized agent plugin for complex Telegram Business contexts. Transcribes authorized voice and video notes into text format and replies via the original connection, preserving context while avoiding unnecessary LLM resource usage. |
| **Why awesome:** | It elegantly handles Telegram's distinct and non-standard event routing model used by its Business API, ensuring that automation remains robust even when media arrives on side channels. Ships with full testing and single-command installation. |
| **Why now:** | As companies increasingly rely on Telegram for operational communication (beyond simple DMs), this plugin enables true, reliable automation of asynchronous voice/video content without requiring a fundamental change in the core agent architecture. |
| **License:** | MIT |
| **Suggested maturity:** | beta |
| **Disclosure:** | author-affiliated; STT functionality may rely on user-configured paid providers within Hermes. |

---

### ✅ III. Launch Execution Checklist (Readiness Report)

| Task | Status/Requirement | Next Step |
| :--- | :--- | :--- |
| **GitHub Repo** | README, Changelog updated with detailed technical explanation of `business_message` handling. Full test coverage committed. | Final merge and verification of release tags. |
|