# Leveraged Monopoly — System Architecture

*A real-time, online multiplayer board game (max 6 players) with modern capital-market mechanics: leverage, margin calls, systemic shocks, securitization, and inflation.*

---

## 0. TL;DR

Two planes, one shared kernel.

- **Real-time plane → Cloudflare.** Durable Objects are the ideal primitive for a turn-based game room: one object per game = single-threaded authoritative state + hibernating WebSockets. Workers do matchmaking/routing, D1/KV/R2 handle persistence, sessions, and replays. Pages/Workers Assets serve the thin frontend from the edge.
- **Compute plane → AWS.** Everything that is *offline and heavy*: Monte-Carlo balance backtests, RL bot training, and analytics. Container-first on Fargate/Batch, GPU on EC2/SageMaker.
- **The unifier: one deterministic economic engine, written in Rust.** Compiled to **WASM** for the edge (runs inside the Durable Object) and to a **native binary + Python binding** for the AWS backtest cluster. Write the rules once; run them wherever they're needed. Same seed → same game, everywhere.

The whole design serves one master: **online sessions must be short, fast, and full of screaming.**

---

## 1. Design Principles

| # | Principle | Why it matters here |
|---|-----------|---------------------|
| 1 | **Server-authoritative, dumb clients** | Clients send *intent* ("mortgage X, borrow Y"), never compute game logic. The server holds the only true state. Cheating is structurally impossible — a client doesn't even know its own balance except by asking the server. |
| 2 | **Pure-functional, deterministic engine** | The engine is `(state, action, rng_seed) -> new_state`. No hidden I/O, no wall-clock, no ambient randomness. This one decision pays off in *four* different places (below). |
| 3 | **Thin, replaceable everything** | Frontend, realtime provider, and the compute plane are all swappable behind interfaces. Container-first, provider-agnostic. Parallel migration over big-bang rewrites. |
| 4 | **Parametrize the pacing knobs** | Player count (2–6), map size (24/36/44), and game length are *parameters in state*, not hardcoded. This is how you get "quick match: 4 players, 24 tiles, 20 min." |
| 5 | **Drama > balance (for humans)** | Balance is for the backtest. Human play optimizes for reversals, betrayal, and one-second bankruptcies. Unforgettable beats fair. |

### 1.1 The determinism dividend

The pure-functional, seeded engine is the crown jewel. It buys you, for free:

1. **Trivial reconnection.** Disconnected player rejoins → server ships the full current state → client rebuilds. No delta reconciliation.
2. **Replays as `seed + action log`.** You never store frame-by-frame state — just the seed and the ordered list of actions. Replaying is re-running the engine. A whole game is a few KB.
3. **Anti-cheat by construction.** The client can't diverge because it never holds authority.
4. **Backtest = the same engine in a loop.** The thing you claim you won't build, but will.

---

## 2. High-Level Topology

```
                          ┌──────────────────────────────────────┐
   Players (browser,      │            CLOUDFLARE (edge)          │
   phone or laptop) ──────┼──> Pages / Workers Assets  (frontend) │
        │                 │                                       │
        │  WebSocket       │   Worker (router / matchmaker)        │
        └─────────────────┼──────────────┐                        │
                          │              ▼                        │
                          │      ┌───────────────────┐            │
                          │      │  Durable Object    │  one per   │
                          │      │  = GAME ROOM       │  active    │
                          │      │  · authoritative   │  game      │
                          │      │    state (memory)  │            │
                          │      │  · WASM engine ◀───┼── shared    │
                          │      │  · WS hibernation  │   kernel    │
                          │      └───────┬───────────┘            │
                          │              │                        │
                          │   D1 (games, users) · KV (room→DO,    │
                          │   sessions) · R2 (replays: seed+log)  │
                          └──────────────┬───────────────────────┘
                                         │  completed-game export
                                         ▼
                          ┌──────────────────────────────────────┐
                          │               AWS (compute)           │
                          │  · Batch/Fargate: Monte-Carlo backtest │
                          │  · SageMaker/EC2 GPU: RL bot training  │
                          │  · S3 + warehouse: balance analytics   │
                          │  · Native Rust engine + PyO3 binding   │
                          └──────────────────────────────────────┘

              ▲ Rust engine compiles to BOTH: WASM (edge) + native (AWS) ▲
```

---

## 3. The Shared Kernel — Deterministic Economic Engine

This is the heart. Everything else is plumbing around it.

### 3.1 Contract

```
reduce(state: GameState, action: Action, seed: u64) -> Result<GameState, RuleError>
```

- **No side effects.** No network, no clock, no ambient RNG. All randomness is drawn from a seeded PRNG carried in `GameState`.
- **Total & validated.** Illegal actions return a typed `RuleError`, never mutate.
- **Serializable state.** `GameState` round-trips to JSON/msgpack for wire + persistence.

### 3.2 State shape (illustrative)

```
GameState {
  config:      { max_players, map_size, victory_condition, inflation_rate, ... }
  rng:         SeededRng            // deterministic; part of the state
  turn:        { active_player, phase, round_number }
  board:       Tile[]              // 24 / 36 / 44 ring, no branches in v1
  players:     Player[]            // net worth, cash, debt, holdings, status
  market:      { price_index, money_supply, shock_clock }
  ledger:      Transaction[]        // append-only, drives replay + audit
}

Player {
  cash, holdings[], debt, margin_ratio, status: Active|MarginCalled|Bankrupt|Disconnected
}
```

### 3.3 Action space

`RollDice`, `Buy`, `Mortgage`, `Leverage(borrow)`, `RepayDebt`, `Securitize(assetId, pct)`, `PayRent`, `EndTurn`, `Concede`. Every side-effectful action is an explicit, validated intent.

### 3.4 Language & runtime path (staged — do NOT skip to Rust)

The multi-cloud requirement ("run the same rules at the edge *and* in the backtest") is exactly the case where Rust→WASM earns its keep. But committing rules to Rust before they're proven *fun* is the classic over-engineering trap. So stage it:

| Phase | Engine lives in | Goal |
|-------|-----------------|------|
| **P0 — Find the fun** | TypeScript (runs directly in the Worker/DO) *or* Python | Prototype mechanics, iterate hourly, throw away freely. |
| **P1 — Lock the rules** | **Rust**, once mechanics stop changing | Single source of truth. Compile to `wasm32` for the DO. |
| **P2 — Feed the beast** | Same Rust crate, native target + **PyO3** | Millions of Monte-Carlo games on AWS at native speed. |

> Rule of thumb: freeze into Rust when either (a) the mechanics stop changing, or (b) the backtest in the prototype language gets too slow to iterate on. Not before.

---

## 4. Game Mechanics

Core Monopoly loop (roll → move → buy/pay rent → build) plus four capital-market layers. They are chosen because they **detonate each other**, not because they add arithmetic.

### 4.1 Leverage + Margin Call *(the soul)*
Property isn't cash-only anymore — mortgage holdings to borrow and buy more. But if `net_worth / debt` falls below the maintenance ratio → **forced liquidation**. This converts "slow grind to bankruptcy" into "one-second collapse." When someone lands on your tile and can't cover rent, they don't quietly hand over cash — their whole leveraged portfolio dominoes.

### 4.2 Systemic Shock / Black Swan
The key is **correlation**. Classic chance cards are independent draws. A systemic shock fires **for everyone at once** (e.g. property values −30%), so every over-leveraged player gets margin-called *simultaneously*. 2008 in your living room — and your friends did it to themselves. The finest social damage is "it wasn't me, it was the market." 😈

### 4.3 Securitization / REIT
Package a property and IPO it — sell equity for cash. Cash-strapped? Sell 40% of Boardwalk to a rival for liquidity — but you now only keep 60% of its rent forever. Creates an in-game equity market *and* manufactured betrayal.

### 4.4 Inflation / Money Supply
Passing "Go" is indexed to inflation, not a fixed +200. The more the bank prints, the thinner cash gets — but assets appreciate. Effect: **cash-holders bleed slowly, asset-holders win lying down.** One mechanic that re-teaches the entire "why savers lose to buyers" grievance.

### 4.5 Deferred to v2 (deliberately excluded)
Options, futures, shorting, credit ratings. Great fun, but they explode the decision tree and turn-time, and reward "the one who can do math" until the other five players quit. Ship the four above first.

### 4.6 Pacing parameters
- **Players: 2–6** (sweet spot 5). Financial decisions make each turn heavier, so the ceiling is lower than classic Monopoly's 8. **Bots backfill** empty seats so 2 humans + 4 bots can still play at 2 a.m.
- **Map: single ring, 24 / 36 / 44 tiles.** No branches, shortcuts, or multi-layer boards in v1 — those only lengthen turns and complicate sync.
- **Length:** derived from players × map size; expose a "quick / standard / long" preset.

---

## 5. Bot Strategy & Balance

### 5.1 Bot policies (also your matchmaking backfill)
Ship a handful of hand-authored policies first:
- **Conservative** — low leverage, hoards cash (and quietly loses to inflation).
- **Degen** — max leverage, first to die *or* first to dominate.
- **Cash-flow** — prioritizes rent yield and securitization income.
- **Contrarian** — buys into shocks.

A clean `Policy` interface (`decide(state) -> action`) means bots and future RL agents are drop-in replacements — and it doubles as the backtest driver.

### 5.2 Balance via backtest (AWS)
Because the engine is deterministic and seeded, balance tuning is empirical, not vibes: fan out tens of thousands of `(config, seed)` games on AWS Batch, then answer questions like *"at what inflation rate is the cash player doomed from turn 1?"* Tune `inflation_rate`, `maintenance_ratio`, and shock frequency against win-rate distributions, not intuition.

### 5.3 RL (v2)
Same `Policy` interface, backed by a trained agent (SageMaker / EC2 GPU). The reward: teach an AI to drain humans. Later problem, but the interface is ready today.

---

## 6. Frontend

### 6.1 Principles
- **One URL, no native app.** Join by link or QR — cross-device, zero install. Non-negotiable for "everyone at home."
- **Dumb client.** Receives the full state over WebSocket and re-renders. No optimistic updates, no client-side rules. Turn-based tolerates ~100 ms latency; simple-and-uncheatable wins over snappy.

### 6.2 Screen priority
1. **My Control Panel (90% of attention).** Your cash, portfolio, and a **net-worth/debt bar that flashes red near a margin call**, plus the buttons you can currently press. Get this wrong and the game is ruined.
2. **Board Overview (30%).** Who's where, who owns what. Online, this matters *less* than face-to-face (there's no shared "public screen"), so ship a legible-but-plain version first.
3. **Drama Events (invest here).** Full-room synchronized popups — "💥 Player liquidated, assets −100%" — and screen-shake on shocks. This is how you rebuild the missing "everyone screams at the public screen" energy for remote play. Worth the effort; everything else stays minimal.

### 6.3 Stack
React (or your preferred framework) + a thin WebSocket client that replaces state on each server push. Hosted on **Cloudflare Pages / Workers Assets** — static, edge-cached, colocated with the game Workers.

---

## 7. Real-Time Plane (Cloudflare) — Detail

### 7.1 Worker — router & matchmaker
Stateless edge entrypoint. Handles create-room / join-room, mints session tokens, resolves a **room code → Durable Object ID** (via KV), and hands the WebSocket upgrade off to the right DO. Also fills empty seats with bot policies.

### 7.2 Durable Object — the game room
This is *the* reason Cloudflare fits this problem. Each active game is one DO:
- **Single-threaded authority.** No race conditions on state mutation — the DO serializes all actions naturally.
- **In-memory authoritative `GameState`**, mutated only by the WASM engine (`reduce`).
- **WebSocket Hibernation API.** Holds every player's socket; can hibernate between turns without dropping connections or burning duration-billing — perfect for a game that's mostly *waiting for the active player*.
- **Broadcast on every accepted action** → all sockets receive the new state.
- **Reconnect = resync.** On rejoin, ship the whole `GameState`; the deterministic engine makes this clean.

### 7.3 Persistence
- **D1 (SQL):** user accounts, completed-game records, leaderboards.
- **KV:** room-code → DO-ID map, session tokens (fast, edge-global, eventually-consistent is fine here).
- **R2:** replays stored as `{ seed, action_log }` — a few KB per game; re-run the engine to watch.

### 7.4 Disconnect / resilience checklist
- State lives in the DO, not the client → rejoin resyncs the full state.
- Disconnected player's turn policy: timeout → skip, or hand to a bot (config choice).
- DO hibernation keeps idle rooms cheap without dropping sockets.

---

## 8. Compute Plane (AWS) — Detail

Everything offline and heavy. Container-first, images in **ECR**.

| Workload | Service | Notes |
|----------|---------|-------|
| **Monte-Carlo backtest** | **AWS Batch** or **Fargate** fan-out | Embarrassingly parallel: each task runs N games at a `(config, seed)`. Native Rust engine → fast. |
| **RL training (v2)** | **SageMaker** or **EC2 GPU** | Trains `Policy` agents against the same engine. |
| **Analytics** | **S3** + Athena / a warehouse | Ingest exported game records + backtest results; query balance. |
| **Engine binding** | Native Rust + **PyO3** | Same crate as the WASM edge build; analysis/orchestration in Python. |

**Data flow Cloudflare → AWS:** completed games (from D1/R2) export to S3 on a schedule (or via a Worker → API). The compute plane never sits in the live request path; it feeds *back* only tuned parameters (inflation rate, maintenance ratio, shock cadence) into the game config.

> Why split at all? Because Durable Objects are unbeatable for the *real-time* problem and terrible for GPU batch jobs — and AWS is the reverse. Put each workload where it's idiomatic; the Rust kernel keeps them consistent.

---

## 9. Data Model & Replays

- **`games`** (D1): id, config, players, winner, started/ended, seed.
- **`replays`** (R2): `{ seed, action_log[] }` — deterministic, so this *is* the full game.
- **`users`** (D1): identity, stats. *(Auth handled by the client/session layer — never enter credentials through the game itself.)*
- **`ledger`** (in-state, append-only): every transaction, drives both live UI history and post-game audit.

Because replay = re-execution, the backtest, the "watch last game," and the anti-cheat audit are **the same code path**.

---

## 10. Deployment & CI/CD

| Layer | Tooling |
|-------|---------|
| Cloudflare (Workers, DO, Pages, D1, KV, R2) | **Wrangler** + config-as-code |
| AWS (Batch, Fargate, ECR, S3, SageMaker) | **Terraform** (provider-agnostic IaC, your taste) |
| Rust engine | One crate, two build targets: `wasm-pack` (edge) + `maturin`/PyO3 (AWS) |
| Frontend | Build → Cloudflare Pages/Workers Assets |
| Pipeline | Git push → build WASM + native + frontend → deploy edge via Wrangler, images to ECR via Terraform |

Environments: `dev` (local DO via `wrangler dev` + local engine) → `staging` → `prod`. Keep the engine crate versioned so edge WASM and AWS native never drift.

---

## 11. Security & Anti-Cheat

- **Server-authoritative**: clients send intents only; the DO validates every action through `reduce`.
- **No secrets in the client**: it can't see hidden state or other players' private info unless the server sends it.
- **No credentials through the game**: sign-in / payment (if ever added) go through a dedicated auth provider, never a game form.
- **Deterministic audit**: any disputed game is re-run from `seed + action_log` to prove the true outcome.

---

## 12. Phased Roadmap

**MVP (make it *fun*, single map, no clouds yet)**
1. Deterministic engine in TS/Python: board, turns, buy/rent, bankruptcy — *plus* leverage + margin call.
2. Local authoritative loop + 2 bot policies. Play it. Is the collapse satisfying?

**v1 (make it *online*, 6-player)**
3. Move engine into a Durable Object; Worker for rooms; WebSocket + reconnect/resync.
4. Thin React client, join-by-link/QR, control panel + margin-call popup.
5. Add systemic shock, securitization, inflation. D1/KV/R2 persistence + replays.

**v2 (make it *deep* & *tuned*)**
6. Freeze rules into Rust → WASM (edge) + native/PyO3 (AWS).
7. AWS backtest cluster for balance; export game records.
8. RL bots; optional derivatives (options/shorting) as opt-in "hard mode."

> Golden rule throughout: **make the mechanic fun before you make it fast, and make it fun before you make it online.** Reverse that order and you get a perfectly-engineered thing nobody wants to play.

---

## 13. One-Paragraph Summary

A server-authoritative, turn-based multiplayer game whose rules live in a single deterministic Rust engine. That engine runs at the edge as WASM inside per-room Cloudflare Durable Objects (with hibernating WebSockets for cheap, resilient real-time play) and natively on AWS for parallel Monte-Carlo balance backtesting and RL bot training. Thin browser clients join by link, send only intents, and re-render whatever state the server pushes. Six-player cap, single-ring parametrized map, and four interlocking capital-market mechanics — leverage/margin calls, systemic shocks, securitization, and inflation — engineered not for balance but for the one-second, table-flipping collapse. 😈
