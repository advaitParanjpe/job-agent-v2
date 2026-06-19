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
  "Location",
  "JD quality",
  "Role",
  "Intake status",
  "Packet status",
  "Reason / warnings",
  "Source",
  "Actions",
]) {
  if (!html.includes(`<th>${column}</th>`)) {
    throw new Error(`dashboard missing ${column} column`);
  }
}
if (!html.includes('id="process-intake-queue"')) {
  throw new Error("dashboard missing explicit intake queue action");
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
assertEqual(dashboard.intakeStatusLabel("queued"), "Queued - not processed");
assertEqual(
  dashboard.reasonAndWarnings({
    reason: "Needs review",
    extraction_warnings: ["qualifications_section_missing"],
  }),
  "Needs review | Warnings: qualifications_section_missing",
);
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
      location: "Austin, TX",
      jd_quality_band: "manual_review",
      role_family: null,
      intake_status: "manual_review",
      packet_status: "ready",
      reason: "Done",
      extraction_warnings: ["location_not_found"],
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
assertEqual(tbody.children[0].children[1].textContent, "Engineer");
assertEqual(tbody.children[0].children[2].textContent, "Austin, TX");
assertEqual(tbody.children[0].children[3].textContent, "manual_review");
assertEqual(tbody.children[0].children[4].textContent, "-");

const queuedBody = createElement("tbody");
dashboard.renderJobs(
  [
    {
      job_id: "job-queued",
      company: null,
      title: null,
      location: null,
      jd_quality_band: null,
      role_family: null,
      intake_status: "queued",
      packet_status: "not_requested",
      source_url: "https://example.com/queued",
    },
  ],
  queuedBody,
  async () => ({}),
);
assertEqual(queuedBody.children[0].children[5].textContent, "Queued - not processed");

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
