// Wire types mirroring the backend's public state (state.to_public_dict) and the
// realtime protocol (src/monopoly/realtime/protocol.py). The client is "dumb":
// it renders whatever the server pushes and sends only intents.

export type TileType = "go" | "property" | "tax" | "event" | "corner";
export type CityGroup = "hong_kong" | "paris" | "new_york" | "";

export interface Tile {
  index: number;
  name: string;
  type: TileType;
  key: string;
  group?: CityGroup;
  price?: number;
  base_rent?: number;
  buildings?: number;
  mortgaged?: boolean;
  shares?: Record<string, number>; // player id (string) -> share
}

export type PlayerStatus = "active" | "margin_called" | "bankrupt" | "disconnected";

export interface Player {
  id: number;
  name: string;
  cash: number;
  position: number;
  debt: number;
  status: PlayerStatus;
  is_bot: boolean;
  policy: string;
  net_worth: number;
  collateral_value: number;
  /** null when the player has no debt (an infinite ratio isn't valid JSON). */
  margin_ratio: number | null;
}

export interface Market {
  price_index: number;
  money_supply: number;
  shock_clock: number;
  shocks_fired: number;
}

export interface LedgerEntry {
  round_number: number;
  player_id: number;
  kind: string;
  amount: number;
  note: string;
}

export interface TradeOffer {
  id: number;
  proposer_id: number;
  recipient_id: number;
  offer_cash: number;
  offer_tiles: Record<string, number>;
  request_cash: number;
  request_tiles: Record<string, number>;
  created_round: number;
}

export interface TurnState {
  active_player: number;
  phase: "await_roll" | "await_action" | "game_over";
  round_number: number;
  last_roll: number[] | null;
}

export interface GameState {
  config: Record<string, unknown> & { map_size: number; round_limit: number };
  turn: TurnState;
  board: Tile[];
  players: Player[];
  market: Market;
  ledger: LedgerEntry[];
  trades: TradeOffer[];
}

// The per-recipient state broadcast.
export interface StateMessage {
  type: "state";
  you: number;
  your_turn: boolean;
  available: string[];
  events: LedgerEntry[];
  state: GameState;
}

/** One seat as reported by the server's `lobby` message. */
export interface LobbySeat {
  seat: number;
  name: string;
  is_bot: boolean;
  connected: boolean;
  /** Local-only marker used by the mock lobby for unclaimed seats. */
  empty?: boolean;
}

export interface AccountProfile {
  id: string;
  display_name: string;
  avatar: string;
  locale: string;
  level: number;
  xp: number;
  xp_into_level: number;
  xp_for_next_level: number;
  rating: number;
  games_played: number;
  games_won: number;
  current_win_streak: number;
  best_win_streak: number;
}
