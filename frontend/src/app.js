const API_BASE_URL = "http://127.0.0.1:8765";

const DASHBOARD_COLUMNS = [
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
    appendCell(row, displayValue(job.overall_score));
    appendCell(row, displayValue(job.recommendation));
    appendCell(row, displayValue(job.role_family));
    appendCell(row, displayValue(job.intake_status));
    appendCell(row, displayValue(job.packet_status));
    appendCell(row, displayValue(job.reason));
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
  if (job.intake_status === "failed" || job.packet_status === "failed") {
    cell.appendChild(buildActionButton(job, "retry", "Retry", onAction));
  }
  cell.appendChild(buildActionButton(job, "archive", "Archive", onAction));
  if (job.placeholder_artifact_path) {
    const artifact = document.createElement("a");
    artifact.href = job.placeholder_artifact_path;
    artifact.target = "_blank";
    artifact.rel = "noreferrer";
    artifact.textContent = "Open placeholder artifact";
    cell.appendChild(artifact);
  }
  row.appendChild(cell);
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

if (typeof document !== "undefined") {
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
  displayValue,
  renderJobs,
};
