// Shared UI pieces. Emoji-forward by design (docs/frontend.md): emoji double as
// a language-neutral visual layer across four locales.

import { ReactNode } from "react";
import { useI18n, LOCALES, Locale } from "./i18n";
import type { AccountProfile, GameState, LedgerEntry, Player, Tile } from "./types";
import { AVATARS } from "./mock";

/* ---------------------------------------------------------------- buttons */

type BtnColor = "green" | "blue" | "gold" | "red" | "purple" | "teal" | "ghost";

export function Btn({
  children, onClick, color = "green", size, block, disabled, className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  color?: BtnColor;
  size?: "lg" | "sm";
  block?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  const cls = [
    "btn",
    color !== "green" ? `btn--${color}` : "",
    size ? `btn--${size}` : "",
    block ? "btn--block" : "",
    className,
  ].filter(Boolean).join(" ");
  return (
    <button className={cls} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

/* ------------------------------------------------------------- language */

export function LanguagePicker() {
  const { locale, setLocale } = useI18n();
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center" }}>
      {LOCALES.map((l) => (
        <button
          key={l.code}
          onClick={() => setLocale(l.code as Locale)}
          className="chip"
          style={{
            cursor: "pointer",
            borderColor: locale === l.code ? "var(--green)" : "var(--line)",
            background: locale === l.code ? "#f0fce6" : "var(--bg-soft)",
          }}
        >
          <span style={{ fontSize: 16 }}>{l.flag}</span> {l.label}
        </button>
      ))}
    </div>
  );
}

/* --------------------------------------------------------------- profile */

/** Level + XP bar + streak: the Duolingo progress trio. */
export function ProfileCard({ account }: { account: AccountProfile }) {
  const { t } = useI18n();
  const pct = account.xp_for_next_level
    ? Math.round((account.xp_into_level / account.xp_for_next_level) * 100)
    : 0;
  return (
    <div className="profile">
      <div className="profile__avatar">{account.avatar || "🦈"}</div>
      <div className="profile__body">
        <div className="profile__top">
          <span className="profile__name">{account.display_name}</span>
          <span className="profile__lvl">⭐ {t("profile.level")} {account.level}</span>
        </div>
        <div className="profile__stats">
          <span>🏆 {account.rating}</span>
          <span>🔥 {account.current_win_streak}</span>
          <span>🎮 {account.games_won}/{account.games_played}</span>
        </div>
        <div className="meter profile__xp" style={{ height: 12 }}>
          <div
            className="meter__fill"
            style={{ width: `${pct}%`, background: "var(--gold)" }}
          />
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- board */

/** Map a tile index (0..23) onto a 7x7 grid perimeter, clockwise from top-left. */
function ringPosition(i: number): { row: number; col: number } {
  if (i <= 6) return { row: 1, col: i + 1 };
  if (i <= 12) return { row: i - 5, col: 7 };
  if (i <= 18) return { row: 7, col: 7 - (i - 12) };
  return { row: 7 - (i - 18), col: 1 };
}

const TILE_EMOJI: Record<string, string> = {
  go: "🏁", tax: "🧾", event: "❓", corner: "🌴",
};

function tileEmoji(tile: Tile): string {
  if (tile.type !== "property") return TILE_EMOJI[tile.type] ?? "⬜";
  if (tile.mortgaged) return "🏚️";
  const b = tile.buildings ?? 0;
  if (b >= 5) return "🏙️";
  if (b > 0) return "🏗️";
  return "🏢";
}

function ownerOf(tile: Tile): number | null {
  const shares = tile.shares ?? {};
  const entries = Object.entries(shares);
  if (entries.length === 0) return null;
  return Number(entries[0][0]);
}

export function Board({ state, you }: { state: GameState; you: number }) {
  const { t } = useI18n();
  const occupants = new Map<number, Player[]>();
  for (const p of state.players) {
    if (p.status === "bankrupt") continue;
    const arr = occupants.get(p.position) ?? [];
    arr.push(p);
    occupants.set(p.position, arr);
  }

  return (
    <div className="board-wrap">
      <div className="board">
        {state.board.map((tile) => {
          const { row, col } = ringPosition(tile.index);
          const owner = ownerOf(tile);
          const here = occupants.get(tile.index) ?? [];
          return (
            <div
              key={tile.index}
              className={[
                "tile",
                tile.group ? `tile--${tile.group}` : "",
                tile.mortgaged ? "tile--mortgaged" : "",
                here.some((p) => p.id === you) ? "tile--here" : "",
              ].filter(Boolean).join(" ")}
              style={{ gridRow: row, gridColumn: col }}
              title={tile.name}
            >
              {tile.group && <div className="tile__band" />}
              <div className="tile__emoji">{tileEmoji(tile)}</div>
              {/* Price only while unowned -- once owned, the owner badge takes
                  that space, which keeps these small tiles legible. */}
              {tile.type === "property" && owner === null && (
                <div className="tile__price">{tile.price}</div>
              )}
              {(tile.buildings ?? 0) > 0 && <div className="tile__builds">×{tile.buildings}</div>}
              {owner !== null && <div className="tile__owner">{AVATARS[owner % AVATARS.length]}</div>}
              {here.length > 0 && (
                <div style={{ position: "absolute", top: 6, left: 3, fontSize: 11 }}>
                  {here.map((p) => AVATARS[p.id % AVATARS.length]).join("")}
                </div>
              )}
            </div>
          );
        })}

        <div className="board-center">
          <div className="board-center__dice">
            {state.turn.last_roll ? `🎲 ${state.turn.last_roll[0]}·${state.turn.last_roll[1]}` : "🎲"}
          </div>
          <div className="board-center__label">{t("game.market")}</div>
          <div className="board-center__index">
            {state.market.price_index >= 1 ? "📈" : "📉"} {state.market.price_index.toFixed(2)}×
          </div>
          <div className="board-center__label">
            💥 {state.market.shocks_fired} · {t("game.round")} {state.turn.round_number}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ player strip */

export function PlayerStrip({ state, you }: { state: GameState; you: number }) {
  return (
    <div className="players">
      {state.players.map((p) => (
        <div
          key={p.id}
          className={[
            "player-pill",
            state.turn.active_player === p.id ? "player-pill--active" : "",
            p.status === "bankrupt" ? "player-pill--bust" : "",
          ].filter(Boolean).join(" ")}
        >
          <span className="player-pill__avatar">{AVATARS[p.id % AVATARS.length]}</span>
          <span>
            {p.id === you ? "⭐ " : ""}{p.name}
            <span className="player-pill__nw"> · 💰{Math.round(p.net_worth)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- event feed */

export function EventFeed({ entries, players }: { entries: LedgerEntry[]; players: Player[] }) {
  const { t } = useI18n();
  const nameOf = (id: number) =>
    id < 0 ? "🌍" : players.find((p) => p.id === id)?.name ?? `#${id}`;
  return (
    <div className="feed">
      {entries.slice(0, 6).map((e, i) => (
        <div className="feed__item" key={i}>
          <span>{AVATARS[Math.max(0, e.player_id) % AVATARS.length]}</span>
          <span>
            <b>{nameOf(e.player_id)}</b> {t(`event.${e.kind}`)}
          </span>
          {e.amount !== 0 && (
            <span className={`feed__amount ${e.amount > 0 ? "feed__amount--pos" : "feed__amount--neg"}`}>
              {e.amount > 0 ? "+" : ""}{e.amount}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------- drama overlay */

export interface Drama {
  emoji: string;
  title: string;
  body: string;
}

export function DramaOverlay({ drama, onClose }: { drama: Drama; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="drama" onClick={onClose}>
      <div className="drama__card pop-in">
        <div className="drama__emoji">{drama.emoji}</div>
        <div className="drama__title">{drama.title}</div>
        <div className="drama__body">{drama.body}</div>
        <Btn color="red" block onClick={onClose}>{t("common.tap")}</Btn>
      </div>
    </div>
  );
}
