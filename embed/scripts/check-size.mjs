// Presupuesto del widget: chatiapp.js comprimido (gzip) debe pesar menos de 150 KB.
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const LIMIT = 150 * 1024;
const file = new URL("../dist/chatiapp.js", import.meta.url);
const size = gzipSync(readFileSync(file), { level: 9 }).length;
const kb = (size / 1024).toFixed(1);
if (size >= LIMIT) {
  console.error(`chatiapp.js pesa ${kb} KB comprimido: supera el límite de 150 KB`);
  process.exit(1);
}
console.log(`chatiapp.js pesa ${kb} KB comprimido (límite: 150 KB)`);
