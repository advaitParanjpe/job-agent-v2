import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const manifest = JSON.parse(readFileSync(join(root, "manifest.json"), "utf8"));
const popup = readFileSync(join(root, "popup.js"), "utf8");

if (manifest.manifest_version !== 3) {
  throw new Error("extension manifest must use MV3");
}

if (!manifest.action?.default_popup) {
  throw new Error("extension manifest must define an action popup");
}

for (const permission of ["activeTab", "scripting"]) {
  if (!manifest.permissions?.includes(permission)) {
    throw new Error(`extension manifest missing ${permission} permission`);
  }
}

for (const field of ["url", "page_title", "visible_text", "source_site", "captured_at"]) {
  if (!popup.includes(field)) {
    throw new Error(`popup payload is missing ${field}`);
  }
}

for (const forbidden of ["auth", "scoreCurrentPage", "generate-packet", "Bearer"]) {
  if (popup.includes(forbidden)) {
    throw new Error(`popup contains forbidden V1 flow token: ${forbidden}`);
  }
}

console.log("extension structure is valid");
