import { defineConfig } from "vite";
import { sharedConfig } from "./vite.shared";

// `@chatiapp/react`: envoltorio de React sobre el mismo elemento; React queda como peer.
export default defineConfig({
  ...sharedConfig,
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "react/dist",
    emptyOutDir: true,
    lib: { entry: "react/src/index.tsx", formats: ["es"], fileName: () => "index.js" },
    rollupOptions: {
      external: ["react", "react-dom", "react-dom/client", "react/jsx-runtime"],
    },
  },
});
