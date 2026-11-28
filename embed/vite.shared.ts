import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";

const root = fileURLToPath(new URL(".", import.meta.url));
const frontend = fileURLToPath(new URL("../frontend", import.meta.url));

/**
 * Los componentes del chat viven en `frontend/` (no se duplican), pero allí no hay `node_modules`
 * cuando solo se instala `embed/`: sus importaciones externas se resuelven desde este paquete.
 */
function resolveFromEmbed(): Plugin {
  return {
    name: "chatiapp-resolve-from-embed",
    enforce: "pre",
    async resolveId(id, importer, options) {
      if (!importer?.startsWith(frontend)) return null;
      if (id.startsWith(".") || id.startsWith("/") || id.startsWith("@/") || id.startsWith("\0")) {
        return null;
      }
      return this.resolve(id, `${root}src/index.ts`, { ...options, skipSelf: true });
    },
  };
}

export const sharedConfig = {
  plugins: [resolveFromEmbed(), react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("../frontend/src", import.meta.url)) },
  },
};
