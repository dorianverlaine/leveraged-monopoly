import { useState } from "react";
import { Btn, LanguagePicker, ProfileCard } from "../components";
import { useI18n } from "../i18n";
import type { ConnStatus } from "../net/client";
import type { AccountProfile } from "../types";

export function Home({
  account,
  status,
  error,
  onCreate,
  onJoin,
  onDemo,
}: {
  account: AccountProfile;
  status: ConnStatus;
  error: string | null;
  onCreate: () => void;
  onJoin: (code: string) => void;
  onDemo: () => void;
}) {
  const { t } = useI18n();
  const [code, setCode] = useState("");
  const connecting = status === "connecting";

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 14,
        padding: "20px",
        textAlign: "center",
        overflowY: "auto",
      }}
    >
      <div className="float" style={{ fontSize: 68, lineHeight: 1 }}>🦈</div>

      <div>
        <h1 className="title" style={{ fontSize: 28 }}>{t("app.title")}</h1>
        <p className="muted" style={{ marginTop: 6, fontSize: 15 }}>{t("app.tagline")}</p>
      </div>

      <ProfileCard account={account} />

      <div style={{ display: "flex", gap: 8, fontSize: 13, fontWeight: 800 }}>
        <span className="chip">🇭🇰 {t("city.hong_kong")}</span>
        <span className="chip">🇫🇷 {t("city.paris")}</span>
        <span className="chip">🗽 {t("city.new_york")}</span>
      </div>

      <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 10 }}>
        <Btn size="lg" block onClick={onCreate} disabled={connecting}>
          {connecting ? "⏳" : "🎮"} {t("lobby.create")}
        </Btn>

        {/* Join by room code */}
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase().slice(0, 4))}
            placeholder="ABCD"
            aria-label={t("lobby.roomCode")}
            style={{
              flex: 1, minWidth: 0, textAlign: "center",
              fontFamily: "inherit", fontWeight: 900, fontSize: 22, letterSpacing: 6,
              border: "2px solid var(--line)", borderRadius: "var(--radius)",
              padding: "10px 8px", color: "var(--ink)", textTransform: "uppercase",
            }}
          />
          <Btn color="blue" onClick={() => onJoin(code)} disabled={code.length < 4 || connecting}>
            {t("lobby.join")}
          </Btn>
        </div>

        <Btn block color="ghost" onClick={onDemo}>{t("home.demo")}</Btn>
      </div>

      {error && (
        <div className="chip" style={{ borderColor: "var(--red)", background: "#fff4f4", color: "var(--red-dark)" }}>
          ⚠️ {t(`error.${error}`) !== `error.${error}` ? t(`error.${error}`) : error}
        </div>
      )}

      <LanguagePicker />
    </div>
  );
}
