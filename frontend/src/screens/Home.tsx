import { Btn, LanguagePicker, ProfileCard } from "../components";
import { useI18n } from "../i18n";
import type { AccountProfile } from "../types";

export function Home({
  account,
  onPlay,
  onDemo,
}: {
  account: AccountProfile;
  onPlay: () => void;
  onDemo: () => void;
}) {
  const { t } = useI18n();
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        padding: "24px 20px",
        textAlign: "center",
        overflowY: "auto",
      }}
    >
      <div className="float" style={{ fontSize: 76, lineHeight: 1 }}>
        🦈
      </div>

      <div>
        <h1 className="title" style={{ fontSize: 30 }}>
          {t("app.title")}
        </h1>
        <p className="muted" style={{ marginTop: 6, fontSize: 15 }}>
          {t("app.tagline")}
        </p>
      </div>

      {/* Level / XP / streak — the Duolingo progress trio */}
      <ProfileCard account={account} />

      {/* The three cities, as a friendly emoji row. */}
      <div style={{ display: "flex", gap: 8, fontSize: 13, fontWeight: 800 }}>
        <span className="chip">🇭🇰 {t("city.hong_kong")}</span>
        <span className="chip">🇫🇷 {t("city.paris")}</span>
        <span className="chip">🗽 {t("city.new_york")}</span>
      </div>

      <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 10 }}>
        <Btn size="lg" block onClick={onPlay}>
          🎮 {t("home.play")}
        </Btn>
        <Btn block color="ghost" onClick={onDemo}>
          {t("home.demo")}
        </Btn>
      </div>

      <LanguagePicker />
    </div>
  );
}
