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

function buildCapturePayload(
  tab,
  visibleText,
  capturedAt = new Date().toISOString(),
  evidence = {},
) {
  return {
    url: tab.url || "",
    page_title: tab.title || "",
    visible_text: cleanVisibleText(visibleText),
    source_site: detectSourceSite(tab.url || ""),
    captured_at: capturedAt,
    evidence,
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
    func: () => {
      function clean(value) {
        return String(value || "")
          .replace(/\s+/g, " ")
          .trim();
      }

      function text(selector) {
        const element = document.querySelector(selector);
        return clean(element?.innerText || element?.textContent || "");
      }

      function many(selectors) {
        const out = [];
        for (const selector of selectors) {
          document.querySelectorAll(selector).forEach((element) => {
            const value = clean(element.innerText || element.textContent || "");
            if (value && !out.includes(value)) {
              out.push(value);
            }
          });
        }
        return out.slice(0, 12);
      }

      function meta() {
        const out = {};
        document.querySelectorAll("meta").forEach((element) => {
          const key = element.getAttribute("property") || element.getAttribute("name");
          const content = clean(element.getAttribute("content") || "");
          if (key && content) {
            out[key] = content;
          }
        });
        return out;
      }

      function jsonLdJobPostings() {
        const out = [];
        const stack = [];
        document.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
          try {
            const parsed = JSON.parse(script.textContent || "null");
            if (Array.isArray(parsed)) {
              stack.push(...parsed);
            } else if (parsed) {
              stack.push(parsed);
            }
          } catch {
            // Ignore malformed JSON-LD but keep capture deterministic.
          }
        });
        while (stack.length) {
          const node = stack.shift();
          if (!node || typeof node !== "object") {
            continue;
          }
          if (Array.isArray(node["@graph"])) {
            stack.push(...node["@graph"]);
          }
          const rawType = node["@type"];
          const types = Array.isArray(rawType) ? rawType : [rawType];
          if (types.map((type) => String(type).toLowerCase()).includes("jobposting")) {
            out.push(node);
          }
        }
        return out.slice(0, 5);
      }

      function detectedSite() {
        const host = window.location.hostname.toLowerCase();
        const href = window.location.href.toLowerCase();
        if (host.includes("greenhouse.io") || href.includes("greenhouse.io")) return "greenhouse";
        if (host.includes("lever.co") || href.includes("lever.co")) return "lever";
        if (host.includes("myworkdayjobs.com") || href.includes("workdayjobs.com")) {
          return "workday";
        }
        if (host.includes("linkedin.com")) return "linkedin";
        if (host.includes("ashbyhq.com")) return "ashby";
        if (host.includes("smartrecruiters.com")) return "smartrecruiters";
        return "generic";
      }

      const visibleText = document.body?.innerText || "";
      const titleSelectors = [
        "h1",
        "[data-testid='job-title']",
        "[data-automation-id='jobPostingHeader']",
        "[data-automation-id='jobTitle']",
        ".posting-headline h2",
        ".job-title",
      ];
      const companySelectors = [
        "[data-testid='company-name']",
        "[data-automation-id='company']",
        "[data-automation-id='jobCompany']",
        ".company-name",
        ".posting-company",
      ];
      const locationSelectors = [
        "[data-testid='job-location']",
        "[data-automation-id='locations']",
        "[data-automation-id='location']",
        ".location",
        ".job-location",
        ".posting-categories .location",
      ];
      const descriptionSelectors = [
        "[data-automation-id='jobPostingDescription']",
        ".job__description",
        ".job-description",
        "#job-description",
        ".posting-page",
        ".ashby-job-posting-content",
        "main",
      ];

      return {
        visible_text: visibleText,
        evidence: {
          document_title: document.title || "",
          detected_site: detectedSite(),
          json_ld_job_postings: jsonLdJobPostings(),
          meta: meta(),
          headings: many(["h1", "h2"]).slice(0, 16),
          likely_title_elements: many(titleSelectors),
          likely_company_elements: many(companySelectors),
          likely_location_elements: many(locationSelectors),
          likely_description_elements: many(descriptionSelectors),
          diagnostics: {
            url: window.location.href,
            visible_text_length: visibleText.length,
            json_ld_count: jsonLdJobPostings().length,
          },
        },
      };
    },
  });
  return result?.result || { visible_text: "", evidence: {} };
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
  const labels = {
    created: "Added to queue",
    existing_active: "Already being analysed",
    existing_complete: "Already exists",
    existing_archived: "Found in archive",
    existing_failed: "Previous analysis failed",
    restored_and_rescore_started: "Re-score started",
  };
  if (result.outcome && labels[result.outcome]) {
    return labels[result.outcome];
  }
  if (result.duplicate) {
    return "Already exists";
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
    const capture = await captureVisibleText(tab.id);
    const payload = buildCapturePayload(tab, capture.visible_text, undefined, capture.evidence);
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
