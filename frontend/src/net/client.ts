// Thin WebSocket client for the realtime protocol
// (see ../../src/monopoly/realtime/protocol.py).
//
// The client is deliberately dumb: it sends intents and applies whatever state
// the server pushes. It never computes game rules.

export interface AnyMsg {
  type: string;
  [key: string]: unknown;
}

export type ConnStatus = "idle" | "connecting" | "open" | "closed" | "error";

/** Dev server proxies /ws to the Python realtime server (see vite.config.ts). */
export function defaultUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

export class GameClient {
  private ws: WebSocket | null = null;
  private queue: AnyMsg[] = [];

  constructor(
    private url: string,
    private onMessage: (msg: AnyMsg) => void,
    private onStatus: (status: ConnStatus) => void
  ) {}

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.onStatus("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.onStatus("open");
      // Flush anything queued while the socket was still opening.
      for (const msg of this.queue.splice(0)) ws.send(JSON.stringify(msg));
    };
    ws.onmessage = (ev) => {
      try {
        this.onMessage(JSON.parse(ev.data as string) as AnyMsg);
      } catch {
        // A frame we can't parse is a server/protocol bug; surface it as an error
        // rather than silently dropping it.
        this.onMessage({ type: "error", code: "bad_frame", message: String(ev.data) });
      }
    };
    ws.onerror = () => this.onStatus("error");
    ws.onclose = () => this.onStatus("closed");
  }

  /** Send a frame, queueing it if the socket hasn't finished opening. */
  send(msg: AnyMsg): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      this.queue.push(msg);
      this.connect();
    }
  }

  close(): void {
    this.ws?.close();
    this.ws = null;
  }
}
