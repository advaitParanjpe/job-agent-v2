import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const html = readFileSync(join(root, "src", "index.html"), "utf8");
const source = readFileSync(join(root, "src", "app.js"), "utf8");

for (const column of [
  "Company",
  "Title",
  "Score",
  "Rec",
  "Role",
  "Intake status",
  "Packet status",
  "Reason",
  "Source",
  "Actions",
]) {
  if (!html.includes(`<th>${column}</th>`)) {
    throw new Error(`dashboard missing ${column} column`);
  }
}

const sandbox = {
  console,
  fetch: async () => ({ ok: true, json: async () => ({ jobs: [] }) }),
  document: { querySelector: () => null, createElement: createElement },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const dashboard = sandbox.JobAgentV2Dashboard;
assertEqual(dashboard.displayValue(null), "-");
assertEqual(dashboard.actionEndpoint("job-1", "generate"), "/api/jobs/job-1/generate");
assertEqual(dashboard.actionEndpoint("job-1", "retry"), "/api/jobs/job-1/retry");
assertEqual(dashboard.actionEndpoint("job-1", "archive"), "/api/jobs/job-1/archive");

const tbody = createElement("tbody");
dashboard.renderJobs(
  [
    {
      job_id: "job-1",
      company: "<unsafe>",
      title: "Engineer",
      overall_score: null,
      recommendation: null,
      role_family: null,
      intake_status: "scored",
      packet_status: "ready",
      reason: "Done",
      source_url: "https://example.com/job",
      placeholder_artifact_path: "artifact.json",
    },
  ],
  tbody,
  async () => ({}),
);

if (tbody.children.length !== 1) {
  throw new Error("dashboard did not render job row");
}
if (tbody.children[0].children[0].textContent !== "<unsafe>") {
  throw new Error("dashboard should render text content without HTML interpolation");
}

console.log("frontend dashboard checks passed");

function createElement(tagName) {
  return {
    tagName,
    children: [],
    textContent: "",
    type: "",
    href: "",
    target: "",
    rel: "",
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    addEventListener() {},
  };
}

function assertEqual(actual, expected) {
  if (actual !== expected) {
    throw new Error(`expected ${expected}, got ${actual}`);
  }
}
