import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const html = readFileSync(join(root, "src", "index.html"), "utf8");
const css = readFileSync(join(root, "src", "styles.css"), "utf8");
const source = readFileSync(join(root, "src", "app.js"), "utf8");

for (const expected of ["Jobs", "Reviews", "System", "add-job", "app-message"]) {
  if (!html.includes(expected)) throw new Error(`dashboard missing ${expected}`);
}
if (!html.includes("Added -> Analysing role -> Choosing CV")) {
  throw new Error("jobs page should explain the stage pipeline");
}
if (html.includes("<table")) throw new Error("jobs overview should not be a dense table");
for (const token of ["--bg", "--panel", "--font-mono", ".stage-steps", ".job-row"]) {
  if (!css.includes(token)) throw new Error(`CSS design token/class missing ${token}`);
}

const sandbox = {
  console,
  fetch: async () => ({ ok: true, json: async () => ({ jobs: [] }) }),
  document: { querySelector: () => null, querySelectorAll: () => [], createElement },
  URLSearchParams,
  confirm: () => true,
  alert: () => {},
  window: { open: () => {} },
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const dashboard = sandbox.JobAgentV2Dashboard;

assertEqual(dashboard.displayValue(null), "-");
assertEqual(dashboard.familyLabel("digital_ic"), "Digital IC / RTL");
assertEqual(dashboard.semanticStatusLabel("request_failed"), "LLM analysis unavailable");
assertEqual(dashboard.actionEndpoint("job-1", "delete"), "/api/jobs/job-1/delete");
assertEqual(dashboard.actionEndpoint("job-1", "restore_and_rescore"), "/api/jobs/job-1/restore-and-rescore");
assertEqual(dashboard.ownerHeaders()["X-JobAgent-Owner"], "local");

assertEqual(dashboard.deriveStage(sampleJob("queued", {
  intake_status: "queued",
  packet_status: "not_requested",
  selected_cv_family: null,
  packet: null,
})), "added");
assertEqual(dashboard.deriveStage(sampleJob("scoring", {
  intake_status: "scoring",
  packet_status: "not_requested",
  selected_cv_family: null,
  packet: null,
})), "analysing");
assertEqual(dashboard.deriveStage(sampleJob("classified", { packet_status: "not_requested" })), "classified");
assertEqual(dashboard.deriveStage(sampleJob("ready")), "ready");
assertEqual(dashboard.deriveStage(sampleJob("review", { family_classification_requires_review: true })), "needs_review");
assertEqual(dashboard.stageDefinition(sampleJob("ready")).label, "Ready");
assertEqual(dashboard.nextActionForJob(sampleJob("ready")).label, "Open packet");

const jobs = [
  sampleJob("job-1"),
  sampleJob("job-2", {
    intake_status: "queued",
    packet_status: "not_requested",
    overall_score: null,
    selected_cv_family: null,
    packet: null,
  }),
];
assertEqual(dashboard.summaryItems(jobs)[0].value, 2);
assertEqual(dashboard.filteredJobs(jobs, "needs_scoring").length, 1);
assertEqual(dashboard.filteredJobs(jobs, "packet_ready").length, 1);

const progress = createElement("div");
progress.appendChild(dashboard.stageProgress("classified"));
if (!elementText(progress).includes("03 Choosing CV")) {
  throw new Error("stage progress should render compact labelled steps");
}

const detail = createElement("div");
dashboard.renderJobDetail(jobs[0], detail, async () => ({}));
const detailText = elementText(detail);
for (const expected of [
  "SELECTED JOB",
  "CURRENT STAGE",
  "Packet ready",
  "Open packet",
  "FIT SCORE",
  "82 / 100",
  "CV SELECTED",
  "Mixed role: Verification + Software",
  "PROJECT PORTFOLIO",
  "Base CV",
  "View requirement coverage",
  "Re-analyse project selection",
  "CV PACKET",
  "Semantic analysis",
  "Previous analyses",
  "Technical details",
  "Archive or delete",
]) {
  if (!detailText.includes(expected)) throw new Error(`job detail missing ${expected}`);
}
if (detailText.includes("phase-b-family-classifier-v1") && !hasDetails(detail)) {
  throw new Error("technical metadata should be inside disclosures");
}
if (detail.innerHTML) throw new Error("job detail should not use raw HTML");

const list = createElement("div");
dashboard.renderJobsPage(jobs, "job-1");
dashboard.renderJobsPage(jobs, "job-2");
dashboard.renderReviewQueue([sampleReview()], list, () => {});
const reviewListText = elementText(list);
if (!reviewListText.includes("Review")) throw new Error("review card should have one Review action");
if (reviewListText.includes("UVM")) throw new Error("review list should hide detailed evidence");

const reviewDetail = createElement("div");
dashboard.renderReviewDetail(sampleReview(), reviewDetail, async () => {});
const reviewText = elementText(reviewDetail);
for (const expected of ["WHAT JOBAGENT RECOMMENDS", "1 Choose CV", "Continue"]) {
  if (!reviewText.includes(expected)) throw new Error(`staged review detail missing ${expected}`);
}

const workers = createElement("div");
dashboard.renderWorkerStatus(sampleWorkerStatus(), workers);
const workerText = elementText(workers);
for (const expected of ["API", "ONLINE", "SCORING WORKER", "PACKET WORKER", "SEMANTIC LLM"]) {
  if (!workerText.includes(expected)) throw new Error(`system view missing ${expected}`);
}
if (!hasDetails(workers)) throw new Error("system diagnostics should be disclosed");

assertEqual(
  dashboard.buildResolutionPayload("override_family", {
    note: "Looks right",
    overrideFamily: "verification",
    replacementValue: "",
  }).resolved_family,
  "verification",
);

let lastFetch = null;
await dashboard.fetchReviews({ status: "pending", review_type: "classification" }, async (url, options) => {
  lastFetch = { url, options };
  return { ok: true, json: async () => ({ reviews: [] }) };
});
if (!lastFetch.url.includes("/api/reviews?status=pending&review_type=classification")) {
  throw new Error("review filters should be encoded");
}
assertEqual(lastFetch.options.headers["X-JobAgent-Owner"], "local");

console.log("frontend dashboard checks passed");

function sampleJob(id, overrides = {}) {
  const base = {
    job_id: id,
    title: "Verification Infrastructure Engineer",
    company: "Acme",
    location: "Austin, TX",
    source_url: "https://example.com/job",
    source_provenance: "manual",
    created_at: "2026-06-30T12:00:00Z",
    updated_at: "2026-06-30T12:01:00Z",
    intake_status: "scored",
    packet_status: "ready",
    selected_cv_family: "verification",
    secondary_cv_family: "software",
    family_classification_decision: "hybrid_match",
    family_classification_requires_review: false,
    family_classifier_version: "phase-b-family-classifier-v1",
    scoring_mode: "hybrid",
    llm_call_status: "success",
    overall_score: 82,
    recommendation: "Apply",
    strengths: ["UVM evidence"],
    gaps: ["None"],
    packet: {
      packet_id: "packet-1",
      status: "ready",
      selected_cv_family: "verification",
      page_count: 1,
      generation_kind: "automated",
    },
    tailoring_decision: {
      decision: {
        base_family: "ml",
        tailoring_status: "review_required",
        inserted_block: null,
        removed_block: null,
        reason: "A high-specificity requirement has a reviewable approved project option.",
        requirement_analysis: {
          requirements: [
            {
              evidence_quote: "NPUs",
              normalized_capabilities: ["npu", "ml_accelerator"],
              importance: 0.58,
            },
          ],
        },
        project_portfolio: {
          candidate_scores: [
            {
              block_id: "tinynpu_digital_ic_v1",
              display_name: "tinyNPU",
              score: 0.63,
              distinctive_capabilities: ["npu", "ml_accelerator"],
            },
          ],
        },
        candidate_blocks: [
          {
            block_id: "tinynpu_digital_ic_v1",
            display_name: "tinyNPU",
            requires_review: true,
            shortlist_reason: "requirement_aware_shortlist",
          },
        ],
      },
    },
    score_breakdown: {
      hybrid: {
        semantic_assessment: {
          grounded_reason: "Primarily Verification because of UVM regressions.",
          strengths: ["UVM regressions", "waveform triage"],
        },
      },
    },
    ui: {
      classification: {
        decision_label: "Mixed role: Verification + Software",
        family_scores: { digital_ic: 0.05, verification: 0.62, software: 0.28, ml: 0.05 },
        rule_evidence: [{ family: "verification", section: "responsibility", phrase: "UVM" }],
        semantic_evidence: [{ quote: "UVM regressions", family: "verification", reason: "Core evidence" }],
        weights: { deterministic: 0.6, semantic: 0.4 },
      },
      semantic: {
        status: "live_success",
        model: "gpt-5.4-mini",
        timestamp: "2026-06-30T12:01:00Z",
        latency_ms: 930,
        summary: "Primarily Verification because the core responsibilities are UVM regressions.",
      },
      packet: { status_label: "Packet ready", selected_cv_family: "verification" },
    },
  };
  return deepMerge(base, overrides);
}

function sampleReview() {
  return {
    review_id: "review-1",
    job_id: "job-1",
    status: "pending",
    reason: "classification_decision:hybrid_match",
    job: { title: "Verification Infrastructure Engineer", company: "Acme" },
    classification: {
      selected_family: "verification",
      decision: "hybrid_match",
      rule_evidence: [{ family: "verification", section: "responsibility", phrase: "UVM" }],
    },
    tailoring: { status: "master_unchanged" },
    allowed_actions: ["approve_classification", "override_family", "defer"],
    metadata: { replacement_options: [] },
  };
}

function sampleWorkerStatus() {
  return {
    semantic_config: { enabled: true, provider: "openai", model: "gpt-5.4-mini", api_key_configured: true },
    database: { demo_cleanup: { job_count: 0 } },
    queues: {
      q1: { queued_count: 1, processing_count: 0, failed_count: 0 },
      q2: { queued_count: 0, processing_count: 0, failed_count: 0 },
      regeneration: { queued_count: 0, processing_count: 0, failed_count: 0 },
    },
    queue_health: {
      q1: { health: "idle", warnings: [] },
      q2: { health: "idle", warnings: [] },
      regeneration: { health: "idle", warnings: [] },
    },
  };
}

function createElement(tagName) {
  return {
    tagName,
    children: [],
    textContent: "",
    className: "",
    type: "",
    href: "",
    target: "",
    rel: "",
    value: "",
    maxLength: 0,
    rows: 0,
    style: {},
    dataset: {},
    innerHTML: "",
    classList: { toggle: () => {} },
    setAttribute() {},
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    addEventListener() {},
  };
}

function elementText(element) {
  return [element.textContent, ...element.children.map(elementText)].join(" ");
}

function hasDetails(element) {
  return element.tagName === "details" || element.children.some(hasDetails);
}

function assertEqual(actual, expected) {
  if (actual !== expected) throw new Error(`expected ${expected}, got ${actual}`);
}

function deepMerge(base, patch) {
  const result = Array.isArray(base) ? [...base] : { ...base };
  for (const [key, value] of Object.entries(patch)) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      base[key] &&
      typeof base[key] === "object"
    ) {
      result[key] = deepMerge(base[key], value);
    } else {
      result[key] = value;
    }
  }
  return result;
}
