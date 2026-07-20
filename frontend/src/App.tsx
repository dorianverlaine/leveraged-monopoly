import { useState } from "react";
import { Home } from "./screens/Home";
import { Lobby } from "./screens/Lobby";
import { Game } from "./screens/Game";
import { mockAccount, mockLobby, mockState } from "./mock";
import { useGame } from "./useGame";
import { useI18n } from "./i18n";
import type { SheetArgs } from "./components/ActionSheet";
import type { StateMessage } from "./types";

/** Demo mode renders the UI from local mock data (no server needed); live mode
 *  drives everything from the realtime server over the WebSocket protocol. */
type Mode = "live" | "demo";

export default function App() {
  const { locale } = useI18n();
  const [mode, setMode] = useState<Mode>("live");
  const [name] = useState("You");
  const live = useGame(name, locale);

  // --- demo-only state -------------------------------------------------
  const [demoScreen, setDemoScreen] = useState<"home" | "lobby" | "game">("home");
  const [demoMsg, setDemoMsg] = useState<StateMessage | null>(null);
  const demoLobby = mockLobby();

  const startDemo = () => {
    setMode("demo");
    setDemoMsg(mockState());
    setDemoScreen("game");
  };

  const handleDemoAction = (type: string) => {
    if (!demoMsg) return;
    if (type === "end_turn") {
      setDemoMsg({
        ...demoMsg,
        your_turn: false,
        state: { ...demoMsg.state, turn: { ...demoMsg.state.turn, active_player: 1 } },
      });
    }
  };

  const screen = mode === "demo" ? demoScreen : live.screen;
  const wide = screen === "game";

  return (
    <div className={`app-shell${wide ? " app-shell--wide" : ""}`}>
      {screen === "home" && (
        <Home
          account={live.account ?? mockAccount()}
          status={live.status}
          error={live.error}
          onCreate={() => { setMode("live"); live.createRoom("quick", 4); }}
          onJoin={(code) => { setMode("live"); live.joinRoom(code); }}
          onDemo={startDemo}
        />
      )}

      {screen === "lobby" && (
        mode === "demo" ? (
          <Lobby
            code={demoLobby.code} seats={demoLobby.seats} you={demoLobby.you} host={demoLobby.host}
            onStart={() => setDemoScreen("game")} onBack={() => setDemoScreen("home")}
          />
        ) : (
          <Lobby
            code={live.room?.code ?? "…"}
            seats={live.seats}
            you={live.room?.seat ?? 0}
            host={live.host}
            onStart={live.start}
            onBack={live.leave}
          />
        )
      )}

      {screen === "game" && (
        mode === "demo"
          ? demoMsg && (
              <Game msg={demoMsg} onAction={handleDemoAction} onExit={() => setDemoScreen("home")} />
            )
          : live.msg && (
              <Game
                msg={live.msg}
                onAction={(type: string, args?: SheetArgs) => live.sendAction(type, args ?? {})}
                onExit={live.leave}
              />
            )
      )}
    </div>
  );
}
