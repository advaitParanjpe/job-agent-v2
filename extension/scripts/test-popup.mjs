import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const source = readFileSync(join(root, "popup.js"), "utf8");
const listeners = {};
const sandbox = {
  URL,
  console,
  fetch: async () => ({ ok: true, json: async () => ({ duplicate: false }) }),
  chrome: {
    tabs: { query: async () => [{ id: 1, url: "https://Example.com/job", title: "Role" }] },
    scripting: { executeScript: async () => [{ result: " Visible\n text " }] },
  },
  document: {
    querySelector(selector) {
      if (selector === "#add-to-queue") {
        return {
          disabled: false,
          addEventListener(event, handler) {
            listeners[event] = handler;
          },
        };
      }
      return { textContent: "" };
    },
  },
};
sandbox.globalThis = sandbox;

vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const extension = sandbox.JobAgentV2Extension;
const payload = extension.buildCapturePayload(
  { url: "https://www.Example.com/jobs/1", title: "Example Job" },
  " A\n\n job\t page ",
  "2026-06-19T12:00:00Z",
);

assertEqual(payload.url, "https://www.Example.com/jobs/1");
assertEqual(payload.page_title, "Example Job");
assertEqual(payload.visible_text, "A job page");
assertEqual(payload.source_site, "example.com");
assertEqual(payload.captured_at, "2026-06-19T12:00:00Z");
assertEqual(extension.outcomeLabel({ duplicate: false }), "Added to queue");
assertEqual(extension.outcomeLabel({ duplicate: true }), "Already queued");

if (typeof listeners.click !== "function") {
  throw new Error("Add to Queue click listener was not registered");
}

console.log("extension popup checks passed");

function assertEqual(actual, expected) {
  if (actual !== expected) {
    throw new Error(`expected ${expected}, got ${actual}`);
  }
}
