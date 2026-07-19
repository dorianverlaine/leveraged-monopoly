# Frontend — Leveraged Monopoly 🦈

Duolingo-flavoured, emoji-forward, four-language client for the game. Built with
**Vite + React + TypeScript** and a hand-written design system (no UI framework —
the tactile "feel" is the point, so it's controlled directly).

```bash
npm install
npm run dev        # http://localhost:5173
```

The dev server proxies `/ws` to the Python realtime server, so run the backend
alongside it for live play:

```bash
monopoly-server    # from the repo root, in the Python env
```

## What's here

| Path | What |
|------|------|
| `src/styles/global.css` | The design system: palette, the tactile 3D "push" button, cards, chips, animations |
| `src/styles/game.css` | Game screen: the 7×7 board ring, control panel, drama overlay |
| `src/i18n/` | Tiny custom i18n (en / zh-Hant / zh-Hans / fr), keyed by the stable codes in [`../docs/i18n.md`](../docs/i18n.md) |
| `src/types.ts` | Wire types mirroring the backend's public state |
| `src/mock.ts` | A realistic mock game so the UI runs and can be designed **without a server** |
| `src/components.tsx` | Board ring, player strip, event feed, drama overlay, buttons |
| `src/screens/` | `Home`, `Game` |

## Design notes

- **The tactile button is the signature.** Solid fill + a darker shadow edge
  underneath; pressing translates it down and collapses the shadow. That physical
  "push" is what makes it feel like Duolingo.
- **Emoji are a first-class visual layer** (per [`../docs/frontend.md`](../docs/frontend.md)) —
  they carry meaning across four languages without translation.
- **The control panel is pinned** to the bottom and never scrolls away: cash,
  net worth, debt, and a margin meter that turns red and pulses near a margin
  call. One big hero CTA carries the turn; secondary tools sit in a compact grid.
- **Dumb client**: buttons are rendered straight from the server's `available`
  list; the client computes no game rules.

## Status

First pass: Home + Game screens against mock state, full design system, i18n.
Still to wire: the live WebSocket client (`authenticate` → `create_room`/
`join_room` → `action`), the lobby screen, and per-action argument prompts
(amount for borrow/repay, tile for build, trade composer).
