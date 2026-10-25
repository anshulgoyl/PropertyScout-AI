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
const dealTabs = document.querySelector("#deal-tabs");
const pipelineSummary = document.querySelector("#pipeline-summary");
const dealControls = document.querySelector("#deal-controls");
const dealCityFilter = document.querySelector("#deal-city-filter");
const dealStatusFilter = document.querySelector("#deal-status-filter");
const dealSort = document.querySelector("#deal-sort");
const dealCompareToggle = document.querySelector("#deal-compare-toggle");
const dealComparison = document.querySelector("#deal-comparison");
const workflowCard = document.querySelector("#workflow-card");
const workflowStatus = document.querySelector("#workflow-status");
let focusedWorkflowThreadId = null;
let activeDealTab = "analyze";
let selectedFinancialThreadId = null;
let dealsByThreadId = new Map();
let comparisonMode = false;
const comparisonThreadIds = new Set();
const dealView = { city: "", status: "all", sort: "score" };
const financialDealThreadIds = new Set(JSON.parse(localStorage.getItem("propertyscout-financial-deals") || "[]"));

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

const safeHttpUrl = (value) => {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
};

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

const DEAL_TABS = [
  { id: "analyze", label: "Analyze" },
  { id: "contact", label: "Contact" },
  { id: "financials", label: "Financial Estimates" },
];

const CONTACT_STAGES = new Set([
  "contact_research",
  "awaiting_contact_resolution",
  "outreach_drafting",
  "awaiting_outreach_approval",
  "awaiting_reply",
  "scheduling",
  "meeting_preparation",
]);

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

const WORKFLOW_AGENT_NAMES = ["Scout", "Analyse", "Research", "Outreach", "Schedule", "Prepare"];

const STAGE_TO_WORKFLOW_AGENT = {
  initialized: 0, discovery: 0, analysis: 1,
  awaiting_shortlist_approval: 2, contact_research: 2, awaiting_contact_resolution: 2,
  outreach_drafting: 3, awaiting_outreach_approval: 3,
  awaiting_reply: 4, scheduling: 4,
  meeting_preparation: 5, complete: 5, failed: 0,
};

function updateWorkflowStage(stage) {
  if (!workflowCard || !workflowStatus) return;
  const activeIndex = STAGE_TO_WORKFLOW_AGENT[stage] ?? 0;
  workflowStatus.textContent = `Active now: ${WORKFLOW_AGENT_NAMES[activeIndex]}`;
  workflowCard.querySelectorAll("[data-workflow-agent]").forEach((item) => {
    const index = Number(item.dataset.workflowAgent);
    item.classList.toggle("active", index === activeIndex);
    item.classList.toggle("done", index < activeIndex);
    item.toggleAttribute("aria-current", index === activeIndex);
  });
}

function focusWorkflowDeal(deal) {
  focusedWorkflowThreadId = deal.thread_id || null;
  updateWorkflowStage(deal.state?.current_stage || "discovery");
}

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
const financialEuros = (value) => `EUR ${Math.round(Number(value) || 0).toLocaleString("en-US")}`;

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

function listingDetailSnippets(property) {
  const evidenceText = (property.evidence || []).map((item) => item.excerpt || "").join("\n");
  const relevant = /\b(baujahr|etage|geschoss|stock|hausgeld|kaltmiete|mieteinnahmen|mietvertrag|vermietet|leerstand|heizung|energie|endenergie|verbrauch|bedarf|modernis|renovier|sanier|balkon|terrasse|aufzug|keller|stellplatz|garage|einbauküche|provision|courtage|erbpacht|sonderumlage|rücklage|wohngeld)\b/i;
  const seen = new Set();
  return evidenceText
    .split(/\n|(?<=[.!?])\s+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter((line) => line.length >= 12 && relevant.test(line))
    .map((line) => line.slice(0, 180).replace(/[,:;\-]+$/, ""))
    .filter((line) => {
      const key = line.toLocaleLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 12);
}

function evidenceFeatureFacts(property) {
  const text = `${property.description || ""}\n${(property.evidence || []).map((item) => item.excerpt || "").join("\n")}`.replace(/\s+/g, " ");
  const capture = (label, pattern) => {
    const value = text.match(pattern)?.[1]?.replace(/\s+/g, " ").trim();
    return value ? `${label}: ${value.replace(/[;,.]+$/, "")}` : null;
  };
  return [
    capture("Floor", /(?:etage|geschoss|stockwerk|lage der wohnung)\s*[:\-]?\s*([^.;]{2,56})/i),
    capture("Total floors", /(?:anzahl der geschosse|gesamt(?:zahl)?\s*(?:der)?\s*geschosse|geschosse im haus)\s*[:\-]?\s*(\d{1,2})/i),
    capture("Available from", /(?:frei ab|bezugsfrei ab|verfügbar ab|frei werdend ab)\s*[:\-]?\s*([^.;]{2,48})/i),
    capture("Monthly service charge", /(?:hausgeld|wohngeld)\s*[:\-]?\s*(?:ca\.?\s*)?([\d. ]{2,12}(?:,\d{1,2})?\s*(?:€|eur))/i),
    capture("Current cold rent", /(?:kaltmiete|nettokaltmiete)\s*[:\-]?\s*(?:ca\.?\s*)?([\d. ]{2,12}(?:,\d{1,2})?\s*(?:€|eur))/i),
    capture("Rental income", /(?:mieteinnahmen|jahresnettokaltmiete|jahresmiete)\s*[:\-]?\s*(?:ca\.?\s*)?([\d. ]{2,14}(?:,\d{1,2})?\s*(?:€|eur))/i),
    capture("Heating", /(?:heizungsart|heizung)\s*[:\-]?\s*([^.;]{2,56})/i),
    capture("Energy consumption", /(?:endenergie(?:verbrauch|bedarf)|energieverbrauch|energiebedarf)\s*[:\-]?\s*([^.;]{2,64})/i),
    capture("Modernisation", /(?:modernisiert|modernisierung|renoviert|sanierung)\s*[:\-]?\s*([^.;]{2,64})/i),
    capture("Maintenance reserve", /(?:instandhaltungsrücklage|rücklage)\s*[:\-]?\s*([^.;]{2,64})/i),
    capture("Special assessment", /(?:sonderumlage)\s*[:\-]?\s*([^.;]{2,64})/i),
    capture("Buyer commission", /(?:käuferprovision|courtage|provision)\s*[:\-]?\s*([^.;]{2,64})/i),
  ].filter(Boolean);
}

function propertyFeaturePanel(property, analysis) {
  const description = `${property.description || ""} ${(property.features || []).join(" ")}`;
  const floor = description.match(/\b(?:\d{1,2}\.?\s*(?:og|etage)|erdgeschoss|dachgeschoss|obergeschoss)\b/i)?.[0];
  const pricePerSqm = property.asking_price?.amount && property.living_area_sqm
    ? { amount: property.asking_price.amount / property.living_area_sqm, currency: property.asking_price.currency }
    : null;
  const items = [
    property.address || (property.postal_code || property.city ? `${property.postal_code || ""} ${property.city || ""}`.trim() : null),
    property.property_type ? humanize(property.property_type) : null,
    property.room_count ? `${property.room_count} rooms` : null,
    property.living_area_sqm ? `${property.living_area_sqm} m² living area` : null,
    property.build_year ? `Built ${property.build_year}` : null,
    floor ? `Floor: ${floor}` : null,
    property.condition ? `Condition: ${humanize(property.condition)}` : null,
    property.energy_class ? `Energy class ${property.energy_class}` : null,
    pricePerSqm ? `Asking ${euros(pricePerSqm)}/m²` : null,
    property.annual_rent ? `Annual rent ${euros(property.annual_rent)}` : null,
    analysis.metrics?.gross_yield ? `${(analysis.metrics.gross_yield * 100).toFixed(1)}% stated gross yield` : null,
    ...(property.features || []).slice(0, 5),
    ...evidenceFeatureFacts(property),
    ...listingDetailSnippets(property).slice(0, 6),
    ...(analysis.missing_critical_data || []).slice(0, 4).map((item) => `To verify: ${humanize(item)}`),
  ].filter(Boolean);
  if (!items.length) return "";
  return `<section class="property-features-panel"><strong>Key property features</strong><small>Facts captured from the selected listing page and this deal's valuation.</small><div>${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></section>`;
}

const diagnosticPanel = (deal) => {
  if (!deal.diagnostic) return "";
  const lines = Object.entries(deal.diagnostic)
    .map(([key, value]) => `${humanize(key)}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join(" · ");
  return `<div class="approval-panel diagnostic"><strong>Diagnostic information</strong><p>${escapeHtml(lines)}</p></div>`;
};

const COMPARABLE_SOURCE_LABELS = {
  validated_discovery_inventory: "Validated discovery",
  nearby_postcode_discovery: "Nearby postcode search",
  fallback_comparable_search: "Comparable search",
};

function comparablePanelHTML(selections) {
  if (!selections.length) {
    return `<section class="comparable-panel" hidden><strong>Comparable listings</strong><p>No suitable comparable listings were available for this deal.</p></section>`;
  }
  const items = selections.map((selection) => {
    const listing = selection.listing || {};
    const listingUrl = safeHttpUrl(listing.listing_url);
    const distance = selection.postcode_distance_km == null ? "Distance unavailable" : `${selection.postcode_distance_km.toFixed(1)} km away`;
    const details = [euros(listing.asking_price), listing.living_area_sqm ? `${listing.living_area_sqm} m²` : null, listing.room_count ? `${listing.room_count} rooms` : null, listing.postal_code || listing.city || null].filter(Boolean).join(" · ");
    return `<li class="comparable-item"><div class="comparable-meta"><span>#${selection.rank} · ${escapeHtml(COMPARABLE_SOURCE_LABELS[selection.source] || humanize(selection.source))}</span><span>${escapeHtml(distance)}</span></div>${listingUrl ? `<a href="${escapeHtml(listingUrl)}" target="_blank" rel="noopener">${escapeHtml(listing.title || "Open comparable listing")} ↗</a>` : `<strong>${escapeHtml(listing.title || "Comparable listing")}</strong>`}<p>${escapeHtml(details)}</p><p class="comparable-reason">${escapeHtml(selection.selection_reason)}</p></li>`;
  }).join("");
  return `<section class="comparable-panel" hidden><div class="comparable-panel-heading"><strong>Comparable listings</strong><span>${selections.length} selected</span></div><ol class="comparable-list">${items}</ol></section>`;
}

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
      const phone = candidate.phone ? ` · ${candidate.phone}` : "";
      return `<option value="${escapeHtml(candidate.contact_id)}">${escapeHtml(`${label} · ${confidence}% confidence${email}${phone}`)}</option>`;
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

function listingContactContext(property, contact) {
  const text = (property?.evidence || []).map((item) => item.excerpt || "").join(" ").toLocaleLowerCase();
  const isBroker = /\b(makler|immobilienmakler|immobilienagentur|immobilienbüro|agentur|real\s+estate|hausverwaltung|gmbh|kg|engel\s*&\s*völkers|provision\s+für\s+käufer|u-?w-?i\s+ulrike\s+wollscheid\s+immobilien)\b/.test(text);
  const isPrivate = /\b(von\s+privat|privatanbieter|privatverkauf|private[rs]?\s+anbieter|direkt\s+vom\s+eigentümer|ohne\s+makler)\b/.test(text);
  const hasForm = /\b(kontaktformular|anfrageformular|formular|anfrage\s+senden|nachricht\s+senden|anbieter\s+kontaktieren|kontakt\s+aufnehmen)\b/.test(text);
  if (isBroker || ["broker", "agency"].includes(contact?.contact_type)) return { label: "Broker listing", detail: "The listing evidence indicates an agency or broker.", hasForm };
  if (isPrivate || contact?.contact_type === "seller") return { label: "Private listing", detail: "The listing evidence indicates a private seller.", hasForm };
  return { label: "Listing type unclear", detail: "The saved listing evidence does not reliably show whether this is private or broker-led.", hasForm, uncertain: true };
}

function contactDetailsPanel(deal) {
  const state = deal.state || {};
  const property = state.property || {};
  const contact = state.selected_contact;
  const context = listingContactContext(property, contact);
  const listingUrl = safeHttpUrl(property.listing_url);
  const phoneOnly = state.outcome === "contact_method_required";
  const fields = [
    contact?.organization ? `<span>${escapeHtml(contact.organization)}</span>` : "",
    contact?.email ? `<a class="deal-source-link" href="mailto:${escapeHtml(contact.email)}">${escapeHtml(contact.email)}</a>` : "",
    contact?.phone ? `<a class="deal-source-link" href="tel:${escapeHtml(contact.phone)}">${escapeHtml(contact.phone)}</a>` : "",
  ].filter(Boolean).join(" · ");
  const confidence = Math.round((contact?.confidence || 0) * 100);
  const listingAction = listingUrl
    ? `<a class="deal-source-link" href="${escapeHtml(listingUrl)}" target="_blank" rel="noopener">Open listing ↗</a>`
    : "Use the original listing or agency website.";
  const nextStep = context.hasForm
    ? "This listing appears to use a contact form. Open the listing and submit its enquiry form; no visible email address is required."
    : "Open the listing to find the listed contact route, or call the agency if a phone number is shown.";
  return `
    <section class="contact-work-panel contact-details" data-contact-panel="details" hidden>
      <h4>Contact details</h4>
      <span class="contact-type${context.uncertain ? " uncertain" : ""}">${escapeHtml(context.label)}</span>
      <p>${escapeHtml(context.detail)}</p>
      ${contact ? `<p><strong>${escapeHtml(contact.name)}</strong> · ${confidence}% confidence</p><p>${fields || "A contact was found, but details are incomplete."}</p>` : `<p><strong>Research Agent could not identify a reliable named contact.</strong></p><p>${phoneOnly ? "A phone contact was found, but no email address is available." : nextStep}</p>`}
      <p>${listingAction}</p>
      <small>Contact information is extracted only from the selected listing page.</small>
      ${deal.pending_approval_type === "contact_resolution" ? approvalPanelHTML(deal) : ""}
    </section>`;
}

function outreachEmailPanel(deal) {
  const contact = deal.state?.selected_contact;
  const property = deal.state?.property || {};
  const interrupt = deal.interrupts?.[0] || {};
  const email = contact?.email;
  const action = deal.pending_approval_type === "outreach" ? approvalPanelHTML(deal) : "";
  const awaitingReply = deal.pending_approval_type === "inbound_reply" ? approvalPanelHTML(deal) : "";
  const subject = interrupt.draft?.subject || `Interested in ${property.title || "your property"}${property.city ? ` in ${property.city}` : ""}`;
  const valuationPrompts = valuationQuestions(property, deal.state?.analysis || {}).slice(2, 6).map((point) => `- ${point}`).join("\n");
  const body = interrupt.draft?.body || `Hello,\n\nI came across "${property.title || "your property"}"${property.city ? ` in ${property.city}` : ""} and it genuinely stood out to me. I would love to understand it a little better and explore whether it could be a good fit.\n\nBefore arranging a viewing, the following details would help me assess the property responsibly:\n\n${valuationPrompts}\n\nI am especially keen to understand the condition of the building and any upcoming costs. If convenient, I would be delighted to arrange a short call or viewing at a time that suits you.\n\nThank you very much, and I look forward to hearing from you.\n\nBest regards`;
  const gmailUrl = new URL("https://mail.google.com/mail/");
  gmailUrl.searchParams.set("view", "cm");
  gmailUrl.searchParams.set("fs", "1");
  if (email) gmailUrl.searchParams.set("to", email);
  gmailUrl.searchParams.set("su", subject);
  gmailUrl.searchParams.set("body", body);
  return `
    <section class="contact-work-panel" data-contact-panel="outreach" hidden>
      <h4>Outreach email</h4>
      ${email ? `<p>Ready for <a class="deal-source-link" href="mailto:${escapeHtml(email)}">${escapeHtml(email)}</a>.</p>` : `<p>No email address is visible yet. This draft is ready to adapt for the listing's contact form or a future email address.</p>`}
      ${action ? `<a class="gmail-draft-button" href="${escapeHtml(gmailUrl.href)}" target="_blank" rel="noopener">Draft in Gmail ↗</a>` : `<label>Subject<input readonly value="${escapeHtml(subject)}" /></label><label>Draft email<textarea readonly rows="13">${escapeHtml(body)}</textarea></label><a class="gmail-draft-button" href="${escapeHtml(gmailUrl.href)}" target="_blank" rel="noopener">Draft in Gmail ↗</a><small>This opens a Gmail compose draft only; it does not send anything.</small>`}
      ${action || awaitingReply}
    </section>`;
}

function valuationQuestions(property, analysis) {
  return [
    property.asking_price ? `Confirm the asking price (${euros(property.asking_price)}), exactly what is included, and the seller's flexibility.` : "Confirm the asking price, what is included, and the seller's flexibility.",
    property.living_area_sqm ? `Verify the legal living area (${property.living_area_sqm} m²), floor plan, floor level, balcony/cellar/parking and any non-living space.` : "Verify the legal living area, floor plan, ancillary space and any included parking.",
    "Establish vacancy or tenancy: current rent, deposit, indexation, tenant duration, notice position and realistic market rent.",
    "Request the last three owners' association minutes, reserve balance, house rules and all planned or approved special assessments.",
    "Break down monthly service charges into recoverable and non-recoverable costs, plus property tax and insurance.",
    "Confirm condition and dates of major works: roof, façade, windows, heating, electrics, plumbing, bathrooms and kitchen.",
    "Review the energy certificate, heating system, energy class and likely efficiency upgrades or regulatory costs.",
    "Check title and legal constraints: leasehold, easements, occupancy rights, heritage restrictions and outstanding liabilities.",
    analysis.thesis ? `Test the valuation thesis against the listing claims: ${analysis.thesis}` : "Ask why the seller is moving and which documents support the stated condition and value.",
  ];
}

function preparePanel(deal) {
  const property = deal.state?.property || {};
  const analysis = deal.state?.analysis || {};
  const points = valuationQuestions(property, analysis);
  return `<section class="contact-work-panel" data-contact-panel="prepare" hidden><h4>Prepare</h4><p>Key points for the first call:</p><ol class="contact-prep-list">${points.map((point) => `<li>${escapeHtml(point)}</li>`).join("")}</ol></section>`;
}

function contactWorkspacePanels(deal) {
  return `<div class="contact-workspace"><div class="contact-work-switcher" role="group" aria-label="Contact deal actions"><button type="button" class="contact-work-toggle" data-contact-toggle="details" aria-expanded="false">Contact details</button><button type="button" class="contact-work-toggle" data-contact-toggle="outreach" aria-expanded="false">Outreach email</button><button type="button" class="contact-work-toggle" data-contact-toggle="prepare" aria-expanded="false">Prepare</button><button type="button" class="contact-work-toggle financial-estimates-button">Prepare Financials</button></div>${contactDetailsPanel(deal)}${outreachEmailPanel(deal)}${preparePanel(deal)}</div>`;
}

function financialDefaults(deal) {
  const property = deal.state?.property || {};
  const area = Number(property.living_area_sqm) || 0;
  const annualRent = Number(property.annual_rent?.amount) || 0;
  const evidence = (property.evidence || []).map((item) => item.excerpt || "").join(" ");
  const monthlyRent = Number(evidence.match(/(?:kaltmiete|nettokaltmiete)\s*[:\-]?\s*(?:ca\.?\s*)?([\d.]+(?:,\d+)?)/i)?.[1]?.replace(/\./g, "").replace(",", ".")) || 0;
  const needsRenovation = /renovierungsbedürftig|sanierungsbedürftig|renovation_needed|modernisierungsbedürftig/i.test(`${property.condition || ""} ${property.description || ""} ${evidence}`);
  const isLet = annualRent > 0 || monthlyRent > 0 || /vermietet|mieteinnahmen/i.test(evidence);
  return {
    purchasePrice: Number(property.asking_price?.amount) || 0,
    renovation: needsRenovation ? Math.round((Number(property.asking_price?.amount) || 0) * 0.08 / 1000) * 1000 : 0,
    acquisitionCostRate: 0.085, rentPerSqm: area && (annualRent || monthlyRent) ? (annualRent || monthlyRent * 12) / area / 12 : 18,
    occupancy: isLet ? 0.97 : 0.9, rentGrowth: 0.03, appreciation: 0.02, loanToValue: 1, interestRate: 0.045,
    repaymentRate: 0.01, nonRecoverable: 80, management: 50, maintenancePerSqm: needsRenovation ? 0.75 : 0.5,
    repairs: needsRenovation ? 2000 : 1000, insurance: 600, taxRate: 0.35, landShare: 0.1, depreciationRate: 0.025,
    maintenanceDeductionYears: 5, furniture: 0,
  };
}

function financialInput(label, name, value, suffix, step = "0.01") {
  return `<label>${escapeHtml(label)}<span class="financial-input"><input data-financial-input="${name}" type="number" step="${step}" value="${Number(value).toFixed(step === "1" ? 0 : 2)}" />${suffix ? `<small>${escapeHtml(suffix)}</small>` : ""}</span></label>`;
}

function financialAssumptionGroups(defaults) {
  const group = (title, description, fields) => `<section class="financial-assumption-group"><header><strong>${title}</strong><small>${description}</small></header><div>${fields.join("")}</div></section>`;
  return [
    group("Purchase & setup", "Price, one-off works and transaction costs", [
      financialInput("Purchase price", "purchasePrice", defaults.purchasePrice, "EUR", "1"),
      financialInput("Renovation", "renovation", defaults.renovation, "EUR", "1"),
      financialInput("Furniture & furnishing", "furniture", defaults.furniture, "EUR", "1"),
      financialInput("Acquisition costs", "acquisitionCostRate", defaults.acquisitionCostRate * 100, "%", "0.1"),
    ]),
    group("Rental income", "Expected rent and occupancy", [
      financialInput("Target rent", "rentPerSqm", defaults.rentPerSqm, "EUR / m² / month"),
      financialInput("Occupancy", "occupancy", defaults.occupancy * 100, "%", "0.1"),
      financialInput("Rent growth", "rentGrowth", defaults.rentGrowth * 100, "% p.a.", "0.1"),
      financialInput("Value growth", "appreciation", defaults.appreciation * 100, "% p.a.", "0.1"),
    ]),
    group("Financing", "Loan size, cost and repayment", [
      financialInput("Loan-to-value (price + renovation)", "loanToValue", defaults.loanToValue * 100, "%", "0.1"),
      financialInput("Interest rate", "interestRate", defaults.interestRate * 100, "% p.a.", "0.1"),
      financialInput("Initial repayment", "repaymentRate", defaults.repaymentRate * 100, "% p.a.", "0.1"),
    ]),
    group("Running costs", "Annual and monthly ownership costs", [
      financialInput("Non-recoverable costs", "nonRecoverable", defaults.nonRecoverable, "EUR / month"),
      financialInput("Management", "management", defaults.management, "EUR / month"),
      financialInput("Maintenance reserve", "maintenancePerSqm", defaults.maintenancePerSqm, "EUR / m² / month"),
      financialInput("Annual repairs", "repairs", defaults.repairs, "EUR", "1"),
      financialInput("Insurance", "insurance", defaults.insurance, "EUR p.a.", "1"),
    ]),
    group("Tax & depreciation", "Personal tax and deductible allowances", [
      financialInput("Marginal tax rate", "taxRate", defaults.taxRate * 100, "%", "0.1"),
      financialInput("Land share", "landShare", defaults.landShare * 100, "%", "0.1"),
      financialInput("Building depreciation", "depreciationRate", defaults.depreciationRate * 100, "% p.a.", "0.1"),
      financialInput("Maintenance deduction", "maintenanceDeductionYears", defaults.maintenanceDeductionYears, "years", "1"),
    ]),
  ].join("");
}

function financialScenarioDefaults(deal, scenario = "base") {
  const defaults = { ...financialDefaults(deal) };
  if (scenario === "conservative") {
    defaults.rentPerSqm *= 0.92;
    defaults.occupancy = Math.min(defaults.occupancy, 0.9);
    defaults.rentGrowth = 0.01;
    defaults.appreciation = 0.005;
    defaults.interestRate += 0.01;
    defaults.repairs *= 1.4;
  } else if (scenario === "optimistic") {
    defaults.rentPerSqm *= 1.06;
    defaults.occupancy = Math.max(defaults.occupancy, 0.97);
    defaults.rentGrowth = 0.04;
    defaults.appreciation = 0.03;
    defaults.interestRate = Math.max(0, defaults.interestRate - 0.005);
    defaults.repairs *= 0.8;
  }
  return defaults;
}

function financialScenarioKey(threadId, scenario) {
  return `propertyscout-financials:${threadId}:${scenario}`;
}

function financialPanel(deal) {
  const property = deal.state?.property || {};
  const scenario = localStorage.getItem(`propertyscout-financial-scenario:${deal.thread_id}`) || "base";
  const defaults = financialScenarioDefaults(deal, scenario);
  const price = property.asking_price?.amount || 0;
  const area = property.living_area_sqm || 0;
  const assumptionGroups = financialAssumptionGroups(defaults);
  return `<section class="financial-panel" data-financial-thread="${escapeHtml(deal.thread_id)}" data-financial-scenario="${scenario}"><div class="financial-header"><div><h4>10-year financial evaluation</h4><p>Adjust the assumptions, then use the model to compare cash flow, financing, tax and wealth over ten years.</p></div><label class="financial-scenario">Scenario<select data-financial-scenario-select><option value="base"${scenario === "base" ? " selected" : ""}>Base case</option><option value="conservative"${scenario === "conservative" ? " selected" : ""}>Conservative</option><option value="optimistic"${scenario === "optimistic" ? " selected" : ""}>Optimistic</option></select><small>Stored for this deal in this browser</small></label></div><div class="financial-layout"><aside class="financial-deal-card"><span>Selected property</span><strong>${escapeHtml(property.title || "Untitled property")}</strong><p>${escapeHtml([property.postal_code, property.city].filter(Boolean).join(" "))}</p><button type="button" class="deal-delete-button financial-delete-button">Delete deal</button><dl><div><dt>Purchase price</dt><dd data-financial-purchase-price>${financialEuros(price)}</dd></div><div><dt>Living area</dt><dd>${area ? `${area} m²` : "n.a."}</dd></div><div><dt>Rooms</dt><dd>${property.room_count || "n.a."}</dd></div><div><dt>Price / m²</dt><dd data-financial-price-sqm>${price && area ? financialEuros(price / area) : "n.a."}</dd></div></dl></aside><div class="financial-assumptions"><h5>Key assumptions</h5><p class="financial-assumption-guide">Editable inputs that drive the purchase cost, rental income, loan, ownership costs and tax estimate.</p>${assumptionGroups}</div><div class="financial-results"><div class="financial-kpis"><div><span>Year 1 cash flow incl. initial cash</span><strong data-financial-metric="cashflow"></strong></div><div><span>Loan amount</span><strong data-financial-metric="loan"></strong></div><div><span>Year 10 equity</span><strong data-financial-metric="equity"></strong></div><div><span>10-year wealth effect</span><strong data-financial-metric="wealth"></strong></div><div><span>Initial cash required</span><strong data-financial-metric="initial"></strong></div></div><div class="financial-charts"><figure><figcaption>Annual cash flow after tax, including initial cash in Year 1</figcaption><canvas data-financial-chart="cashflow" width="500" height="180"></canvas></figure><figure><figcaption>Property value vs. net equity</figcaption><canvas data-financial-chart="equity" width="500" height="180"></canvas></figure><figure><figcaption>Rental income vs. ownership costs</figcaption><canvas data-financial-chart="income-costs" width="500" height="180"></canvas></figure><figure><figcaption>Total wealth effect</figcaption><canvas data-financial-chart="wealth" width="500" height="180"></canvas></figure></div></div></div><div class="financial-table-wrap"><table class="financial-table"><thead><tr><th>Year</th><th>Rental income</th><th>Cash flow after tax</th><th>Property value</th><th>Net equity</th><th>Total wealth effect</th></tr></thead><tbody data-financial-table></tbody></table></div></section>`;
}

function financialValues(panel, deal) {
  const scenario = panel.dataset.financialScenario || "base";
  const defaults = financialScenarioDefaults(deal, scenario);
  const saved = JSON.parse(localStorage.getItem(financialScenarioKey(deal.thread_id, scenario)) || localStorage.getItem(`propertyscout-financials:${deal.thread_id}`) || "{}");
  const raw = {};
  panel.querySelectorAll("[data-financial-input]").forEach((input) => { raw[input.dataset.financialInput] = Number(input.value); });
  const values = { ...defaults, ...saved, ...raw };
  ["acquisitionCostRate", "occupancy", "rentGrowth", "appreciation", "loanToValue", "interestRate", "repaymentRate", "taxRate", "landShare", "depreciationRate"].forEach((key) => { values[key] /= 100; });
  return values;
}

function financialProjection(deal, inputs) {
  const property = deal.state?.property || {};
  const price = Number(inputs.purchasePrice) || 0;
  const area = Number(property.living_area_sqm) || 0;
  const renovation = inputs.renovation;
  const assetCost = price + renovation;
  const acquisitionCosts = assetCost * inputs.acquisitionCostRate;
  const totalCost = assetCost + acquisitionCosts + inputs.furniture;
  const initialLoan = assetCost * inputs.loanToValue;
  const initialCash = totalCost - initialLoan;
  const annualDebtService = initialLoan * (inputs.interestRate + inputs.repaymentRate);
  const annualDeduction = inputs.maintenanceDeductionYears ? renovation / inputs.maintenanceDeductionYears : 0;
  let outstanding = initialLoan;
  let cumulativeCashFlow = 0;
  return Array.from({ length: 10 }, (_, index) => {
    const year = index + 1;
    const growth = (1 + inputs.rentGrowth) ** index;
    const rentalIncome = area * inputs.rentPerSqm * 12 * inputs.occupancy * growth;
    const interest = outstanding * inputs.interestRate;
    const principal = Math.min(outstanding, Math.max(0, annualDebtService - interest));
    const operatingCosts = (inputs.nonRecoverable + inputs.management + area * inputs.maintenancePerSqm) * 12 * growth + inputs.repairs * growth + inputs.insurance * growth;
    const deductibleCosts = (inputs.nonRecoverable + inputs.management) * 12 * growth + inputs.repairs * growth + inputs.insurance * growth;
    const preTaxCashFlow = rentalIncome - interest - operatingCosts - principal - (year === 1 ? initialCash : 0);
    const depreciation = price * (1 - inputs.landShare) * inputs.depreciationRate;
    const furnitureDepreciation = inputs.furniture * 0.1;
    const taxableResult = rentalIncome - interest - deductibleCosts - depreciation - furnitureDepreciation - (year <= inputs.maintenanceDeductionYears ? annualDeduction : 0);
    const taxEffect = -taxableResult * inputs.taxRate;
    const afterTaxCashFlow = preTaxCashFlow + taxEffect;
    outstanding = Math.max(0, outstanding - principal);
    const propertyValue = assetCost * (1 + inputs.appreciation) ** year;
    const equity = propertyValue - outstanding;
    cumulativeCashFlow += afterTaxCashFlow;
    return { year, rentalIncome, operatingCosts, interest, principal, initialLoan, initialCash, afterTaxCashFlow, propertyValue, equity, wealth: equity + cumulativeCashFlow };
  });
}

function drawFinancialChart(canvas, series, { bars = false } = {}) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width; const height = canvas.height; const left = 48; const right = 12; const top = 24; const bottom = 26;
  ctx.clearRect(0, 0, width, height);
  const values = series.flatMap((item) => item.values);
  const min = Math.min(0, ...values); const max = Math.max(0, ...values); const spread = max - min || 1;
  const yFor = (value) => height - bottom - ((value - min) / spread) * (height - top - bottom);
  const xFor = (index, count) => left + index * (width - left - right) / Math.max(1, count - 1);
  const baseline = yFor(0);
  ctx.font = "10px Inter, sans-serif";
  [min, (min + max) / 2, max].forEach((value) => {
    const y = yFor(value);
    ctx.strokeStyle = "#dfe5e1"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(width - right, y); ctx.stroke();
    ctx.fillStyle = "#68736e"; ctx.fillText(`€${Math.round(value / 1000)}k`, 2, y + 3);
  });
  series.forEach((item, seriesIndex) => {
    ctx.strokeStyle = item.color; ctx.fillStyle = item.color; ctx.lineWidth = 3;
    if (bars) {
      const available = width - left - right;
      const barWidth = Math.max(5, available / item.values.length * .55);
      item.values.forEach((value, index) => { const x = left + index * (available / item.values.length) + (available / item.values.length - barWidth) / 2; const y = yFor(value); ctx.fillRect(x, Math.min(y, baseline), barWidth, Math.abs(baseline - y)); });
    } else {
      ctx.beginPath();
      item.values.forEach((value, index) => { const x = xFor(index, item.values.length); const y = yFor(value); index ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
    }
    if (item.label) { ctx.fillStyle = item.color; ctx.fillRect(left + seriesIndex * 112, 7, 8, 8); ctx.fillStyle = "#68736e"; ctx.fillText(item.label, left + 12 + seriesIndex * 112, 14); }
  });
  ctx.fillStyle = "#68736e";
  const labelCount = series[0]?.values.length || 0;
  Array.from({ length: labelCount }, (_, index) => {
    const x = xFor(index, labelCount);
    ctx.fillText(String(index + 1), x - 3, height - 7);
  });
}

function renderFinancialPanel(panel, deal) {
  const inputs = financialValues(panel, deal);
  const rows = financialProjection(deal, inputs);
  const table = panel.querySelector("[data-financial-table]");
  table.innerHTML = rows.map((row) => `<tr><td>${row.year}</td><td>${financialEuros(row.rentalIncome)}</td><td>${financialEuros(row.afterTaxCashFlow)}</td><td>${financialEuros(row.propertyValue)}</td><td>${financialEuros(row.equity)}</td><td>${financialEuros(row.wealth)}</td></tr>`).join("");
  const last = rows.at(-1); const first = rows[0]; const property = deal.state?.property || {};
  panel.querySelector("[data-financial-metric='cashflow']").textContent = financialEuros(first.afterTaxCashFlow);
  panel.querySelector("[data-financial-metric='loan']").textContent = financialEuros(first.initialLoan);
  panel.querySelector("[data-financial-metric='equity']").textContent = financialEuros(last.equity);
  panel.querySelector("[data-financial-metric='wealth']").textContent = financialEuros(last.wealth);
  panel.querySelector("[data-financial-metric='initial']").textContent = financialEuros(first.initialCash);
  panel.querySelector("[data-financial-purchase-price]").textContent = financialEuros(inputs.purchasePrice);
  panel.querySelector("[data-financial-price-sqm]").textContent = property.living_area_sqm
    ? financialEuros(inputs.purchasePrice / property.living_area_sqm)
    : "n.a.";
  drawFinancialChart(panel.querySelector("[data-financial-chart='cashflow']"), [{ values: rows.map((row) => row.afterTaxCashFlow), color: "#0b7a52" }], { bars: true });
  drawFinancialChart(panel.querySelector("[data-financial-chart='equity']"), [{ label: "Value", values: rows.map((row) => row.propertyValue), color: "#2b5e94" }, { label: "Equity", values: rows.map((row) => row.equity), color: "#0b7a52" }]);
  drawFinancialChart(panel.querySelector("[data-financial-chart='income-costs']"), [{ label: "Income", values: rows.map((row) => row.rentalIncome), color: "#0b7a52" }, { label: "Costs", values: rows.map((row) => row.operatingCosts + row.interest + row.principal), color: "#bc7a19" }]);
  drawFinancialChart(panel.querySelector("[data-financial-chart='wealth']"), [{ values: rows.map((row) => row.wealth), color: "#2b5e94" }]);
}

function initialiseFinancialPanel(card, deal) {
  const panel = card.querySelector("[data-financial-thread]");
  if (!panel || panel.dataset.initialised) return renderFinancialPanel(panel, deal);
  const loadScenario = (scenario) => {
    panel.dataset.financialScenario = scenario;
    const saved = JSON.parse(localStorage.getItem(financialScenarioKey(deal.thread_id, scenario)) || "{}");
    const defaults = financialScenarioDefaults(deal, scenario);
    panel.querySelectorAll("[data-financial-input]").forEach((input) => {
      const savedValue = saved[input.dataset.financialInput];
      const value = savedValue ?? defaults[input.dataset.financialInput];
      const percentageFields = ["acquisitionCostRate", "occupancy", "rentGrowth", "appreciation", "loanToValue", "interestRate", "repaymentRate", "taxRate", "landShare", "depreciationRate"];
      input.value = percentageFields.includes(input.dataset.financialInput) && savedValue == null ? value * 100 : value;
    });
    renderFinancialPanel(panel, deal);
  };
  loadScenario(panel.dataset.financialScenario || "base");
  panel.querySelectorAll("[data-financial-input]").forEach((input) => {
    input.addEventListener("input", () => {
      const data = Object.fromEntries([...panel.querySelectorAll("[data-financial-input]")].map((field) => [field.dataset.financialInput, Number(field.value)]));
      localStorage.setItem(financialScenarioKey(deal.thread_id, panel.dataset.financialScenario || "base"), JSON.stringify(data));
      renderFinancialPanel(panel, deal);
    });
  });
  panel.querySelector("[data-financial-scenario-select]")?.addEventListener("change", (event) => {
    const scenario = event.target.value;
    localStorage.setItem(`propertyscout-financial-scenario:${deal.thread_id}`, scenario);
    loadScenario(scenario);
  });
  panel.dataset.initialised = "true";
  renderFinancialPanel(panel, deal);
}

function wireContactPanels(card) {
  const toggles = card.querySelectorAll("[data-contact-toggle]");
  if (!toggles.length) return;
  toggles.forEach((toggle) => {
    toggle.addEventListener("click", () => {
      const target = toggle.dataset.contactToggle;
      const panel = card.querySelector(`[data-contact-panel="${target}"]`);
      const opening = panel?.hidden;
      card.querySelectorAll("[data-contact-panel]").forEach((item) => { item.hidden = true; });
      toggles.forEach((item) => item.setAttribute("aria-expanded", "false"));
      if (panel && opening) {
        panel.hidden = false;
        toggle.setAttribute("aria-expanded", "true");
      }
    });
  });
}

function dealHistory(deal) {
  const state = deal.state || {};
  const history = [["Selected", "Added from discovery for review"], ["Analyse", state.analysis ? "Assessment and comparable review ready" : "Analysis is being prepared"]];
  if (deal.status === "waiting_human") history.push(["Decision needed", "Waiting for your review"]);
  if (deal.status === "rejected") history.push(["Decision", "Not progressing at this time"]);
  if (dealPipelineTab(deal) === "contact") history.push(["Research", "Contact and listing facts are available to review"]);
  if (financialDealThreadIds.has(deal.thread_id)) history.push(["Financial estimates", "10-year estimate prepared"]);
  return `<section class="deal-history"><h4>Decision history</h4><ol>${history.map(([title, detail]) => `<li><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></li>`).join("")}</ol></section>`;
}

function primaryDealAction(deal) {
  if (dealPipelineTab(deal) === "contact") return "Open contact tools";
  if (deal.status === "waiting_human") return "Review decision";
  if (deal.status === "rejected") return "Review analysis";
  return "Open analysis";
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
  const listingUrl = safeHttpUrl(property.listing_url);
  const comparableCount = state.comparable_selections?.length ?? 0;
  const dealLinks = [
    listingUrl
      ? `<a class="deal-source-link" href="${escapeHtml(listingUrl)}" target="_blank" rel="noopener">View listing ↗</a>`
      : "",
    `<button type="button" class="deal-comparable-toggle" aria-expanded="false" aria-label="Show ${comparableCount} comparable listings">${comparableCount} Comparable${comparableCount === 1 ? "" : "s"}</button>`,
  ].filter(Boolean).join("");

  card.innerHTML = `
    <div class="result-meta">
      <span>${escapeHtml(property.postal_code || property.city || "")}</span>
      <span class="status ${meta.cls}">${meta.label}</span>
      ${comparisonMode ? `<label class="compare-choice"><input type="checkbox" data-compare-choice ${comparisonThreadIds.has(deal.thread_id) ? "checked" : ""} /> Compare</label>` : ""}
      <button type="button" class="deal-delete-button" aria-label="Delete this deal">Delete</button>
    </div>
    <h3>${escapeHtml(property.title || "Untitled property")}</h3>
    <div class="deal-metrics">
      <span class="score-badge">Deal Score ${score == null ? "—" : `${score}/100`}</span>
      <span>${percent(yieldValue)} gross yield</span>
      <span>${cashFlow ? `${euros(cashFlow)}/mo` : "—"}</span>
      <span>${property.build_year ? `Built ${property.build_year}` : "—"}</span>
      <span>${property.energy_class ? `Energy ${escapeHtml(property.energy_class)}` : "—"}</span>
    </div>
    <p class="deal-summary">${escapeHtml(summary)}</p>
    <button type="button" class="primary-deal-action" data-deal-details aria-expanded="false">${primaryDealAction(deal)}</button>
    <div class="deal-details" hidden>
      <div class="deal-links">${dealLinks}</div>
      ${comparablePanelHTML(state.comparable_selections || [])}
      ${propertyMetrics(property)}
      ${valuationPanel(state)}
      ${propertyFeaturePanel(property, analysis)}
      ${missingDataPanel(analysis, deal.status)}
      ${dealPipelineTab(deal) === "contact" ? contactWorkspacePanels(deal) : approvalPanelHTML(deal)}
      ${dealHistory(deal)}
      ${diagnosticPanel(deal)}
      <p class="card-error error" hidden></p>
    </div>`;
  const interrupt = deal.interrupts?.[0] || {};
  const outreachPanel = card.querySelector("[data-approval='outreach']");
  if (outreachPanel) {
    outreachPanel.querySelector(".draft-subject").value = interrupt.draft?.subject || "";
    outreachPanel.querySelector(".draft-body").value = interrupt.draft?.body || "";
  }
  const replyPanel = card.querySelector("[data-approval='inbound_reply']");
  if (replyPanel) {
    replyPanel.querySelector(".reply-sender").value = interrupt.expected_sender_email || "";
  }
  card.addEventListener("click", () => focusWorkflowDeal(deal));
  card.addEventListener("focusin", () => focusWorkflowDeal(deal));
  wireComparablePanel(card, state.current_stage, comparableCount);
  wireContactPanels(card);
  card.querySelector("[data-deal-details]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    const details = card.querySelector(".deal-details");
    const opening = details.hidden;
    details.hidden = !opening;
    event.currentTarget.setAttribute("aria-expanded", String(opening));
    event.currentTarget.textContent = opening ? "Hide details" : primaryDealAction(deal);
  });
  card.querySelector("[data-compare-choice]")?.addEventListener("change", (event) => {
    if (event.target.checked) {
      if (comparisonThreadIds.size >= 4) {
        event.target.checked = false;
        window.alert("Choose up to four deals to compare.");
        return;
      }
      comparisonThreadIds.add(deal.thread_id);
    } else comparisonThreadIds.delete(deal.thread_id);
    renderDashboard(Array.from(dealsByThreadId.values()));
  });
  card.querySelector(".financial-estimates-button")?.addEventListener("click", () => {
    financialDealThreadIds.add(deal.thread_id);
    localStorage.setItem("propertyscout-financial-deals", JSON.stringify([...financialDealThreadIds]));
    selectedFinancialThreadId = deal.thread_id;
    focusedWorkflowThreadId = deal.thread_id;
    activeDealTab = "financials";
    renderDashboard(Array.from(dealsByThreadId.values()));
  });
  card.querySelector(".deal-delete-button")?.addEventListener("click", (event) => {
    event.stopPropagation();
    deleteDeal(deal);
  });
  return card;
}

function dealPipelineTab(deal) {
  const state = deal.state || {};
  if (
    CONTACT_STAGES.has(state.current_stage)
    || state.outcome === "shortlist_approved"
    || state.outcome === "contact_not_found"
    || state.outcome === "contact_method_required"
    || deal.pending_approval_type === "contact_resolution"
    || deal.pending_approval_type === "outreach"
  ) {
    return "contact";
  }
  return "analyze";
}

function financialDealPicker(deals, selectedThreadId) {
  if (!deals.length) return "";
  return `<section class="financial-deal-picker" aria-label="Financial estimate properties"><div><span>Financial estimate properties</span><p>Choose a property to update its assumptions and 10-year forecast.</p></div><div class="financial-deal-picker-list">${deals.map((deal) => { const property = deal.state?.property || {}; return `<button type="button" class="financial-deal-choice${deal.thread_id === selectedThreadId ? " active" : ""}" data-financial-deal-choice="${escapeHtml(deal.thread_id)}"><strong>${escapeHtml(property.title || "Untitled property")}</strong><span>${escapeHtml([property.postal_code, property.city].filter(Boolean).join(" ") || "Location unavailable")}</span><small>${euros(property.asking_price)}</small></button>`; }).join("")}</div></section>`;
}

function renderDealTabs(deals) {
  const counts = { analyze: 0, contact: 0 };
  deals.forEach((deal) => { counts[dealPipelineTab(deal)] += 1; });
  const financialCount = deals.filter((deal) => financialDealThreadIds.has(deal.thread_id)).length;
  dealTabs.replaceChildren(...DEAL_TABS.map(({ id, label }) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `deal-tab${id === activeDealTab ? " active" : ""}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(id === activeDealTab));
    button.textContent = id === "financials" ? `${label} (${financialCount})` : `${label} (${counts[id]})`;
    button.addEventListener("click", () => {
      activeDealTab = id;
      renderDashboard(deals);
    });
    return button;
  }));
}

function renderPipelineSummary(deals) {
  const counts = {
    all: deals.length,
    action: deals.filter((deal) => deal.status === "waiting_human").length,
    contact: deals.filter((deal) => dealPipelineTab(deal) === "contact").length,
    financial: deals.filter((deal) => financialDealThreadIds.has(deal.thread_id)).length,
  };
  pipelineSummary.innerHTML = [
    ["all", "All deals", counts.all],
    ["action", "Needs your action", counts.action],
    ["contact", "Contact work", counts.contact],
    ["financial", "Financial estimates", counts.financial],
  ].map(([kind, label, count]) => `<button type="button" class="pipeline-stat ${kind}" data-pipeline-stat="${kind}"><strong>${count}</strong><span>${label}</span></button>`).join("");
  pipelineSummary.querySelectorAll("[data-pipeline-stat]").forEach((button) => button.addEventListener("click", () => {
    const kind = button.dataset.pipelineStat;
    if (kind === "contact") activeDealTab = "contact";
    else if (kind === "financial") activeDealTab = "financials";
    else { activeDealTab = "analyze"; dealView.status = kind === "action" ? "needs-action" : "all"; dealStatusFilter.value = dealView.status; }
    renderDashboard(deals);
  }));
}

function syncDealControls(deals) {
  const cities = [...new Set(deals.map((deal) => deal.state?.property?.city).filter(Boolean))].sort();
  const selected = dealView.city;
  dealCityFilter.innerHTML = `<option value="">All locations</option>${cities.map((city) => `<option value="${escapeHtml(city)}"${city === selected ? " selected" : ""}>${escapeHtml(city)}</option>`).join("")}`;
  dealStatusFilter.value = dealView.status;
  dealSort.value = dealView.sort;
  dealCompareToggle.textContent = comparisonMode ? "Done comparing" : "Compare deals";
  dealCompareToggle.classList.toggle("active", comparisonMode);
}

function filterAndSortDeals(deals) {
  const filtered = deals.filter((deal) => {
    const city = deal.state?.property?.city || "";
    if (dealView.city && city !== dealView.city) return false;
    if (dealView.status === "needs-action") return deal.status === "waiting_human";
    if (dealView.status === "active") return ["running", "needs_research"].includes(deal.status);
    if (dealView.status === "rejected") return deal.status === "rejected";
    return true;
  });
  return filtered.sort((a, b) => {
    const propertyA = a.state?.property || {}; const propertyB = b.state?.property || {};
    const analysisA = a.state?.analysis || {}; const analysisB = b.state?.analysis || {};
    if (dealView.sort === "price-low") return (propertyA.asking_price?.amount || Infinity) - (propertyB.asking_price?.amount || Infinity);
    if (dealView.sort === "price-high") return (propertyB.asking_price?.amount || 0) - (propertyA.asking_price?.amount || 0);
    if (dealView.sort === "gap") return (analysisA.valuation?.price_gap_percent ?? Infinity) - (analysisB.valuation?.price_gap_percent ?? Infinity);
    return (analysisB.score ?? -1) - (analysisA.score ?? -1);
  });
}

function renderDealComparison(deals) {
  const selected = deals.filter((deal) => comparisonThreadIds.has(deal.thread_id));
  dealComparison.hidden = !comparisonMode;
  if (!comparisonMode) return;
  if (selected.length < 2) {
    dealComparison.innerHTML = `<p>Select two to four deals to compare their core numbers side by side.</p>`;
    return;
  }
  const row = (label, value) => `<tr><th>${label}</th>${selected.map((deal) => `<td>${value(deal)}</td>`).join("")}</tr>`;
  dealComparison.innerHTML = `<div class="comparison-heading"><div><p class="eyebrow">Comparison</p><h3>${selected.length} selected deals</h3></div><button type="button" class="ghost-button" data-clear-comparison>Clear selection</button></div><div class="comparison-table-wrap"><table><thead><tr><th>Measure</th>${selected.map((deal) => `<th>${escapeHtml(deal.state?.property?.title || "Untitled property")}</th>`).join("")}</tr></thead><tbody>${row("Asking price", (deal) => euros(deal.state?.property?.asking_price))}${row("Living area", (deal) => { const area = deal.state?.property?.living_area_sqm; return area ? `${area} m²` : "n.a."; })}${row("Price / m²", (deal) => { const property = deal.state?.property || {}; return property.asking_price?.amount && property.living_area_sqm ? financialEuros(property.asking_price.amount / property.living_area_sqm) : "n.a."; })}${row("Deal score", (deal) => deal.state?.analysis?.score == null ? "n.a." : `${deal.state.analysis.score}/100`)}${row("Price vs estimate", (deal) => { const gap = deal.state?.analysis?.valuation?.price_gap_percent; return gap == null ? "n.a." : `${gap.toFixed(1)}%`; })}${row("Comparables", (deal) => String(deal.state?.comparable_selections?.length || 0))}</tbody></table></div>`;
  dealComparison.querySelector("[data-clear-comparison]")?.addEventListener("click", () => { comparisonThreadIds.clear(); renderDashboard(Array.from(dealsByThreadId.values())); });
}

function wireComparablePanel(card, stage, comparableCount) {
  const button = card.querySelector(".deal-comparable-toggle");
  const panel = card.querySelector(".comparable-panel");
  if (!button || !panel) return;
  button.addEventListener("click", () => {
    const opening = panel.hidden;
    panel.hidden = !opening;
    button.setAttribute("aria-expanded", String(opening));
    button.textContent = opening ? "Hide Comparables" : `${comparableCount} Comparable${comparableCount === 1 ? "" : "s"}`;
    updateWorkflowStage(stage);
  });
}

dealGrid.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-decision], button[data-action]");
  if (!button) return;
  const card = button.closest(".deal-card");
  const panel = button.closest("[data-approval]");
  const deal = card ? dealsByThreadId.get(card.dataset.threadId) : null;
  if (!card || !panel || !deal) return;

  event.preventDefault();
  event.stopPropagation();
  const kind = panel.dataset.approval;
  const interrupt = deal.interrupts?.[0] || {};
  const send = (payload, confirmMessage) =>
    resumeDeal(deal.thread_id, payload, confirmMessage, card);

  if (kind === "shortlist") {
    const feedback = panel.querySelector(".feedback")?.value.trim();
    send({
      decision: button.dataset.decision,
      decided_by: "dashboard",
      ...(feedback ? { feedback } : {}),
    });
  } else if (kind === "contact_resolution") {
    send({ contact_id: panel.querySelector(".contact-select")?.value });
  } else if (kind === "outreach") {
    const decision = button.dataset.decision;
    const payload = { decision, decided_by: "dashboard" };
    if (decision === "approved") {
      payload.subject = panel.querySelector(".draft-subject")?.value || "";
      payload.body = panel.querySelector(".draft-body")?.value || "";
    }
    const confirmMessage = decision === "approved"
      ? `Approving will send the outreach email to ${interrupt.draft?.recipient_email || "the selected contact"} through the configured gateway (currently the local fake gateway). Continue?`
      : null;
    send(payload, confirmMessage);
  } else if (kind === "inbound_reply") {
    const times = (panel.querySelector(".reply-times")?.value || "")
      .split(",").map((item) => item.trim()).filter(Boolean);
    send({
      message_id: `manual-${Date.now()}`,
      sender_email: panel.querySelector(".reply-sender")?.value.trim() || "",
      received_at: new Date().toISOString(),
      body: panel.querySelector(".reply-body")?.value.trim() || "",
      ...(times.length ? { proposed_times: times } : {}),
    });
  } else if (kind === "schedule_exception") {
    send({ decision: button.dataset.decision, decided_by: "dashboard" });
  }
});

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

async function deleteDeal(deal) {
  const title = deal.state?.property?.title || "this deal";
  if (!window.confirm(`Delete ${title} from your local deal pipeline? This cannot be undone.`)) return;
  try {
    const response = await fetch(`/deals/${deal.thread_id}`, { method: "DELETE" });
    if (!response.ok) throw new Error(await readError(response));
    financialDealThreadIds.delete(deal.thread_id);
    localStorage.setItem("propertyscout-financial-deals", JSON.stringify([...financialDealThreadIds]));
    if (selectedFinancialThreadId === deal.thread_id) selectedFinancialThreadId = null;
    await loadDeals();
  } catch (error) {
    window.alert(`Could not delete this deal: ${error.message}`);
  }
}

function renderDashboard(deals) {
  dealsByThreadId = new Map(deals.map((deal) => [deal.thread_id, deal]));
  const sorted = [...deals].sort(
    (a, b) => (STATUS_PRIORITY[a.status] ?? 9) - (STATUS_PRIORITY[b.status] ?? 9)
  );
  dealCount.textContent = `${deals.length} deal${deals.length === 1 ? "" : "s"} tracked`;
  renderPipelineSummary(deals);
  syncDealControls(deals);
  if (sorted.length === 0) {
    renderDealTabs([]);
    dealGrid.replaceChildren();
    dashboardEmpty.textContent = "No deals yet. Start a property search above to create deals.";
    dashboardEmpty.hidden = false;
    return;
  }
  // A dashboard can contain deals at different stages. Keep the workflow card
  // attached to the deal the user selected, rather than guessing from another
  // waiting deal elsewhere in the pipeline.
  const focusedDeal = focusedWorkflowThreadId
    ? sorted.find((deal) => deal.thread_id === focusedWorkflowThreadId)
    : null;
  updateWorkflowStage(focusedDeal?.state?.current_stage || "discovery");
  renderDealTabs(sorted);
  if (activeDealTab === "financials") {
    dealControls.hidden = true;
    dealComparison.hidden = true;
    const financialDeals = sorted.filter((deal) => financialDealThreadIds.has(deal.thread_id));
    const selectedDeal = financialDeals.find((deal) => deal.thread_id === selectedFinancialThreadId) || financialDeals[0];
    if (!selectedDeal) {
      dashboardEmpty.textContent = "Choose Prepare Financials on a deal in Contact to open its financial estimates.";
      dashboardEmpty.hidden = false;
      dealGrid.replaceChildren();
    } else {
      selectedFinancialThreadId = selectedDeal.thread_id;
      const financialView = document.createElement("article");
      financialView.className = "financial-deal-view";
      financialView.innerHTML = `${financialDealPicker(financialDeals, selectedDeal.thread_id)}${financialPanel(selectedDeal)}`;
      dealGrid.replaceChildren(financialView);
      initialiseFinancialPanel(financialView, selectedDeal);
      financialView.querySelector(".financial-delete-button")?.addEventListener("click", () => deleteDeal(selectedDeal));
      financialView.querySelectorAll("[data-financial-deal-choice]").forEach((choice) => {
        choice.addEventListener("click", () => {
          selectedFinancialThreadId = choice.dataset.financialDealChoice;
          renderDashboard(Array.from(dealsByThreadId.values()));
        });
      });
      dashboardEmpty.hidden = true;
      focusWorkflowDeal(selectedDeal);
    }
    dashboardSection.hidden = false;
    return;
  }
  dealControls.hidden = false;
  const visibleDeals = filterAndSortDeals(sorted.filter((deal) => dealPipelineTab(deal) === activeDealTab));
  renderDealComparison(visibleDeals);
  dashboardEmpty.hidden = true;
  if (visibleDeals.length === 0) {
    dashboardEmpty.textContent = activeDealTab === "contact"
      ? "No deals are ready for contact work yet. Approve a deal in Analyze to move it here."
      : "No deals match these filters. Try another location or status.";
    dashboardEmpty.hidden = false;
  }
  dealGrid.replaceChildren(...visibleDeals.map(dealCard));
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
dealCityFilter.addEventListener("change", () => { dealView.city = dealCityFilter.value; renderDashboard(Array.from(dealsByThreadId.values())); });
dealStatusFilter.addEventListener("change", () => { dealView.status = dealStatusFilter.value; renderDashboard(Array.from(dealsByThreadId.values())); });
dealSort.addEventListener("change", () => { dealView.sort = dealSort.value; renderDashboard(Array.from(dealsByThreadId.values())); });
dealCompareToggle.addEventListener("click", () => {
  comparisonMode = !comparisonMode;
  if (!comparisonMode) comparisonThreadIds.clear();
  renderDashboard(Array.from(dealsByThreadId.values()));
});
loadDeals();

const discoverySection = document.querySelector("#discovery");
const discoveryGrid = document.querySelector("#discovery-grid");
const discoveryCount = document.querySelector("#discovery-count");
const discoveryDiagnostics = document.querySelector("#discovery-diagnostics");
const discoveryEmpty = document.querySelector("#discovery-empty");
const refreshDiscoveriesButton = document.querySelector("#refresh-discoveries");
const clearDiscoveriesButton = document.querySelector("#clear-discoveries");

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


let activeDiscoveryTab = "validated";
let currentDiscoveryRun = null;

function clearDiscoveryView(message = "No active discovery inventory. Start a property search to scout listings.") {
  currentSearchId = null;
  currentDiscoveryRun = null;
  activeDiscoveryTab = "validated";
  discoveryGrid.replaceChildren();
  document.querySelector("#discovery-tabs")?.replaceChildren();
  discoveryDiagnostics.replaceChildren();
  discoveryCount.textContent = "";
  discoveryEmpty.textContent = message;
  discoveryEmpty.hidden = false;
  discoverySection.hidden = false;
}

function renderDiscovery(run) {
  currentSearchId = run.search_id;
  currentDiscoveryRun = run;

  // Default to validated listings for every new search.
  activeDiscoveryTab = "validated";

  const counts = run.counts || {};
  const total = Object.values(counts).reduce(
    (sum, value) => sum + value, 0
  );

  const diagnostics = [
    `${total} discovered item(s)`,
    `${run.search_calls} search call(s)`,
    `${run.index_fetches} index fetch(es)`,
    `${run.detail_fetches} detail fetch(es)`,
  ];

  if (run.cross_query_duplicates) {
    diagnostics.push(
      `${run.cross_query_duplicates} duplicate URL(s) skipped`
    );
  }

  discoveryCount.textContent = diagnostics.join(" · ");

  const chips = Object.entries(counts)
    .map(([status, count]) => {
      const meta = DISCOVERY_STATUS_META[status] || {
        label: humanize(status),
      };
      return `<span class="count-chip">${meta.label}: ${count}</span>`;
    })
    .join("");

  const errorChips = (run.search_errors || [])
    .map(
      (error) =>
        `<span class="count-chip error">Search error: ${escapeHtml(error)}</span>`
    )
    .join("");

  discoveryDiagnostics.innerHTML = chips + errorChips;

  if (total === 0) {
    discoveryGrid.replaceChildren();
    discoveryEmpty.textContent =
      "No discoveries recorded for this search yet.";
    discoveryEmpty.hidden = false;
    discoverySection.hidden = false;
    return;
  }

  discoveryEmpty.hidden = true;
  discoverySection.hidden = false;

  renderDiscoveryTabs();
}

function renderDiscoveryTabs() {
  if (!currentDiscoveryRun) return;

  const records = currentDiscoveryRun.records || [];

  const validated = records.filter(
    (record) => record.status === "complete"
  );

  const others = records.filter(
    (record) => record.status !== "complete"
  );

  const tabs = document.getElementById("discovery-tabs");

  if (tabs) {
    tabs.innerHTML = `
      <button
        type="button"
        class="discovery-tab ${activeDiscoveryTab === "validated" ? "active" : ""}"
        data-tab="validated"
        aria-pressed="${activeDiscoveryTab === "validated"}"
      >
        Validated (${validated.length})
      </button>

      <button
        type="button"
        class="discovery-tab ${activeDiscoveryTab === "others" ? "active" : ""}"
        data-tab="others"
        aria-pressed="${activeDiscoveryTab === "others"}"
      >
        Other listings (${others.length})
      </button>
    `;

    tabs.querySelectorAll(".discovery-tab").forEach((button) => {
      button.addEventListener("click", () => {
        activeDiscoveryTab = button.dataset.tab;
        renderDiscoveryTabs();
      });
    });
  }

  const visibleRecords =
    activeDiscoveryTab === "validated" ? validated : others;

  discoveryGrid.replaceChildren(
    ...visibleRecords.map(discoveryCard)
  );

  discoveryEmpty.hidden = visibleRecords.length > 0;

  if (visibleRecords.length === 0) {
    discoveryEmpty.textContent =
      activeDiscoveryTab === "validated"
        ? "No validated properties found in this search."
        : "No other discovery records.";
  }
}


async function loadDiscoveries(searchId) {
  if (!searchId && !currentSearchId) {
    clearDiscoveryView();
    return;
  }
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

    if (searchId && !history.some((item) => item.search_id === searchId)) {
      throw new Error("The new discovery run could not be found.");
    }

    const runId = target || history[0].search_id;


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
  focusedWorkflowThreadId = null;
  updateWorkflowStage("analysis");
  const send = (body) =>
    fetch(`/discoveries/${currentSearchId}/deals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  try {
    const response = await send({ url, criteria: requestFromForm() });
    if (!response.ok) throw new Error(await readError(response));
    const createdDeal = await response.json();
    focusWorkflowDeal(createdDeal);
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
clearDiscoveriesButton.addEventListener("click", async () => {
  if (!currentSearchId) {
    clearDiscoveryView("There is no active discovery inventory to clear.");
    return;
  }
  if (!window.confirm("Clear this discovery inventory? Your existing deals will stay unchanged.")) return;
  const response = await fetch(`/discoveries/${currentSearchId}`, { method: "DELETE" });
  if (!response.ok) {
    discoveryEmpty.textContent = await readError(response);
    discoveryEmpty.hidden = false;
    return;
  }
  clearDiscoveryView("Discovery inventory cleared. Your deals are unchanged.");
});
clearDiscoveryView();

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  // A fresh Scout run must not show either tab from the previous inventory.
  clearDiscoveryView("Scouting properties…");
  resultsSection.hidden = true;
  resultGrid.replaceChildren();
  resultCount.textContent = "";

  errorBox.hidden = true;
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "Scouting properties…";
  try {
    const response = await fetch("/searches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestFromForm()),
    });
    const rawBody = await response.text();
    let body = {};
    try {
      body = rawBody ? JSON.parse(rawBody) : {};
    } catch {
      body = {};
    }
    if (!response.ok) {
      throw new Error(body.detail?.[0]?.msg || body.detail || `The search could not be started (server returned ${response.status}).`);
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

  discoveryGrid.replaceChildren();
  discoveryDiagnostics.replaceChildren();
  discoveryCount.textContent = "";
  discoveryEmpty.textContent = "Search failed. No new results to display.";
  discoveryEmpty.hidden = false;
  discoverySection.hidden = false;
} finally {

    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Start property search";
  }
});
