# Leveraged Monopoly — Backend

A real-time, turn-based multiplayer board game (up to 6 players) with modern
capital-market mechanics: **leverage, margin calls, systemic shocks,
securitization, and inflation**. This repository is the **Python backend** — the
deterministic economic engine and everything around it that can be tested
headlessly, without any cloud.

> This is an international, open collaboration project. **All code comments are in
> English.** Please keep them that way in contributions.

---

## Why this exists

The whole design rests on one idea (see [`docs/architecture.md`](docs/architecture.md)):
a single **pure, deterministic, seeded economic engine**.

```
reduce(state, action) -> new_state | RuleError
```

- **No side effects.** No clock, no network, no ambient randomness — all
  randomness is drawn from a seeded PRNG carried *inside* the state.
- **Same seed → same game, everywhere.** This one property buys us trivial
  reconnection (resend the state), tiny replays (`seed + action_log` *is* the
  game), anti-cheat by construction (clients hold no authority), and a backtest
  that is just the engine run in a loop.

The engine is **Python everywhere** — one implementation, one language, for the
live server, replays, and the backtest alike. (The original architecture staged a
later rewrite into Rust → WASM; we have decided against it — see
[ADR 0001](docs/decisions/0001-python-only-no-rust.md). A turn-based game and a
horizontally-scalable, deterministic backtest don't need native speed, and one
language is far simpler to iterate on.)

---

## Repository layout

Everything is modular so individual rule layers, bots, or the future
persistence/transport layer can be swapped without touching the kernel.

```
src/monopoly/
├── engine/                # The deterministic kernel — the heart of the system
│   ├── rng.py             # SplitMix64 seeded PRNG (deterministic, portable)
│   ├── state.py           # GameState, GameConfig, TurnState, Transaction, new_game()
│   ├── board.py           # 3-city themed ring (HK/Paris/NY), groups, development
│   ├── player.py          # Player + lifecycle status
│   ├── market.py          # Price index, money supply, shock clock
│   ├── actions.py         # The action space (intents clients may send)
│   ├── errors.py          # Typed RuleError codes (the engine is total)
│   ├── valuation.py       # Derived metrics: net worth, collateral, monopoly
│   ├── reducer.py         # reduce(state, action) — the one pure entry point
│   └── mechanics/         # One module per rule layer:
│       ├── movement.py         #   dice, moving the ring, GO salary
│       ├── trading.py          #   buying property, paying rent (+monopoly bonus)
│       ├── building.py         #   develop a monopoly (houses → skyscraper)
│       ├── trade.py            #   player-to-player trade offers (not turn-gated)
│       ├── leverage.py         #   borrowing, repaying, mortgaging
│       ├── securitization.py   #   IPO a slice of a property for cash
│       ├── margin.py           #   margin calls, forced liquidation, bankruptcy
│       ├── inflation.py        #   per-round price growth + interest accrual
│       └── shock.py            #   correlated systemic price shocks
├── bots/                  # Policy interface + hand-authored strategies
│   ├── policy.py          #   decide(state, player_id) -> Action, respond_to_trade
│   ├── conservative.py    #   low leverage, hoards cash
│   ├── degen.py           #   max leverage, first to die or dominate
│   ├── cashflow.py        #   rent yield + securitization income
│   ├── contrarian.py      #   buys into the crash
│   ├── shark.py           #   the smart one: times shocks, completes monopolies
│   └── registry.py        #   name -> policy lookup (drop-in agents)
├── config/                # Pacing presets (quick/standard/long) + roster builder
├── simulation/            # Headless game loop, replay, Monte-Carlo backtest
│   ├── runner.py          #   play_game(...), replay(...), summarize_game(...)
│   └── backtest.py        #   run_batch(...) -> win-rate distributions
├── realtime/              # Authoritative WebSocket rooms (P1 transport)
│   ├── room.py            #   GameRoom — transport-agnostic, unit-tested
│   ├── hub.py              #   GameHub matchmaker + room codes
│   ├── protocol.py        #   the JSON wire contract (frontend spec)
│   ├── hints.py           #   best-effort "available actions" for the UI
│   └── server.py          #   `monopoly-server` — thin websockets adapter
├── persistence/           # Completed-game records + replays (SQLite ≈ D1)
│   ├── db.py              #   connection + schema (accounts, sessions, games…)
│   └── store.py           #   GameStore — game records, replays, match history
├── accounts/              # Passwordless identity + chess.com/Duolingo progression
│   ├── progression.py     #   pure XP / level curve + multiplayer Elo maths
│   ├── store.py           #   AccountStore — guests, sessions, profile, leaderboard
│   ├── service.py         #   record_finished_game — save game + update accounts
│   └── models.py          #   Account + GameOutcome value objects
├── cli.py                 # `monopoly-demo` — play a game in the terminal
└── history_cli.py         # `monopoly-history` — recent games, leaderboard, replay
tests/                     # pytest suite (determinism, mechanics, full games,
                            # realtime rooms, persistence, accounts)
docs/i18n.md               # the frontend i18n contract (4 languages)
```

---

## Game mechanics (the four capital-market layers)

These are chosen because they **detonate each other**, not because they add
arithmetic:

| Layer | What it does | Where it lives |
|-------|--------------|----------------|
| **Leverage + margin call** | Borrow against your portfolio to buy more; a falling collateral ratio triggers *forced liquidation* — a one-second collapse. | `mechanics/leverage.py`, `mechanics/margin.py` |
| **Systemic shock** | A correlated crash that hits everyone's asset values *at once*, margin-calling every over-leveraged player simultaneously. | `mechanics/shock.py` |
| **Securitization / REIT** | IPO a slice of a property for immediate cash; you keep only the un-sold share of its rent forever. | `mechanics/securitization.py` |
| **Inflation / money supply** | GO salary and asset values scale with a growing price index; cash bleeds, assets appreciate. | `mechanics/inflation.py` |

All the knobs (player count, map size, inflation rate, maintenance ratio, shock
cadence, victory condition) are **data** in `GameConfig`, never hardcoded.

### The board & development (the classic strategic spine)

The map is three real financial capitals — **Hong Kong, Paris, New York** — laid
out as three contiguous districts on one ring ([`engine/board.py`](src/monopoly/engine/board.py)).
Each city is a **property group**:

- **Monopoly bonus.** Sole-own *every* landmark of a city and its rent **doubles**.
- **Development.** A monopoly can be built up — houses → a skyscraper
  ([`mechanics/building.py`](src/monopoly/engine/mechanics/building.py)) — each
  level multiplying rent sharply (up to ~120× base at the top).
- **Interactions.** A developed landmark can't be mortgaged or securitized until
  its buildings are sold; a margin call / bankruptcy demolishes them. Securitizing
  any share of a city forfeits its monopoly. This is the substrate the capital
  layers detonate: trade to complete a set, leverage it to build, then a shock
  (or a rival's well-timed counter-trade) wipes out the over-developed player.

### Player-to-player trading

Landing alone on all six landmarks of a city is rare, so players **negotiate**
([`mechanics/trade.py`](src/monopoly/engine/mechanics/trade.py)) — the classic
Monopoly social/betrayal layer, and how development actually happens in
practice. Propose cash and/or property shares both ways; the recipient accepts,
rejects, or lets it sit. Two things make this architecturally distinct from
every other action:

- **Not turn-gated.** Real trade talk happens anytime — propose, accept, reject,
  and cancel work regardless of whose turn it is (every other action requires
  your turn).
- **Re-validated at accept, not just re-executed.** State can drift between a
  proposal and its acceptance (spent cash, mortgaged the tile, gone bankrupt);
  an offer is re-checked in full at accept time and dropped if it's gone stale,
  rather than partially executed.
- Since a traded property can be the collateral behind someone's leverage,
  accepting a trade re-runs solvency — giving away a leveraged monopoly can
  margin-call you, or receiving one can rescue you, in the same action.

---

## Quick start

```bash
# 1. Create an environment and install (standard-library only; pytest for tests)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Play a headless demo game
monopoly-demo --preset quick --seed 42 --players 5
#   ...or without installing:
PYTHONPATH=src python -m monopoly.cli --preset standard --seed 7

# 3. Run the tests
pytest -q
```

### Use it as a library

```python
from monopoly.config import quick_match, build_roster
from monopoly.simulation import play_game, replay

config = quick_match(max_players=4)
roster = build_roster(config)                 # empty seats filled with bots
result = play_game(config, seed=42, roster=roster)

print(result.winner_name, result.rounds_played, result.shocks_fired)

# The whole game is just seed + action_log — replay reproduces it exactly.
final_state = replay(config, seed=42, roster=build_roster(config),
                     action_log=result.action_log)
```

### Drive the engine directly

```python
from monopoly.engine import new_game, reduce, actions, GameConfig, Player, RuleError

state = new_game(GameConfig(max_players=2, map_size=24), seed=1,
                 players=[Player(0, "Alice", 0), Player(1, "Bob", 0)])

result = reduce(state, actions.roll_dice(0))
if isinstance(result, RuleError):
    print("rejected:", result)     # illegal actions never mutate state
else:
    state = result                 # success returns a brand-new state
```

### Real-time multiplayer server (P1)

A WebSocket server wraps the engine in **authoritative rooms** — one room owns one
`GameState`, mutated only through `reduce`. The room logic
([`realtime/room.py`](src/monopoly/realtime/room.py)) is transport-agnostic and
unit-tested; the [`websockets`](https://pypi.org/project/websockets/) adapter
([`realtime/server.py`](src/monopoly/realtime/server.py)) is a thin shell. Each
room is a single-threaded, in-memory authoritative object, so the server runs as
a long-lived Python process on AWS and scales out by pinning each room to its
owning instance (see [ADR 0001](docs/decisions/0001-python-only-no-rust.md)).

```bash
pip install -e ".[realtime]"
monopoly-server --host 127.0.0.1 --port 8765
```

The full wire protocol (the contract for any frontend) lives in
[`realtime/protocol.py`](src/monopoly/realtime/protocol.py). In short — all frames
are JSON:

| Client → Server | Server → Client |
|-----------------|-----------------|
| `create_room` · `join_room` · `reconnect` · `start` · `action` | `room_created` · `joined` · `lobby` · `state` · `error` |

Key properties:

- **Dumb clients.** Each accepted action broadcasts the full public state; clients
  re-render, never compute rules.
- **Anti-cheat by seat binding.** The server ignores a client's claimed
  `player_id` and uses the seat bound to its connection.
- **No RNG leak.** Clients receive `to_public_dict()` — the seeded PRNG state is
  stripped so the future can't be predicted.
- **Bots + reconnection.** Empty seats and disconnected humans are bot-driven so a
  game never stalls; reconnect with your token to resync the full state.
- **Join by code.** 4-character room codes from an unambiguous alphabet.

### Persistence: game history & replays (P1)

Completed games are recorded to a small SQLite database — the local stand-in for
the D1 tables in the cloud design (architecture 7.3, 9). The schema and
connection layer live in [`persistence/db.py`](src/monopoly/persistence/db.py);
everything else talks only to the repository,
[`persistence/store.py`](src/monopoly/persistence/store.py)'s `GameStore` — no
other module touches `sqlite3` directly, so swapping the target to D1 later only
touches `db.py`.

```bash
# The server records history by default (SQLite at ~/.local/share/leveraged-monopoly/games.db):
monopoly-server

# Disable it, or point at a specific file:
monopoly-server --no-persist
monopoly-server --db ./my-games.db

# Inspect what's recorded:
monopoly-history recent
monopoly-history leaderboard
monopoly-history replay <game_id>
```

What's stored per finished game: the config, the seed, the roster, and the full
`action_log` — **the whole replay in a few KB**, exactly like the headless
simulation's `GameResult` (`realtime/room.py`'s `GameRoom.to_game_result()` and
`monopoly.simulation.summarize_game()` produce the identical shape, so live
multiplayer games and backtest games persist through one code path). `replay`
re-runs the stored `seed + action_log` through the engine and prints the
recomputed standings — proving the record matches what the engine actually
produces.

### Accounts & progression (P1)

A **passwordless** account system gives the chess.com / Duolingo-style spine the
frontend needs: persistent identity, profile, and progression. It never collects
or stores a password — an account is keyed by a guest *device key* (or, later, an
external provider's subject id); the credential exchange always happens at that
provider, never in the game (architecture 11).

- **Identity** ([`accounts/store.py`](src/monopoly/accounts/store.py)): guest
  accounts with a "remember-me" device key, opaque server-issued **session
  tokens**, and profile fields (display name, avatar, **locale**).
- **Progression** ([`accounts/progression.py`](src/monopoly/accounts/progression.py),
  pure maths): **XP + levels** (always-up, Duolingo-style) and a **multiplayer
  Elo rating** (a ladder that can go down, chess.com-style), plus win streaks.
  Playing solo against bots earns XP but doesn't move your rating.
- **Wiring**: authenticate over WebSocket (`authenticate` → `authenticated`),
  then pass the `session` token to `create_room` / `join_room`. When a game ends,
  [`record_finished_game`](src/monopoly/accounts/service.py) saves the record and
  updates every human account's XP / level / rating / streak in one step. Play
  without logging in and you're an anonymous guest — the game is still recorded,
  it just earns no progression.

```bash
monopoly-history leaderboard --by rating   # or --by xp / --by wins
```

### Internationalization

The frontend targets four languages — **English, 繁體中文, 简体中文, Français**.
The backend is language-neutral: it emits **stable codes** (`RuleErrorCode`,
ledger `kind`, `ActionType`) and English only as a developer fallback, so the
frontend translates by code and never shows server English. Each account stores
its `locale`. The full contract and a starter glossary are in
[`docs/i18n.md`](docs/i18n.md).

---

## Design principles

1. **Server-authoritative, dumb clients.** Clients send *intent*; the engine
   holds the only true state. Cheating is structurally impossible.
2. **Pure-functional, deterministic engine.** `(state, action) -> new_state`,
   randomness seeded and carried in the state.
3. **Thin, replaceable everything.** The engine is dependency-free standard
   library; transport, persistence, and the compute plane sit behind interfaces.
4. **Parametrize the pacing.** Player count, map size, and length are parameters.
5. **Drama > balance (for humans).** Balance is what the backtest is for; human
   play optimizes for the one-second, table-flipping collapse.

---

## Roadmap

- **Done (P0):** deterministic engine, bots, headless simulation + backtest.
- **Done (P1 transport):** authoritative rooms behind a WebSocket server
  (join-by-code, bots, reconnection, anti-cheat).
- **Done (P1 persistence):** completed-game records, replays, and match history
  in SQLite (Postgres for scale); `monopoly-history` CLI.
- **Done (P1 accounts):** passwordless identity, sessions, and progression
  (XP / levels / Elo / streaks); 4-language i18n contract for the frontend.
- **Done (balance + smart bot):** presets tuned so the capital-market layer
  actually fires and assets appreciate between shocks (so aggression pays,
  restoring the "asset-holders win" thesis). Added the **`shark`** bot — it times
  the public shock clock (levers up between shocks, de-risks right before) and
  completes monopolies by trade; it is the strongest policy, while the reckless
  `degen` still dies. Simulation runner now resolves trades (not turn-gated).
- **Next:** a thin, multilingual React client (Duolingo / chess.com styling,
  emoji-forward — see [`docs/frontend.md`](docs/frontend.md)) against the
  `realtime/protocol.py` + `docs/i18n.md` contracts.
- **Then:** deploy — Python game server on **AWS**, frontend on **Cloudflare
  Pages**, Cloudflare as the edge (DNS / TLS / WebSocket proxy / WAF). Scale out by
  sharding rooms across instances. RL bots.

The engine stays **Python everywhere** — no Rust rewrite; see
[ADR 0001](docs/decisions/0001-python-only-no-rust.md). The original design
document is [`docs/architecture.md`](docs/architecture.md) (v0.1; its Rust / Durable
Object staging is superseded by ADR 0001).

## License

MIT — see [`LICENSE`](LICENSE).
