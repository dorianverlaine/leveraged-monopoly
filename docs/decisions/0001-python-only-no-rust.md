# ADR 0001 — Python everywhere; no Rust / WASM freeze

- **Status:** Accepted (2026-07-19)
- **Supersedes:** the P2 "freeze the rules into Rust → WASM (edge) + native/PyO3
  (AWS)" staging in [`../architecture.md`](../architecture.md) (§0, §3.4, §8, §10, §12).

## Context

The original architecture (v0.1) staged the deterministic engine to be rewritten
("frozen") from Python into a single **Rust** crate once the mechanics stopped
changing, compiled to two targets:

- **WASM**, to run inside **Cloudflare Durable Objects** at the edge (one DO per
  game room); and
- **native + PyO3**, to run the Monte-Carlo backtest on AWS at native speed.

That plan's whole justification was performance and the edge-compute model. We
are choosing **not** to pursue it.

## Decision

**The engine, and the entire backend, stays Python — one implementation, one
language, forever.** We will not rewrite the rules in Rust (or any second
language). Consequently:

1. **No dual-target build.** There is no WASM edge build and no native/PyO3
   build. `src/monopoly` is the single source of truth wherever the game runs —
   live server, replay, and backtest.
2. **Cloudflare Durable Objects are out of scope.** DOs execute only
   JavaScript/WASM, so a Python engine cannot run in one. The authoritative
   real-time rooms run as a **long-lived Python process on AWS**.
3. **Cloudflare's role is edge-only** (see ADR consequences below), not compute.

## Consequences

### Deployment (now the permanent topology, not a stepping stone)

- **AWS** hosts the stateful game server (`monopoly-server`, an asyncio process
  holding authoritative rooms in memory), the database, and the offline backtest
  / future RL compute.
- **Cloudflare** is the edge layer only: **Pages** (host the React frontend),
  **DNS + TLS**, **WebSocket reverse-proxy** to AWS, and **WAF / DDoS / rate-limit
  / bot protection**. It never runs game logic.

### Scaling (Python-native, no Durable Objects)

Rooms are in-memory and single-threaded per game (an asyncio task), which is the
property DOs would have given us for free. Without DOs we get it on AWS by:

- **MVP:** a single instance — rooms in memory, plenty for hundreds of players.
- **Scale-out:** a stateless router maps `room code -> backend instance` and pins
  each room to its owning instance (sticky by room, because the state is in that
  process's memory). Add instances horizontally. Optionally externalize the
  room/session registry to Redis. Reconnect still works (state lives in the
  owning instance); replays remain `seed + action_log`.

### Backtest performance (the thing Rust was for)

The Monte-Carlo backtest is **embarrassingly parallel** and deterministic, so we
scale it **horizontally** (multiprocessing locally, AWS Batch/Fargate fan-out in
the cloud) rather than by making a single game fast. This recovers throughput
without a second language. If a genuine hotspot ever appears, we optimize the
Python hot path (vectorize / multiprocess / PyPy) before ever reconsidering a
native rewrite.

### What is unaffected (the good parts survive intact)

The decision changes **nothing** about the current code or the core design
principles — they never depended on Rust:

- Determinism, the pure `reduce(state, action)` reducer, seeded RNG carried in
  state, `seed + action_log` replays, and server-authoritative anti-cheat all
  stay exactly as they are.
- The `GameRoom` being **transport-agnostic** is still valuable — it just means
  "runnable in any Python host and shardable by room", rather than "portable to a
  Durable Object".

## Net effect

This **removes** an entire future phase (the P2 Rust freeze) and simplifies the
system to one language. It trades a theoretical peak-performance ceiling — which a
turn-based game and a horizontally-scalable backtest do not need — for much lower
complexity and faster iteration.
