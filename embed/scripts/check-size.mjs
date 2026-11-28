// Presupuesto del widget: lo que la página descarga al cargar `chatiapp.js` (el cargador, el
// módulo del widget y los trozos que este importa de inmediato), comprimido, pesa menos de 150 KB.
// Las partes diferidas (gráficos, formato de SQL) solo se descargan cuando se usan.
import { readFileSync, readdirSync } from "node:fs";
import { gzipSync } from "node:zlib";

const LIMIT = 150 * 1024;
const dist = new URL("../dist/", import.meta.url);
const gz = (name) => gzipSync(readFileSync(new URL(name, dist)), { level: 9 }).length;
const kb = (bytes) => `${(bytes / 1024).toFixed(1)} KB`;

// Importaciones estáticas (`import ... from "./x.js"`), en cascada.
function eager(name, seen = new Set()) {
  if (seen.has(name)) return seen;
  seen.add(name);
  const source = readFileSync(new URL(name, dist), "utf8");
  for (const match of source.matchAll(/^(?:import|export)\b[^;]*?from\s*["'](\.[^"']+)["']/gm)) {
    eager(new URL(match[1], new URL(name, dist)).href.replace(dist.href, ""), seen);
  }
  return seen;
}

const files = ["chatiapp.js", ...eager("chatiapp-widget.js")];
const total = files.reduce((sum, name) => sum + gz(name), 0);
const all = readdirSync(new URL("chunks/", dist)).map((name) => `chunks/${name}`);
for (const name of [...files, ...all.filter((name) => !files.includes(name))]) {
  console.log(`  ${files.includes(name) ? "inicial" : "diferido"}  ${kb(gz(name)).padStart(9)}  ${name}`);
}
if (total >= LIMIT) {
  console.error(`chatiapp.js pesa ${kb(total)} comprimido: supera el límite de 150 KB`);
  process.exit(1);
}
console.log(`chatiapp.js pesa ${kb(total)} comprimido (límite: 150 KB)`);
