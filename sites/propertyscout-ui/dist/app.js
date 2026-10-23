const form = document.querySelector("#search-form");
const submitButton = document.querySelector("#submit-button");
const errorBox = document.querySelector("#form-error");
const resultsSection = document.querySelector("#results");
const resultGrid = document.querySelector("#result-grid");
const resultCount = document.querySelector("#result-count");

const dealGrid = document.querySelector("#deal-grid");
const dealCount = document.querySelector("#deal-count");
const dashboardSection = document.querySelector("#dashboard");
const dashboardEmpty = document.querySelector("#dashboard-empty");
const refreshButton = document.querySelector("#refresh-deals");

const cleanOptionalNumber = (data, name) => {
  const value = data.get(name);
  return value === "" ? null : Number(value);
};

function requestFromForm() {
  const data = new FormData(form);
  const list = (name) => data.get(name).split(",").map((item) => item.trim()).filter(Boolean);
  return {
    city: data.get("city").trim(),
    postal_code: data.get("postal_code").trim() || null,
    minimum_rooms: cleanOptionalNumber(data, "minimum_rooms"),
    minimum_size_sqm: cleanOptionalNumber(data, "minimum_size_sqm"),
    maximum_price: Number(data.get("maximum_price")),
    property_type: data.get("property_type"),
    minimum_gross_yield_percent: cleanOptionalNumber(data, "minimum_gross_yield_percent"),
    strategy: data.get("strategy"),
    required_features: list("required_features"),
    excluded_features: list("excluded_features"),
  };
}

const humanize = (value = "in progress") => value.replaceAll("_", " ");

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));

const STATUS_META = {
  waiting_human: { label: "Needs your approval", cls: "waiting" },
  running: { label: "In progress", cls: "running" },
  completed: { label: "Completed", cls: "done" },
  rejected: { label: "Rejected", cls: "rejected" },
  needs_research: { label: "Needs research", cls: "research" },
  awaiting_followup: { label: "Dormant · awaiting follow-up", cls: "dormant" },
  failed: { label: "Failed", cls: "failed" },
  unknown: { label: "Needs review", cls: "unknown" },
};

const STATUS_PRIORITY = {
  waiting_human: 0,
  running: 1,
  needs_research: 2,
  awaiting_followup: 3,
  unknown: 3,
  completed: 4,
  rejected: 5,
  failed: 6,
};

const STEPS = ["Scout", "Analyse", "Approve", "Contact", "Outreach", "Schedule"];

const STAGE_TO_STEP = {
  initialized: 0,
  discovery: 0,
  analysis: 1,
  awaiting_shortlist_approval: 2,
  contact_research: 2,
  awaiting_contact_resolution: 2,
  outreach_drafting: 3,
  awaiting_outreach_approval: 3,
  awaiting_reply: 4,
  scheduling: 4,
  meeting_preparation: 5,
  complete: 6,
  failed: 0,
};

const readError = async (response) => {
  try {
    const body = await response.json();
    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg).join("; ");
    }
    return typeof body.detail === "string" ? body.detail : response.statusText;
  } catch {
    return response.statusText;
  }
};

const percent = (value) => (value == null ? "—" : `${(value * 100).toFixed(1)}%`);
const euros = (money) => (money ? `${money.currency} ${money.amount.toLocaleString()}` : "—");

function stageTracker(stage) {
  const activeIndex = STAGE_TO_STEP[stage] ?? 0;
  const items = STEPS.map((name, index) => {
    const cls = index < activeIndex ? "done" : index === activeIndex ? "active" : "";
    return `<li class="${cls}"><span class="stage-dot" aria-hidden="true"></span><small>${name}</small></li>`;
  });
  return `<ol class="stage-tracker" aria-label="Workflow progress">${items.join("")}</ol>`;
}

const propertyMetrics = (property) => `
  <div class="metric">
    <span>${property.room_count ?? "—"} rooms · ${property.living_area_sqm ?? "—"} m²</span>
    <span>${euros(property.asking_price)}</span>
  </div>`;

const missingDataPanel = (analysis, status) =>
  status === "needs_research" && analysis.missing_critical_data?.length
    ? `<div class="approval-panel diagnostic"><strong>Missing critical data</strong><p>${escapeHtml(analysis.missing_critical_data.map(humanize).join(", "))}</p></div>`
    : "";

const valuationPanel = (state) => {
  const valuation = state.analysis?.valuation;
  if (!valuation) return "";
  const gap = valuation.value_gap;
  const gapText = `${gap > 0 ? "+" : ""}${(gap * 100).toFixed(1)}%`;
  const gapClass = gap > 0.25 ? "gap-bad" : gap > 0.05 ? "gap-warn" : "gap-good";
  const condition = valuation.condition ? humanize(valuation.condition) : "condition unknown";
  return `
    <div class="approval-panel valuation-panel">
      <strong>Market valuation</strong>
      <p>${euros(valuation.estimated_market_value)} estimated · ${escapeHtml(valuation.basis)}</p>
      <div class="deal-metrics">
        <span class="score-badge ${gapClass}">Price ${gapText} vs. estimate</span>
        <span>${valuation.price_per_sqm ? `${euros(valuation.price_per_sqm)}/m²` : "—"}</span>
        <span>${escapeHtml(condition)}</span>
      </div>
    </div>`;
};

const diagnosticPanel = (deal) => {
  if (!deal.diagnostic) return "";
  const lines = Object.entries(deal.diagnostic)
    .map(([key, value]) => `${humanize(key)}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
  return `<div class="approval-panel diagnostic"><strong>Diagnostic information</strong><p>${escapeHtml(lines)}</p></div>`;
};

function approvalPanelHTML(deal) {
  if (deal.status !== "waiting_human") return "";
  const type = deal.pending_approval_type;
  const interrupt = deal.interrupts?.[0] || {};

  if (type === "shortlist") {
    return `
      <div class="approval-panel" data-approval="shortlist">
        <strong>Shortlist approval</strong>
        <p>${escapeHtml(interrupt.analysis?.thesis || "Review this candidate for your shortlist.")}</p>
        <label>Feedback <small>optional</small><textarea class="feedback" rows="2" placeholder="Optional feedback"></textarea></label>
        <div class="approval-actions">
          <button type="button" class="approve" data-decision="approved">Approve</button>
          <button type="button" class="reject" data-decision="rejected">Reject</button>
          <button type="button" class="neutral" data-decision="revision_requested">Request revision</button>
        </div>
      </div>`;
  }

  if (type === "contact_resolution") {
    const options = (interrupt.candidates || []).map((candidate) => {
      const label = candidate.name || candidate.organization || "Unknown contact";
      const confidence = Math.round((candidate.confidence || 0) * 100);
      const email = candidate.email ? ` · ${candidate.email}` : "";
      return `<option value="${escapeHtml(candidate.contact_id)}">${escapeHtml(`${label} · ${confidence}% confidence${email}`)}</option>`;
    });
    return `
      <div class="approval-panel" data-approval="contact_resolution">
        <strong>Resolve contact</strong>
        <p>Several plausible contacts were found. Pick the one to approach.</p>
        <label>Contact<select class="contact-select">${options}</select></label>
        <div class="approval-actions">
          <button type="button" class="approve" data-action="resolve">Use this contact</button>
        </div>
      </div>`;
  }

  if (type === "outreach") {
    return `
      <div class="approval-panel" data-approval="outreach">
        <strong>Outreach approval</strong>
        <p>Recipient: ${escapeHtml(interrupt.draft?.recipient_email || "unknown")}</p>
        <label>Subject<input class="draft-subject" /></label>
        <label>Body<textarea class="draft-body" rows="6"></textarea></label>
        <div class="approval-actions">
          <button type="button" class="approve" data-decision="approved">Approve &amp; send</button>
          <button type="button" class="reject" data-decision="rejected">Reject</button>
          <button type="button" class="neutral" data-decision="revision_requested">Request revision</button>
        </div>
        <small>Approval sends the message through the configured gateway (currently the local fake gateway) after your confirmation.</small>
      </div>`;
  }

  if (type === "inbound_reply") {
    return `
      <div class="approval-panel" data-approval="inbound_reply">
        <strong>Broker reply (simulated)</strong>
        <p>The workflow is waiting for a reply from ${escapeHtml(interrupt.expected_sender_email || "the broker")}. Reply ingestion is simulated through this form.</p>
        <label>Sender email<input class="reply-sender" /></label>
        <label>Message<textarea class="reply-body" rows="3"></textarea></label>
        <label>Proposed times <small>optional, comma-separated ISO datetimes</small><input class="reply-times" placeholder="2026-10-24T10:00:00+02:00" /></label>
        <div class="approval-actions">
          <button type="button" class="approve" data-action="send-reply">Record reply</button>
        </div>
      </div>`;
  }

  if (type === "schedule_exception") {
    const meeting = interrupt.meeting || {};
    return `
      <div class="approval-panel" data-approval="schedule_exception">
        <strong>Out-of-policy meeting</strong>
        <p>${escapeHtml(interrupt.reason || "Proposed time is outside configured availability")}</p>
        <p>Proposed: ${escapeHtml(meeting.starts_at || "unknown time")}${meeting.timezone ? ` (${escapeHtml(meeting.timezone)})` : ""}</p>
        <div class="approval-actions">
          <button type="button" class="approve" data-decision="approved">Approve anyway</button>
          <button type="button" class="reject" data-decision="rejected">Reject</button>
        </div>
      </div>`;
  }

  return "";
}

function dealCard(deal) {
  const state = deal.state || {};
  const property = state.property || {};
  const analysis = state.analysis || {};
  const meta = STATUS_META[deal.status] || STATUS_META.unknown;
  const card = document.createElement("article");
  card.className = "result-card deal-card";
  card.dataset.threadId = deal.thread_id;

  const summary =
    state.scout_assessment?.reasons?.join(" · ") ||
    analysis.thesis ||
    property.description ||
    "Awaiting agent processing.";
  const score = analysis.score;
  const yieldValue = analysis.metrics?.gross_yield;
  const cashFlow = analysis.metrics?.monthly_cash_flow;

  card.innerHTML = `
    <div class="result-meta">
      <span>${escapeHtml(property.postal_code || property.city || "")}</span>
      <span class="status ${meta.cls}">${meta.label}</span>
    </div>
    <h3>${escapeHtml(property.title || "Untitled property")}</h3>
    <div class="deal-metrics">
      <span class="score-badge">Deal Score ${score == null ? "—" : `${score}/100`}</span>
      <span>${percent(yieldValue)} gross yield</span>
      <span>${cashFlow ? `${euros(cashFlow)}/mo` : "—"}</span>
      <span>${property.build_year ? `Built ${property.build_year}` : "—"}</span>
      <span>${property.energy_class ? `Energy ${escapeHtml(property.energy_class)}` : "—"}</span>
    </div>
    <p>${escapeHtml(summary)}</p>
    ${stageTracker(state.current_stage)}
    ${propertyMetrics(property)}
    ${valuationPanel(state)}
    ${missingDataPanel(analysis, deal.status)}
    ${approvalPanelHTML(deal)}
    ${diagnosticPanel(deal)}
    <p class="card-error error" hidden></p>`;
  wireApprovalPanel(card, deal);
  return card;
}

function wireApprovalPanel(card, deal) {
  const panel = card.querySelector(".approval-panel:not(.diagnostic)");
  if (!panel) return;
  const threadId = deal.thread_id;
  const interrupt = deal.interrupts?.[0] || {};
  const kind = panel.dataset.approval;
  const send = (payload, confirmMessage) =>
    resumeDeal(threadId, payload, confirmMessage, card);

  if (kind === "shortlist") {
    panel.querySelectorAll("[data-decision]").forEach((button) => {
      button.addEventListener("click", () => {
        const feedback = panel.querySelector(".feedback").value.trim();
        send({
          decision: button.dataset.decision,
          decided_by: "dashboard",
          ...(feedback ? { feedback } : {}),
        });
      });
    });
  }

  if (kind === "contact_resolution") {
    panel.querySelector("[data-action='resolve']").addEventListener("click", () => {
      send({ contact_id: panel.querySelector(".contact-select").value });
    });
  }

  if (kind === "outreach") {
    const subjectInput = panel.querySelector(".draft-subject");
    const bodyInput = panel.querySelector(".draft-body");
    subjectInput.value = interrupt.draft?.subject || "";
    bodyInput.value = interrupt.draft?.body || "";
    panel.querySelectorAll("[data-decision]").forEach((button) => {
      button.addEventListener("click", () => {
        const decision = button.dataset.decision;
        const payload = { decision, decided_by: "dashboard" };
        if (decision === "approved") {
          payload.subject = subjectInput.value;
          payload.body = bodyInput.value;
        }
        const confirmMessage = decision === "approved"
          ? `Approving will send the outreach email to ${interrupt.draft?.recipient_email || "the selected contact"} through the configured gateway (currently the local fake gateway). Continue?`
          : null;
        send(payload, confirmMessage);
      });
    });
  }

  if (kind === "inbound_reply") {
    panel.querySelector(".reply-sender").value = interrupt.expected_sender_email || "";
    panel.querySelector("[data-action='send-reply']").addEventListener("click", () => {
      const times = panel.querySelector(".reply-times").value
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      send({
        message_id: `manual-${Date.now()}`,
        sender_email: panel.querySelector(".reply-sender").value.trim(),
        received_at: new Date().toISOString(),
        body: panel.querySelector(".reply-body").value.trim(),
        ...(times.length ? { proposed_times: times } : {}),
      });
    });
  }

  if (kind === "schedule_exception") {
    panel.querySelectorAll("[data-decision]").forEach((button) => {
      button.addEventListener("click", () => {
        send({ decision: button.dataset.decision, decided_by: "dashboard" });
      });
    });
  }
}

async function resumeDeal(threadId, payload, confirmMessage, card) {
  if (confirmMessage && !window.confirm(confirmMessage)) return;
  const cardError = card.querySelector(".card-error");
  cardError.hidden = true;
  try {
    const response = await fetch(`/deals/${threadId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ response: payload }),
    });
    if (!response.ok) throw new Error(await readError(response));
    await loadDeals();
  } catch (error) {
    cardError.textContent = error.message;
    cardError.hidden = false;
  }
}

function renderDashboard(deals) {
  const sorted = [...deals].sort(
    (a, b) => (STATUS_PRIORITY[a.status] ?? 9) - (STATUS_PRIORITY[b.status] ?? 9)
  );
  dealCount.textContent = `${deals.length} deal${deals.length === 1 ? "" : "s"} tracked`;
  if (sorted.length === 0) {
    dealGrid.replaceChildren();
    dashboardEmpty.textContent = "No deals yet. Start a property search above to create deals.";
    dashboardEmpty.hidden = false;
    return;
  }
  dashboardEmpty.hidden = true;
  dealGrid.replaceChildren(...sorted.map(dealCard));
  dashboardSection.hidden = false;
}

async function loadDeals() {
  try {
    const response = await fetch("/deals");
    if (!response.ok) throw new Error("Could not load deals.");
    const deals = await response.json();
    renderDashboard(deals);
  } catch (error) {
    dealGrid.replaceChildren();
    dashboardEmpty.textContent = error.message;
    dashboardEmpty.hidden = false;
    dashboardSection.hidden = false;
  }
}

refreshButton.addEventListener("click", loadDeals);
loadDeals();

const discoverySection = document.querySelector("#discovery");
const discoveryGrid = document.querySelector("#discovery-grid");
const discoveryCount = document.querySelector("#discovery-count");
const discoveryDiagnostics = document.querySelector("#discovery-diagnostics");
const discoveryEmpty = document.querySelector("#discovery-empty");
const refreshDiscoveriesButton = document.querySelector("#refresh-discoveries");

const DISCOVERY_STATUS_META = {
  complete: { label: "Validated", cls: "dis-complete" },
  incomplete: { label: "Incomplete", cls: "dis-incomplete" },
  rejected: { label: "Rejected", cls: "dis-rejected" },
  quarantined: { label: "Quarantined", cls: "dis-quarantined" },
  index_page: { label: "Index page", cls: "dis-index" },
  fetch_failed: { label: "Fetch failed", cls: "dis-failed" },
  budget_exhausted: { label: "Budget exhausted", cls: "dis-budget" },
};

let currentSearchId = null;

const eurosPlain = (value) =>
  value == null ? "—" : `EUR ${value.toLocaleString("en-US")}`;

function discoveryStatusBadge(status) {
  const meta = DISCOVERY_STATUS_META[status] || {
    label: humanize(status),
    cls: "dis-budget",
  };
  return `<span class="status-badge ${meta.cls}">${meta.label}</span>`;
}

function discoveryReasonLine(record) {
  const parts = [];
  if (record.reasons?.length) {
    parts.push(`Reasons: ${record.reasons.map(humanize).join(", ")}`);
  }
  if (record.missing?.length) {
    parts.push(`Missing: ${record.missing.map(humanize).join(", ")}`);
  }
  if (record.possible_duplicates?.length) {
    parts.push(`Possible duplicate of ${record.possible_duplicates.length} listing(s)`);
  }
  return parts.length
    ? `<p class="discovery-reasons">${escapeHtml(parts.join(" · "))}</p>`
    : "";
}

function discoveryCard(record) {
  const card = document.createElement("article");
  card.className = "result-card discovery-card";
  card.dataset.url = record.url;
  const selectable = record.status === "complete";
  const criteria = record.matches_criteria
    ? `<span class="criteria-match">Matches criteria ✓</span>`
    : `<span class="criteria-miss">Outside criteria</span>`;
  card.innerHTML = `
    <div class="result-meta">
      ${discoveryStatusBadge(record.status)}
      ${criteria}
      <span>${escapeHtml(record.portal)}</span>
    </div>
    <h3>${escapeHtml(record.title || record.url)}</h3>
    <div class="metric">
      <span>${record.rooms ?? "—"} rooms · ${record.area_m2 ?? "—"} m² · ${escapeHtml(record.city || "—")}${record.postal_code ? ` · ${record.postal_code}` : ""}</span>
      <span>${eurosPlain(record.price_eur)}</span>
    </div>
    ${discoveryReasonLine(record)}
    <div class="result-meta">
      <a href="${escapeHtml(record.url)}" target="_blank" rel="noopener">Open source listing ↗</a>
    </div>
    ${selectable ? `<button type="button" class="ghost-button analyze-button">Select for analysis</button>` : ""}
    <p class="card-error" role="alert" hidden></p>`;
  const button = card.querySelector(".analyze-button");
  if (button) {
    button.addEventListener("click", () => {
      startDiscoveryDeal(card, record.url);
    });
  }
  return card;
}

function renderDiscovery(run) {
  currentSearchId = run.search_id;
  const counts = run.counts || {};
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const diagnostics = [
    `${total} discovered item(s)`,
    `${run.search_calls} search call(s)`,
    `${run.index_fetches} index fetch(es)`,
    `${run.detail_fetches} detail fetch(es)`,
  ];
  if (run.cross_query_duplicates) {
    diagnostics.push(`${run.cross_query_duplicates} duplicate URL(s) skipped`);
  }
  discoveryCount.textContent = diagnostics.join(" · ");
  const chips = Object.entries(counts)
    .map(([status, count]) => {
      const meta = DISCOVERY_STATUS_META[status] || { label: humanize(status) };
      return `<span class="count-chip">${meta.label}: ${count}</span>`;
    })
    .join("");
  const errorChips = (run.search_errors || [])
    .map((error) => `<span class="count-chip error">Search error: ${escapeHtml(error)}</span>`)
    .join("");
  discoveryDiagnostics.innerHTML = chips + errorChips;
  if (total === 0) {
    discoveryGrid.replaceChildren();
    discoveryEmpty.textContent = "No discoveries recorded for this search yet.";
    discoveryEmpty.hidden = false;
    discoverySection.hidden = false;
    return;
  }
  discoveryEmpty.hidden = true;
  discoveryGrid.replaceChildren(...run.records.map(discoveryCard));
  discoverySection.hidden = false;
}

async function loadDiscoveries(searchId) {
  try {
    const historyResponse = await fetch("/discoveries");
    if (!historyResponse.ok) throw new Error("Could not load discovery history.");
    const history = await historyResponse.json();
    if (history.length === 0) {
      discoveryGrid.replaceChildren();
      discoveryDiagnostics.replaceChildren();
      discoveryEmpty.textContent =
        "No discovery search has run yet. Start a property search above to populate the inventory.";
      discoveryEmpty.hidden = false;
      discoverySection.hidden = false;
      return;
    }
    const target = searchId || currentSearchId;
    const known = history.some((item) => item.search_id === target);
    const runId = known ? target : history[0].search_id;
    const runResponse = await fetch(`/discoveries/${runId}`);
    if (!runResponse.ok) throw new Error("Could not load the discovery run.");
    renderDiscovery(await runResponse.json());
  } catch (error) {
    discoveryGrid.replaceChildren();
    discoveryEmpty.textContent = error.message;
    discoveryEmpty.hidden = false;
    discoverySection.hidden = false;
  }
}

async function startDiscoveryDeal(card, url) {
  const cardError = card.querySelector(".card-error");
  const button = card.querySelector(".analyze-button");
  cardError.hidden = true;
  if (button) button.disabled = true;
  const send = (body) =>
    fetch(`/discoveries/${currentSearchId}/deals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  try {
    let response = await send({ url });
    if (response.status === 422) {
      response = await send({ url, criteria: requestFromForm() });
    }
    if (!response.ok) throw new Error(await readError(response));
    cardError.textContent = "Analysis workflow started — see it in your deals below.";
    cardError.hidden = false;
    await loadDeals();
  } catch (error) {
    cardError.textContent = error.message;
    cardError.hidden = false;
  } finally {
    if (button) button.disabled = false;
  }
}

refreshDiscoveriesButton.addEventListener("click", () => loadDiscoveries());
loadDiscoveries();



form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "Scouting properties…";
  try {
    const response = await fetch("/searches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestFromForm()),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail?.[0]?.msg || body.detail || "The search could not be started.");
    }
    if (body.deals.length === 0) {
      if (body.discovery) {
        resultsSection.hidden = true;
        await loadDiscoveries(body.discovery.search_id);
        discoverySection.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      resultCount.textContent = "0 listings reviewed";
      const empty = document.createElement("article");
      empty.className = "result-card empty-result";
      empty.innerHTML = `
        <div class="result-meta"><span>Live search complete</span></div>
        <h3>No reliable listings found</h3>
        <p>Keenable returned no public purchase pages with enough structured data to validate. Try a broader postcode, price, or size.</p>`;
      resultGrid.replaceChildren(empty);
      resultsSection.hidden = false;
      resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      resultsSection.hidden = true;
      await loadDeals();
      dashboardSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Start property search";
  }
});
