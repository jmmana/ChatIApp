import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { sharedConfig } from "./vite.shared";

const stub = (name: string) => fileURLToPath(new URL(`./exp-stubs/${name}.ts`, import.meta.url));

export default defineConfig(({ mode }) => {
  const alias: Record<string, string> = { ...sharedConfig.resolve.alias };
  if (mode.includes("sql")) alias["sql-formatter"] = stub("sql");
  if (mode.includes("charts")) alias["recharts"] = stub("recharts");
  return {
    ...sharedConfig,
    resolve: { alias },
    define: { "process.env.NODE_ENV": JSON.stringify("production") },
    build: {
      outDir: "exp-dist",
      lib: { entry: "src/index.ts", name: "X", formats: ["iife"], fileName: () => "x.js" },
    },
  };
});
