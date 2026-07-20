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
- **The control panel is pinned** and never scrolls away: cash, net worth, debt,
  and a margin meter that turns red and pulses near a margin call. One big hero
  CTA carries the turn; secondary tools sit in a compact grid.
- **Responsive, with two real layouts** (breakpoint at 900px):
  - *Mobile* — a single column. The board is sized with container-query units
    (`min(100cqw, 100cqh)`) so the **whole ring always fits on screen** next to
    the panel, with no scrolling; the event feed collapses to a one-line ticker.
  - *Desktop* — three columns: players + full event feed on the left, a large
    board in the centre (with landmark names, which don't fit on mobile), and
    the control panel down the right so it never squeezes the board.
  Home and Lobby stay a centred narrow column at every width.
- **Dumb client**: buttons are rendered straight from the server's `available`
  list; the client computes no game rules.

## Status

**Connected to the live backend.** The client authenticates as a guest, creates
or joins a room by code, starts the game, and plays against the real engine and
bots over WebSocket (`src/net/client.ts` + `src/useGame.ts`). Demo mode still
runs the whole UI from `src/mock.ts` with no server, which keeps design work
fast and offline.

Actions that need parameters open a bottom sheet
(`src/components/ActionSheet.tsx`): an amount slider for borrow/repay, a tile
picker for build/mortgage/redeem/sell, tile + percentage for securitize, and a
trade composer (counterparty, cash both directions, and which landmarks each
side puts in). `buy` fills in the tile you're standing on automatically.

Still to build: a game-over / winner screen, dice-roll animation, and reconnect
UI (the protocol supports `reconnect` with the seat token, the client doesn't
use it yet).
