import { createRequire } from "node:module";

// Node carga este archivo como ESM y no ve las exportaciones con nombre del paquete CommonJS
// (`defineConfig`, `expect`): se piden con require, sin perder los tipos.
const { defineConfig, devices } = createRequire(import.meta.url)(
  "@playwright/test",
) as typeof import("@playwright/test");

// Requiere `pnpm run build` (usa dist/) y los navegadores: `pnpm exec playwright install chromium`.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "*.spec.ts",
  reporter: "list",
  use: { baseURL: "http://localhost:4102" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "node e2e/servers.mjs",
    url: "http://localhost:4102/",
    reuseExistingServer: false,
  },
});
