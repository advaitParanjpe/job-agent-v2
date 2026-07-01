const API_BASE_URL = "http://127.0.0.1:8765";
const OWNER_ID = "local";
const REVIEWER_ID = "local-user";

const FAMILY_LABELS = {
  digital_ic: "Digital IC / RTL",
  verification: "Verification",
  software: "Software",
  ml: "Machine Learning",
};
const FAMILY_IDS = Object.keys(FAMILY_LABELS);

const STAGE_ORDER = ["added", "analysing", "classified", "generating", "ready"];
const STAGES = {
  added: {
    label: "Added",
    title: "Role added",
    description: "JobAgent has the role. Start analysis when you are ready.",
    visual: "neutral",
    primary: "Run analysis",
  },
  analysing: {
    label: "Analysing role",
    title: "Analysing role",
    description: "JobAgent is reading the role, scoring your fit, and choosing a CV family.",
    visual: "working",
    primary: null,
  },
  classified: {
    label: "Choosing CV",
    title: "CV selected",
    description: "The role has been scored and matched to the closest CV family.",
    visual: "neutral",
    primary: "Generate CV",
  },
  generating: {
    label: "Generating packet",
    title: "Generating packet",
    description: "JobAgent is creating the CV packet from approved local content.",
    visual: "working",
    primary: null,
  },
  ready: {
    label: "Ready",
    title: "Packet ready",
    description: "Your application packet is ready to open.",
    visual: "success",
    primary: "Open packet",
  },
  needs_review: {
    label: "Needs review",
    title: "Review needed",
    description: "JobAgent needs your decision before this result should be treated as final.",
    visual: "attention",
    primary: "Review recommendation",
  },
  reviewed: {
    label: "Reviewed",
    title: "Review saved",
    description: "Your review decision was saved. Existing packets remain available.",
    visual: "success",
    primary: "View details",
  },
  regenerating: {
    label: "Regenerating",
    title: "Creating reviewed packet",
    description: "JobAgent is creating a reviewed packet from your approved decision.",
    visual: "working",
    primary: null,
  },
  reviewed_ready: {
    label: "Reviewed packet ready",
    title: "Reviewed packet ready",
    description: "The reviewed packet is available.",
    visual: "success",
    primary: "Open reviewed packet",
  },
  failed: {
    label: "Action needed",
    title: "Action needed",
    description: "Something failed. Existing completed packet artifacts remain available.",
    visual: "danger",
    primary: "Retry",
  },
  archived: {
    label: "Archived",
    title: "Archived",
    description: "This job is hidden from the active queue. Audit records remain available.",
    visual: "muted",
    primary: null,
  },
};

const SEMANTIC_STATUS_LABELS = {
  live_success: "Live LLM analysis used",
  simulated_success: "Simulated semantic analysis used",
  disabled: "LLM analysis disabled",
  not_configured: "LLM analysis not configured",
  fallback_used: "Rule-based classification used",
  request_failed: "LLM analysis unavailable",
  response_invalid: "LLM analysis unavailable",
  timed_out: "LLM analysis unavailable",
  not_attempted: "LLM analysis not attempted",
};

let state = {
  jobs: [],
  selectedJobId: null,
  reviews: [],
  workers: null,
  reviewStep: 1,
  message: "",
};

function ownerHeaders(extra = {}) {
  return { "X-JobAgent-Owner": OWNER_ID, ...extra };
}

async function apiRequest(path, options = {}, fetchImpl = fetch) {
  const request = { ...options, headers: ownerHeaders(options.headers || {}) };
  if (options.body && typeof options.body !== "string") {
    request.body = JSON.stringify(options.body);
    request.headers = ownerHeaders({
      "Content-Type": "application/json",
      ...(options.headers || {}),
    });
  }
  const response = await fetchImpl(`${API_BASE_URL}${path}`, request);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

async function apiPost(path, fetchImpl = fetch) {
  return apiRequest(path, { method: "POST" }, fetchImpl);
}

async function fetchJobs(fetchImpl = fetch) {
  return apiRequest("/api/jobs", {}, fetchImpl);
}

async function fetchReviews(filters = {}, fetchImpl = fetch) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return apiRequest(`/api/reviews${params.toString() ? `?${params}` : ""}`, {}, fetchImpl);
}

async function fetchReview(reviewId, fetchImpl = fetch) {
  return apiRequest(`/api/reviews/${reviewId}`, {}, fetchImpl);
}

async function fetchWorkerStatus(fetchImpl = fetch) {
  return apiRequest("/api/workers/status", {}, fetchImpl);
}

async function resolveReview(reviewId, payload, fetchImpl = fetch) {
  return apiRequest(`/api/reviews/${reviewId}/resolve`, { method: "POST", body: payload }, fetchImpl);
}

async function createJobReview(jobId, payload, fetchImpl = fetch) {
  return apiRequest(`/api/jobs/${jobId}/reviews`, { method: "POST", body: payload }, fetchImpl);
}

function displayValue(value, fallback = "-") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function familyLabel(value) {
  return FAMILY_LABELS[value] || displayValue(value);
}

function semanticStatusLabel(status) {
  return SEMANTIC_STATUS_LABELS[status] || displayValue(status);
}

function actionEndpoint(jobId, action) {
  const map = {
    generate: `/api/jobs/${jobId}/generate`,
    retry: `/api/jobs/${jobId}/retry`,
    archive: `/api/jobs/${jobId}/archive`,
    delete: `/api/jobs/${jobId}/delete`,
    rescore: `/api/jobs/${jobId}/rescore`,
    restore: `/api/jobs/${jobId}/restore`,
    restore_and_rescore: `/api/jobs/${jobId}/restore-and-rescore`,
    star: `/api/jobs/${jobId}/star`,
    unstar: `/api/jobs/${jobId}/unstar`,
  };
  if (!map[action]) throw new Error(`unknown action: ${action}`);
  return map[action];
}

function deriveStage(job) {
  if (!job) return "added";
  if (job.archived_at) return "archived";
  if (job.packet_status === "failed" || job.intake_status === "failed") return "failed";
  if (job.family_classification_requires_review || job.intake_status === "manual_review") {
    return "needs_review";
  }
  if (job.packet_status === "ready") return "ready";
  if (job.packet_status === "queued" || job.packet_status === "generating") return "generating";
  if (job.intake_status === "scored" || job.selected_cv_family) return "classified";
  if (["extracting", "structuring", "scoring"].includes(job.intake_status)) return "analysing";
  return "added";
}

function stageDefinition(job) {
  return STAGES[deriveStage(job)] || STAGES.added;
}

function nextActionForJob(job) {
  const stage = deriveStage(job);
  if (stage === "added") return { label: "Run analysis", action: "analyse" };
  if (stage === "classified") return { label: "Generate CV", action: "generate" };
  if (stage === "needs_review") return { label: "Review recommendation", action: "review" };
  if (stage === "ready" && job.packet) return { label: "Open packet", action: "open_packet" };
  if (stage === "failed") return { label: "Retry", action: "retry" };
  if (stage === "archived") return { label: "Restore and re-score", action: "restore_and_rescore" };
  if (stage === "reviewed_ready" && job.packet) return { label: "Open reviewed packet", action: "open_packet" };
  return null;
}

function filteredJobs(jobs, filter) {
  if (filter === "needs_scoring") {
    return jobs.filter((job) => ["added", "analysing"].includes(deriveStage(job)));
  }
  if (filter === "needs_review") return jobs.filter((job) => deriveStage(job) === "needs_review");
  if (filter === "packet_ready") return jobs.filter((job) => deriveStage(job) === "ready");
  return jobs;
}

function summaryItems(jobs) {
  return [
    { label: "Jobs", value: jobs.length },
    { label: "Working", value: jobs.filter((job) => ["analysing", "generating"].includes(deriveStage(job))).length },
    { label: "Needs review", value: jobs.filter((job) => deriveStage(job) === "needs_review").length },
    { label: "Ready", value: jobs.filter((job) => deriveStage(job) === "ready").length },
  ];
}

function renderJobsPage(jobs, selectedJobId = null) {
  const list = document.querySelector("#jobs-list");
  const detail = document.querySelector("#job-detail");
  const status = document.querySelector("#jobs-status");
  const summary = document.querySelector("#jobs-summary");
  if (!list || !detail) return;
  state.jobs = jobs;
  state.selectedJobId = selectedJobId || state.selectedJobId || (jobs[0] && jobs[0].job_id);
  if (summary) renderSummaryRail(summary, jobs);
  const visible = filteredJobs(jobs, inputValue("#job-filter", "all"));
  list.textContent = "";
  if (!jobs.length) {
    if (status) status.textContent = "NO JOBS";
    list.appendChild(emptyState("NO JOBS YET", [
      "Add a role and JobAgent will score your fit.",
      "Then it chooses a CV and generates an application packet.",
    ], "Add job"));
    detail.textContent = "";
    return;
  }
  if (status) status.textContent = `${visible.length} ACTIVE`;
  for (const job of visible) {
    list.appendChild(jobRow(job, state.selectedJobId === job.job_id));
  }
  const selected = jobs.find((job) => job.job_id === state.selectedJobId) || visible[0] || jobs[0];
  renderJobDetail(selected, detail);
}

function renderSummaryRail(container, jobs) {
  container.textContent = "";
  for (const item of summaryItems(jobs)) {
    const card = document.createElement("article");
    card.className = "metric";
    card.appendChild(mono(item.label));
    const value = document.createElement("strong");
    value.textContent = String(item.value);
    card.appendChild(value);
    container.appendChild(card);
  }
}

function emptyState(title, lines, actionLabelText) {
  const wrapper = document.createElement("section");
  wrapper.className = "empty-state panel";
  wrapper.appendChild(sectionKicker(title));
  const list = document.createElement("ol");
  for (const line of lines) {
    const li = document.createElement("li");
    li.textContent = line;
    list.appendChild(li);
  }
  wrapper.appendChild(list);
  const action = document.createElement("button");
  action.type = "button";
  action.className = "button-primary";
  action.textContent = actionLabelText;
  action.addEventListener("click", () => notify("Use the Chrome extension to add a job."));
  wrapper.appendChild(action);
  return wrapper;
}

function jobRow(job, selected) {
  const row = document.createElement("button");
  row.type = "button";
  row.className = selected ? "job-row is-selected" : "job-row";
  row.setAttribute?.("aria-pressed", selected ? "true" : "false");
  row.addEventListener("click", () => renderJobsPage(state.jobs, job.job_id));
  const top = document.createElement("span");
  top.className = "job-row-company";
  top.textContent = displayValue(job.company, "Unknown company");
  const title = document.createElement("span");
  title.className = "job-row-title";
  title.textContent = displayValue(job.title, "Untitled job");
  const line = document.createElement("span");
  line.className = "job-row-meta";
  const parts = [stageDefinition(job).label];
  if (job.overall_score !== null && job.overall_score !== undefined) parts.push(`Fit ${job.overall_score}`);
  if (deriveStage(job) === "needs_review") parts.push("Review");
  line.textContent = parts.join(" / ");
  row.appendChild(top);
  row.appendChild(title);
  row.appendChild(line);
  return row;
}

function renderJobDetail(job, container, onAction = apiPost) {
  container.textContent = "";
  if (!job) return;
  const stage = stageDefinition(job);
  container.appendChild(jobHero(job));
  container.appendChild(stagePanel(job, stage, onAction));
  container.appendChild(keyResult(job));
  container.appendChild(fitPanel(job));
  container.appendChild(classificationPanel(job));
  container.appendChild(projectPortfolioPanel(job));
  container.appendChild(packetPanel(job));
  container.appendChild(advancedDetails(job));
}

function jobHero(job) {
  const header = document.createElement("header");
  header.className = "detail-hero";
  header.appendChild(sectionKicker("SELECTED JOB"));
  const title = document.createElement("h2");
  title.textContent = displayValue(job.title, "Untitled job").toUpperCase();
  const meta = document.createElement("p");
  meta.textContent = [
    displayValue(job.company, "Unknown company"),
    displayValue(job.location),
  ].filter((value) => value !== "-").join(" / ");
  const source = actionLink("Open source", job.source_url || "#");
  source.className = "text-link";
  header.appendChild(title);
  header.appendChild(meta);
  header.appendChild(source);
  return header;
}

function stagePanel(job, stage, onAction) {
  const panel = document.createElement("section");
  panel.className = `stage-card panel state-${stage.visual}`;
  panel.appendChild(sectionKicker("CURRENT STAGE"));
  const title = document.createElement("h3");
  title.textContent = stage.title;
  const description = document.createElement("p");
  description.textContent = stageDescription(job, stage);
  panel.appendChild(title);
  panel.appendChild(description);
  panel.appendChild(stageProgress(deriveStage(job)));
  const action = nextActionForJob(job);
  if (action) panel.appendChild(primaryActionButton(job, action, onAction));
  return panel;
}

function stageDescription(job, stage) {
  if (deriveStage(job) === "classified" && job.selected_cv_family) {
    return `JobAgent selected ${familyLabel(job.selected_cv_family)} for this role.`;
  }
  if (deriveStage(job) === "ready" && job.selected_cv_family) {
    return `Your ${familyLabel(job.selected_cv_family)} CV packet is ready.`;
  }
  if (deriveStage(job) === "needs_review") {
    return classificationSummary(job) || stage.description;
  }
  return stage.description;
}

function stageProgress(currentStage) {
  const wrapper = document.createElement("ol");
  wrapper.className = "stage-steps";
  const currentIndex = progressIndex(currentStage);
  STAGE_ORDER.forEach((key, index) => {
    const item = document.createElement("li");
    const state = index < currentIndex ? "done" : index === currentIndex ? "current" : "waiting";
    item.className = `step step-${state}`;
    item.textContent = `${String(index + 1).padStart(2, "0")} ${STAGES[key].label}`;
    wrapper.appendChild(item);
  });
  return wrapper;
}

function progressIndex(stage) {
  if (stage === "needs_review") return 2;
  if (stage === "failed") return 0;
  const index = STAGE_ORDER.indexOf(stage);
  return index >= 0 ? index : 0;
}

function primaryActionButton(job, action, onAction) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button-primary";
  button.textContent = action.label;
  button.addEventListener("click", async () => {
    if (action.action === "open_packet" && job.packet) {
      window.open(`${API_BASE_URL}/api/packets/${job.packet.packet_id}/pdf`, "_blank", "noreferrer");
      notify("Packet opened");
      return;
    }
    if (action.action === "analyse") {
      await onAction("/api/workers/q1/run-once");
      notify("Analysis started");
      await loadJobs();
      return;
    }
    if (action.action === "generate") {
      await onAction(actionEndpoint(job.job_id, "generate"));
      notify("CV generation queued");
      await loadJobs();
      return;
    }
    if (action.action === "review") {
      await requestManualReview(job);
      notify("Review opened");
      return;
    }
    if (action.action === "retry") {
      await onAction(actionEndpoint(job.job_id, "retry"));
      notify("Retry queued");
      await loadJobs();
      return;
    }
    if (action.action === "restore_and_rescore") {
      await onAction(actionEndpoint(job.job_id, "restore_and_rescore"));
      notify("Re-score started");
      await loadJobs();
    }
  });
  return button;
}

function keyResult(job) {
  const panel = document.createElement("section");
  panel.className = "result-strip";
  panel.appendChild(resultItem("FIT SCORE", job.overall_score === null || job.overall_score === undefined ? "Pending" : `${job.overall_score} / 100`));
  panel.appendChild(resultItem("CV SELECTED", familyLabel(job.selected_cv_family)));
  panel.appendChild(resultItem("PACKET", packetStatusLabel(job)));
  return panel;
}

function resultItem(label, value) {
  const item = document.createElement("div");
  item.appendChild(mono(label));
  const strong = document.createElement("strong");
  strong.textContent = displayValue(value);
  item.appendChild(strong);
  return item;
}

function fitPanel(job) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("CANDIDATE FIT"));
  const score = document.createElement("p");
  score.className = "big-score";
  score.textContent = job.overall_score === null || job.overall_score === undefined
    ? "Pending"
    : `${job.overall_score} / 100`;
  panel.appendChild(score);
  panel.appendChild(note(displayValue(job.recommendation, "Waiting for analysis")));
  panel.appendChild(twoColumnLists("Strengths", job.strengths || [], "Gaps", job.gaps || []));
  panel.appendChild(detailsBlock("View scoring details", diagnosticsList(job)));
  return panel;
}

function classificationPanel(job) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("CV SELECTED"));
  const selected = document.createElement("h3");
  selected.textContent = familyLabel(job.selected_cv_family);
  panel.appendChild(selected);
  panel.appendChild(note(classificationSummary(job) || "CV selection will appear after analysis."));
  panel.appendChild(detailsBlock("View classification details", classificationDetails(job)));
  return panel;
}

function classificationSummary(job) {
  const decision = job.ui?.classification?.decision_label || "";
  if (decision.startsWith("Mixed role")) return `${decision}. ${semanticSummary(job)}`;
  if (job.selected_cv_family) return `${decision || "Clear match"}: ${familyLabel(job.selected_cv_family)}.`;
  return "";
}

function semanticSummary(job) {
  return job.ui?.semantic?.summary || "Rule-based signals explain the CV choice.";
}

function classificationDetails(job) {
  const wrapper = document.createElement("div");
  wrapper.appendChild(scoreBars(job.ui?.classification?.family_scores || {}, job.selected_cv_family, job.secondary_cv_family));
  wrapper.appendChild(detailsBlock("Rule-based signals", evidenceList(job.ui?.classification?.rule_evidence || [])));
  return wrapper;
}

function projectPortfolioPanel(job) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("PROJECT PORTFOLIO"));
  const decision = job.tailoring_decision?.decision || job.tailoring_decision || {};
  const inserted = decision.inserted_block;
  const removed = decision.removed_block;
  const base = decision.base_family || job.selected_cv_family;
  panel.appendChild(detailLine("Base CV", familyLabel(base)));
  if (inserted) {
    panel.appendChild(detailLine("Included", blockDisplayName(inserted, decision)));
    panel.appendChild(note(portfolioExplanation(decision, inserted)));
    panel.appendChild(detailLine("Replaced", blockDisplayName(removed, decision)));
  } else if (decision.tailoring_status === "review_required") {
    const recommendation = reviewablePortfolioCandidate(decision);
    panel.appendChild(detailLine("Recommendation", recommendation ? blockDisplayName(recommendation.block_id, decision) : "Review"));
    panel.appendChild(note(portfolioExplanation(decision, recommendation?.block_id)));
  } else {
    panel.appendChild(detailLine("Selection", "Master project set"));
    panel.appendChild(note("The approved project set remains unchanged."));
  }
  panel.appendChild(detailsBlock("View requirement coverage", requirementCoverageDetails(decision)));
  panel.appendChild(detailsBlock("View alternative portfolio", alternativePortfolioDetails(decision)));
  const reanalyse = document.createElement("button");
  reanalyse.type = "button";
  reanalyse.className = "button-secondary";
  reanalyse.textContent = "Re-analyse project selection";
  reanalyse.addEventListener("click", async () => {
    await apiPost(actionEndpoint(job.job_id, "reanalyze-project-selection"));
    notify("Project selection re-analysed");
    await loadJobs();
  });
  panel.appendChild(reanalyse);
  return panel;
}

function portfolioExplanation(decision, blockId) {
  if (!blockId) return displayValue(decision.reason, "Project selection needs review.");
  const capabilities = candidateCapabilities(decision, blockId);
  if (capabilities.includes("npu") || capabilities.includes("ml_accelerator")) {
    return "The base CV remains Machine Learning, but this role includes NPU or accelerator requirements that this approved project demonstrates.";
  }
  return displayValue(decision.reason, "This approved project improves requirement coverage for the role.");
}

function reviewablePortfolioCandidate(decision) {
  const candidates = decision.candidate_blocks || decision.scores?.candidate_blocks || [];
  return candidates.find((item) => item.shortlist_reason && item.requires_review) || null;
}

function candidateCapabilities(decision, blockId) {
  const scores = decision.project_portfolio?.candidate_scores || [];
  const match = scores.find((item) => item.block_id === blockId);
  return match ? match.distinctive_capabilities || [] : [];
}

function blockDisplayName(blockId, decision) {
  if (!blockId) return "Master unchanged";
  const candidates = [
    ...(decision.project_portfolio?.candidate_scores || []),
    ...(decision.candidate_blocks || []),
    ...(decision.scores?.candidate_blocks || []),
  ];
  const match = candidates.find((item) => item.block_id === blockId);
  return match?.display_name || blockId.replaceAll("_", " ");
}

function requirementCoverageDetails(decision) {
  const wrapper = document.createElement("div");
  const requirements = decision.requirement_analysis?.requirements || [];
  if (!requirements.length) {
    wrapper.appendChild(note("No requirement-aware project analysis was recorded for this job."));
    return wrapper;
  }
  const list = document.createElement("ul");
  for (const requirement of requirements.slice(0, 8)) {
    const li = document.createElement("li");
    li.textContent = `${requirement.evidence_quote}: ${requirement.normalized_capabilities.join(", ")} (${Math.round(Number(requirement.importance || 0) * 100)}%)`;
    list.appendChild(li);
  }
  wrapper.appendChild(list);
  return wrapper;
}

function alternativePortfolioDetails(decision) {
  const wrapper = document.createElement("div");
  const scores = decision.project_portfolio?.candidate_scores || [];
  if (!scores.length) {
    wrapper.appendChild(note("No alternative portfolio scores were recorded."));
    return wrapper;
  }
  const list = document.createElement("ul");
  for (const item of scores.slice(0, 6)) {
    const li = document.createElement("li");
    li.textContent = `${item.display_name || item.block_id}: ${Math.round(Number(item.score || 0) * 100)}% coverage`;
    list.appendChild(li);
  }
  wrapper.appendChild(list);
  return wrapper;
}

function packetPanel(job) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("CV PACKET"));
  panel.appendChild(detailLine("State", packetStatusLabel(job)));
  panel.appendChild(detailLine("CV family", familyLabel(job.ui?.packet?.selected_cv_family || job.selected_cv_family)));
  panel.appendChild(note(packetExplanation(job)));
  if (job.packet) {
    const links = document.createElement("div");
    links.className = "link-row";
    links.appendChild(actionLink("Open PDF", `${API_BASE_URL}/api/packets/${job.packet.packet_id}/pdf`));
    links.appendChild(actionLink("View packet details", `${API_BASE_URL}/api/packets/${job.packet.packet_id}/manifest`));
    panel.appendChild(links);
  }
  return panel;
}

function packetStatusLabel(job) {
  return job.ui?.packet?.status_label || displayValue(job.packet_status, "Not started");
}

function packetExplanation(job) {
  if (job.packet_status === "ready") return "Approved local CV content was used.";
  if (job.packet_status === "queued") return "Packet generation is queued.";
  if (job.packet_status === "generating") return "Packet generation is in progress.";
  if (job.packet_status === "failed") return "Your previous packet, if any, remains available.";
  return "No packet has been generated yet.";
}

function advancedDetails(job) {
  const wrapper = document.createElement("section");
  wrapper.className = "advanced-stack";
  wrapper.appendChild(semanticSection(job));
  wrapper.appendChild(analysisHistorySection(job));
  wrapper.appendChild(detailsBlock("Technical details", diagnosticsList(job)));
  wrapper.appendChild(destructiveDetails(job));
  return wrapper;
}

function analysisHistorySection(job) {
  const wrapper = detailsBlock("Previous analyses", document.createElement("div"));
  const content = wrapper.children[1];
  const runs = Array.isArray(job.analysis_runs) ? job.analysis_runs : [];
  if (!runs.length) {
    content.appendChild(note("No previous analyses recorded for this job."));
    return wrapper;
  }
  const list = document.createElement("ul");
  for (const run of runs.slice(0, 8)) {
    const li = document.createElement("li");
    const fit = run.candidate_fit?.overall_score === undefined || run.candidate_fit?.overall_score === null
      ? "Fit pending"
      : `Fit ${run.candidate_fit.overall_score}`;
    const family = familyLabel(run.family_classification?.selected_family);
    const semantic = semanticStatusLabel(run.semantic_requirements?.status || "not_attempted");
    const packet = run.packet_id ? "Packet linked" : "No packet";
    li.textContent = [
      displayDate(run.created_at),
      displayValue(run.trigger).replaceAll("_", " "),
      fit,
      family,
      semantic,
      packet,
    ].filter(Boolean).join(" / ");
    list.appendChild(li);
  }
  content.appendChild(list);
  return wrapper;
}

function semanticSection(job) {
  const semantic = job.ui?.semantic || {};
  const wrapper = detailsBlock("Semantic analysis", document.createElement("div"));
  const content = wrapper.children[1];
  content.appendChild(detailLine("Status", semanticStatusLabel(semantic.status)));
  if (semantic.model) {
    const latency = semantic.latency_ms ? ` / ${semantic.latency_ms} ms` : "";
    content.appendChild(detailLine("Model", `${semantic.model}${latency}`));
  }
  content.appendChild(note(semantic.summary || semanticFallbackText(semantic.status)));
  content.appendChild(detailsBlock("View semantic evidence", semanticEvidence(job)));
  return wrapper;
}

function semanticFallbackText(status) {
  if (status === "live_success") return "Live semantic evidence was used.";
  return "Rule-based classification was used instead.";
}

function semanticEvidence(job) {
  const wrapper = document.createElement("div");
  const assessment = job.score_breakdown?.hybrid?.semantic_assessment;
  const evidence = job.ui?.classification?.semantic_evidence || [];
  if (assessment?.grounded_reason) wrapper.appendChild(note(assessment.grounded_reason));
  if (assessment?.strengths) wrapper.appendChild(listBlock("Semantic strengths", assessment.strengths));
  if (evidence.length) wrapper.appendChild(evidenceList(evidence));
  if (!wrapper.children.length) wrapper.appendChild(note("No semantic evidence was recorded."));
  return wrapper;
}

function destructiveDetails(job) {
  const details = detailsBlock("Archive or delete", document.createElement("div"));
  const content = details.children[1];
  content.appendChild(note("Demo/test jobs are deleted. Real jobs are archived so audit records remain."));
  const button = document.createElement("button");
  button.type = "button";
  button.className = "button-danger";
  button.textContent = job.source_provenance === "demo" || job.source_provenance === "test"
    ? "Delete job"
    : "Archive job";
  button.addEventListener("click", async () => {
    const message = button.textContent === "Delete job"
      ? "Delete this demo/test job and linked records?"
      : "Archive this job and hide it from the active list?";
    if (!confirm(message)) return;
    await apiPost(actionEndpoint(job.job_id, "delete"));
    notify(button.textContent === "Delete job" ? "Job deleted" : "Job archived");
    await loadJobs();
  });
  content.appendChild(button);
  if (job.archived_at) {
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "button-secondary";
    restore.textContent = "Restore only";
    restore.addEventListener("click", async () => {
      await apiPost(actionEndpoint(job.job_id, "restore"));
      notify("Job restored");
      await loadJobs();
    });
    content.appendChild(restore);
  } else if (job.intake_status === "scored" || job.intake_status === "failed" || job.intake_status === "manual_review") {
    const rescore = document.createElement("button");
    rescore.type = "button";
    rescore.className = "button-secondary";
    rescore.textContent = "Re-score job";
    rescore.addEventListener("click", async () => {
      await apiPost(actionEndpoint(job.job_id, "rescore"));
      notify("Re-score started");
      await loadJobs();
    });
    content.appendChild(rescore);
  }
  return details;
}

function renderReviewQueue(reviews, container, onSelect = loadReviewDetail) {
  container.textContent = "";
  if (!reviews.length) {
    container.appendChild(emptyPanel("NO REVIEWS", "Nothing needs your attention."));
    return;
  }
  for (const review of reviews) {
    const card = document.createElement("article");
    card.className = "review-card panel";
    card.appendChild(sectionKicker(displayValue(review.status, "pending").toUpperCase()));
    const title = document.createElement("h3");
    title.textContent = displayValue(review.job?.title, "Untitled job");
    const company = document.createElement("p");
    company.textContent = displayValue(review.job?.company, "Unknown company");
    card.appendChild(title);
    card.appendChild(company);
    card.appendChild(note(reviewReason(review)));
    card.appendChild(detailLine("Recommendation", familyLabel(review.classification?.selected_family)));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button-primary";
    button.textContent = "Review";
    button.addEventListener("click", () => onSelect(review.review_id));
    card.appendChild(button);
    container.appendChild(card);
  }
}

function reviewReason(review) {
  const reason = displayValue(review.reason, "Needs review");
  if (reason.includes("hybrid")) return "The role combines more than one CV family.";
  if (reason.includes("close")) return "Two CV families scored closely.";
  if (reason.includes("low")) return "The role did not strongly match one CV family.";
  if (review.tailoring?.inserted_block) return "An approved project change needs your approval.";
  return reason.replaceAll("_", " ");
}

function renderReviewDetail(review, container, onResolve = submitReviewResolution) {
  state.reviewStep = 1;
  drawReviewDetail(review, container, onResolve);
}

function drawReviewDetail(review, container, onResolve = submitReviewResolution) {
  container.textContent = "";
  container.appendChild(sectionKicker("REVIEW"));
  const title = document.createElement("h2");
  title.textContent = displayValue(review.job?.title, "Untitled job");
  container.appendChild(title);
  container.appendChild(note(reviewReason(review)));
  container.appendChild(reviewStepIndicator(state.reviewStep));
  container.appendChild(reviewRecommendation(review));
  if (state.reviewStep >= 2) container.appendChild(reviewChangeStep(review));
  if (state.reviewStep >= 3) container.appendChild(reviewConfirmStep(review, onResolve));
}

function reviewStepIndicator(step) {
  const list = document.createElement("ol");
  list.className = "review-steps";
  ["Choose CV", "Project choice", "Confirm"].forEach((label, index) => {
    const item = document.createElement("li");
    item.className = index + 1 === step ? "current" : index + 1 < step ? "done" : "";
    item.textContent = `${index + 1} ${label}`;
    list.appendChild(item);
  });
  return list;
}

function reviewRecommendation(review) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("WHAT JOBAGENT RECOMMENDS"));
  panel.appendChild(detailLine("CV family", familyLabel(review.classification?.selected_family)));
  panel.appendChild(note(reviewReason(review)));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "button-secondary";
  next.textContent = "Continue";
  next.addEventListener("click", () => {
    state.reviewStep = 2;
    drawReviewDetail(review, document.querySelector("#review-detail"));
  });
  panel.appendChild(next);
  return panel;
}

function reviewChangeStep(review) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("WHAT WILL CHANGE"));
  panel.appendChild(detailLine("Current recommendation", familyLabel(review.classification?.selected_family)));
  panel.appendChild(detailLine("Project change", displayValue(review.tailoring?.inserted_block || "Master unchanged")));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "button-secondary";
  next.textContent = "Confirm decision";
  next.addEventListener("click", () => {
    state.reviewStep = 3;
    drawReviewDetail(review, document.querySelector("#review-detail"));
  });
  panel.appendChild(next);
  return panel;
}

function reviewConfirmStep(review, onResolve) {
  const panel = document.createElement("section");
  panel.className = "panel compact-section";
  panel.appendChild(sectionKicker("CONFIRM"));
  const actionSelect = document.createElement("select");
  actionSelect.setAttribute?.("aria-label", "Review action");
  for (const action of review.allowed_actions || []) {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = actionLabel(action);
    actionSelect.appendChild(option);
  }
  panel.appendChild(actionSelect);
  const family = familySelect("CV family");
  panel.appendChild(family.label);
  const replacement = replacementSelect(review);
  if (replacement.label) panel.appendChild(replacement.label);
  const noteLabel = document.createElement("label");
  noteLabel.textContent = "Review note";
  const textarea = document.createElement("textarea");
  textarea.maxLength = 500;
  textarea.rows = 3;
  noteLabel.appendChild(textarea);
  panel.appendChild(noteLabel);
  panel.appendChild(detailsBlock("Why", evidenceList(review.classification?.rule_evidence || [])));
  const save = document.createElement("button");
  save.type = "button";
  save.className = "button-primary";
  save.textContent = "Save review";
  save.addEventListener("click", async () => {
    const payload = buildResolutionPayload(actionSelect.value, {
      note: textarea.value,
      overrideFamily: family.select.value,
      replacementValue: replacement.select ? replacement.select.value : "",
    });
    if (packetChangingAction(payload) && !confirmReviewResolution()) return;
    await onResolve(review, payload);
  });
  panel.appendChild(save);
  return panel;
}

function renderWorkerStatus(data, container) {
  container.textContent = "";
  const cards = [
    ["API", "ONLINE"],
    ["SCORING WORKER", systemHealth(data, "q1")],
    ["PACKET WORKER", systemHealth(data, "q2")],
    ["REGENERATION", systemHealth(data, "regeneration")],
    ["SEMANTIC LLM", data.semantic_config?.enabled ? "ACTIVE" : "OFF"],
  ];
  for (const [label, value] of cards) {
    const card = document.createElement("article");
    card.className = "system-card panel";
    card.appendChild(mono(label));
    const strong = document.createElement("strong");
    strong.textContent = value;
    card.appendChild(strong);
    container.appendChild(card);
  }
  container.appendChild(detailsBlock("Queue diagnostics", queueDiagnostics(data)));
  container.appendChild(detailsBlock("Semantic provider", semanticConfigDetails(data)));
  container.appendChild(detailsBlock("Database and artifacts", databaseDetails(data)));
}

function systemHealth(data, type) {
  return displayValue(data.queue_health?.[type]?.health, "offline").toUpperCase();
}

function queueDiagnostics(data) {
  const wrapper = document.createElement("div");
  for (const type of ["q1", "q2", "regeneration"]) {
    const queue = data.queues?.[type] || {};
    wrapper.appendChild(detailLine(workerLabel(type), `Queued ${displayValue(queue.queued_count, "0")} / Processing ${displayValue(queue.processing_count, "0")} / Failed ${displayValue(queue.failed_count, "0")}`));
  }
  return wrapper;
}

function semanticConfigDetails(data) {
  const wrapper = document.createElement("div");
  wrapper.appendChild(detailLine("Provider", displayValue(data.semantic_config?.provider, "openai")));
  wrapper.appendChild(detailLine("Model", displayValue(data.semantic_config?.model)));
  wrapper.appendChild(detailLine("API key", data.semantic_config?.api_key_configured ? "Configured" : "Missing"));
  return wrapper;
}

function databaseDetails(data) {
  const wrapper = document.createElement("div");
  wrapper.appendChild(detailLine("Demo jobs", displayValue(data.database?.demo_cleanup?.job_count, "0")));
  wrapper.appendChild(note("Generated artifact paths are intentionally hidden in the normal interface."));
  return wrapper;
}

function workerLabel(type) {
  return { q1: "Scoring", q2: "Packet", regeneration: "Regeneration" }[type] || type;
}

function scoreBars(scores, selected, secondary) {
  const wrapper = document.createElement("div");
  wrapper.className = "score-bars";
  for (const family of FAMILY_IDS) {
    const score = Number(scores[family] || 0);
    const row = document.createElement("div");
    row.className = "score-row";
    row.appendChild(textSpan(`${familyLabel(family)}${family === selected ? " selected" : family === secondary ? " secondary" : ""}`));
    const bar = document.createElement("span");
    bar.className = "score-bar";
    const fill = document.createElement("span");
    fill.className = "score-fill";
    fill.style.width = `${Math.max(0, Math.min(100, score * 100))}%`;
    bar.appendChild(fill);
    row.appendChild(bar);
    row.appendChild(textSpan(`${Math.round(score * 100)}%`));
    wrapper.appendChild(row);
  }
  return wrapper;
}

function evidenceList(items) {
  const list = document.createElement("ul");
  if (!Array.isArray(items) || !items.length) {
    const li = document.createElement("li");
    li.textContent = "No evidence recorded.";
    list.appendChild(li);
    return list;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item.quote
      ? `"${item.quote}" -> ${familyLabel(item.family)}: ${displayValue(item.reason)}`
      : [familyLabel(item.family), displayValue(item.section), displayValue(item.phrase)].join(" / ");
    list.appendChild(li);
  }
  return list;
}

function diagnosticsList(job) {
  return listBlock("Technical metadata", [
    `Intake: ${displayValue(job.intake_status)}`,
    `Packet: ${displayValue(job.packet_status)}`,
    `Classifier: ${displayValue(job.family_classifier_version)}`,
    `Scoring mode: ${displayValue(job.scoring_mode)}`,
    `Semantic call: ${displayValue(job.llm_call_status)}`,
    `Provenance: ${displayValue(job.source_provenance)}`,
  ]);
}

function twoColumnLists(leftTitle, leftItems, rightTitle, rightItems) {
  const wrapper = document.createElement("div");
  wrapper.className = "two-list";
  wrapper.appendChild(listBlock(leftTitle, leftItems));
  wrapper.appendChild(listBlock(rightTitle, rightItems));
  return wrapper;
}

function detailsBlock(title, content) {
  const details = document.createElement("details");
  details.className = "disclosure";
  const summary = document.createElement("summary");
  summary.textContent = title;
  details.appendChild(summary);
  details.appendChild(content);
  return details;
}

function listBlock(title, items) {
  const wrapper = document.createElement("div");
  const h = document.createElement("h4");
  h.textContent = title;
  const ul = document.createElement("ul");
  const values = Array.isArray(items) && items.length ? items : ["None recorded."];
  for (const item of values) {
    const li = document.createElement("li");
    li.textContent = displayValue(item);
    ul.appendChild(li);
  }
  wrapper.appendChild(h);
  wrapper.appendChild(ul);
  return wrapper;
}

function emptyPanel(title, text) {
  const panel = document.createElement("section");
  panel.className = "panel empty-state";
  panel.appendChild(sectionKicker(title));
  panel.appendChild(note(text));
  return panel;
}

function detailLine(label, value) {
  const row = document.createElement("p");
  row.className = "detail-line";
  row.appendChild(mono(`${label}:`));
  const span = document.createElement("span");
  span.textContent = displayValue(value);
  row.appendChild(span);
  return row;
}

function sectionKicker(text) {
  const p = document.createElement("p");
  p.className = "section-kicker";
  p.textContent = text;
  return p;
}

function note(text) {
  const p = document.createElement("p");
  p.className = "help-text";
  p.textContent = displayValue(text);
  return p;
}

function mono(text) {
  const span = document.createElement("span");
  span.className = "mono";
  span.textContent = displayValue(text);
  return span;
}

function textSpan(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

function actionLink(label, href) {
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noreferrer";
  a.textContent = label;
  return a;
}

function inputValue(selector, fallback) {
  const element = document.querySelector(selector);
  return element && "value" in element ? element.value : fallback;
}

function displayDate(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function familySelect(labelText) {
  const label = document.createElement("label");
  label.textContent = labelText;
  const select = document.createElement("select");
  for (const family of FAMILY_IDS) {
    const option = document.createElement("option");
    option.value = family;
    option.textContent = FAMILY_LABELS[family];
    select.appendChild(option);
  }
  label.appendChild(select);
  return { label, select };
}

function replacementSelect(review) {
  const options = review.metadata?.replacement_options || [];
  if (!options.length) return { label: null, select: null };
  const label = document.createElement("label");
  label.textContent = "Approved replacement";
  const select = document.createElement("select");
  for (const option of options) {
    const item = document.createElement("option");
    item.value = `${option.base_family}|${option.removed_block}|${option.inserted_block}`;
    item.textContent = `${familyLabel(option.base_family)}: ${option.removed_name} -> ${option.inserted_name}`;
    select.appendChild(item);
  }
  label.appendChild(select);
  return { label, select };
}

function buildResolutionPayload(action, values) {
  const payload = { action, reviewer_id: REVIEWER_ID };
  if (values.note) payload.review_note = values.note.slice(0, 500);
  if (action === "override_family" || action === "use_master_unchanged") {
    if (!FAMILY_IDS.includes(values.overrideFamily)) {
      throw new Error("Choose one of the four registered families.");
    }
    payload.resolved_family = values.overrideFamily;
  }
  if (action === "select_approved_replacement") {
    const parts = String(values.replacementValue || "").split("|");
    if (parts.length !== 3) throw new Error("Choose an approved replacement.");
    payload.resolved_family = parts[0];
    payload.removed_block = parts[1];
    payload.inserted_block = parts[2];
  }
  return payload;
}

function actionLabel(action) {
  return {
    approve_classification: "Approve recommendation",
    override_family: "Choose another CV family",
    mark_out_of_scope: "Mark out of scope",
    defer: "Decide later",
    approve_tailoring: "Approve project change",
    use_master_unchanged: "Use master unchanged",
    select_approved_replacement: "Choose approved project swap",
    approve_order: "Approve project order",
    reject_tailoring: "Reject project change",
  }[action] || action;
}

function packetChangingAction(payload) {
  return [
    "override_family",
    "use_master_unchanged",
    "approve_tailoring",
    "select_approved_replacement",
    "approve_order",
    "reject_tailoring",
  ].includes(payload.action);
}

function confirmReviewResolution() {
  return confirm("Save this review? Packet-changing decisions may queue a reviewed packet.");
}

async function requestManualReview(job) {
  await createJobReview(job.job_id, { review_type: "classification", reason: "manual_review_requested" });
  switchView("reviews");
  await loadReviews();
}

async function submitReviewResolution(review, payload) {
  await resolveReview(review.review_id, payload);
  notify("Review saved");
  await loadReviews();
  await loadJobs();
}

async function loadJobs() {
  setStatus("#jobs-status", "LOADING");
  try {
    const payload = await fetchJobs();
    renderJobsPage(payload.jobs || []);
  } catch (error) {
    setStatus("#jobs-status", "API UNAVAILABLE");
    const detail = document.querySelector("#job-detail");
    if (detail) {
      detail.textContent = "";
      detail.appendChild(emptyPanel("API UNAVAILABLE", "Start the local JobAgent stack and refresh."));
    }
  }
}

async function loadReviews() {
  setStatus("#reviews-status", "LOADING");
  try {
    const payload = await fetchReviews(reviewFiltersFromDocument());
    state.reviews = payload.reviews || [];
    renderReviewQueue(state.reviews, document.querySelector("#reviews-list"));
    setStatus("#reviews-status", state.reviews.length ? `${state.reviews.length} REVIEW` : "NO REVIEWS");
  } catch (error) {
    setStatus("#reviews-status", "REVIEW API UNAVAILABLE");
  }
}

async function loadReviewDetail(reviewId) {
  const payload = await fetchReview(reviewId);
  renderReviewDetail(payload.review, document.querySelector("#review-detail"));
}

async function loadWorkers() {
  setStatus("#workers-status", "LOADING");
  try {
    const payload = await fetchWorkerStatus();
    state.workers = payload;
    renderWorkerStatus(payload, document.querySelector("#workers-list"));
    setStatus("#workers-status", "SYSTEM READY");
  } catch (error) {
    setStatus("#workers-status", "API UNAVAILABLE");
  }
}

function setStatus(selector, value) {
  const status = document.querySelector(selector);
  if (status) status.textContent = value;
}

function reviewFiltersFromDocument() {
  return {
    status: inputValue("#review-status-filter", "pending"),
    review_type: inputValue("#review-type-filter", ""),
    family: inputValue("#review-family-filter", ""),
  };
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((view) => {
    view.classList.toggle("is-active", view.id === `${name}-view`);
  });
  document.querySelectorAll(".nav-tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.view === name);
  });
  if (name === "reviews") loadReviews();
  if (name === "system") loadWorkers();
}

function notify(message) {
  state.message = message;
  const toast = document.querySelector("#app-message");
  if (toast) toast.textContent = message;
}

function bindDashboard() {
  document.querySelectorAll(".nav-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });
  document.querySelector("#refresh-all")?.addEventListener("click", () => {
    Promise.all([loadJobs(), loadReviews(), loadWorkers()]);
    notify("Refreshed");
  });
  document.querySelector("#add-job")?.addEventListener("click", () => {
    notify("Use the Chrome extension to add a job.");
  });
  document.querySelector("#job-filter")?.addEventListener("change", () => renderJobsPage(state.jobs));
  document.querySelector("#review-filters")?.addEventListener("submit", (event) => {
    event.preventDefault();
    loadReviews();
  });
  document.querySelector("#refresh-workers")?.addEventListener("click", loadWorkers);
  document.querySelector("#remove-demo-jobs")?.addEventListener("click", async () => {
    const preview = await apiRequest("/api/demo-jobs/preview");
    const count = preview.preview?.job_count || 0;
    if (!count) {
      notify("No demo jobs marked for removal");
      return;
    }
    if (!confirm(`Remove ${count} demo jobs? Real jobs are preserved.`)) return;
    await apiPost("/api/demo-jobs/clear");
    notify("Demo jobs removed");
    await loadJobs();
    await loadWorkers();
  });
}

if (typeof document !== "undefined" && document.addEventListener) {
  document.addEventListener("DOMContentLoaded", () => {
    bindDashboard();
    loadJobs();
  });
}

globalThis.JobAgentV2Dashboard = {
  displayValue,
  familyLabel,
  semanticStatusLabel,
  actionEndpoint,
  ownerHeaders,
  fetchJobs,
  fetchReviews,
  fetchWorkerStatus,
  resolveReview,
  createJobReview,
  renderJobsPage,
  renderJobDetail,
  renderReviewQueue,
  renderReviewDetail,
  renderWorkerStatus,
  buildResolutionPayload,
  filteredJobs,
  summaryItems,
  deriveStage,
  stageDefinition,
  nextActionForJob,
  stageProgress,
};
