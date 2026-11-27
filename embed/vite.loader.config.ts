import { defineConfig } from "vite";

// `chatiapp.js`: cargador clásico (IIFE) que importa el widget de su misma carpeta.
export default defineConfig({
  build: {
    emptyOutDir: false,
    lib: { entry: "src/loader.ts", name: "ChatIAppLoader", formats: ["iife"], fileName: () => "chatiapp.js" },
  },
});
