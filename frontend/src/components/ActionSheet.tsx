// Per-action argument input. Several actions need parameters the server can't
// guess -- how much to borrow, which landmark to develop, what to put in a
// trade -- so tapping those opens this bottom sheet.
//
// Everything computed here (eligible tiles, borrow ceiling, build cost) is a
// *hint* for the UI only; the reducer re-validates every action authoritatively.

import { useState } from "react";
import { Btn } from "../components";
import { useI18n } from "../i18n";
import { AVATARS } from "../mock";
import type { StateMessage, Tile } from "../types";

export type SheetArgs = Record<string, unknown>;

/* ------------------------------------------------------------ ownership */

function soleOwner(tile: Tile): number | null {
  const shares = tile.shares ?? {};
  const keys = Object.keys(shares);
  if (keys.length !== 1) return null;
  return shares[keys[0]] >= 0.9999 ? Number(keys[0]) : null;
}

function myShare(tile: Tile, me: number): number {
  return tile.shares?.[String(me)] ?? 0;
}

function hasMonopoly(board: Tile[], group: string | undefined, me: number): boolean {
  if (!group) return false;
  const tiles = board.filter((t) => t.type === "property" && t.group === group);
  return tiles.length > 0 && tiles.every((t) => soleOwner(t) === me);
}

const CITY_VAR: Record<string, string> = {
  hong_kong: "var(--city-hk)",
  paris: "var(--city-paris)",
  new_york: "var(--city-ny)",
};

/* -------------------------------------------------------------- pieces */

function TileRow({
  tile, meta, selected, onClick,
}: {
  tile: Tile; meta?: string; selected?: boolean; onClick: () => void;
}) {
  return (
    <button className={`pick ${selected ? "pick--on" : ""}`} onClick={onClick}>
      <span className="pick__band" style={{ background: CITY_VAR[tile.group ?? ""] ?? "var(--line)" }} />
      <span className="pick__emoji">{tile.buildings ? "🏗️" : tile.mortgaged ? "🏚️" : "🏢"}</span>
      <span>{tile.name}</span>
      {meta && <span className="pick__meta">{meta}</span>}
    </button>
  );
}

function AmountPicker({
  max, unit, onConfirm, onCancel, confirmLabel,
}: {
  max: number; unit: string; onConfirm: (n: number) => void; onCancel: () => void; confirmLabel: string;
}) {
  const [value, setValue] = useState(Math.max(1, Math.floor(max / 2)));
  if (max <= 0) {
    return <div className="sheet__empty">🚫 —</div>;
  }
  return (
    <>
      <div className="sheet__amount">
        {unit}
        {value}
      </div>
      <input
        className="slider"
        type="range"
        min={1}
        max={max}
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
      />
      <div className="sheet__quick" style={{ marginTop: 10 }}>
        {[0.25, 0.5, 1].map((f) => (
          <span key={f} className="chip" onClick={() => setValue(Math.max(1, Math.round(max * f)))}>
            {f === 1 ? "MAX" : `${f * 100}%`}
          </span>
        ))}
      </div>
      <div className="sheet__row">
        <Btn block color="ghost" onClick={onCancel}>✕</Btn>
        <Btn block onClick={() => onConfirm(value)}>{confirmLabel}</Btn>
      </div>
    </>
  );
}

/* --------------------------------------------------------------- sheet */

export function ActionSheet({
  action, msg, onCancel, onConfirm,
}: {
  action: string;
  msg: StateMessage;
  onCancel: () => void;
  onConfirm: (args: SheetArgs) => void;
}) {
  const { t } = useI18n();
  const state = msg.state;
  const me = state.players.find((p) => p.id === msg.you)!;
  const board = state.board;
  const cfg = state.config as Record<string, number>;
  const buildRatio = cfg.build_cost_ratio ?? 0.5;
  const leverageRatio = cfg.max_leverage_ratio ?? 0.8;

  // Trade composer state.
  const [target, setTarget] = useState<number | null>(null);
  const [giveCash, setGiveCash] = useState(0);
  const [wantCash, setWantCash] = useState(0);
  const [giveTiles, setGiveTiles] = useState<number[]>([]);
  const [wantTiles, setWantTiles] = useState<number[]>([]);

  const buildCost = (tile: Tile) => Math.round((tile.price ?? 0) * buildRatio);
  const tradeable = (tile: Tile) => !tile.mortgaged && !(tile.buildings ?? 0);

  let title = t(`action.${action}`);
  let body: React.ReactNode = null;

  switch (action) {
    case "leverage": {
      const max = Math.max(0, Math.floor(me.collateral_value * leverageRatio - me.debt));
      body = (
        <AmountPicker
          max={max}
          unit="💵 "
          confirmLabel={t("action.leverage")}
          onCancel={onCancel}
          onConfirm={(amount) => onConfirm({ amount })}
        />
      );
      break;
    }
    case "repay_debt": {
      const max = Math.max(0, Math.min(Math.floor(me.debt), Math.floor(me.cash)));
      body = (
        <AmountPicker
          max={max}
          unit="💳 "
          confirmLabel={t("action.repay_debt")}
          onCancel={onCancel}
          onConfirm={(amount) => onConfirm({ amount })}
        />
      );
      break;
    }
    case "build":
    case "mortgage":
    case "unmortgage":
    case "sell_building": {
      const eligible = board.filter((tile) => {
        if (tile.type !== "property") return false;
        const sole = soleOwner(tile) === msg.you;
        if (action === "build") {
          return sole && !tile.mortgaged && (tile.buildings ?? 0) < 5 &&
            hasMonopoly(board, tile.group, msg.you) && me.cash >= buildCost(tile);
        }
        if (action === "mortgage") return sole && !tile.mortgaged && !(tile.buildings ?? 0);
        if (action === "unmortgage") return myShare(tile, msg.you) > 0 && !!tile.mortgaged;
        return myShare(tile, msg.you) > 0 && (tile.buildings ?? 0) > 0; // sell_building
      });
      body = eligible.length ? (
        <>
          {eligible.map((tile) => (
            <TileRow
              key={tile.index}
              tile={tile}
              meta={action === "build" ? `💵 ${buildCost(tile)}` : `${tile.price}`}
              onClick={() => onConfirm({ tile_index: tile.index })}
            />
          ))}
          <div className="sheet__row">
            <Btn block color="ghost" onClick={onCancel}>✕</Btn>
          </div>
        </>
      ) : (
        <>
          <div className="sheet__empty">🚫</div>
          <Btn block color="ghost" onClick={onCancel}>✕</Btn>
        </>
      );
      break;
    }
    case "securitize": {
      const eligible = board.filter(
        (tile) => tile.type === "property" && myShare(tile, msg.you) > 0 && tradeable(tile)
      );
      body = <SecuritizePicker tiles={eligible} onCancel={onCancel} onConfirm={onConfirm} />;
      break;
    }
    case "propose_trade": {
      const others = state.players.filter((p) => p.id !== msg.you && p.status !== "bankrupt");
      const mine = board.filter((tl) => tl.type === "property" && soleOwner(tl) === msg.you && tradeable(tl));
      const theirs = target === null
        ? []
        : board.filter((tl) => tl.type === "property" && soleOwner(tl) === target && tradeable(tl));
      const toggle = (list: number[], set: (v: number[]) => void, i: number) =>
        set(list.includes(i) ? list.filter((x) => x !== i) : [...list, i]);
      const targetPlayer = others.find((p) => p.id === target);

      body = (
        <>
          <div className="sheet__section">👤</div>
          <div className="sheet__quick">
            {others.map((p) => (
              <span
                key={p.id}
                className="chip"
                style={{
                  cursor: "pointer",
                  borderColor: target === p.id ? "var(--green)" : "var(--line)",
                  background: target === p.id ? "#f0fce6" : "var(--bg-soft)",
                }}
                onClick={() => { setTarget(p.id); setWantTiles([]); setWantCash(0); }}
              >
                {AVATARS[p.id % AVATARS.length]} {p.name}
              </span>
            ))}
          </div>

          {target !== null && (
            <>
              <div className="sheet__section">➡️ 💰 {giveCash}</div>
              <input className="slider" type="range" min={0} max={Math.floor(me.cash)}
                value={giveCash} onChange={(e) => setGiveCash(Number(e.target.value))} />
              {mine.map((tile) => (
                <TileRow key={tile.index} tile={tile} selected={giveTiles.includes(tile.index)}
                  onClick={() => toggle(giveTiles, setGiveTiles, tile.index)} />
              ))}

              <div className="sheet__section">⬅️ 💰 {wantCash}</div>
              <input className="slider" type="range" min={0}
                max={Math.max(0, Math.floor(targetPlayer?.cash ?? 0))}
                value={wantCash} onChange={(e) => setWantCash(Number(e.target.value))} />
              {theirs.map((tile) => (
                <TileRow key={tile.index} tile={tile} selected={wantTiles.includes(tile.index)}
                  onClick={() => toggle(wantTiles, setWantTiles, tile.index)} />
              ))}
            </>
          )}

          <div className="sheet__row">
            <Btn block color="ghost" onClick={onCancel}>✕</Btn>
            <Btn
              block
              color="purple"
              disabled={
                target === null ||
                (!giveCash && !wantCash && !giveTiles.length && !wantTiles.length)
              }
              onClick={() =>
                onConfirm({
                  target_player_id: target,
                  offer_cash: giveCash,
                  offer_tiles: Object.fromEntries(giveTiles.map((i) => [i, 1])),
                  request_cash: wantCash,
                  request_tiles: Object.fromEntries(wantTiles.map((i) => [i, 1])),
                })
              }
            >
              🤝
            </Btn>
          </div>
        </>
      );
      break;
    }
    default:
      body = (
        <div className="sheet__row">
          <Btn block color="ghost" onClick={onCancel}>✕</Btn>
          <Btn block onClick={() => onConfirm({})}>OK</Btn>
        </div>
      );
  }

  return (
    <div className="sheet-backdrop" onClick={onCancel}>
      <div className="sheet rise" onClick={(e) => e.stopPropagation()}>
        <div className="sheet__title">{title}</div>
        {/* Explain what the action actually does -- players can't be expected to
            infer "securitize" from a button label. */}
        <div className="sheet__help">{t(`help.${action}`)}</div>
        <div className="sheet__sub">
          💰 {Math.round(me.cash)} · 🏦 {Math.round(me.debt)}
        </div>
        {body}
      </div>
    </div>
  );
}

/** Securitize needs two answers: which landmark, then how much of it to sell. */
function SecuritizePicker({
  tiles, onCancel, onConfirm,
}: {
  tiles: Tile[]; onCancel: () => void; onConfirm: (args: SheetArgs) => void;
}) {
  const [tile, setTile] = useState<Tile | null>(null);
  const [pct, setPct] = useState(50);
  if (!tiles.length) {
    return (
      <>
        <div className="sheet__empty">🚫</div>
        <Btn block color="ghost" onClick={onCancel}>✕</Btn>
      </>
    );
  }
  return (
    <>
      {tiles.map((tl) => (
        <TileRow key={tl.index} tile={tl} selected={tile?.index === tl.index}
          meta={`${tl.price}`} onClick={() => setTile(tl)} />
      ))}
      {tile && (
        <>
          <div className="sheet__amount">📈 {pct}%</div>
          <input className="slider" type="range" min={5} max={100} step={5}
            value={pct} onChange={(e) => setPct(Number(e.target.value))} />
        </>
      )}
      <div className="sheet__row">
        <Btn block color="ghost" onClick={onCancel}>✕</Btn>
        <Btn block color="purple" disabled={!tile}
          onClick={() => tile && onConfirm({ tile_index: tile.index, percent: pct / 100 })}>
          📈
        </Btn>
      </div>
    </>
  );
}
