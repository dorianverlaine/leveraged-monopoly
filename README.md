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

The Python implementation here is the **P0/P1 stage**: prove the mechanics are
fun and correct in a language we can iterate on hourly. Once the rules stop
changing, the same engine is intended to be re-frozen into Rust → WASM (edge) and
native + PyO3 (AWS backtest), exactly as the architecture document stages it.

---

## Repository layout

Everything is modular so individual rule layers, bots, or the future
persistence/transport layer can be swapped without touching the kernel.

```
src/monopoly/
├── engine/                # The deterministic kernel — the heart of the system
│   ├── rng.py             # SplitMix64 seeded PRNG (portable to Rust later)
│   ├── state.py           # GameState, GameConfig, TurnState, Transaction, new_game()
│   ├── board.py           # Tile / ring generation (24 / 36 / 44), fractional ownership
│   ├── player.py          # Player + lifecycle status
│   ├── market.py          # Price index, money supply, shock clock
│   ├── actions.py         # The action space (intents clients may send)
│   ├── errors.py          # Typed RuleError codes (the engine is total)
│   ├── valuation.py       # Derived metrics: net worth, collateral, margin ratio
│   ├── reducer.py         # reduce(state, action) — the one pure entry point
│   └── mechanics/         # One module per rule layer:
│       ├── movement.py         #   dice, moving the ring, GO salary
│       ├── trading.py          #   buying property, paying rent
│       ├── leverage.py         #   borrowing, repaying, mortgaging
│       ├── securitization.py   #   IPO a slice of a property for cash
│       ├── margin.py           #   margin calls, forced liquidation, bankruptcy
│       ├── inflation.py        #   per-round price growth + interest accrual
│       └── shock.py            #   correlated systemic price shocks
├── bots/                  # Policy interface + 4 hand-authored strategies
│   ├── policy.py          #   decide(state, player_id) -> Action  (+ helpers)
│   ├── conservative.py    #   low leverage, hoards cash
│   ├── degen.py           #   max leverage, first to die or dominate
│   ├── cashflow.py        #   rent yield + securitization income
│   ├── contrarian.py      #   buys into the crash
│   └── registry.py        #   name -> policy lookup (drop-in agents)
├── config/                # Pacing presets (quick/standard/long) + roster builder
├── simulation/            # Headless game loop, replay, Monte-Carlo backtest
│   ├── runner.py          #   play_game(...) and replay(...)
│   └── backtest.py        #   run_batch(...) -> win-rate distributions
└── cli.py                 # `monopoly-demo` — play a game in the terminal
tests/                     # pytest suite (determinism, mechanics, full games)
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
([`realtime/server.py`](src/monopoly/realtime/server.py)) is a thin shell, so the
same room can later be lifted into a Cloudflare Durable Object.

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
- **Next (P1 persistence):** accounts, completed-game records, and replay storage
  (D1/KV/R2 in the cloud design; SQLite/Postgres works locally). Then a thin
  React client against the protocol above.
- **Later (P2):** freeze the proven rules into a Rust kernel (WASM at the edge,
  native + PyO3 for the AWS Monte-Carlo backtest cluster); RL bots.

See [`docs/architecture.md`](docs/architecture.md) for the full system design.

## License

MIT — see [`LICENSE`](LICENSE).
