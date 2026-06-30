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
  "Score",
  "Recommendation",
  "Role",
  "CV family",
  "Scoring mode",
  "Star / priority",
  "Q2 eligibility",
  "Intake status",
  "Q2 task status",
  "Promotion reason",
  "Packet",
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
if (!html.includes('id="reviews-list"')) {
  throw new Error("dashboard missing review queue section");
}
if (!html.includes('id="workers-list"')) {
  throw new Error("dashboard missing worker status section");
}

const sandbox = {
  console,
  fetch: async () => ({ ok: true, json: async () => ({ jobs: [] }) }),
  document: { querySelector: () => null, createElement: createElement },
  URLSearchParams,
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
assertEqual(dashboard.actionEndpoint("job-1", "rescore"), "/api/jobs/job-1/rescore");
assertEqual(dashboard.actionEndpoint("job-1", "star"), "/api/jobs/job-1/star");
assertEqual(dashboard.ownerHeaders()["X-JobAgent-Owner"], "local");
assertEqual(
  dashboard.regenerationStatusLabel("queued"),
  "Queued - waiting for the regeneration worker.",
);
assertEqual(dashboard.secondsLabel(65), "1m 5s");

const tbody = createElement("tbody");
dashboard.renderJobs(
  [
    {
      job_id: "job-1",
      company: "<unsafe>",
      title: "Engineer",
      location: "Austin, TX",
      overall_score: 81,
      recommendation: "Apply",
      role_family: "Software Engineering",
      selected_cv_family: "software",
      scoring_mode: "hybrid",
      starred: true,
      manual_priority: 1,
      q2_eligibility: "in_q2",
      intake_status: "scored",
      packet_status: "ready",
      promotion_reason: "score_threshold",
      reason: "Done",
      extraction_warnings: ["location_not_found"],
      source_url: "https://example.com/job",
      placeholder_artifact_path: "artifact.json",
      packet: { packet_id: "packet-1", status: "ready", selected_cv_family: "software", page_count: 2 },
    },
  ],
  tbody,
  async () => ({}),
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
assertEqual(tbody.children[0].children[3].textContent, "81");
assertEqual(tbody.children[0].children[4].textContent, "Apply");
assertEqual(tbody.children[0].children[5].textContent, "Software Engineering");
assertEqual(tbody.children[0].children[6].textContent, "Software Engineering");
assertEqual(tbody.children[0].children[7].textContent, "hybrid");
assertEqual(tbody.children[0].children[8].textContent, "Starred");
assertEqual(tbody.children[0].children[9].textContent, "in_q2");
assertEqual(tbody.children[0].children[11].textContent, "ready");
assertEqual(tbody.children[0].children[12].textContent, "score_threshold");
assertEqual(tbody.children[0].children[13].textContent, "Generated - requires fitting (2 pages)");
assertEqual(dashboard.packetSummary({ status: "failed", failure_reason: "compile failed" }), "Failed: compile failed");
if (!elementText(tbody.children[0].children[16]).includes("Review family selection")) {
  throw new Error("scored jobs should offer manual family review");
}

const queuedBody = createElement("tbody");
dashboard.renderJobs(
  [
    {
      job_id: "job-queued",
      company: null,
      title: null,
      location: null,
      overall_score: null,
      recommendation: null,
      role_family: null,
      selected_cv_family: null,
      scoring_mode: null,
      starred: false,
      manual_priority: 0,
      q2_eligibility: "not_scored",
      intake_status: "queued",
      packet_status: "not_requested",
      promotion_reason: null,
      source_url: "https://example.com/queued",
    },
  ],
  queuedBody,
  async () => ({}),
  async () => ({}),
);
assertEqual(queuedBody.children[0].children[10].textContent, "Queued - not processed");

const review = sampleReview();
const workers = createElement("div");
dashboard.renderWorkerStatus(sampleWorkerStatus(), workers);
const workerText = elementText(workers);
for (const expected of [
  "Queue 1",
  "Queue 2",
  "Regeneration",
  "degraded",
  "queued_work_without_healthy_worker",
]) {
  if (!workerText.includes(expected)) {
    throw new Error(`worker status missing ${expected}`);
  }
}

const reviewList = createElement("div");
dashboard.renderReviewQueue([review], reviewList, () => {});
if (!elementText(reviewList).includes("wrong_family_reported")) {
  throw new Error("review queue should show review reason");
}
if (!elementText(reviewList).includes("Digital IC / RTL")) {
  throw new Error("review queue should show family label");
}

const emptyReviews = createElement("div");
dashboard.renderReviewQueue([], emptyReviews, () => {});
if (!elementText(emptyReviews).includes("No reviews match")) {
  throw new Error("review queue should show empty state");
}

const detail = createElement("div");
dashboard.renderReviewDetail(review, detail, async () => {});
const detailText = elementText(detail);
for (const expected of [
  "Automated classification",
  "Digital IC / RTL (selected)",
  "Verification / SoC Verification (secondary)",
  "0.480 (48%)",
  "Deterministic evidence",
  "No semantic evidence was recorded",
  "Automated tailoring",
  "SparrowML",
  "Immutable content guarantee",
  "Approve selected family",
  "Select approved replacement",
]) {
  if (!detailText.includes(expected)) {
    throw new Error(`review detail missing ${expected}`);
  }
}
if (detail.innerHTML) {
  throw new Error("review detail should not use raw HTML rendering");
}

const resolvedDetail = createElement("div");
dashboard.renderReviewDetail(
  {
    ...review,
    status: "overridden",
    history: [
      {
        action: "override_family",
        reviewer_id: "tester",
        regeneration_status: "complete",
        regeneration_packet_id: "packet-reviewed",
        source_packet_id: "packet-1",
        completed_at: "2026-06-30T12:05:00Z",
        review_note: "<b>private</b>",
      },
    ],
  },
  resolvedDetail,
  async () => {},
);
if (!elementText(resolvedDetail).includes("Resolution history")) {
  throw new Error("resolved reviews should display history");
}
if (!elementText(resolvedDetail).includes("Complete - reviewed packet is available.")) {
  throw new Error("resolved reviews should display completed regeneration status");
}
if (!elementText(resolvedDetail).includes("packet-reviewed")) {
  throw new Error("resolved reviews should link reviewed packet");
}

const overridePayload = dashboard.buildResolutionPayload("override_family", {
  note: "Looks like verification",
  overrideFamily: "verification",
  replacementValue: "",
});
assertEqual(overridePayload.action, "override_family");
assertEqual(overridePayload.resolved_family, "verification");
assertEqual(overridePayload.review_note, "Looks like verification");

const replacementPayload = dashboard.buildResolutionPayload("select_approved_replacement", {
  note: "",
  overrideFamily: "digital_ic",
  replacementValue: "digital_ic|sparrow_cluster_digital_ic_v1|sparrowml_ml_v1",
});
assertEqual(replacementPayload.resolved_family, "digital_ic");
assertEqual(replacementPayload.removed_block, "sparrow_cluster_digital_ic_v1");
assertEqual(replacementPayload.inserted_block, "sparrowml_ml_v1");

assertThrows(() => dashboard.buildResolutionPayload("override_family", {
  note: "",
  overrideFamily: "analog_ic",
  replacementValue: "",
}));
assertThrows(() => dashboard.buildResolutionPayload("select_approved_replacement", {
  note: "",
  overrideFamily: "digital_ic",
  replacementValue: "arbitrary_block",
}));

let lastFetch = null;
await dashboard.fetchReviews({ status: "pending", review_type: "classification" }, async (url, options) => {
  lastFetch = { url, options };
  return { ok: true, json: async () => ({ reviews: [] }) };
});
if (!lastFetch.url.includes("/api/reviews?status=pending&review_type=classification")) {
  throw new Error("review filters should be encoded in API request");
}
assertEqual(lastFetch.options.headers["X-JobAgent-Owner"], "local");

await dashboard.resolveReview("review-1", { action: "defer", reviewer_id: "tester" }, async (url, options) => {
  lastFetch = { url, options };
  return { ok: true, json: async () => ({ review }) };
});
assertEqual(lastFetch.options.headers["Content-Type"], "application/json");
assertEqual(lastFetch.options.headers["X-JobAgent-Owner"], "local");
assertEqual(JSON.parse(lastFetch.options.body).action, "defer");

await dashboard.createJobReview("job-1", { review_type: "classification", reason: "wrong_family_reported" }, async (url, options) => {
  lastFetch = { url, options };
  return { ok: true, json: async () => ({ review }) };
});
if (!lastFetch.url.endsWith("/api/jobs/job-1/reviews")) {
  throw new Error("manual review creation should call job review endpoint");
}

await dashboard.fetchWorkerStatus(async (url, options) => {
  lastFetch = { url, options };
  return { ok: true, json: async () => sampleWorkerStatus() };
});
if (!lastFetch.url.endsWith("/api/workers/status")) {
  throw new Error("worker status should call status endpoint");
}

console.log("frontend dashboard checks passed");

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

function elementText(element) {
  return [
    element.textContent || "",
    ...(element.children || []).map((child) => elementText(child)),
  ].join("");
}

function assertThrows(callback) {
  let threw = false;
  try {
    callback();
  } catch {
    threw = true;
  }
  if (!threw) {
    throw new Error("expected callback to throw");
  }
}

function sampleReview() {
  return {
    review_id: "review-1",
    job_id: "job-1",
    packet_id: "packet-1",
    review_type: "classification",
    status: "pending",
    reason: "wrong_family_reported",
    created_at: "2026-06-30T12:00:00Z",
    job: { title: "RTL ML Engineer", company: "<unsafe>", selected_cv_family: "digital_ic" },
    classification: {
      selected_family: "digital_ic",
      secondary_family: "verification",
      decision: "close_match",
      confidence: 0.48,
      requires_review: true,
      classifier_version: "phase-b-family-classifier-v1",
      config_version: "phase-b-family-classifier-config-v1",
      family_scores: {
        digital_ic: 0.48,
        verification: 0.44,
        software: 0.05,
        ml: 0.03,
      },
      rule_evidence: [
        { family: "digital_ic", section: "responsibility", phrase: "<script>rtl</script>", polarity: "positive" },
      ],
      semantic_evidence: [],
    },
    tailoring: {
      base_family: "digital_ic",
      base_blocks: ["tinynpu_digital_ic_v1", "sparrow_cluster_digital_ic_v1"],
      final_blocks: ["tinynpu_digital_ic_v1", "sparrowml_ml_v1"],
      removed_block: "sparrow_cluster_digital_ic_v1",
      inserted_block: "sparrowml_ml_v1",
      replacement_gain: 0.18,
      tailoring_status: "tailored",
      fallback_reason: null,
      policy_version: "phase-d-one-block-tailoring-v1",
      registry_version: "project-block-registry-v1",
    },
    metadata: {
      families: {
        digital_ic: "Digital IC / RTL",
        verification: "Verification / SoC Verification",
        software: "Software Engineering",
        ml: "Machine Learning Engineering",
      },
      project_blocks: {
        tinynpu_digital_ic_v1: {
          display_name: "tinyNPU",
          family: "digital_ic",
          preview: "Designed accelerator RTL.",
        },
        sparrow_cluster_digital_ic_v1: {
          display_name: "Sparrow Cluster",
          family: "digital_ic",
          preview: "Built coherent cluster.",
        },
        sparrowml_ml_v1: {
          display_name: "SparrowML",
          family: "ml",
          preview: "Built sparse ML runtime.",
        },
      },
      replacement_options: [
        {
          base_family: "digital_ic",
          removed_block: "sparrow_cluster_digital_ic_v1",
          inserted_block: "sparrowml_ml_v1",
          removed_name: "Sparrow Cluster",
          inserted_name: "SparrowML",
          reason: "Approved compatible hybrid block.",
        },
      ],
    },
    allowed_actions: [
      "approve_classification",
      "override_family",
      "mark_out_of_scope",
      "defer",
      "select_approved_replacement",
    ],
    history: [],
  };
}

function sampleWorkerStatus() {
  return {
    workers: [
      {
        worker_type: "q1",
        health: "idle",
        current_job_id: null,
        last_success_at: "2026-06-30T12:00:00Z",
        last_failure_at: null,
      },
    ],
    queues: {
      q1: { queued_count: 0, processing_count: 0, failed_count: 0 },
      q2: { queued_count: 2, processing_count: 0, failed_count: 1 },
      regeneration: { queued_count: 1, processing_count: 0, failed_count: 0 },
    },
    queue_health: {
      q1: { health: "idle", warnings: [], healthy_worker_count: 1 },
      q2: {
        health: "degraded",
        warnings: ["queued_work_without_healthy_worker"],
        healthy_worker_count: 0,
        oldest_queued_age_seconds: 65,
      },
      regeneration: { health: "offline", warnings: [], healthy_worker_count: 0 },
    },
  };
}
