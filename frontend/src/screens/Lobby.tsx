import { Btn } from "../components";
import { useI18n } from "../i18n";
import { AVATARS } from "../mock";
import type { LobbySeat } from "../types";

export function Lobby({
  code,
  seats,
  you,
  host,
  onStart,
  onBack,
}: {
  code: string;
  seats: LobbySeat[];
  you: number;
  host: number;
  onStart: () => void;
  onBack: () => void;
}) {
  const { t } = useI18n();
  const isHost = you === host;
  const humans = seats.filter((s) => !s.empty).length;

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* header */}
      <div className="topbar">
        <button className="chip" onClick={onBack} style={{ cursor: "pointer" }}>
          ←
        </button>
        <span className="title" style={{ fontSize: 18 }}>
          🎪 {t("lobby.title")}
        </span>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>
        {/* the room code, big and friendly to read aloud */}
        <div className="roomcode pop-in">
          <div className="roomcode__label">{t("lobby.roomCode")}</div>
          <div className="roomcode__value">{code}</div>
          <div className="roomcode__hint">{t("lobby.share")}</div>
        </div>

        {/* seats */}
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
            <span className="title" style={{ fontSize: 16 }}>
              👥 {t("lobby.seats")}
            </span>
            <span className="muted" style={{ fontSize: 13 }}>
              {humans}/{seats.length}
            </span>
          </div>

          <div className="seats">
            {seats.map((s) =>
              s.empty ? (
                <div className="seat seat--empty" key={s.seat}>
                  ➕ {t("lobby.emptySeat")}
                </div>
              ) : (
                <div
                  className={`seat ${s.seat === you ? "seat--you" : ""}`}
                  key={s.seat}
                >
                  <span className="seat__avatar">{AVATARS[s.seat % AVATARS.length]}</span>
                  <span className="seat__name">{s.name}</span>
                  {s.seat === you && <span className="badge badge--you">{t("lobby.you")}</span>}
                  {s.seat === host && <span className="badge badge--host">👑 {t("lobby.host")}</span>}
                  {s.is_bot && <span className="badge badge--bot">🤖 {t("lobby.bot")}</span>}
                </div>
              )
            )}
          </div>
        </div>
      </div>

      {/* start */}
      <div className="panel">
        {isHost ? (
          <Btn size="lg" block onClick={onStart}>
            🚀 {t("lobby.start")}
          </Btn>
        ) : (
          <p className="muted center" style={{ padding: 8 }}>
            ⏳ {t("lobby.waiting")}
          </p>
        )}
      </div>
    </div>
  );
}
