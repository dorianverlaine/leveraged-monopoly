import { useState } from "react";
import { Board, Btn, Drama, DramaOverlay, EventFeed, PlayerStrip } from "../components";
import { useI18n } from "../i18n";
import { AVATARS } from "../mock";
import type { StateMessage } from "../types";

/** Actions that get the big primary treatment when available. */
const PRIMARY = new Set(["roll_dice", "buy", "build", "accept_trade"]);
const COLOR: Record<string, "green" | "blue" | "gold" | "red" | "purple" | "teal" | "ghost"> = {
  roll_dice: "green",
  buy: "green",
  build: "teal",
  leverage: "gold",
  repay_debt: "blue",
  securitize: "purple",
  mortgage: "gold",
  unmortgage: "blue",
  sell_building: "ghost",
  propose_trade: "purple",
  accept_trade: "green",
  reject_trade: "ghost",
  end_turn: "blue",
  concede: "ghost",
};

export function Game({
  msg,
  onAction,
  onExit,
}: {
  msg: StateMessage;
  onAction: (type: string) => void;
  onExit: () => void;
}) {
  const { t } = useI18n();
  const [drama, setDrama] = useState<Drama | null>(null);

  const state = msg.state;
  const me = state.players.find((p) => p.id === msg.you)!;
  const active = state.players.find((p) => p.id === state.turn.active_player)!;
  const shockNow = state.market.shock_clock <= 1;

  // Margin health: infinite (no debt) is safe; below ~1.5 is a real risk.
  const ratio = me.debt > 0 ? me.margin_ratio : Infinity;
  const danger = Number.isFinite(ratio) && ratio < 1.55;
  const warn = Number.isFinite(ratio) && ratio >= 1.55 && ratio < 2.2;
  const meterPct = !Number.isFinite(ratio) ? 100 : Math.max(4, Math.min(100, ((ratio - 1) / 2) * 100));
  const meterColor = danger ? "var(--red)" : warn ? "var(--gold)" : "var(--green)";

  const showShockDrama = () =>
    setDrama({
      emoji: "💥",
      title: t("drama.shock.title"),
      body: t("drama.shock.body", { pct: 30 }),
    });

  const incoming = state.trades.filter((tr) => tr.recipient_id === msg.you);

  // The action that carries the turn forward gets the hero treatment; trade
  // responses live in their own card, so they're excluded here.
  const responses = new Set(["accept_trade", "reject_trade"]);
  const hero =
    (["roll_dice", "buy", "build"] as const).find((a) => msg.available.includes(a)) ??
    (msg.available.includes("end_turn") ? "end_turn" : undefined);
  const secondary = msg.available.filter((a) => a !== hero && !responses.has(a));

  return (
    <div className={`game ${shockNow ? "shake" : ""}`}>
      {/* ---- top bar ---- */}
      <div className="topbar">
        <button className="chip" onClick={onExit} style={{ cursor: "pointer" }}>
          ←
        </button>
        <span className="chip">
          ⏱️ {t("game.round")} {state.turn.round_number}
        </span>
        <div className="topbar__spacer" />
        <button
          className={`chip shock-chip ${shockNow ? "shock-chip--hot pulse-danger" : ""}`}
          onClick={showShockDrama}
          style={{ cursor: "pointer" }}
        >
          {shockNow
            ? t("game.shock_now")
            : t("game.shock_in", { n: state.market.shock_clock })}
        </button>
      </div>

      {/* Body: one column on mobile, three columns on desktop. */}
      <div className="game__body">
        {/* Left (desktop) / top (mobile): players, plus the full event feed. */}
        <aside className="game__side">
          <PlayerStrip state={state} you={msg.you} />
          <EventFeed entries={state.ledger} players={state.players} />
        </aside>

        {/* Centre: turn banner + the board, sized to fit without scrolling. */}
        <main className="game__center">
          <div className="turnbar">
            <div className="title">
              {msg.your_turn ? `⭐ ${t("game.your_turn")}` : t("game.their_turn", { name: active.name })}
            </div>
          </div>

          <Board state={state} you={msg.you} />

          {/* Mobile-only single-line ticker (desktop shows the full feed left). */}
          {state.ledger[0] && (
            <div className="ticker">
              <span>{AVATARS[Math.max(0, state.ledger[0].player_id) % AVATARS.length]}</span>
              <span>{t(`event.${state.ledger[0].kind}`)}</span>
              {state.ledger[0].amount !== 0 && (
                <span
                  className="ticker__amount"
                  style={{ color: state.ledger[0].amount > 0 ? "var(--green-dark)" : "var(--red-dark)" }}
                >
                  {state.ledger[0].amount > 0 ? "+" : ""}
                  {state.ledger[0].amount}
                </span>
              )}
            </div>
          )}
        </main>

        {/* Right (desktop) / bottom (mobile): the control panel. */}
        <section className="panel">
        {incoming.length > 0 && (
          <div className="trade rise">
            <div className="trade__title">🤝 {t("game.trades")}</div>
            <div style={{ fontSize: 14 }}>
              💰 <b>+{incoming[0].offer_cash}</b> ⇄ 🏙️{" "}
              {Object.keys(incoming[0].request_tiles)
                .map((i) => state.board[Number(i)]?.name)
                .join(", ")}
            </div>
            <div className="trade__row">
              <Btn size="sm" block onClick={() => onAction("accept_trade")}>
                {t("action.accept_trade")}
              </Btn>
              <Btn size="sm" block color="ghost" onClick={() => onAction("reject_trade")}>
                {t("action.reject_trade")}
              </Btn>
            </div>
          </div>
        )}

        <div className="panel__row">
          <div className="stat">
            <div className="stat__label">💰 {t("game.cash")}</div>
            <div className="stat__value">{Math.round(me.cash)}</div>
          </div>
          <div className="stat">
            <div className="stat__label">📊 {t("game.networth")}</div>
            <div className="stat__value">{Math.round(me.net_worth)}</div>
          </div>
          <div className={`stat ${danger ? "stat--danger" : ""}`}>
            <div className="stat__label">🏦 {t("game.debt")}</div>
            <div className="stat__value">{Math.round(me.debt)}</div>
          </div>
        </div>

        {/* margin health bar — flashes red near a margin call */}
        <div className="margin-row">
          <span style={{ color: danger ? "var(--red-dark)" : warn ? "var(--gold-dark)" : "var(--green-dark)" }}>
            {danger ? `🚨 ${t("game.margin_danger")}` : warn ? `⚠️ ${t("game.margin_warn")}` : `🛡️ ${t("game.margin_safe")}`}
          </span>
        </div>
        <div className={`meter ${danger ? "pulse-danger" : ""}`} style={{ marginBottom: 14 }}>
          <div className="meter__fill" style={{ width: `${meterPct}%`, background: meterColor }} />
        </div>

        {/* Actions, driven entirely by the server's `available` list. One hero
            CTA carries the turn forward; the rest are compact tools. */}
        {hero && (
          <div className="actions-hero">
            <Btn color={COLOR[hero] ?? "green"} block onClick={() => onAction(hero)}>
              {t(`action.${hero}`)}
            </Btn>
          </div>
        )}
        <div className="actions">
          {secondary.map((a) => (
            <Btn key={a} color={COLOR[a] ?? "blue"} onClick={() => onAction(a)}>
              {t(`action.${a}`)}
            </Btn>
          ))}
        </div>
        </section>
      </div>

      {drama && <DramaOverlay drama={drama} onClose={() => setDrama(null)} />}
    </div>
  );
}
