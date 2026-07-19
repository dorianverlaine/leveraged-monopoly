import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /ws to the Python realtime server (monopoly-server) so
// the frontend can talk to it without CORS in local development.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/ws": {
        target: "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
});
