import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // En desarrollo, /api se redirige al backend.
    proxy: {
      "/api": { target: backend, changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    // `e2e/` lo ejecuta Playwright (`pnpm run test:e2e`), no Vitest.
    exclude: ["e2e/**", "node_modules/**"],
    setupFiles: ["./src/test/setup.ts"],
  },
});
