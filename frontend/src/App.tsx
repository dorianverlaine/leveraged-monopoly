import { useState } from "react";
import { Home } from "./screens/Home";
import { Lobby } from "./screens/Lobby";
import { Game } from "./screens/Game";
import { mockAccount, mockLobby, mockState } from "./mock";
import type { StateMessage } from "./types";

type Screen = "home" | "lobby" | "game";

export default function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [msg, setMsg] = useState<StateMessage | null>(null);

  const account = mockAccount();
  const lobby = mockLobby();

  // Demo mode renders a realistic game locally so the UI can be built and shown
  // without a running server. The live path (WebSocket) will replace setMsg with
  // the server's pushes -- the client stays "dumb" either way.
  const startGame = () => {
    setMsg(mockState());
    setScreen("game");
  };

  const handleAction = (type: string) => {
    if (!msg) return;
    // In demo mode we only acknowledge locally; the live client will send
    // {type:"action", action:{type}} and await the next state push.
    if (type === "end_turn") {
      setMsg({
        ...msg,
        your_turn: false,
        state: { ...msg.state, turn: { ...msg.state.turn, active_player: 1 } },
      });
    }
  };

  return (
    <div className="app-shell">
      {screen === "home" && (
        <Home account={account} onPlay={() => setScreen("lobby")} onDemo={startGame} />
      )}
      {screen === "lobby" && (
        <Lobby
          code={lobby.code}
          seats={lobby.seats}
          you={lobby.you}
          host={lobby.host}
          onStart={startGame}
          onBack={() => setScreen("home")}
        />
      )}
      {screen === "game" && msg && (
        <Game msg={msg} onAction={handleAction} onExit={() => setScreen("home")} />
      )}
    </div>
  );
}
