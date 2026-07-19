# Frontend design requirements

The frontend isn't built yet; this file collects the product/design requirements
agreed so far, so the eventual build honors them. See also the wire protocol
([`../src/monopoly/realtime/protocol.py`](../src/monopoly/realtime/protocol.py))
and the i18n contract ([`i18n.md`](i18n.md)).

## Style & tone

- **Duolingo × chess.com.** Friendly, punchy, game-y (Duolingo) crossed with a
  competitive ladder feel — profiles, ratings, leaderboards (chess.com).
- **Emoji-forward.** Use emoji **heavily** throughout the UI: actions, resources,
  events, cities, status, drama popups, buttons, empty states. They double as a
  language-neutral visual layer (helpful given four languages) and carry the
  playful tone. Examples of the intent (not a fixed mapping): 🎲 roll · 🏙️ city ·
  🏦 leverage · 💥 systemic shock · 📉 margin call · 🤝 trade · 🏗️ build ·
  🏆 winner · 💸 bankruptcy · 🔥 win streak. The drama overlays especially should
  lean into emoji + motion.

## Non-negotiables (from the architecture & prior decisions)

- **Dumb client.** Receives the full public state each push and re-renders; never
  computes game rules. Enable/disable controls from the `available` array.
- **Multilingual: English, 繁體中文, 简体中文, Français.** Translate by stable
  code/key, never show the server's English `message`/`note`. See `i18n.md`.
- **Join by link / QR, one URL, no install.** Cross-device.
- **Control panel first (90% of attention):** cash, portfolio, and a
  net-worth/debt bar that **flashes red near a margin call**, plus the currently
  pressable buttons. Board overview is secondary.
- **Trading UI is not turn-gated.** Incoming/outgoing offers (`state.trades`) can
  be responded to anytime, regardless of whose turn it is.
- **No credentials in the game.** Auth is guest/session tokens via the accounts
  layer; never a password field in the game UI.

## Stack (tentative, decide at build time)

React + a thin WebSocket client, hosted on Cloudflare Pages (per ADR 0001:
frontend on Cloudflare, game server on AWS). An i18n library keyed by the codes
in `i18n.md`.
