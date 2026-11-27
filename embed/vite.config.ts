import { defineConfig } from "vitest/config";
import { sharedConfig } from "./vite.shared";

// El widget como módulo ES con partes diferidas. `chatiapp.js` (el cargador) se construye aparte
// con `vite.loader.config.ts`; el contenedor sirve ambos en /embed/v1/.
export default defineConfig({
  ...sharedConfig,
  // El modo biblioteca no lo reemplaza solo y el script corre en la página de otro.
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    lib: { entry: "src/index.ts", formats: ["es"], fileName: () => "chatiapp-widget.js" },
    rollupOptions: { output: { chunkFileNames: "chunks/[name]-[hash].js" } },
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
