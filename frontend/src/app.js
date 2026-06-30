const API_BASE_URL = "http://127.0.0.1:8765";
const OWNER_ID = "local";
const REVIEWER_ID = "local-user";

const FAMILY_LABELS = {
  digital_ic: "Digital IC / RTL",
  verification: "Verification / SoC Verification",
  software: "Software Engineering",
  ml: "Machine Learning Engineering",
};

const FAMILY_IDS = Object.keys(FAMILY_LABELS);

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

/**
 * @typedef {Object} ReviewListItem
 * @property {string} review_id
 * @property {string} job_id
 * @property {string} review_type
 * @property {string} status
 * @property {string} reason
 * @property {Object} classification
 * @property {Object} tailoring
 */

/**
 * @typedef {Object} ReviewResolutionRequest
 * @property {string} action
 * @property {string} reviewer_id
 * @property {string=} review_note
 * @property {string=} resolved_family
 * @property {string=} removed_block
 * @property {string=} inserted_block
 */

function ownerHeaders(extra = {}) {
  return { "X-JobAgent-Owner": OWNER_ID, ...extra };
}

async function apiRequest(path, options = {}, fetchImpl = fetch) {
  const headers = ownerHeaders(options.headers || {});
  const request = { ...options, headers };
  if (options.body && typeof options.body !== "string") {
    request.body = JSON.stringify(options.body);
    request.headers = ownerHeaders({ "Content-Type": "application/json", ...(options.headers || {}) });
  }
  const response = await fetchImpl(`${API_BASE_URL}${path}`, request);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
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
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return apiRequest(`/api/reviews${suffix}`, {}, fetchImpl);
}

async function fetchReview(reviewId, fetchImpl = fetch) {
  return apiRequest(`/api/reviews/${reviewId}`, {}, fetchImpl);
}

async function fetchWorkerStatus(fetchImpl = fetch) {
  return apiRequest("/api/workers/status", {}, fetchImpl);
}

async function resolveReview(reviewId, payload, fetchImpl = fetch) {
  return apiRequest(
    `/api/reviews/${reviewId}/resolve`,
    { method: "POST", body: payload },
    fetchImpl,
  );
}

async function createJobReview(jobId, payload, fetchImpl = fetch) {
  return apiRequest(
    `/api/jobs/${jobId}/reviews`,
    { method: "POST", body: payload },
    fetchImpl,
  );
}

function displayValue(value, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value);
}

function familyLabel(value, metadata = null) {
  const labels = metadata && metadata.families ? metadata.families : FAMILY_LABELS;
  return labels[value] || displayValue(value);
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

function buildReviewFamilyButton(job, onManualReview) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Review family selection";
  button.addEventListener("click", async () => {
    await onManualReview(job);
  });
  return button;
}

function renderJobs(jobs, tbody, onAction = apiPost, onManualReview = requestManualReview) {
  tbody.textContent = "";
  for (const job of jobs) {
    const row = document.createElement("tr");
    appendCell(row, displayValue(job.company));
    appendCell(row, displayValue(job.title));
    appendCell(row, displayValue(job.location));
    appendCell(row, displayValue(job.overall_score));
    appendCell(row, displayValue(job.recommendation));
    appendCell(row, displayValue(job.role_family));
    appendCell(row, familyLabel(job.selected_cv_family));
    appendCell(row, displayValue(job.scoring_mode));
    appendCell(row, job.starred ? "Starred" : displayValue(job.manual_priority, "Normal"));
    appendCell(row, displayValue(job.q2_eligibility));
    appendCell(row, intakeStatusLabel(job.intake_status));
    appendCell(row, displayValue(job.packet_status));
    appendCell(row, displayValue(job.promotion_reason));
    appendCell(row, packetSummary(job.packet));
    appendCell(row, reasonAndWarnings(job));
    appendSourceCell(row, job.source_url);
    appendActionsCell(row, job, onAction, onManualReview);
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

function appendActionsCell(row, job, onAction, onManualReview) {
  const cell = document.createElement("td");
  cell.appendChild(buildActionButton(job, "generate", "Generate now", onAction));
  cell.appendChild(
    buildActionButton(job, job.starred ? "unstar" : "star", job.starred ? "Unstar" : "Star", onAction),
  );
  if (job.intake_status === "scored") {
    cell.appendChild(buildActionButton(job, "rescore", "Rescore", onAction));
    cell.appendChild(buildReviewFamilyButton(job, onManualReview));
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
  if (packet.status === "ready" && packet.page_count > 1) return `Generated - requires fitting (${packet.page_count} pages)`;
  return `${packet.status} | ${packet.selected_cv_family || "-"} | ${packet.page_count || "?"} page(s)`;
}

function reasonAndWarnings(job) {
  const parts = [];
  if (job.reason) parts.push(job.reason);
  if (job.manual_review_reason) parts.push(job.manual_review_reason);
  if (job.failure_reason) parts.push(job.failure_reason);
  if (job.duplicate_warning) parts.push(job.duplicate_warning);
  if (Array.isArray(job.extraction_warnings) && job.extraction_warnings.length) {
    parts.push(`Warnings: ${job.extraction_warnings.join(", ")}`);
  }
  return parts.join(" | ") || "-";
}

function reviewFiltersFromDocument() {
  return {
    status: inputValue("#review-status-filter", "pending"),
    review_type: inputValue("#review-type-filter", ""),
    family: inputValue("#review-family-filter", ""),
  };
}

function inputValue(selector, fallback) {
  const element = document.querySelector(selector);
  return element && "value" in element ? element.value : fallback;
}

function renderReviewQueue(reviews, container, onSelect = loadReviewDetail) {
  container.textContent = "";
  if (!reviews.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No reviews match the current filters.";
    container.appendChild(empty);
    return;
  }
  const list = document.createElement("div");
  list.className = "review-cards";
  for (const review of reviews) {
    const article = document.createElement("article");
    article.className = "review-card";
    const title = document.createElement("h3");
    title.textContent = `${displayValue(review.job && review.job.title, "Untitled job")} - ${displayValue(review.job && review.job.company, "Unknown company")}`;
    article.appendChild(title);
    article.appendChild(detailLine("Type", displayValue(review.review_type)));
    article.appendChild(detailLine("Status", displayValue(review.status)));
    article.appendChild(detailLine("Reason", displayValue(review.reason)));
    article.appendChild(detailLine("Selected family", familyLabel(review.classification && review.classification.selected_family)));
    article.appendChild(detailLine("Secondary family", familyLabel(review.classification && review.classification.secondary_family)));
    article.appendChild(detailLine("Decision", displayValue(review.classification && review.classification.decision)));
    article.appendChild(detailLine("Tailoring", displayValue(review.tailoring && review.tailoring.status)));
    article.appendChild(detailLine("Created", displayValue(review.created_at)));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Review decision";
    button.addEventListener("click", () => onSelect(review.review_id));
    article.appendChild(button);
    list.appendChild(article);
  }
  container.appendChild(list);
}

function renderWorkerStatus(data, container) {
  container.textContent = "";
  const queues = data.queues || {};
  const health = data.queue_health || {};
  const workers = data.workers || [];
  for (const type of ["q1", "q2", "regeneration"]) {
    const card = document.createElement("article");
    card.className = "worker-card";
    const heading = document.createElement("h3");
    heading.textContent = workerLabel(type);
    card.appendChild(heading);
    const queue = queues[type] || {};
    const queueHealth = health[type] || {};
    const instances = workers.filter((worker) => worker.worker_type === type);
    card.appendChild(detailLine("State", displayValue(queueHealth.health, "offline")));
    card.appendChild(detailLine("Queued", displayValue(queue.queued_count, "0")));
    card.appendChild(detailLine("Processing", displayValue(queue.processing_count, "0")));
    card.appendChild(detailLine("Failed", displayValue(queue.failed_count, "0")));
    card.appendChild(detailLine("Oldest queued age", secondsLabel(queueHealth.oldest_queued_age_seconds)));
    card.appendChild(detailLine("Healthy workers", displayValue(queueHealth.healthy_worker_count, "0")));
    const active = instances.find((worker) => worker.current_job_id);
    card.appendChild(detailLine("Current job", active ? active.current_job_id : "-"));
    const latest = instances[0] || {};
    card.appendChild(detailLine("Last success", displayValue(latest.last_success_at)));
    card.appendChild(detailLine("Last failure", displayValue(latest.last_failure_at)));
    const warnings = queueHealth.warnings || [];
    card.appendChild(detailLine("Warnings", warnings.length ? warnings.join(", ") : "-"));
    container.appendChild(card);
  }
}

function workerLabel(type) {
  return {
    q1: "Queue 1",
    q2: "Queue 2",
    regeneration: "Regeneration",
  }[type] || displayValue(type);
}

function secondsLabel(value) {
  if (value === null || value === undefined) return "-";
  const seconds = Math.round(Number(value));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function renderReviewDetail(review, container, onResolve = submitReviewResolution) {
  container.textContent = "";
  const heading = document.createElement("h3");
  heading.textContent = `Review ${review.review_id}`;
  container.appendChild(heading);
  container.appendChild(detailLine("Job", `${displayValue(review.job && review.job.title)} at ${displayValue(review.job && review.job.company)}`));
  container.appendChild(detailLine("Status", displayValue(review.status)));
  container.appendChild(detailLine("Reason", displayValue(review.reason)));
  renderClassification(review, container);
  renderTailoring(review, container);
  renderImmutableNotice(container);
  if (review.status === "pending") {
    renderReviewActions(review, container, onResolve);
  } else {
    renderResolutionHistory(review, container);
  }
}

function renderClassification(review, container) {
  const classification = review.classification;
  const section = document.createElement("section");
  section.className = "review-subsection";
  const heading = document.createElement("h4");
  heading.textContent = "Automated classification";
  section.appendChild(heading);
  if (!classification) {
    const missing = document.createElement("p");
    missing.textContent = "No classification audit record is available for this review.";
    section.appendChild(missing);
    container.appendChild(section);
    return;
  }
  section.appendChild(detailLine("Selected family", familyLabel(classification.selected_family, review.metadata)));
  section.appendChild(detailLine("Secondary family", familyLabel(classification.secondary_family, review.metadata)));
  section.appendChild(detailLine("Decision category", displayValue(classification.decision)));
  section.appendChild(detailLine("Confidence", displayValue(classification.confidence)));
  section.appendChild(detailLine("Requires review", classification.requires_review ? "Yes" : "No"));
  section.appendChild(detailLine("Classifier version", displayValue(classification.classifier_version)));
  section.appendChild(detailLine("Config version", displayValue(classification.config_version)));
  section.appendChild(scoreBars(classification.family_scores || {}, classification.selected_family, classification.secondary_family, review.metadata));
  const note = document.createElement("p");
  note.className = "help-text";
  note.textContent = "These scores classify the type of role; they do not represent your overall fit for the position.";
  section.appendChild(note);
  section.appendChild(evidenceList("Deterministic evidence", classification.rule_evidence));
  section.appendChild(evidenceList("Semantic evidence", classification.semantic_evidence, "No semantic evidence was recorded; deterministic classification was used."));
  container.appendChild(section);
}

function scoreBars(scores, selected, secondary, metadata) {
  const wrapper = document.createElement("div");
  wrapper.className = "score-bars";
  for (const family of FAMILY_IDS) {
    const score = Number(scores[family] || 0);
    const row = document.createElement("div");
    row.className = "score-row";
    const label = document.createElement("span");
    const tags = [];
    if (family === selected) tags.push("selected");
    if (family === secondary) tags.push("secondary");
    label.textContent = `${familyLabel(family, metadata)}${tags.length ? ` (${tags.join(", ")})` : ""}`;
    const bar = document.createElement("span");
    bar.className = "score-bar";
    const fill = document.createElement("span");
    fill.className = "score-fill";
    fill.style.width = `${Math.max(0, Math.min(100, score * 100))}%`;
    bar.appendChild(fill);
    const value = document.createElement("span");
    value.textContent = `${score.toFixed(3)} (${Math.round(score * 100)}%)`;
    row.appendChild(label);
    row.appendChild(bar);
    row.appendChild(value);
    wrapper.appendChild(row);
  }
  return wrapper;
}

function evidenceList(title, items, emptyText = "No evidence recorded.") {
  const wrapper = document.createElement("div");
  const heading = document.createElement("h5");
  heading.textContent = title;
  wrapper.appendChild(heading);
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("p");
    empty.className = "help-text";
    empty.textContent = emptyText;
    wrapper.appendChild(empty);
    return wrapper;
  }
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = [
      displayValue(item.family),
      displayValue(item.section),
      displayValue(item.phrase),
      displayValue(item.polarity),
    ].join(" | ");
    list.appendChild(li);
  }
  wrapper.appendChild(list);
  return wrapper;
}

function renderTailoring(review, container) {
  const tailoring = review.tailoring;
  const section = document.createElement("section");
  section.className = "review-subsection";
  const heading = document.createElement("h4");
  heading.textContent = "Automated tailoring";
  section.appendChild(heading);
  if (!tailoring) {
    const missing = document.createElement("p");
    missing.textContent = "No tailoring decision is available for this review.";
    section.appendChild(missing);
    container.appendChild(section);
    return;
  }
  section.appendChild(detailLine("Base family", familyLabel(tailoring.base_family, review.metadata)));
  section.appendChild(detailLine("Status", displayValue(tailoring.tailoring_status || tailoring.status)));
  section.appendChild(detailLine("Removed block", blockLabel(review, tailoring.removed_block)));
  section.appendChild(detailLine("Inserted block", blockLabel(review, tailoring.inserted_block)));
  section.appendChild(detailLine("Replacement gain", displayValue(tailoring.replacement_gain)));
  section.appendChild(detailLine("Fallback reason", displayValue(tailoring.fallback_reason)));
  section.appendChild(detailLine("Policy version", displayValue(tailoring.policy_version)));
  section.appendChild(detailLine("Registry version", displayValue(tailoring.registry_version)));
  section.appendChild(blockList("Original projects", tailoring.base_blocks || [], review));
  section.appendChild(blockList("Final project order", tailoring.final_blocks || [], review));
  container.appendChild(section);
}

function blockLabel(review, blockId) {
  if (!blockId) return "-";
  const block = review.metadata && review.metadata.project_blocks
    ? review.metadata.project_blocks[blockId]
    : null;
  return block ? `${block.display_name} (${blockId})` : blockId;
}

function blockList(title, blockIds, review) {
  const wrapper = document.createElement("div");
  const heading = document.createElement("h5");
  heading.textContent = title;
  wrapper.appendChild(heading);
  const list = document.createElement("ol");
  for (const blockId of blockIds) {
    const li = document.createElement("li");
    const block = review.metadata && review.metadata.project_blocks
      ? review.metadata.project_blocks[blockId]
      : null;
    li.textContent = block
      ? `${block.display_name} (${block.family}) - ${block.preview}`
      : blockId;
    list.appendChild(li);
  }
  wrapper.appendChild(list);
  return wrapper;
}

function renderImmutableNotice(container) {
  const notice = document.createElement("p");
  notice.className = "immutable-notice";
  notice.textContent = "Immutable content guarantee: Education and Experience will not change. Skills remain fixed for the chosen family. Only approved whole-project blocks can change, and bullet text cannot be edited.";
  container.appendChild(notice);
}

function renderReviewActions(review, container, onResolve) {
  const section = document.createElement("section");
  section.className = "review-actions";
  const heading = document.createElement("h4");
  heading.textContent = "Resolve review";
  section.appendChild(heading);

  const noteLabel = document.createElement("label");
  noteLabel.textContent = "Review note";
  const note = document.createElement("textarea");
  note.maxLength = 500;
  note.rows = 3;
  noteLabel.appendChild(note);
  section.appendChild(noteLabel);

  const overrideFamily = familySelect("Override family");
  section.appendChild(overrideFamily.label);

  const replacement = replacementSelect(review);
  if (replacement.label) section.appendChild(replacement.label);

  const actions = document.createElement("div");
  actions.className = "action-row";
  for (const action of review.allowed_actions || []) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = actionLabel(action);
    button.addEventListener("click", async () => {
      const payload = buildResolutionPayload(action, {
        note: note.value,
        overrideFamily: overrideFamily.select.value,
        replacementValue: replacement.select ? replacement.select.value : "",
      });
      if (packetChangingAction(payload) && !confirmReviewResolution(review, payload)) {
        return;
      }
      await onResolve(review, payload);
    });
    actions.appendChild(button);
  }
  section.appendChild(actions);
  container.appendChild(section);
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
  const options = (review.metadata && review.metadata.replacement_options) || [];
  if (!options.length) return { label: null, select: null };
  const label = document.createElement("label");
  label.textContent = "Approved replacement";
  const select = document.createElement("select");
  for (const option of options) {
    const item = document.createElement("option");
    item.value = `${option.base_family}|${option.removed_block}|${option.inserted_block}`;
    item.textContent = `${familyLabel(option.base_family, review.metadata)}: ${option.removed_name} -> ${option.inserted_name}: ${displayValue(option.reason)}`;
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
    const parts = values.replacementValue ? values.replacementValue.split("|") : [];
    if (parts.length !== 3) {
      throw new Error("Choose an approved compatible replacement.");
    }
    const [baseFamily, removed, inserted] = parts;
    if (!FAMILY_IDS.includes(baseFamily)) {
      throw new Error("Choose one of the four registered families.");
    }
    payload.resolved_family = baseFamily;
    payload.removed_block = removed;
    payload.inserted_block = inserted;
  }
  return payload;
}

function packetChangingAction(payload) {
  return ["override_family", "use_master_unchanged", "select_approved_replacement", "reject_tailoring"].includes(payload.action);
}

function confirmReviewResolution(review, payload) {
  if (typeof confirm !== "function") return true;
  const classification = review.classification || {};
  const originalFamily = familyLabel(classification.selected_family || (review.tailoring && review.tailoring.base_family), review.metadata);
  const resolvedFamily = familyLabel(payload.resolved_family || classification.selected_family, review.metadata);
  return confirm(
    `Resolve review?\nOriginal family: ${originalFamily}\nResolved family: ${resolvedFamily}\nRegeneration will be queued when packet output changes.\nImmutable sections remain unchanged.`,
  );
}

function actionLabel(action) {
  return {
    approve_classification: "Approve selected family",
    override_family: "Override family",
    mark_out_of_scope: "Mark out of scope",
    defer: "Defer",
    approve_tailoring: "Approve current substitution",
    use_master_unchanged: "Use master CV unchanged",
    select_approved_replacement: "Select approved replacement",
    approve_order: "Approve project order",
    reject_tailoring: "Reject tailoring",
  }[action] || action;
}

function renderResolutionHistory(review, container) {
  const section = document.createElement("section");
  section.className = "resolution-history";
  const heading = document.createElement("h4");
  heading.textContent = "Resolution history";
  section.appendChild(heading);
  const history = review.history || [];
  if (!history.length) {
    const empty = document.createElement("p");
    empty.textContent = "No resolution history recorded.";
    section.appendChild(empty);
  }
  for (const item of history) {
    const wrapper = document.createElement("div");
    wrapper.className = "resolution-item";
    wrapper.appendChild(detailLine("Decision", `${item.action} by ${item.reviewer_id}`));
    wrapper.appendChild(detailLine("Regeneration", regenerationStatusLabel(item.regeneration_status)));
    if (item.attempt_count) {
      wrapper.appendChild(detailLine("Attempts", item.attempt_count));
    }
    if (item.queued_at) wrapper.appendChild(detailLine("Queued", item.queued_at));
    if (item.started_at) wrapper.appendChild(detailLine("Started", item.started_at));
    if (item.completed_at) wrapper.appendChild(detailLine("Completed", item.completed_at));
    if (item.failure_reason) {
      wrapper.appendChild(detailLine("Failure", item.failure_reason));
    }
    if (item.source_packet_id) {
      wrapper.appendChild(packetLinkLine("Previous packet", item.source_packet_id));
    }
    if (item.regeneration_packet_id) {
      wrapper.appendChild(packetLinkLine("Reviewed packet", item.regeneration_packet_id));
    }
    wrapper.appendChild(detailLine("Note", displayValue(item.review_note, "No note")));
    section.appendChild(wrapper);
  }
  container.appendChild(section);
}

function regenerationStatusLabel(status) {
  if (status === "queued") {
    return "Queued - waiting for the regeneration worker.";
  }
  if (status === "not_required") return "Not required";
  if (status === "processing") return "Processing - reviewed packet is being generated.";
  if (status === "complete") return "Complete - reviewed packet is available.";
  if (status === "failed" || status === "regeneration_failed") {
    return "Failed - previous valid packet remains available.";
  }
  return displayValue(status, "Unknown");
}

function packetLinkLine(label, packetId) {
  const row = document.createElement("p");
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  row.appendChild(strong);
  const link = document.createElement("a");
  link.href = `${API_BASE_URL}/api/packets/${packetId}/pdf`;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = packetId;
  row.appendChild(link);
  return row;
}

function detailLine(label, value) {
  const row = document.createElement("p");
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  row.appendChild(strong);
  const span = document.createElement("span");
  span.textContent = displayValue(value);
  row.appendChild(span);
  return row;
}

async function refreshDashboard() {
  const tbody = document.querySelector("#jobs-body");
  if (!tbody) return;
  const data = await fetchJobs();
  renderJobs(data.jobs, tbody, async (endpoint) => {
    await apiPost(endpoint);
    await refreshDashboard();
  }, requestManualReview);
}

async function refreshReviews() {
  const list = document.querySelector("#reviews-list");
  const status = document.querySelector("#reviews-status");
  if (!list) return;
  setStatus(status, "Loading reviews...");
  try {
    const data = await fetchReviews(reviewFiltersFromDocument());
    renderReviewQueue(data.reviews || [], list, loadReviewDetail);
    setStatus(status, data.reviews && data.reviews.length ? `${data.reviews.length} review(s)` : "No reviews match the current filters.");
  } catch (error) {
    list.textContent = "";
    setStatus(status, `Review API unavailable: ${error.message || error}`);
  }
}

async function refreshWorkers() {
  const container = document.querySelector("#workers-list");
  const status = document.querySelector("#workers-status");
  if (!container) return;
  setStatus(status, "Loading worker status...");
  try {
    const data = await fetchWorkerStatus();
    renderWorkerStatus(data, container);
    setStatus(status, "Worker status loaded.");
  } catch (error) {
    container.textContent = "";
    setStatus(status, `Worker status unavailable: ${error.message || error}`);
  }
}

async function loadReviewDetail(reviewId) {
  const container = document.querySelector("#review-detail");
  const status = document.querySelector("#reviews-status");
  if (!container) return;
  setStatus(status, "Loading review detail...");
  try {
    const data = await fetchReview(reviewId);
    renderReviewDetail(data.review, container, submitReviewResolution);
    setStatus(status, "Review detail loaded.");
  } catch (error) {
    container.textContent = "";
    setStatus(status, `Review not found or unavailable: ${error.message || error}`);
  }
}

async function submitReviewResolution(review, payload) {
  const status = document.querySelector("#reviews-status");
  try {
    const data = await resolveReview(review.review_id, payload);
    renderReviewDetail(data.review, document.querySelector("#review-detail"), submitReviewResolution);
    await refreshReviews();
    setStatus(status, `Review resolved. ${regenerationStatusLabel(data.review.resolution && data.review.resolution.regeneration_status)}`);
  } catch (error) {
    setStatus(status, `Review validation failed: ${error.message || error}`);
  }
}

async function requestManualReview(job) {
  const status = document.querySelector("#reviews-status");
  try {
    const data = await createJobReview(job.job_id, {
      review_type: "classification",
      reason: "wrong_family_reported",
    });
    renderReviewDetail(data.review, document.querySelector("#review-detail"), submitReviewResolution);
    await refreshReviews();
    setStatus(status, "Family review opened.");
  } catch (error) {
    setStatus(status, `Could not open family review: ${error.message || error}`);
  }
}

function setStatus(element, message) {
  if (element) element.textContent = message;
}

function bindIntakeQueueAction() {
  const button = document.querySelector("#process-intake-queue");
  if (!button) return;
  button.addEventListener("click", async () => {
    await apiPost("/api/workers/q1/run-once");
    await refreshDashboard();
    await refreshReviews();
  });
}

function bindReviewFilters() {
  const form = document.querySelector("#review-filters");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await refreshReviews();
  });
}

function bindWorkerRefresh() {
  const button = document.querySelector("#refresh-workers");
  if (!button) return;
  button.addEventListener("click", async () => {
    await refreshWorkers();
  });
}

if (typeof document !== "undefined") {
  bindIntakeQueueAction();
  bindReviewFilters();
  bindWorkerRefresh();
  refreshDashboard().catch((error) => {
    const tbody = document.querySelector("#jobs-body");
    if (tbody) tbody.textContent = String(error.message || error);
  });
  refreshReviews().catch((error) => {
    const status = document.querySelector("#reviews-status");
    setStatus(status, String(error.message || error));
  });
  refreshWorkers().catch((error) => {
    const status = document.querySelector("#workers-status");
    setStatus(status, String(error.message || error));
  });
}

globalThis.JobAgentV2Dashboard = {
  API_BASE_URL,
  DASHBOARD_COLUMNS,
  FAMILY_IDS,
  actionEndpoint,
  apiRequest,
  bindIntakeQueueAction,
  buildResolutionPayload,
  createJobReview,
  displayValue,
  fetchReview,
  fetchReviews,
  fetchWorkerStatus,
  intakeStatusLabel,
  ownerHeaders,
  packetSummary,
  reasonAndWarnings,
  regenerationStatusLabel,
  renderJobs,
  renderReviewDetail,
  renderReviewQueue,
  renderWorkerStatus,
  resolveReview,
  secondsLabel,
};
