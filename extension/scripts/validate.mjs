import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf8"));

if (manifest.manifest_version !== 3) {
  throw new Error("extension manifest must use MV3");
}

if (!manifest.action?.default_popup) {
  throw new Error("extension manifest must define an action popup");
}

console.log("extension structure is valid");

