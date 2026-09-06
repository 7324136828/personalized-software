import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Set VITE_HOST=0.0.0.0 (or pass `--host` on the CLI) to make the dev and
// preview servers reachable from other devices on the same network. run_app.py
// --lan / --host does this for you.
const host = process.env.VITE_HOST || undefined;

export default defineConfig({
  plugins: [react()],
  server: {
    host,
    port: 5174,
    open: false,
    proxy: {
      "/api": process.env.CONTENT_API_TARGET ?? "http://127.0.0.1:8765",
    },
  },
  preview: {
    host,
    port: 4173,
  },
  build: { outDir: "dist", sourcemap: true },
});
