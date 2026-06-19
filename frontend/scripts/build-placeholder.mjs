import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const dist = join(root, "dist");

mkdirSync(dist, { recursive: true });
for (const file of readdirSync(join(root, "src"))) {
  copyFileSync(join(root, "src", file), join(dist, file));
}
console.log("frontend build complete");
