import { defineConfig } from "vitest/config";
import { sharedConfig } from "./vite.shared";

// `chatiapp.js`: un solo archivo que el contenedor sirve en /embed/v1/chatiapp.js.
export default defineConfig({
  ...sharedConfig,
  // El modo biblioteca no lo reemplaza solo y el script corre en la página de otro.
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    lib: {
      entry: "src/index.ts",
      name: "ChatIApp",
      formats: ["iife"],
      fileName: () => "chatiapp.js",
    },
    cssCodeSplit: false,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
