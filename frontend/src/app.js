const API_BASE_URL = "http://127.0.0.1:8765";

const DASHBOARD_COLUMNS = [
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
];

async function apiPost(path, fetchImpl = fetch) {
  const response = await fetchImpl(`${API_BASE_URL}${path}`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

async function fetchJobs(fetchImpl = fetch) {
  const response = await fetchImpl(`${API_BASE_URL}/api/jobs`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function displayValue(value, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function intakeStatusLabel(status) {
  if (status === "queued") {
    return "Queued - not processed";
  }
  return displayValue(status);
}

function actionEndpoint(jobId, action) {
  if (action === "generate") {
    return `/api/jobs/${jobId}/generate`;
  }
  if (action === "retry") {
    return `/api/jobs/${jobId}/retry`;
  }
  if (action === "archive") {
    return `/api/jobs/${jobId}/archive`;
  }
  if (action === "rescore") {
    return `/api/jobs/${jobId}/rescore`;
  }
  if (action === "star") {
    return `/api/jobs/${jobId}/star`;
  }
  if (action === "unstar") {
    return `/api/jobs/${jobId}/unstar`;
  }
  throw new Error(`unknown action: ${action}`);
}

function buildActionButton(job, action, label, onAction) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    await onAction(actionEndpoint(job.job_id, action));
  });
  return button;
}

function renderJobs(jobs, tbody, onAction = apiPost) {
  tbody.textContent = "";
  for (const job of jobs) {
    const row = document.createElement("tr");
    appendCell(row, displayValue(job.company));
    appendCell(row, displayValue(job.title));
    appendCell(row, displayValue(job.location));
    appendCell(row, displayValue(job.overall_score));
    appendCell(row, displayValue(job.recommendation));
    appendCell(row, displayValue(job.role_family));
    appendCell(row, displayValue(job.selected_cv_family));
    appendCell(row, displayValue(job.scoring_mode));
    appendCell(row, job.starred ? "Starred" : displayValue(job.manual_priority, "Normal"));
    appendCell(row, displayValue(job.q2_eligibility));
    appendCell(row, intakeStatusLabel(job.intake_status));
    appendCell(row, displayValue(job.packet_status));
    appendCell(row, displayValue(job.promotion_reason));
    appendCell(row, packetSummary(job.packet));
    appendCell(row, reasonAndWarnings(job));
    appendSourceCell(row, job.source_url);
    appendActionsCell(row, job, onAction);
    tbody.appendChild(row);
  }
}

function appendCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  row.appendChild(cell);
}

function appendSourceCell(row, sourceUrl) {
  const cell = document.createElement("td");
  const link = document.createElement("a");
  link.href = sourceUrl;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Open source";
  cell.appendChild(link);
  row.appendChild(cell);
}

function appendActionsCell(row, job, onAction) {
  const cell = document.createElement("td");
  cell.appendChild(buildActionButton(job, "generate", "Generate now", onAction));
  cell.appendChild(buildActionButton(job, job.starred ? "unstar" : "star", job.starred ? "Unstar" : "Star", onAction));
  if (job.intake_status === "scored") {
    cell.appendChild(buildActionButton(job, "rescore", "Rescore", onAction));
    const details = document.createElement("a");
    details.href = `${API_BASE_URL}/api/jobs/${job.job_id}/score`;
    details.target = "_blank";
    details.rel = "noreferrer";
    details.textContent = "Score details";
    cell.appendChild(details);
  }
  if (
    job.intake_status === "failed" ||
    job.intake_status === "manual_review" ||
    job.packet_status === "failed" ||
    job.packet_status === "manual_review"
  ) {
    cell.appendChild(buildActionButton(job, "retry", "Retry", onAction));
  }
  cell.appendChild(buildActionButton(job, "archive", "Archive", onAction));
  if (job.packet) {
    const pdf = document.createElement("a");
    pdf.href = `${API_BASE_URL}/api/packets/${job.packet.packet_id}/pdf`;
    pdf.target = "_blank";
    pdf.rel = "noreferrer";
    pdf.textContent = "Open PDF";
    cell.appendChild(pdf);
    const manifest = document.createElement("a");
    manifest.href = `${API_BASE_URL}/api/packets/${job.packet.packet_id}/manifest`;
    manifest.target = "_blank";
    manifest.rel = "noreferrer";
    manifest.textContent = "View manifest";
    cell.appendChild(manifest);
  }
  row.appendChild(cell);
}

function packetSummary(packet) {
  if (!packet) return "-";
  if (packet.status === "failed") return `Failed: ${packet.failure_reason || "unknown failure"}`;
  if (packet.status === "ready" && packet.page_count > 1) return `Generated — requires fitting (${packet.page_count} pages)`;
  return `${packet.status} | ${packet.selected_cv_family || "-"} | ${packet.page_count || "?"} page(s)`;
}

function reasonAndWarnings(job) {
  const parts = [];
  if (job.reason) {
    parts.push(job.reason);
  }
  if (job.manual_review_reason) {
    parts.push(job.manual_review_reason);
  }
  if (job.failure_reason) {
    parts.push(job.failure_reason);
  }
  if (job.duplicate_warning) {
    parts.push(job.duplicate_warning);
  }
  if (Array.isArray(job.extraction_warnings) && job.extraction_warnings.length) {
    parts.push(`Warnings: ${job.extraction_warnings.join(", ")}`);
  }
  return parts.join(" | ") || "-";
}

async function refreshDashboard() {
  const tbody = document.querySelector("#jobs-body");
  if (!tbody) {
    return;
  }
  const data = await fetchJobs();
  renderJobs(data.jobs, tbody, async (endpoint) => {
    await apiPost(endpoint);
    await refreshDashboard();
  });
}

function bindIntakeQueueAction() {
  const button = document.querySelector("#process-intake-queue");
  if (!button) {
    return;
  }
  button.addEventListener("click", async () => {
    await apiPost("/api/workers/q1/run-once");
    await refreshDashboard();
  });
}

if (typeof document !== "undefined") {
  bindIntakeQueueAction();
  refreshDashboard().catch((error) => {
    const tbody = document.querySelector("#jobs-body");
    if (tbody) {
      tbody.textContent = String(error.message || error);
    }
  });
}

globalThis.JobAgentV2Dashboard = {
  DASHBOARD_COLUMNS,
  actionEndpoint,
  bindIntakeQueueAction,
  displayValue,
  intakeStatusLabel,
  packetSummary,
  reasonAndWarnings,
  renderJobs,
};
