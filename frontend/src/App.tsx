import { useState } from "react";
import { Home } from "./screens/Home";
import { Game } from "./screens/Game";
import { mockState } from "./mock";
import type { StateMessage } from "./types";

type Screen = "home" | "game";

export default function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [msg, setMsg] = useState<StateMessage | null>(null);

  // Demo mode renders a realistic game locally so the UI can be built and shown
  // without a running server. The live path (WebSocket) replaces setMsg with the
  // server's pushes -- the client stays "dumb" either way.
  const startDemo = () => {
    setMsg(mockState());
    setScreen("game");
  };

  const handleAction = (type: string) => {
    // In demo mode we just acknowledge; the live client sends
    // {type:"action", action:{type}} over the socket and awaits the next state push.
    if (!msg) return;
    if (type === "end_turn") {
      setMsg({
        ...msg,
        your_turn: false,
        state: {
          ...msg.state,
          turn: { ...msg.state.turn, active_player: 1 },
        },
      });
    }
  };

  return (
    <div className="app-shell">
      {screen === "home" && <Home onPlay={startDemo} onDemo={startDemo} />}
      {screen === "game" && msg && (
        <Game msg={msg} onAction={handleAction} onExit={() => setScreen("home")} />
      )}
    </div>
  );
}
