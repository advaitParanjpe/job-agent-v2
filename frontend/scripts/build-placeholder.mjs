import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const dist = join(root, "dist");

mkdirSync(dist, { recursive: true });
copyFileSync(join(root, "src", "index.html"), join(dist, "index.html"));
console.log("frontend placeholder build complete");

