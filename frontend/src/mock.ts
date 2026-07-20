// A realistic mock game state so the UI can be developed, demoed and screenshotted
// without a running server. Mirrors what the backend's 24-tile board produces.

import type { AccountProfile, GameState, LobbySeat, StateMessage, Tile } from "./types";

const HK = ["Sham Shui Po", "Mong Kok", "Yau Ma Tei", "Tsim Sha Tsui", "North Point", "Wan Chai"];
const PARIS = ["Belleville", "Menilmontant", "Bastille", "Le Marais", "Montmartre", "Opera"];
const NY = ["The Bronx", "Harlem", "Queens", "Brooklyn", "Chinatown", "SoHo"];

function landmark(index: number, name: string, group: string, tier: number): Tile {
  const price = 60 + tier * 20;
  return {
    index,
    name,
    type: "property",
    key: `${group}:${name.toLowerCase().replace(/\s+/g, "_")}`,
    group: group as Tile["group"],
    price,
    base_rent: Math.max(2, Math.floor(price / 8)),
    buildings: 0,
    mortgaged: false,
    shares: {},
  };
}

export function mockBoard(): Tile[] {
  const tiles: Tile[] = [{ index: 0, name: "GO", type: "go", key: "go" }];
  HK.forEach((n, i) => tiles.push(landmark(tiles.length, n, "hong_kong", i)));
  tiles.push({ index: tiles.length, name: "Wealth Tax", type: "tax", key: "wealth_tax" });
  PARIS.forEach((n, i) => tiles.push(landmark(tiles.length, n, "paris", i)));
  tiles.push({ index: tiles.length, name: "Vacation", type: "corner", key: "vacation" });
  NY.forEach((n, i) => tiles.push(landmark(tiles.length, n, "new_york", i)));
  tiles.push({ index: tiles.length, name: "Marketplace", type: "corner", key: "marketplace" });
  tiles.push({ index: tiles.length, name: "Event", type: "event", key: "event" });
  tiles.push({ index: tiles.length, name: "Event", type: "event", key: "event" });
  return tiles;
}

export function mockState(): StateMessage {
  const board = mockBoard();
  // Give the board some life: ownership, a monopoly, some development.
  board[1].shares = { "0": 1 };
  board[2].shares = { "0": 1 };
  board[3].shares = { "0": 1 };
  board[4].shares = { "1": 1 };
  board[5].shares = { "2": 1 };
  board[8].shares = { "1": 1 };
  board[9].shares = { "1": 1 };
  board[10].shares = { "3": 1 };
  board[11].shares = { "0": 1 };
  board[15].shares = { "2": 1 };
  board[16].shares = { "2": 1 };
  board[17].shares = { "2": 1 };
  board[18].shares = { "2": 1 };
  board[19].shares = { "2": 1 };
  board[20].shares = { "2": 1 };  // player 2 holds all of New York -> monopoly
  board[19].buildings = 2;
  board[20].buildings = 3;
  board[9].mortgaged = true;

  const state: GameState = {
    config: { map_size: 24, round_limit: 20 },
    turn: { active_player: 0, phase: "await_action", round_number: 7, last_roll: [4, 3] },
    board,
    players: [
      {
        id: 0, name: "You", cash: 420, position: 11, debt: 260, status: "active",
        is_bot: false, policy: "", net_worth: 812, collateral_value: 520, margin_ratio: 1.52,
      },
      {
        id: 1, name: "Bot-degen", cash: 90, position: 4, debt: 610, status: "active",
        is_bot: true, policy: "degen", net_worth: 240, collateral_value: 700, margin_ratio: 1.14,
      },
      {
        id: 2, name: "Bot-shark", cash: 980, position: 20, debt: 0, status: "active",
        is_bot: true, policy: "shark", net_worth: 2140, collateral_value: 1160, margin_ratio: null,
      },
      {
        id: 3, name: "Bot-conservative", cash: 610, position: 7, debt: 0, status: "active",
        is_bot: true, policy: "conservative", net_worth: 730, collateral_value: 120, margin_ratio: null,
      },
    ],
    market: { price_index: 1.34, money_supply: 3200, shock_clock: 1, shocks_fired: 2 },
    ledger: [
      { round_number: 7, player_id: 0, kind: "rent", amount: -48, note: "Rent paid on Le Marais" },
      { round_number: 7, player_id: 2, kind: "build", amount: -90, note: "Built a floor on SoHo" },
      { round_number: 6, player_id: 1, kind: "leverage", amount: 200, note: "Borrowed against portfolio" },
      { round_number: 6, player_id: -1, kind: "shock", amount: 0, note: "Systemic shock" },
      { round_number: 5, player_id: 0, kind: "buy", amount: -120, note: "Bought Le Marais" },
    ],
    trades: [
      {
        id: 3, proposer_id: 2, recipient_id: 0,
        offer_cash: 240, offer_tiles: {},
        request_cash: 0, request_tiles: { "11": 1 }, created_round: 7,
      },
    ],
  };

  return {
    type: "state",
    you: 0,
    your_turn: true,
    available: ["end_turn", "buy", "leverage", "repay_debt", "securitize", "propose_trade", "accept_trade", "reject_trade", "concede"],
    events: [],
    state,
  };
}

export const AVATARS = ["🦈", "😈", "🐙", "🦊", "🐼", "🦁"];

/** A mock signed-in profile (mirrors the backend account's public_profile). */
export function mockAccount(): AccountProfile {
  return {
    id: "demo",
    display_name: "You",
    avatar: "🦈",
    locale: "zh-Hant",
    level: 7,
    xp: 2340,
    xp_into_level: 140,
    xp_for_next_level: 700,
    rating: 1180,
    games_played: 23,
    games_won: 9,
    current_win_streak: 3,
    best_win_streak: 5,
  };
}

/** A mock lobby: you (host), a friend, two bots and two open seats. */
export type { LobbySeat };

export function mockLobby(): { code: string; host: number; you: number; seats: LobbySeat[] } {
  return {
    code: "DT8P",
    host: 0,
    you: 0,
    seats: [
      { seat: 0, name: "You", is_bot: false, connected: true },
      { seat: 1, name: "Mireille", is_bot: false, connected: true },
      { seat: 2, name: "Bot-shark", is_bot: true, connected: true },
      { seat: 3, name: "Bot-degen", is_bot: true, connected: true },
      { seat: 4, name: "", is_bot: false, connected: false, empty: true },
      { seat: 5, name: "", is_bot: false, connected: false, empty: true },
    ],
  };
}
