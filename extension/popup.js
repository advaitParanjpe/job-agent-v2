const API_BASE_URL = "http://127.0.0.1:8765";

function cleanVisibleText(text) {
  return String(text || "")
    .replace(/\s+/g, " ")
    .trim();
}

function detectSourceSite(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function buildCapturePayload(tab, visibleText, capturedAt = new Date().toISOString()) {
  return {
    url: tab.url || "",
    page_title: tab.title || "",
    visible_text: cleanVisibleText(visibleText),
    source_site: detectSourceSite(tab.url || ""),
    captured_at: capturedAt,
  };
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs.length) {
    throw new Error("No active tab");
  }
  return tabs[0];
}

async function captureVisibleText(tabId) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => document.body?.innerText || "",
  });
  return result?.result || "";
}

async function submitCapture(payload, fetchImpl = fetch) {
  const response = await fetchImpl(`${API_BASE_URL}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function outcomeLabel(result) {
  if (result.duplicate) {
    return "Already queued";
  }
  return "Added to queue";
}

async function addCurrentPageToQueue() {
  const status = document.querySelector("#status");
  const button = document.querySelector("#add-to-queue");
  try {
    if (button) {
      button.disabled = true;
    }
    if (status) {
      status.textContent = "Adding...";
    }
    const tab = await getActiveTab();
    const visibleText = await captureVisibleText(tab.id);
    const payload = buildCapturePayload(tab, visibleText);
    const result = await submitCapture(payload);
    if (status) {
      status.textContent = outcomeLabel(result);
    }
  } catch (error) {
    if (status) {
      const message = String(error?.message || "");
      status.textContent = message.includes("Failed to fetch")
        ? "Backend unavailable"
        : "Request failed";
    }
  } finally {
    if (button) {
      button.disabled = false;
    }
  }
}

const button = document.querySelector("#add-to-queue");
if (button) {
  button.addEventListener("click", addCurrentPageToQueue);
}

globalThis.JobAgentV2Extension = {
  buildCapturePayload,
  cleanVisibleText,
  detectSourceSite,
  outcomeLabel,
};
