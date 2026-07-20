// Live-game state machine: owns the socket, drives the protocol handshake, and
// exposes exactly what the screens need. Mirrors realtime/protocol.py.
//
// Flow: connect -> authenticate(guest) -> create_room | join_room -> lobby
//       -> start -> a stream of `state` pushes.

import { useCallback, useRef, useState } from "react";
import { AnyMsg, ConnStatus, GameClient, defaultUrl } from "./net/client";
import type { AccountProfile, LobbySeat, StateMessage } from "./types";
import type { Locale } from "./i18n";

export type LiveScreen = "home" | "lobby" | "game";

interface RoomInfo {
  code: string;
  seat: number;
  token: string;
}

/** What we intended to do once authentication completes. */
type Pending =
  | { kind: "create"; preset: string; players: number }
  | { kind: "join"; code: string }
  | null;

export function useGame(playerName: string, locale: Locale) {
  const clientRef = useRef<GameClient | null>(null);
  const pendingRef = useRef<Pending>(null);

  const [status, setStatus] = useState<ConnStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState<AccountProfile | null>(null);
  const [room, setRoom] = useState<RoomInfo | null>(null);
  const [seats, setSeats] = useState<LobbySeat[]>([]);
  const [host, setHost] = useState(0);
  const [msg, setMsg] = useState<StateMessage | null>(null);
  const [screen, setScreen] = useState<LiveScreen>("home");

  const handle = useCallback((m: AnyMsg) => {
    switch (m.type) {
      case "authenticated": {
        setAccount(m.account as AccountProfile);
        // Resume whatever the player asked for before we were logged in.
        const pending = pendingRef.current;
        pendingRef.current = null;
        const session = m.session as string;
        if (pending?.kind === "create") {
          clientRef.current?.send({
            type: "create_room",
            session,
            name: playerName,
            preset: pending.preset,
            players: pending.players,
          });
        } else if (pending?.kind === "join") {
          clientRef.current?.send({
            type: "join_room",
            session,
            room: pending.code,
            name: playerName,
          });
        }
        break;
      }
      case "room_created":
      case "joined":
        setRoom({ code: m.room as string, seat: m.seat as number, token: m.token as string });
        setScreen("lobby");
        setError(null);
        break;
      case "lobby":
        setSeats(m.seats as LobbySeat[]);
        setHost(m.host as number);
        break;
      case "state":
        setMsg(m as unknown as StateMessage);
        setScreen("game");
        break;
      case "error":
        // Surface the stable code; the frontend localises it (docs/i18n.md) and
        // never shows the server's English message text to the player.
        setError(m.code as string);
        break;
    }
  }, [playerName]);

  const ensureClient = useCallback(() => {
    if (!clientRef.current) {
      clientRef.current = new GameClient(defaultUrl(), handle, setStatus);
    }
    return clientRef.current;
  }, [handle]);

  /** Connect + authenticate as a guest, then run `pending` once logged in. */
  const authenticateThen = useCallback(
    (pending: Pending) => {
      pendingRef.current = pending;
      setError(null);
      const client = ensureClient();
      client.connect();
      client.send({ type: "authenticate", mode: "guest", name: playerName, locale });
    },
    [ensureClient, playerName, locale]
  );

  const createRoom = useCallback(
    (preset = "quick", players = 4) => authenticateThen({ kind: "create", preset, players }),
    [authenticateThen]
  );

  const joinRoom = useCallback(
    (code: string) => authenticateThen({ kind: "join", code: code.trim().toUpperCase() }),
    [authenticateThen]
  );

  const start = useCallback(() => clientRef.current?.send({ type: "start" }), []);

  /** Send a game action. `args` carries the per-action parameters. */
  const sendAction = useCallback((type: string, args: Record<string, unknown> = {}) => {
    clientRef.current?.send({ type: "action", action: { type, ...args } });
  }, []);

  const leave = useCallback(() => {
    clientRef.current?.close();
    clientRef.current = null;
    setRoom(null);
    setSeats([]);
    setMsg(null);
    setScreen("home");
    setStatus("idle");
  }, []);

  return {
    status, error, account, room, seats, host, msg, screen,
    createRoom, joinRoom, start, sendAction, leave, setScreen,
  };
}
