import { defineConfig, devices } from "@playwright/test";

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
