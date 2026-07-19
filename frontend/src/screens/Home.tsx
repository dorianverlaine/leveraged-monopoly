import { Btn, LanguagePicker } from "../components";
import { useI18n } from "../i18n";

export function Home({ onPlay, onDemo }: { onPlay: () => void; onDemo: () => void }) {
  const { t } = useI18n();
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 18,
        padding: "32px 24px",
        textAlign: "center",
      }}
    >
      <div className="float" style={{ fontSize: 92, lineHeight: 1 }}>
        🦈
      </div>

      <div>
        <h1 className="title" style={{ fontSize: 34 }}>
          {t("app.title")}
        </h1>
        <p className="muted" style={{ marginTop: 8, fontSize: 16 }}>
          {t("app.tagline")}
        </p>
      </div>

      {/* The three cities, as a friendly emoji row. */}
      <div style={{ display: "flex", gap: 10, fontSize: 13, fontWeight: 800 }}>
        <span className="chip">🇭🇰 {t("city.hong_kong")}</span>
        <span className="chip">🇫🇷 {t("city.paris")}</span>
        <span className="chip">🗽 {t("city.new_york")}</span>
      </div>

      <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 12, marginTop: 8 }}>
        <Btn size="lg" block onClick={onPlay}>
          🎮 {t("home.play")}
        </Btn>
        <Btn size="lg" block color="ghost" onClick={onDemo}>
          {t("home.demo")}
        </Btn>
      </div>

      <p className="muted" style={{ fontSize: 13 }}>
        👤 {t("home.guest")}
      </p>

      <div style={{ marginTop: 6 }}>
        <LanguagePicker />
      </div>
    </div>
  );
}
