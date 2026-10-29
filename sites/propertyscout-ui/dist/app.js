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
const propertyEducationSection = document.querySelector("#property-education");
const propertyEducationButton = document.querySelector("[data-property-education-nav]");
const educationDetail = document.querySelector("[data-education-detail]");
const howItWorksSection = document.querySelector("#how-it-works");
const howItWorksButton = document.querySelector("[data-how-it-works-nav]");
const howStageDetail = document.querySelector("[data-how-stage-detail]");
const workflowCard = document.querySelector("#workflow-card");
const workflowStatus = document.querySelector("#workflow-status");
const WORKSPACE_VIEWS = ["scout", "analyze", "contact", "financials", "documents", "property-education", "how-it-works"];
const savedWorkspaceView = localStorage.getItem("propertyscout-active-workspace");
let focusedWorkflowThreadId = null;
const savedDealTab = localStorage.getItem("propertyscout-active-deal-tab");
let activeDealTab = ["analyze", "contact", "financials", "documents"].includes(savedDealTab)
  ? savedDealTab
  : "analyze";
let activeSidebarItem = WORKSPACE_VIEWS.includes(savedWorkspaceView) ? savedWorkspaceView : "scout";
let selectedFinancialThreadId = null;
let selectedDocumentThreadId = null;
let dealsByThreadId = new Map();
let comparisonMode = false;
const comparisonThreadIds = new Set();
const dealView = { city: "", status: "all", sort: "score" };
const financialDealThreadIds = new Set(JSON.parse(localStorage.getItem("propertyscout-financial-deals") || "[]"));
const documentDealThreadIds = new Set(JSON.parse(localStorage.getItem("propertyscout-document-deals") || "[]"));
const documentConfirmations = JSON.parse(localStorage.getItem("propertyscout-document-confirmations") || "{}");
const documentReviewSummaries = JSON.parse(localStorage.getItem("propertyscout-document-review-summaries") || "{}");

function confirmedDocumentLabels(threadId) {
  return new Set(documentConfirmations[threadId] || []);
}

function toggleDocumentConfirmation(threadId, label) {
  const confirmed = confirmedDocumentLabels(threadId);
  if (confirmed.has(label)) confirmed.delete(label);
  else confirmed.add(label);
  documentConfirmations[threadId] = [...confirmed];
  localStorage.setItem("propertyscout-document-confirmations", JSON.stringify(documentConfirmations));
}

function saveDocumentReviewSummary(threadId, summary) {
  documentReviewSummaries[threadId] = summary;
  localStorage.setItem("propertyscout-document-review-summaries", JSON.stringify(documentReviewSummaries));
}

function rememberWorkspace(view) {
  activeSidebarItem = view;
  localStorage.setItem("propertyscout-active-workspace", view);
}

function closeLearningViews() {
  propertyEducationSection.hidden = true;
  howItWorksSection.hidden = true;
  howItWorksButton?.classList.remove("active");
  propertyEducationButton?.classList.remove("active");
}

function showScoutWorkspace({ focus = false } = {}) {
  closeLearningViews();
  document.querySelectorAll(".hero, .workspace, #results, #discovery").forEach((section) => { section.hidden = false; });
  dashboardSection.hidden = true;
  rememberWorkspace("scout");
  document.querySelector("[data-scout-nav]")?.classList.add("active");
  dealTabs.querySelectorAll(".deal-tab").forEach((item) => item.classList.remove("active"));
  if (focus) {
    form.scrollIntoView({ behavior: "smooth", block: "start" });
    form.querySelector("input, select")?.focus({ preventScroll: true });
  }
}

function showDealWorkspace() {
  closeLearningViews();
  document.querySelectorAll(".hero, .workspace, #results, #discovery").forEach((section) => { section.hidden = true; });
  dashboardSection.hidden = false;
  rememberWorkspace(activeDealTab);
  document.querySelector("[data-scout-nav]")?.classList.remove("active");
}

function showHowItWorks() {
  document.querySelectorAll(".hero, .workspace, #results, #discovery, #dashboard").forEach((section) => { section.hidden = true; });
  propertyEducationSection.hidden = true;
  howItWorksSection.hidden = false;
  rememberWorkspace("how-it-works");
  document.querySelector("[data-scout-nav]")?.classList.remove("active");
  dealTabs.querySelectorAll(".deal-tab").forEach((item) => item.classList.remove("active"));
  howItWorksButton?.classList.add("active");
  propertyEducationButton?.classList.remove("active");
  howItWorksSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function showPropertyEducation() {
  document.querySelectorAll(".hero, .workspace, #results, #discovery, #dashboard").forEach((section) => { section.hidden = true; });
  howItWorksSection.hidden = true;
  propertyEducationSection.hidden = false;
  rememberWorkspace("property-education");
  document.querySelector("[data-scout-nav]")?.classList.remove("active");
  dealTabs.querySelectorAll(".deal-tab").forEach((item) => item.classList.remove("active"));
  howItWorksButton?.classList.remove("active");
  propertyEducationButton?.classList.add("active");
  if (!propertyEducationSection.querySelector(".education-tile.active")) showEducationTopic("leverage");
  setEducationCategory(activeEducationCategory);
  propertyEducationSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function hideHowItWorks() {
  closeLearningViews();
}

const HOW_STAGE_DETAILS = {
  scout: {
    title: "Scout",
    description: "Define what a good investment looks like for you, then build a focused shortlist. You stay in control of which opportunities are worth taking into a deeper review.",
    features: [
      ["Set your buy criteria", "Choose the city or postcode, budget, minimum size and rooms, property type, and any additional requirements that matter to your strategy."],
      ["Find matching opportunities", "Start a search to collect available listings that fit those criteria in one place."],
      ["Review search results", "See each result’s basic property information and listing source before deciding whether it deserves closer attention."],
      ["Understand listing quality", "A clear status helps you separate usable listings from incomplete, rejected, or unavailable results—so you do not spend time on weak leads."],
      ["Choose your shortlist", "Select only the properties you want to investigate. They move to Analyze; the rest remain outside your active deal pipeline."],
    ],
  },
  analyze: {
    title: "Analyze",
    description: "Turn a listing into an informed investment decision. Compare the asking price with market evidence, understand the strongest and weakest facts, then decide whether it is worth contacting the seller or broker.",
    features: [
      ["See the deal score", "Open the score explanation to understand how the property performed in the initial screen and which information is still affecting confidence."],
      ["Check the market value", "Compare the asking price against selected comparable listings, including the price gap and the evidence used to estimate value."],
      ["Open the comparable listings", "Review the individual comparable properties behind the estimate instead of relying on a number without context."],
      ["Read the key facts quickly", "See concise details such as living area, rooms, price per m², build year, energy class, condition and standout features."],
      ["Spot missing information", "See important unanswered questions—such as rent, condition, energy, or market evidence—before you spend more time on the deal."],
      ["Review and decide", "Expand the decision review when you want the complete assessment, then approve, reject, or request a revision. Rejected listings keep a short explanation of why they did not pass."],
      ["Start from a PDF exposé", "Upload a new property exposé to create a new deal from the facts stated in the document, with supporting online evidence checked where available."],
      ["Compare shortlisted deals", "Choose up to four properties and compare their core price, size, score and comparable-market measures side by side."],
    ],
  },
  contact: {
    title: "Contact",
    description: "Use this stage for the properties that have earned more effort. Confirm who you are dealing with, fill the gaps that matter, and send a clear first message with the right questions.",
    features: [
      ["Know who represents the listing", "See whether the available evidence suggests a private seller, a broker, or is still unclear, alongside the named contact or agency when available."],
      ["Review contact details", "Open the contact panel to see the available contact route and go directly to the original listing when you need to verify it."],
      ["Send a stronger first enquiry", "Use the prepared outreach email, with the key requests highlighted, then open it as a Gmail draft when you are ready to send."],
      ["Prepare the right questions", "Get a focused checklist for the broker or seller, including the evidence that is still missing for this specific property."],
      ["Refresh key listing facts", "When you approve a deal for Contact, the app makes a further check for available property and contact information before you continue."],
      ["Add new broker evidence", "Upload a broker’s exposé or contact PDF for an existing deal. Only the details stated in that document are added to the property record."],
      ["Move into financial planning", "Choose Prepare Financials once you have enough facts to test the purchase and financing case."],
    ],
  },
  financial: {
    title: "Financial estimate",
    description: "Test the numbers before you negotiate. Adjust the assumptions to reflect your own purchase, financing and rent plan, then use the result to decide what price you can justify.",
    features: [
      ["Model the full purchase", "Edit the assumptions that drive acquisition costs, rental income, financing, ownership costs and the tax estimate."],
      ["See the 10-year picture", "Review projected cash flow, property value, loan balance, equity and total wealth effect over ten years."],
      ["Check your return", "See the 10-year ROI on your initial cash alongside the upfront cash requirement, so a headline yield is not viewed in isolation."],
      ["Stress-test the plan", "Switch between base, conservative and optimistic scenarios to see how resilient the decision is when the assumptions change."],
      ["Use the charts", "Compare cash flow, equity, rental income, ownership costs and wealth over time through the interactive financial view."],
      ["Prepare a negotiation position", "Get an opening price and target price with a rationale based on the comparable-market evidence and the unresolved property risks."],
      ["Keep evidence in view", "The property’s price, size, rooms and comparable context stay next to the model so your assumptions remain grounded in the actual listing."],
      ["Send a ready deal to documents", "When the financial case is strong enough to progress, choose Documents & contracts to start the purchase-file review."],
    ],
  },
  documents: {
    title: "Documents & contract",
    description: "Build a clear purchase file before you commit. Keep each property’s paperwork separate, see what is still missing, and identify the points to clarify before a notary appointment.",
    features: [
      ["Work on one property at a time", "Choose a property from the selector so its documents, requests and review results stay separate from every other deal."],
      ["Use the standard purchase checklist", "Track the core paperwork commonly needed for a purchase, including items such as the land-register extract, draft contract, energy certificate and floor plan."],
      ["See listing-specific requests", "Get an additional checklist based on the property’s particular characteristics and the gaps found during analysis."],
      ["Upload received documents", "Store PDFs, Word files, text files and images with the selected property in your local workspace."],
      ["Track what has arrived", "Relevant checklist items are marked when matching documents are uploaded, making the remaining requests easy to see."],
      ["Review for discrepancies", "Compare extracted document facts with the listing and surface any clear contradictions that need clarification."],
      ["Prepare the contract conversation", "Review suggested contract topics and questions to raise with the broker, lender, adviser or notary before you sign."],
    ],
  },
};

const EDUCATION_DETAILS = {
  leverage: {
    title: "Build with leverage—not speculation",
    description: "Property is often attractive because you can combine your equity with long-term financing to buy a larger asset than cash alone would allow. With a carefully selected rental property, the rent can contribute to the property’s running costs and loan payments while your ownership share grows. The investment case should still work if prices stay flat: buy because the rent, financing and condition make sense, not because you assume a quick resale gain.",
    takeaways: ["Keep enough liquidity after the purchase instead of putting every euro into the down payment.", "Model the deal at today’s financing rate and include a higher-rate refinancing scenario.", "Treat a property as a long-term operating asset, not a short-term trading position."],
    link: ["Read Finanztip’s guide to rental property as an investment", "https://www.finanztip.de/baufinanzierung/immobilie-kapitalanlage/"],
  },
  tax: {
    title: "Use the tax framework intelligently",
    description: "Rental income is taxable, but eligible costs connected to earning it may reduce the taxable result. Depending on the property and your individual circumstances, this can include loan interest, certain operating and management costs, and depreciation of the building. Tax effects can improve a sound deal; they should never be the only reason to buy one. Discuss the assumptions and ownership structure with a qualified tax adviser before relying on them.",
    takeaways: ["Separate the purchase price allocation for land and building before estimating depreciation.", "Keep evidence for every deductible cost from day one.", "Compare the after-tax case with a conservative pre-tax cash-flow scenario."],
    link: ["Learn how investors assess rental-property returns", "https://www.finanztip.de/baufinanzierung/immobilie-kapitalanlage/"],
  },
  asset: {
    title: "Own a real, useful asset",
    description: "Housing meets an everyday need. A well-located, well-maintained home can remain relevant to tenants through changing market cycles, giving the investment a practical income base. That does not mean every property is investable: local employment, transport, liveability, energy efficiency, layout and the building’s condition all influence future tenant demand and resale appeal.",
    takeaways: ["Study the immediate neighbourhood, not just the city’s average statistics.", "Prioritise a layout, condition and energy profile a future tenant can understand and value.", "Ask whether you would still want to own the property if the market were slower for several years."],
    link: ["Explore a consumer checklist for assessing a property purchase", "https://www.finanztip.de/baufinanzierung/immobilie-kapitalanlage/"],
  },
  risk: {
    title: "Protect the downside before chasing return",
    description: "The most durable property investments are underwritten for the difficult months, not the perfect ones. Consider a vacancy period, a rent that grows more slowly than expected, a higher refinancing rate, a special owners’ association assessment or a repair that cannot be postponed. If the cash reserve and monthly plan can absorb those events, your decisions are calmer and your negotiation position is stronger.",
    takeaways: ["Add every acquisition cost: transfer tax, notary, land register and any broker fee.", "Review homeowners’ association minutes, reserves and planned works before buying a condominium.", "Keep a dedicated reserve for repairs and income interruptions."],
    link: ["Read the Verbraucherzentrale guide to financing and purchase costs", "https://www.verbraucherzentrale.de/wissen/geld-versicherungen/bau-und-immobilienfinanzierung/immobilienfinanzierung-haeufige-fragen-rund-um-hauskauf-und-hauskredit-6992"],
  },
  process: {
    title: "Follow a repeatable process",
    description: "Professional investors make fewer emotional decisions because they compare opportunities through the same sequence every time. Define your strategy and cash limit, use Scout to create a shortlist, use Analyze to test the price and evidence, then contact only the strongest deals. Before an offer, review the financial scenario and request the documents that reveal the property’s real obligations.",
    takeaways: ["Write your buy criteria before you see the next attractive listing.", "Move a deal forward only when the evidence earned the next step.", "Keep the property facts, calculations and documents together so you can explain your decision."],
    link: ["See common property-financing considerations", "https://www.verbraucherzentrale.de/wissen/geld-versicherungen/bau-und-immobilienfinanzierung/immobilienfinanzierung-diese-modelle-gibt-es-und-das-sollten-sie-beachten-5801"],
  },
  cashflow: {
    title: "Let cash flow lead the decision",
    description: "Gross yield is a helpful first filter, but it is not the return you keep. A purchase becomes investable when the rent, interest, repayment, management, non-recoverable costs, maintenance and vacancy allowance work together. Testing these assumptions makes it easier to identify the price at which the deal becomes sensible—and gives you a clear rationale when negotiating with a broker or seller.",
    takeaways: ["Use realistic achievable rent, not the most optimistic asking-rent estimate.", "Model monthly cash flow alongside the longer-term ROI and refinancing risk.", "Set a walk-away price before the conversation becomes emotional."],
    link: ["Use an independent guide to test a rental-property investment", "https://www.finanztip.de/baufinanzierung/immobilie-kapitalanlage/"],
  },
  pricing: {
    title: "Underwrite the all-in purchase price",
    description: "The advertised price is only the starting point. A defensible investment compares the price per square metre with genuinely comparable local sales and listings, then adds every acquisition cost before assessing return. Broker terms, transfer tax, notary, land-register fees and any immediate works belong in the same decision—not in a separate afterthought.",
    takeaways: ["Compare price per m² only with nearby homes of similar age, condition, floor, size and tenure.", "Model transfer tax, notary, land-register and broker costs in the initial cash requirement.", "Confirm the broker engagement and fee split before treating any advertised price as all-in.", "Set a maximum all-in purchase price before opening negotiations."],
    link: ["Read the Verbraucherzentrale guide to buying and financing", "https://www.verbraucherzentrale.de/wissen/geld-versicherungen/bau-und-immobilienfinanzierung/immobilienfinanzierung-haeufige-fragen-rund-um-hauskauf-und-hauskredit-6992"],
  },
  building: {
    title: "Read the building, not only the apartment",
    description: "A bright kitchen or fresh paint can conceal expensive building-level work. The investor case should reflect the roof, facade, pipes, windows, electrical installation, balconies, lift, insulation and heating—not only the condition inside the unit. Area calculations and layout also affect rent, valuation and future tenant appeal.",
    takeaways: ["Verify the living-area calculation; a difference in m² changes both yield and valuation.", "Assess the floor plan, storage, daylight, access and floor level for the target tenant—not just nominal size.", "Identify deferred repairs and understand their timing, scope and likely funding source.", "Review energy class, heating type, system age and practical retrofit options."],
    link: ["Understand current heating and energy rules for existing buildings", "https://www.bmwsb.bund.de/DE/bauen/innovation-klimaschutz/gebaeudeenergiegesetz/gebaeudeenergiegesetz_node.html"],
  },
  weg: {
    title: "Treat the WEG as part of the asset",
    description: "When buying a condominium, you are also buying into a homeowners’ association. The financial health, governance and maintenance position of the WEG can be as important as the apartment itself. A low reserve, unresolved repair backlog or planned major work can turn an apparently attractive unit into a costly investment.",
    takeaways: ["Read the last three owners’ meeting minutes for planned works, disputes and special assessments.", "Separate recoverable tenant costs from owner-only Hausgeld, management costs and reserve contributions.", "Review the reserve fund, annual statement and current economic plan rather than relying on one monthly Hausgeld figure.", "Request the declaration of division and community rules to understand rights, obligations and restrictions."],
    link: ["Use the German consumer guide to prepare a property purchase", "https://www.verbraucherzentrale.de/wissen/geld-versicherungen/bau-und-immobilienfinanzierung/immobilienfinanzierung-haeufige-fragen-rund-um-hauskauf-und-hauskredit-6992"],
  },
  legal: {
    title: "Verify the legal reality",
    description: "The listing description is not the legal record. Before making an offer, confirm ownership, land-register burdens, rights of way, residential rights, parking rights, permitted use and whether additions or conversions have the required approvals. These facts can determine whether a feature is valuable, restricted or not legally usable at all.",
    takeaways: ["Review the land-register extract for ownership, encumbrances, easements and existing land charges.", "For houses or plots, confirm boundaries, access and shared-driveway arrangements.", "Check permits and approved plans for extensions, attic conversions, balconies and changes of use.", "Confirm whether parking, garage and storage are owned separately, special-use rights or simply advertised amenities."],
    link: ["Review the legal framework for German real-estate transfers", "https://www.gesetze-im-internet.de/grestg_1983/"],
  },
  tenancy: {
    title: "Invest in the income, not the headline rent",
    description: "A rental investment is an operating asset. Establish who the likely tenant is, what rent is sustainable, and what the current tenancy actually permits. Current rent, achievable rent, rent regulation, vacancy, lease clauses and reletting costs should all be tested before a yield figure is trusted.",
    takeaways: ["Verify current rent, deposit, arrears, lease type, index or stepped-rent clauses and notice restrictions.", "Use realistic achievable rent and local Mietspiegel context—not the most optimistic advertised potential.", "Define the target tenant and test whether location, layout and condition genuinely serve that group.", "Model vacancy, reletting time and incentives alongside ongoing management and maintenance costs."],
    link: ["Learn the key questions to ask before financing a property", "https://www.verbraucherzentrale.de/wissen/geld-versicherungen/bau-und-immobilienfinanzierung/immobilienfinanzierung-diese-modelle-gibt-es-und-das-sollten-sie-beachten-5801"],
  },
  resilience: {
    title: "Plan for resilience and exit",
    description: "A property should remain investable through ordinary setbacks: a quieter rental market, an insurance claim, a repair, a refinancing event or slower price growth. Review environmental exposure, neighbourhood change, utilities and insurance alongside the exit strategy. The goal is a property you can comfortably hold, not one you must sell at the wrong time.",
    takeaways: ["Check building insurance, deductibles, past claims and flood or natural-hazard cover.", "Assess flood, heat, storm, groundwater, noise and planned development in the immediate area.", "Confirm broadband, utility capacity and practical future infrastructure such as EV charging.", "Model a long hold and a conservative resale: acquisition costs and early loan repayment can make a fast exit expensive."],
    link: ["Read consumer guidance on long-term property financing risk", "https://www.verbraucherzentrale.de/wissen/geld-versicherungen/bau-und-immobilienfinanzierung/immobilienfinanzierung-haeufige-fragen-rund-um-hauskauf-und-hauskredit-6992"],
  },
};

let activeEducationCategory = "foundation";

function setEducationCategory(category) {
  activeEducationCategory = category;
  const categoryButtons = propertyEducationSection?.querySelectorAll("[data-education-category-filter]") || [];
  const tiles = [...(propertyEducationSection?.querySelectorAll(".education-tile") || [])];
  categoryButtons.forEach((button) => {
    const active = button.dataset.educationCategoryFilter === category;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const visibleTiles = tiles.filter((tile) => {
    const visible = category === "all" || tile.dataset.educationCategory === category;
    tile.hidden = !visible;
    return visible;
  });
  const count = propertyEducationSection?.querySelector("[data-education-count]");
  if (count) count.textContent = `${visibleTiles.length} of ${tiles.length} investor lenses`;
  const selectedTile = propertyEducationSection?.querySelector(".education-tile.active");
  if (!selectedTile || selectedTile.hidden) showEducationTopic(visibleTiles[0]?.dataset.educationTopic);
}

function showEducationTopic(topic) {
  const detail = EDUCATION_DETAILS[topic];
  if (!detail || !educationDetail) return;
  propertyEducationSection.querySelectorAll(".education-tile").forEach((tile) => {
    const active = tile.dataset.educationTopic === topic;
    tile.classList.toggle("active", active);
    tile.setAttribute("aria-expanded", String(active));
  });
  const selectedDeal = dealsByThreadId.get(focusedWorkflowThreadId) || [...dealsByThreadId.values()][0];
  const dealLink = selectedDeal ? `<button type="button" class="education-deal-link" data-education-deal="${escapeHtml(selectedDeal.thread_id)}">See this in your selected deal</button>` : "";
  educationDetail.innerHTML = `<div><span>Investor lens</span><h3>${escapeHtml(detail.title)}</h3><p>${escapeHtml(detail.description)}</p></div><div><h4>Put it into practice</h4><ul>${detail.takeaways.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>${dealLink}<a href="${detail.link[1]}" target="_blank" rel="noopener">${escapeHtml(detail.link[0])} ↗</a></div>`;
  educationDetail.querySelector("[data-education-deal]")?.addEventListener("click", (event) => {
    const deal = dealsByThreadId.get(event.currentTarget.dataset.educationDeal);
    if (!deal) return;
    activeDealTab = dealPipelineTab(deal);
    showDealWorkspace();
    renderDashboard(Array.from(dealsByThreadId.values()));
    dashboardSection.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function wireEducationTiles() {
  propertyEducationSection?.addEventListener("click", (event) => {
    const categoryButton = event.target.closest("[data-education-category-filter]");
    if (categoryButton && propertyEducationSection.contains(categoryButton)) {
      setEducationCategory(categoryButton.dataset.educationCategoryFilter);
      return;
    }
    const tile = event.target.closest(".education-tile");
    if (!tile || !propertyEducationSection.contains(tile)) return;
    showEducationTopic(tile.dataset.educationTopic);
  });
}

function wireHowItWorksCards() {
  howItWorksSection?.querySelectorAll("[data-how-stage]").forEach((button) => {
    button.addEventListener("click", () => {
      const stage = button.dataset.howStage;
      const detail = HOW_STAGE_DETAILS[stage];
      if (!detail) return;
      const wasOpen = button.getAttribute("aria-expanded") === "true";
      howItWorksSection.querySelectorAll("[data-how-stage]").forEach((item) => {
        item.setAttribute("aria-expanded", "false");
        item.classList.remove("active");
      });
      if (wasOpen) {
        howStageDetail.hidden = true;
        howStageDetail.innerHTML = "";
        return;
      }
      button.setAttribute("aria-expanded", "true");
      button.classList.add("active");
      const features = detail.features.map(([title, description]) => `<article><strong>${escapeHtml(title)}</strong><p>${escapeHtml(description)}</p></article>`).join("");
      howStageDetail.innerHTML = `<div class="how-stage-summary"><span>Selected stage</span><div><strong>${escapeHtml(detail.title)}</strong><p>${escapeHtml(detail.description)}</p></div></div><div class="how-stage-features"><h3>What you can do here</h3>${features}</div>`;
      howStageDetail.hidden = false;
    });
  });
}

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
  { id: "analyze", label: "Analyze", icon: "⌕" },
  { id: "contact", label: "Contact", icon: "☏" },
  { id: "financials", label: "Financial Estimates", icon: "€" },
  { id: "documents", label: "Documents & Contract", icon: "▤" },
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
const euros = (money) => (money ? `${money.currency} ${Math.round(money.amount).toLocaleString("en-US")}` : "—");
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

function scoreExplanationPanel(analysis) {
  const score = analysis.score;
  const components = analysis.score_components;
  const drivers = Array.isArray(analysis.score_drivers) ? analysis.score_drivers : [];
  if (score == null || (!components && !drivers.length)) return "";
  const criteria = [
    ["value_gap", "Price vs. market estimate", 45],
    ["comp_confidence", "Comparable confidence", 20],
    ["condition_energy", "Condition & energy", 20],
    ["data_completeness", "Data completeness", 15],
  ];
  const rows = drivers.length
    ? drivers.map((driver) => `<li><div><span>${escapeHtml(driver.label)}</span><small>${escapeHtml(driver.detail)}</small></div><strong>${Number(driver.value || 0).toFixed(0)} <small>/ ${Number(driver.maximum || 0).toFixed(0)}</small></strong></li>`).join("")
    : criteria.map(([key, label, maximum]) => `<li><span>${escapeHtml(label)}</span><strong>${Number(components[key] || 0).toFixed(0)} <small>/ ${maximum}</small></strong></li>`).join("");
  return `<section class="score-explanation" data-score-panel hidden><div><p class="eyebrow">Deal score explained</p><h4>${score}/100</h4></div><p>The score is a screening aid based on the saved listing and comparable data. It is not a valuation or investment recommendation.</p><ul>${rows}</ul></section>`;
}

function evidenceConfidencePanel(analysis) {
  const confidence = analysis?.confidence;
  if (!confidence?.level || !confidence?.reason) return "";
  return `<section class="evidence-confidence confidence-${escapeHtml(confidence.level)}"><div><p class="eyebrow">Evidence confidence</p><h4>${escapeHtml(confidence.level)}</h4></div><p>${escapeHtml(confidence.reason)}</p></section>`;
}

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
  ].filter(Boolean).sort((a, b) => Number(a.includes("not stated")) - Number(b.includes("not stated")));
}

function propertyEnergyClass(property) {
  if (property.energy_class) return property.energy_class;
  const evidence = (property.evidence || []).map((item) => item.excerpt || "").join("\n");
  return evidence.match(/(?:energie(?:effizienz)?klasse|energieausweis)\s*[:\-]?\s*(?:klasse\s*)?([A-G](?:\+\+)?)/i)?.[1]?.toUpperCase() || null;
}

function propertyFeaturePanel(property, analysis) {
  const description = `${property.description || ""} ${(property.features || []).join(" ")}`;
  const floor = description.match(/\b(?:\d{1,2}\.?\s*(?:og|etage)|erdgeschoss|dachgeschoss|obergeschoss)\b/i)?.[0];
  const pricePerSqm = property.asking_price?.amount && property.living_area_sqm
    ? { amount: property.asking_price.amount / property.living_area_sqm, currency: property.asking_price.currency }
    : null;
  const energyClass = propertyEnergyClass(property);
  const detailFacts = evidenceFeatureFacts(property)
    .filter((fact) => /(?:heating|current cold rent|monthly service charge|rental income|modernisation|available from)/i.test(fact))
    .slice(0, 2);
  const listingFeatures = (property.features || [])
    .map((feature) => String(feature).replace(/\s+/g, " ").trim())
    .filter((feature) => feature && feature.length <= 42)
    .slice(0, 4);
  const items = [
    property.property_type ? humanize(property.property_type) : null,
    property.room_count ? `${property.room_count} rooms` : null,
    property.living_area_sqm ? `${property.living_area_sqm} m²` : null,
    property.asking_price ? euros(property.asking_price) : null,
    pricePerSqm ? `${euros(pricePerSqm)}/m²` : null,
    ...listingFeatures,
    property.build_year ? `Built ${property.build_year}` : null,
    energyClass ? `Energy ${energyClass}` : null,
    property.condition ? humanize(property.condition) : null,
    floor ? floor : null,
    ...detailFacts,
  ].filter(Boolean).slice(0, 9);
  if (!items.length) return "";
  return `<section class="property-features-panel"><strong>At a glance</strong><div>${items.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></section>`;
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
        <p>Review the summary and valuation above, then decide whether this property should move into contact research.</p>
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
  const text = [property?.title, property?.description, ...(property?.features || []), ...(property?.evidence || []).map((item) => item.excerpt || "")].filter(Boolean).join(" ").toLocaleLowerCase();
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
  const contact = state.selected_contact || state.contact_candidates?.[0];
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
      ${contact ? `<p><strong>${escapeHtml(contact.name)}</strong> · ${confidence}% confidence</p><p>${fields || "A contact was found, but no direct email or phone number was saved."}</p>` : `<p><strong>No named contact was present in the saved listing evidence.</strong></p><p>${phoneOnly ? "A phone contact was found, but no email address is available." : nextStep}</p>`}
      <p>${listingAction}</p>
      <button type="button" class="ghost-button" data-enrich-contact>Refresh listing facts & contact</button>
      <small>Runs one additional Keyless listing fetch for this deal (maximum five credits; this action is recorded and will not repeat on refresh).</small>
      <small>Contact information is extracted only from the selected listing page.</small>
      ${deal.pending_approval_type === "contact_resolution" ? approvalPanelHTML(deal) : ""}
    </section>`;
}

function emailPreview(body) {
  return body.split("\n").map((line) => {
    const content = escapeHtml(line);
    return line.startsWith("- ") ? `<strong>${content}</strong>` : content;
  }).join("<br>");
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
      ${action ? `<a class="gmail-draft-button" href="${escapeHtml(gmailUrl.href)}" target="_blank" rel="noopener">Draft in Gmail ↗</a>` : `<label>Subject<input readonly value="${escapeHtml(subject)}" /></label><div class="outreach-email-preview" aria-label="Outreach email preview">${emailPreview(body)}</div><a class="gmail-draft-button" href="${escapeHtml(gmailUrl.href)}" target="_blank" rel="noopener">Draft in Gmail ↗</a><small>Key request lines are highlighted in this preview. Gmail opens a plain-text draft and does not send anything.</small>`}
      ${action || awaitingReply}
    </section>`;
}

function valuationQuestions(property, analysis) {
  return [
    "Establish vacancy or tenancy: current rent, deposit, indexation, tenant duration, notice position and realistic market rent.",
    "Request the last three owners' association minutes, reserve balance, house rules and all planned or approved special assessments.",
    "Break down monthly service charges into recoverable and non-recoverable costs, plus property tax and insurance.",
    "Confirm condition and dates of major works: roof, façade, windows, heating, electrics, plumbing, bathrooms and kitchen.",
    "Review the energy certificate, heating system, energy class and likely efficiency upgrades or regulatory costs.",
    "Check title and legal constraints: leasehold, easements, occupancy rights, heritage restrictions and outstanding liabilities.",
    analysis.thesis ? `Test the valuation thesis against the listing claims: ${analysis.thesis}` : "Understand the seller's timing, decision process and appetite for a straightforward transaction.",
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
  const price = Number(property.asking_price?.amount) || 0;
  const pricePerSqm = area ? price / area : 0;
  const annualRent = Number(property.annual_rent?.amount) || 0;
  const evidence = (property.evidence || []).map((item) => item.excerpt || "").join(" ");
  const monthlyRent = Number(evidence.match(/(?:kaltmiete|nettokaltmiete)\s*[:\-]?\s*(?:ca\.?\s*)?([\d.]+(?:,\d+)?)/i)?.[1]?.replace(/\./g, "").replace(",", ".")) || 0;
  const monthlyServiceCharge = Number(evidence.match(/(?:hausgeld|wohngeld)\s*[:\-]?\s*(?:ca\.?\s*)?([\d.]+(?:,\d+)?)/i)?.[1]?.replace(/\./g, "").replace(",", ".")) || 0;
  const listingText = `${property.condition || ""} ${property.description || ""} ${evidence} ${(property.features || []).join(" ")}`;
  const needsRenovation = /renovierungsbedürftig|sanierungsbedürftig|renovation_needed|modernisierungsbedürftig/i.test(listingText);
  const isLet = annualRent > 0 || monthlyRent > 0 || /vermietet|mieteinnahmen/i.test(evidence);
  const buildYear = Number(property.build_year) || 0;
  const energyClass = propertyEnergyClass(property);
  const energyRisk = ["E", "F", "G"].includes(energyClass);
  const olderBuilding = buildYear > 0 && buildYear < 1985;
  const priceGap = Number(deal.state?.analysis?.valuation?.price_gap_percent);
  const hasBrokerFee = /(?:käuferprovision|courtage|provision)\b/i.test(listingText);
  const noBrokerFee = /provisionsfrei|ohne\s+provision/i.test(listingText);
  const targetYield = pricePerSqm >= 5000 ? 0.032 : pricePerSqm >= 3200 ? 0.04 : 0.048;
  const derivedRent = area && price ? price * targetYield / area / 12 : 18;
  const renovationRate = needsRenovation ? 0.08 : energyRisk ? 0.035 : olderBuilding ? 0.02 : 0;
  const assumptionBasis = [];
  if (annualRent || monthlyRent) assumptionBasis.push("rent stated in the listing");
  else if (pricePerSqm) assumptionBasis.push("asking price and size");
  if (monthlyServiceCharge) assumptionBasis.push("stated monthly service charge");
  if (needsRenovation || energyRisk || olderBuilding) assumptionBasis.push("building condition, age or energy data");
  if (Number.isFinite(priceGap)) assumptionBasis.push("comparable-market price gap");
  return {
    purchasePrice: price,
    renovation: Math.round(price * renovationRate / 1000) * 1000,
    acquisitionCostRate: noBrokerFee ? 0.075 : hasBrokerFee ? 0.1 : 0.09,
    rentPerSqm: area && (annualRent || monthlyRent) ? (annualRent || monthlyRent * 12) / area / 12 : derivedRent,
    occupancy: isLet ? 0.97 : 0.92,
    rentGrowth: isLet ? 0.02 : 0.025,
    appreciation: Number.isFinite(priceGap) ? (priceGap > 10 ? 0.012 : priceGap < -10 ? 0.025 : 0.018) : 0.02,
    loanToValue: price >= 600000 ? 0.8 : price >= 350000 ? 0.85 : 0.9,
    interestRate: 0.045,
    repaymentRate: 0.015,
    nonRecoverable: monthlyServiceCharge ? Math.round(monthlyServiceCharge * 0.3) : Math.max(45, Math.round(area * 1.15)),
    management: Math.max(30, Math.round(area * 0.65)),
    maintenancePerSqm: needsRenovation ? 0.9 : energyRisk || olderBuilding ? 0.7 : 0.45,
    repairs: needsRenovation ? Math.max(3000, Math.round(price * 0.01 / 500) * 500) : energyRisk || olderBuilding ? 1800 : 900,
    insurance: Math.max(350, Math.round(area * 7)),
    taxRate: 0.35,
    landShare: 0.1,
    depreciationRate: 0.025,
    maintenanceDeductionYears: 5,
    furniture: 0,
    assumptionBasis,
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

const FINANCIAL_MODEL_VERSION = "v2";

function financialScenarioKey(threadId, scenario) {
  return `propertyscout-financials:${FINANCIAL_MODEL_VERSION}:${threadId}:${scenario}`;
}

function negotiationTactic(deal) {
  const property = deal.state?.property || {};
  const asking = Number(property.asking_price?.amount) || 0;
  const valuation = Number(deal.state?.valuation?.estimated_value?.amount || deal.state?.valuation?.estimated_price?.amount || deal.state?.market_basis?.estimated_value?.amount) || 0;
  const comparablePrices = (deal.state?.comparable_selections || [])
    .map((selection) => Number(selection.listing?.asking_price?.amount))
    .filter(Boolean)
    .sort((a, b) => a - b);
  const median = comparablePrices.length ? comparablePrices[Math.floor(comparablePrices.length / 2)] : 0;
  const reference = valuation || median;
  if (!asking || !reference) return `<section class="negotiation-tactic"><p class="eyebrow">Negotiation tactic</p><h5>Build the evidence first</h5><p>No comparable-backed valuation is available yet. Ask for the exposé, recent owners’ association minutes, energy certificate, rent schedule, and condition evidence before making a price case.</p></section>`;
  const opening = Math.round(Math.min(asking, reference) * 0.95 / 1000) * 1000;
  const target = Math.round(Math.min(asking, reference) * 0.98 / 1000) * 1000;
  const gap = asking - reference;
  const rationale = gap > 0
    ? `The asking price is ${financialEuros(gap)} above the comparable-based reference. Lead with the valuation and ask the broker to explain the premium using condition, rent, or building evidence.`
    : `The asking price is already below the comparable-based reference. Use the bid to protect against unresolved condition, energy, and owners’ association risks rather than claiming the home is overpriced.`;
  return `<section class="negotiation-tactic"><p class="eyebrow">Negotiation tactic</p><h5>Open at ${financialEuros(opening)} · target ${financialEuros(target)}</h5><p>${escapeHtml(rationale)}</p><small>Reference: ${financialEuros(reference)}${comparablePrices.length ? ` from ${comparablePrices.length} selected comparable${comparablePrices.length === 1 ? "" : "s"}` : " from the market valuation"}. This is a negotiation aid, not a formal appraisal.</small></section>`;
}

function financialValidationPrompts(deal) {
  const property = deal.state?.property || {};
  const analysis = deal.state?.analysis || {};
  const prompts = [];
  if (!property.annual_rent) prompts.push("annual net rent or a current rent schedule");
  if (!property.energy_class) prompts.push("the energy certificate and energy class");
  if (!property.build_year) prompts.push("the build year and major modernization dates");
  if (!analysis.valuation) prompts.push("a comparable-backed market valuation");
  if (!prompts.length) return "";
  return `<aside class="financial-validation"><strong>Confirm with the seller or broker</strong><p>Before relying on the outcome, confirm ${escapeHtml(prompts.join(", "))}.</p></aside>`;
}

function financialPanel(deal) {
  const property = deal.state?.property || {};
  const scenario = localStorage.getItem(`propertyscout-financial-scenario:${deal.thread_id}`) || "base";
  const defaults = financialScenarioDefaults(deal, scenario);
  const price = property.asking_price?.amount || 0;
  const area = property.living_area_sqm || 0;
  const assumptionGroups = financialAssumptionGroups(defaults);
  const basis = defaults.assumptionBasis.length
    ? `Starting values use this listing’s ${defaults.assumptionBasis.join(", ")}.`
    : "Starting values use the available listing facts. Review and adjust them for your own financing and tax position.";
  return `<section class="financial-panel" data-financial-thread="${escapeHtml(deal.thread_id)}" data-financial-scenario="${scenario}"><div class="financial-header"><div><h4>10-year financial evaluation</h4><p>Adjust the assumptions, then use the model to compare cash flow, financing, tax and wealth over ten years.</p><p class="financial-review-reminder"><strong>Review &amp; adjust the assumptions below with the seller or broker. Keep them conservative.</strong></p></div><label class="financial-scenario">Scenario<select data-financial-scenario-select><option value="base"${scenario === "base" ? " selected" : ""}>Base case</option><option value="conservative"${scenario === "conservative" ? " selected" : ""}>Conservative</option><option value="optimistic"${scenario === "optimistic" ? " selected" : ""}>Optimistic</option></select><small>Stored for this deal in this browser</small></label></div><div class="financial-layout"><aside class="financial-deal-card"><span>Property facts</span><strong>${escapeHtml(property.title || "Untitled property")}</strong><p>${escapeHtml([property.postal_code, property.city].filter(Boolean).join(" "))}</p><div class="financial-deal-actions"><button type="button" class="ghost-button financial-documents-button">Documents & contracts</button><button type="button" class="deal-delete-button financial-delete-button">Delete deal</button></div><dl><div><dt>Purchase price</dt><dd data-financial-purchase-price>${financialEuros(price)}</dd></div><div><dt>Living area</dt><dd>${area ? `${area} m²` : "n.a."}</dd></div><div><dt>Rooms</dt><dd>${property.room_count || "n.a."}</dd></div><div><dt>Price / m²</dt><dd data-financial-price-sqm>${price && area ? financialEuros(price / area) : "n.a."}</dd></div></dl></aside><div class="financial-assumptions"><p class="eyebrow">Your assumptions</p><h5>Key assumptions</h5><p class="financial-assumption-guide">${escapeHtml(basis)}</p>${financialValidationPrompts(deal)}<button type="button" class="ghost-button financial-reset-button" data-financial-reset>Reset to listing-based values</button>${assumptionGroups}</div><div class="financial-results"><p class="eyebrow">Investment outcome</p><div class="financial-kpis"><div><span>Year 1 cash flow incl. initial cash</span><strong data-financial-metric="cashflow"></strong></div><div><span>Loan amount</span><strong data-financial-metric="loan"></strong></div><div><span>Year 10 equity</span><strong data-financial-metric="equity"></strong></div><div><span>10-year wealth effect</span><strong data-financial-metric="wealth"></strong></div><div><span>10-year ROI on initial cash</span><strong data-financial-metric="roi"></strong></div><div><span>Initial cash required</span><strong data-financial-metric="initial"></strong></div></div><div class="financial-charts"><figure><figcaption>Annual cash flow after tax, including initial cash in Year 1</figcaption><canvas data-financial-chart="cashflow" width="500" height="180"></canvas></figure><figure><figcaption>Property value vs. net equity</figcaption><canvas data-financial-chart="equity" width="500" height="180"></canvas></figure><figure><figcaption>Rental income vs. ownership costs</figcaption><canvas data-financial-chart="income-costs" width="500" height="180"></canvas></figure><figure><figcaption>Total wealth effect</figcaption><canvas data-financial-chart="wealth" width="500" height="180"></canvas></figure></div>${negotiationTactic(deal)}</div></div><div class="financial-table-wrap"><table class="financial-table"><thead><tr><th>Year</th><th>Rental income</th><th>Cash flow after tax</th><th>Property value</th><th>Net equity</th><th>Total wealth effect</th></tr></thead><tbody data-financial-table></tbody></table></div></section>`;
}

function financialValues(panel, deal) {
  const scenario = panel.dataset.financialScenario || "base";
  const defaults = financialScenarioDefaults(deal, scenario);
  const saved = JSON.parse(localStorage.getItem(financialScenarioKey(deal.thread_id, scenario)) || "{}");
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
  panel.querySelector("[data-financial-metric='roi']").textContent = first.initialCash > 0 ? percent((last.wealth - first.initialCash) / first.initialCash) : "n.a.";
  panel.querySelector("[data-financial-purchase-price]").textContent = financialEuros(inputs.purchasePrice);
  panel.querySelector("[data-financial-price-sqm]").textContent = property.living_area_sqm
    ? financialEuros(inputs.purchasePrice / property.living_area_sqm)
    : "n.a.";
  const origins = ["asking price", "living area", "rooms"]
    .map((field) => `${field}: ${factOrigin(deal, field)}`)
    .join(" · ");
  let originNote = panel.querySelector("[data-financial-fact-origin]");
  if (!originNote) {
    originNote = document.createElement("small");
    originNote.className = "financial-fact-origin";
    originNote.dataset.financialFactOrigin = "";
    panel.querySelector(".financial-deal-card dl")?.after(originNote);
  }
  if (originNote) originNote.textContent = `Source: ${origins}. Price / m² is calculated from the first two facts.`;
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
  panel.querySelector("[data-financial-reset]")?.addEventListener("click", () => {
    const scenario = panel.dataset.financialScenario || "base";
    localStorage.removeItem(financialScenarioKey(deal.thread_id, scenario));
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
  card.querySelector("[data-enrich-contact]")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = "Refreshing listing facts…";
    const response = await fetch(`/deals/${card.dataset.threadId}/enrich-contact`, { method: "POST" });
    if (!response.ok) {
      const result = await response.json().catch(() => ({}));
      button.disabled = false;
      button.textContent = result.detail || "Could not refresh listing facts";
      return;
    }
    await loadDeals();
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
  if (deal.status === "waiting_human") return "Open decision review";
  if (deal.status === "rejected") return "Open analysis review";
  return "Open deal review";
}

function nextBestActionPanel(deal) {
  const action = deal.next_best_action;
  if (!action?.label || !action?.detail || !action?.destination) return "";
  return `<section class="next-best-action"><div><p class="eyebrow">Next best action</p><h4>${escapeHtml(action.label)}</h4><p>${escapeHtml(action.detail)}</p></div><button type="button" data-next-best-action data-next-destination="${escapeHtml(action.destination)}">${escapeHtml(action.label)}</button></section>`;
}

function evidenceLedgerPanel(deal) {
  const items = deal.evidence_summary || [];
  if (!items.length) return "";
  return `<section class="evidence-ledger"><p class="eyebrow">Evidence ledger</p><h4>Where the key facts come from</h4><dl>${items.map((item) => `<div><dt>${escapeHtml(item.field)}</dt><dd>${escapeHtml(item.origin)}</dd></div>`).join("")}</dl></section>`;
}

function factOrigin(deal, field) {
  return deal.evidence_summary?.find((item) => item.field === field)?.origin || "Needs confirmation";
}

function rejectionExplanation(deal) {
  if (deal.status !== "rejected") return "";
  const state = deal.state || {};
  const reasons = state.scout_assessment?.reasons;
  if (Array.isArray(reasons) && reasons.length) return reasons.join(" · ");
  if (state.analysis?.thesis) return state.analysis.thesis;
  const rejectedApproval = Object.values(state.approvals || {}).find(
    (approval) => approval?.decision === "rejected" && approval.feedback,
  );
  return rejectedApproval?.feedback || "";
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
  const rejectionReason = rejectionExplanation(deal);
  const listingKind = listingContactContext(property, state.selected_contact || state.contact_candidates?.[0]);
  const dealLinks = [
    listingUrl
      ? `<a class="deal-source-link" href="${escapeHtml(listingUrl)}" target="_blank" rel="noopener">View listing ↗</a>`
      : "",
    `<button type="button" class="deal-comparable-toggle" aria-expanded="false" aria-label="Show ${comparableCount} comparable listings">${comparableCount} Comparable${comparableCount === 1 ? "" : "s"}</button>`,
  ].filter(Boolean).join("");

  card.innerHTML = `
    <div class="result-meta">
      <span>${escapeHtml(property.postal_code || property.city || "")}</span>
      <span class="status ${meta.cls}">${escapeHtml(deal.workflow_label || meta.label)}</span>
      ${rejectionReason ? `<span class="rejection-explanation" title="${escapeHtml(rejectionReason)}">${escapeHtml(rejectionReason)}</span>` : ""}
      ${comparisonMode ? `<label class="compare-choice"><input type="checkbox" data-compare-choice ${comparisonThreadIds.has(deal.thread_id) ? "checked" : ""} /> Compare</label>` : ""}
      <button type="button" class="deal-delete-button" aria-label="Delete this deal">Delete</button>
    </div>
    <h3>${escapeHtml(property.title || "Untitled property")}</h3>
    <div class="deal-metrics">
      <button type="button" class="score-badge score-explainer" data-score-explanation aria-expanded="false" title="Explain deal score">Deal Score ${score == null ? "—" : `${score}/100`} <span aria-hidden="true">?</span></button>
      <span>${percent(yieldValue)} gross yield</span>
      <span>${cashFlow ? `${euros(cashFlow)}/mo` : "—"}</span>
      <span>${property.build_year ? `Built ${property.build_year}` : "—"}</span>
      <span>${property.energy_class ? `Energy ${escapeHtml(property.energy_class)}` : "—"}</span>
      ${analysis.confidence?.level ? `<span class="evidence-confidence-badge confidence-${escapeHtml(analysis.confidence.level)}">Evidence ${escapeHtml(analysis.confidence.level)}</span>` : ""}
      <span class="listing-kind ${listingKind.uncertain ? "uncertain" : ""}" title="${escapeHtml(listingKind.detail)}">${listingKind.uncertain ? "◌" : listingKind.label.startsWith("Broker") ? "▣" : "◇"} ${escapeHtml(listingKind.label.replace(" listing", ""))}</span>
    </div>
    <p class="deal-summary">${escapeHtml(summary)}</p>
    <button type="button" class="decision-review-toggle" data-deal-details aria-expanded="false" aria-label="${primaryDealAction(deal)}" title="${primaryDealAction(deal)}">⌄</button>
    <div class="deal-details" hidden>
      <div class="deal-links">${dealLinks}<button type="button" class="ghost-button print-summary-button" data-print-summary>Print deal summary</button></div>
      ${comparablePanelHTML(state.comparable_selections || [])}
      ${propertyMetrics(property)}
      ${nextBestActionPanel(deal)}
      ${evidenceLedgerPanel(deal)}
      ${evidenceConfidencePanel(analysis)}
      ${scoreExplanationPanel(analysis)}
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
  card.querySelector("[data-print-summary]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    document.querySelectorAll(".print-target").forEach((item) => item.classList.remove("print-target"));
    card.classList.add("print-target");
    document.body.classList.add("printing-deal");
    window.print();
    window.setTimeout(() => {
      card.classList.remove("print-target");
      document.body.classList.remove("printing-deal");
    }, 0);
  });
  card.querySelector("[data-score-explanation]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    const details = card.querySelector(".deal-details");
    const panel = card.querySelector("[data-score-panel]");
    if (!panel) return;
    details.hidden = false;
    panel.hidden = !panel.hidden;
    const expanded = !panel.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(expanded));
    event.currentTarget.title = expanded ? "Hide deal score explanation" : "Explain deal score";
    const reviewToggle = card.querySelector("[data-deal-details]");
    if (reviewToggle) {
      reviewToggle.textContent = "⌃";
      reviewToggle.setAttribute("aria-expanded", "true");
      reviewToggle.setAttribute("aria-label", "Close decision review");
      reviewToggle.title = "Close decision review";
    }
  });
  card.querySelector("[data-deal-details]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    const details = card.querySelector(".deal-details");
    const opening = details.hidden;
    details.hidden = !opening;
    if (!opening) {
      card.querySelector("[data-score-panel]")?.setAttribute("hidden", "");
      card.querySelector("[data-score-explanation]")?.setAttribute("aria-expanded", "false");
    }
    event.currentTarget.setAttribute("aria-expanded", String(opening));
    const label = opening ? "Close decision review" : primaryDealAction(deal);
    event.currentTarget.textContent = opening ? "⌃" : "⌄";
    event.currentTarget.setAttribute("aria-label", label);
    event.currentTarget.title = label;
  });
  card.querySelector("[data-next-best-action]")?.addEventListener("click", (event) => {
    event.stopPropagation();
    const destination = event.currentTarget.dataset.nextDestination;
    if (!["analyze", "contact", "financials", "documents"].includes(destination)) return;
    activeDealTab = destination;
    localStorage.setItem("propertyscout-active-deal-tab", activeDealTab);
    showDealWorkspace();
    renderDashboard(Array.from(dealsByThreadId.values()));
    dashboardSection.scrollIntoView({ behavior: "smooth", block: "start" });
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
  const counts = { analyze: 0, contact: 0, documents: 0 };
  deals.forEach((deal) => { counts[dealPipelineTab(deal)] += 1; });
  const financialCount = deals.filter((deal) => financialDealThreadIds.has(deal.thread_id)).length;
  const documentCount = deals.filter((deal) => documentDealThreadIds.has(deal.thread_id)).length;
  dealTabs.replaceChildren(...DEAL_TABS.map(({ id, label, icon }) => {
    const button = document.createElement("button");
    button.type = "button";
    // Learning pages can load the deal data in the background. Only highlight
    // a pipeline stage when that stage is the page the investor is viewing.
    const isCurrentWorkspace = activeSidebarItem === id;
    button.className = `deal-tab${isCurrentWorkspace ? " active" : ""}`;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(isCurrentWorkspace));
    const count = id === "financials" ? financialCount : id === "documents" ? documentCount : counts[id];
    button.innerHTML = `<span class="stage-icon" aria-hidden="true">${icon}</span><span>${label} (${count})</span>`;
    button.addEventListener("click", () => {
      activeDealTab = id;
      renderDashboard(deals);
      dashboardSection.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    return button;
  }));
  document.querySelector("[data-scout-nav]")?.classList.toggle("active", activeSidebarItem === "scout");
}

function renderPipelineSummary(deals) {
  const counts = {
    analyze: deals.filter((deal) => dealPipelineTab(deal) === "analyze").length,
    contact: deals.filter((deal) => dealPipelineTab(deal) === "contact").length,
    financial: deals.filter((deal) => financialDealThreadIds.has(deal.thread_id)).length,
    documents: deals.filter((deal) => documentDealThreadIds.has(deal.thread_id)).length,
  };
  pipelineSummary.innerHTML = [
    ["analyze", "Analyze", counts.analyze],
    ["contact", "Contact work", counts.contact],
    ["financial", "Financial estimates", counts.financial],
    ["documents", "Documents & contract", counts.documents],
  ].map(([kind, label, count]) => {
    const tab = kind === "financial" ? "financials" : kind;
    return `<button type="button" class="pipeline-stat ${kind}${activeDealTab === tab ? " active" : ""}" data-pipeline-stat="${kind}"><strong>${count}</strong><span>${label}</span></button>`;
  }).join("");
  pipelineSummary.querySelectorAll("[data-pipeline-stat]").forEach((button) => button.addEventListener("click", () => {
    const kind = button.dataset.pipelineStat;
    if (kind === "contact") activeDealTab = "contact";
    else if (kind === "financial") activeDealTab = "financials";
    else if (kind === "documents") activeDealTab = "documents";
    else { activeDealTab = "analyze"; dealView.status = "all"; dealStatusFilter.value = dealView.status; }
    activeSidebarItem = activeDealTab;
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
  const unavailable = "Needs confirmation";
  dealComparison.innerHTML = `<div class="comparison-heading"><div><p class="eyebrow">Comparison</p><h3>${selected.length} selected deals</h3><p>Numbers that are not evidenced are shown as needing confirmation rather than treated as zero.</p></div><button type="button" class="ghost-button" data-clear-comparison>Clear selection</button></div><div class="comparison-table-wrap"><table><thead><tr><th>Measure</th>${selected.map((deal) => `<th>${escapeHtml(deal.state?.property?.title || "Untitled property")}</th>`).join("")}</tr></thead><tbody>${row("Asking price", (deal) => euros(deal.state?.property?.asking_price) || unavailable)}${row("Living area", (deal) => { const area = deal.state?.property?.living_area_sqm; return area ? `${area} m²` : unavailable; })}${row("Price / m²", (deal) => { const property = deal.state?.property || {}; return property.asking_price?.amount && property.living_area_sqm ? financialEuros(property.asking_price.amount / property.living_area_sqm) : unavailable; })}${row("Deal score", (deal) => deal.state?.analysis?.score == null ? unavailable : `${deal.state.analysis.score}/100`)}${row("Evidence confidence", (deal) => deal.state?.analysis?.confidence?.level || unavailable)}${row("Price vs estimate", (deal) => { const gap = deal.state?.analysis?.valuation?.price_gap_percent; return gap == null ? unavailable : `${gap.toFixed(1)}%`; })}${row("Comparable evidence", (deal) => { const count = deal.state?.comparable_selections?.length || 0; return count ? `${count} comparable${count === 1 ? "" : "s"}` : unavailable; })}${row("Rent evidence", (deal) => deal.state?.property?.annual_rent?.amount ? `${financialEuros(deal.state.property.annual_rent.amount)} / year` : unavailable)}${row("Energy and building", (deal) => { const property = deal.state?.property || {}; const facts = [property.energy_class ? `Energy ${property.energy_class}` : null, property.build_year ? `Built ${property.build_year}` : null].filter(Boolean); return facts.length ? facts.join(" · ") : unavailable; })}${row("Workflow status", (deal) => deal.workflow_label || unavailable)}${row("Next action", (deal) => deal.next_best_action?.label || unavailable)}</tbody></table></div>`;
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

const STANDARD_PURCHASE_DOCUMENTS = [
  { group: "Critical before an offer", label: "Land-register extract", keywords: ["grundbuch", "land register"], purpose: "Confirms ownership, registered rights, and encumbrances." },
  { group: "Critical before an offer", label: "Draft purchase contract", keywords: ["kaufvertrag", "purchase contract", "vertragsentwurf"], purpose: "Lets you review the proposed obligations before you commit." },
  { group: "Critical before an offer", label: "Energy certificate", keywords: ["energieausweis", "energy certificate"], purpose: "Supports your energy-cost and renovation-risk assessment." },
  { group: "Needed for financing", label: "Floor plan", keywords: ["grundriss", "floor plan"], purpose: "Helps verify the layout and usable space you are financing." },
  { group: "Needed for financing", label: "Living-area calculation", keywords: ["wohnflaeche", "wohnfläche", "living area"], purpose: "Confirms the stated area behind the price-per-square-metre calculation." },
  { group: "Needed for financing", label: "Building-insurance evidence", keywords: ["versicherung", "insurance"], purpose: "Shows how the building is insured and what may need clarification." },
  { group: "Due diligence", label: "Building description", keywords: ["baubeschreibung", "building description", "expose", "exposé"], purpose: "Records the stated condition, construction, and included features." },
  { group: "Due diligence", label: "Renovation and maintenance evidence", keywords: ["sanierung", "modernisierung", "renovierung", "instandhaltung"], purpose: "Helps you separate completed work from upcoming capital costs." },
  { group: "Due diligence", label: "Property handover record", keywords: ["uebergabe", "übergabe", "handover"], purpose: "Clarifies condition, meters, and handover responsibilities." },
  { group: "Due diligence", label: "Proof of ownership and seller authority", keywords: ["vollmacht", "power of attorney", "eigentum"], purpose: "Helps confirm that the seller or representative can act for the property." },
];

function normalizedDocumentName(value) {
  return String(value || "").toLocaleLowerCase("de-DE")
    .replace(/ä/g, "ae").replace(/ö/g, "oe").replace(/ü/g, "ue").replace(/ß/g, "ss");
}

function listingSpecificDocuments(deal) {
  const property = deal.state?.property || {};
  const listingText = normalizedDocumentName(`${property.property_type || ""} ${property.description || ""} ${(property.features || []).join(" ")}`);
  const isApartment = /apartment|wohnung|eigentumswohnung/.test(listingText);
  const isLet = Boolean(property.annual_rent) || /vermietet|mietvertrag|tenant/.test(listingText);
  const requirements = isApartment
    ? [
      ["Declaration of division", ["teilungserklaerung", "declaration of division"]],
      ["Community rules", ["gemeinschaftsordnung", "community rules"]],
      ["Allocation plan", ["aufteilungsplan", "allocation plan"]],
      ["Last 3–5 owners’ meeting minutes", ["eigentuemerversammlung", "protokoll", "weg"]],
      ["Current economic plan", ["wirtschaftsplan", "economic plan"]],
      ["Last 3 annual accounts", ["jahresabrechnung", "annual account"]],
      ["Reserve / asset report", ["vermoegensbericht", "ruecklage", "reserve"]],
      ["Resolution collection", ["beschlusssammlung", "resolution"]],
    ]
    : [
      ["Cadastral map and site plan", ["flurkarte", "lageplan", "cadastral", "site plan"]],
      ["Building permits and approvals", ["baugenehmigung", "building permit", "genehmigung"]],
      ["Utility and development-cost evidence", ["erschliessung", "development cost", "anschluss"]],
      ["Drainage / pipe inspection", ["kanal", "drainage", "rohr"]],
      ["Contamination and soil information", ["altlast", "contamination", "boden"]],
      ["Structural, roof and façade reports", ["dach", "fassade", "statik", "structural"]],
    ];
  if (isLet) requirements.push(
    ["Current tenancy agreement", ["mietvertrag", "tenancy agreement"]],
    ["Rent history and latest service-charge statement", ["mietaufstellung", "miete", "nebenkosten", "service charge"]],
  );
  return requirements.slice(0, 10);
}

function documentChecklistMarkup(title, requirements, files, className = "", threadId = "") {
  const uploadedNames = files.map((file) => normalizedDocumentName(file.name));
  const confirmed = confirmedDocumentLabels(threadId);
  const rows = requirements.map((item) => {
    const [label, keywords] = Array.isArray(item) ? item : [item.label, item.keywords];
    const purpose = Array.isArray(item) ? "Confirm this document with the broker before you commit." : item.purpose;
    const uploaded = keywords.some((keyword) => uploadedNames.some((name) => name.includes(normalizedDocumentName(keyword))));
    const manuallyConfirmed = confirmed.has(label);
    const complete = uploaded || manuallyConfirmed;
    const status = uploaded ? "Uploaded" : (manuallyConfirmed ? "Confirmed" : "Request");
    return `<li class="${complete ? "uploaded" : "missing"}"><span aria-hidden="true">${complete ? "✓" : "○"}</span><span><b>${escapeHtml(label)}</b><em>Why it matters: ${escapeHtml(purpose)}</em></span><button type="button" class="document-confirm-button" data-document-confirm="${escapeHtml(label)}">${manuallyConfirmed ? "Unconfirm" : "Confirm item"}</button><small>${status}</small></li>`;
  }).join("");
  return `<section class="document-checklist ${escapeHtml(className)}"><h4>${escapeHtml(title)}</h4><ul>${rows}</ul></section>`;
}

function standardDocumentChecklistMarkup(files, threadId) {
  const groups = ["Critical before an offer", "Needed for financing", "Due diligence"];
  return groups.map((group) => documentChecklistMarkup(
    group,
    STANDARD_PURCHASE_DOCUMENTS.filter((document) => document.group === group),
    files,
    group === "Critical before an offer" ? "document-checklist-critical" : "",
    threadId,
  )).join("");
}

dealGrid.addEventListener("click", async (event) => {
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
    const approved = button.dataset.decision === "approved";
    const resumed = await send({
      decision: button.dataset.decision,
      decided_by: "dashboard",
      ...(feedback ? { feedback } : {}),
    });
    if (approved && resumed) await enrichApprovedListing(deal.thread_id, card);
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
  if (confirmMessage && !window.confirm(confirmMessage)) return false;
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
    return true;
  } catch (error) {
    cardError.textContent = error.message;
    cardError.hidden = false;
    return false;
  }
}

async function enrichApprovedListing(threadId, card) {
  const cardError = card.querySelector(".card-error");
  const action = card.querySelector('[data-decision="approved"]');
  if (action) {
    action.disabled = true;
    action.textContent = "Checking listing facts…";
  }
  try {
    const response = await fetch(`/deals/${threadId}/enrich-contact`, { method: "POST" });
    if (!response.ok) throw new Error(await readError(response));
    await loadDeals();
  } catch (error) {
    cardError.textContent = `Approved and moved to Contact. Listing fact check could not finish: ${error.message}`;
    cardError.hidden = false;
    if (action) {
      action.disabled = false;
      action.textContent = "Approve";
    }
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

function renderDashboard(deals, { showWorkspace = true } = {}) {
  if (showWorkspace) showDealWorkspace();
  // Refreshing the page or the deal list should keep the investor in the
  // workflow stage they were reviewing, rather than returning to Analyze.
  localStorage.setItem("propertyscout-active-deal-tab", activeDealTab);
  dealGrid.dataset.stage = activeDealTab;
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
      financialView.querySelector(".financial-documents-button")?.addEventListener("click", () => {
        documentDealThreadIds.add(selectedDeal.thread_id);
        localStorage.setItem("propertyscout-document-deals", JSON.stringify([...documentDealThreadIds]));
        selectedDocumentThreadId = selectedDeal.thread_id;
        activeDealTab = "documents";
        rememberWorkspace("documents");
        renderDashboard(Array.from(dealsByThreadId.values()));
        document.querySelector("#dashboard")?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      financialView.querySelectorAll("[data-financial-deal-choice]").forEach((choice) => {
        choice.addEventListener("click", () => {
          selectedFinancialThreadId = choice.dataset.financialDealChoice;
          renderDashboard(Array.from(dealsByThreadId.values()));
        });
      });
      dashboardEmpty.hidden = true;
      focusWorkflowDeal(selectedDeal);
    }
    if (showWorkspace) dashboardSection.hidden = false;
    return;
  }
  if (activeDealTab === "documents") {
    dealControls.hidden = true;
    dealComparison.hidden = true;
    const eligibleDocumentDeals = sorted.filter((deal) => documentDealThreadIds.has(deal.thread_id));
    if (!eligibleDocumentDeals.length) {
      dealGrid.innerHTML = `<div class="empty-note"><strong>No properties are in Documents & contracts yet.</strong><p>Open a property in Financial Estimates, then choose Documents & contracts to send it here.</p></div>`;
      dashboardEmpty.hidden = true;
      if (showWorkspace) dashboardSection.hidden = false;
      return;
    }
    const documentDeals = eligibleDocumentDeals.map((deal) => `<option value="${escapeHtml(deal.thread_id)}"${deal.thread_id === selectedDocumentThreadId ? " selected" : ""}>${escapeHtml(deal.state?.property?.title || "Untitled property")}</option>`).join("");
    dealGrid.innerHTML = `<section class="document-review"><div class="document-review-heading"><p class="eyebrow">Document & contract review</p><h3>Know what to request before you commit</h3><p>Choose a property, then use the checklist to request the documents that matter. Uploaded files are stored locally and marked automatically when their file name matches a checklist item.</p></div><label class="document-property-select">Property<select data-document-deal>${documentDeals}</select></label><div class="document-workspace"><aside data-document-checklists class="document-checklists"></aside><section class="document-upload-panel"><h4>Upload received documents</h4><label>Listing documents<input data-document-files type="file" multiple accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png" /></label><div class="document-actions"><button type="button" data-document-upload>Save documents locally</button><button type="button" class="ghost-button" data-document-review>Review documents</button></div><p data-document-status></p><div data-document-inventory class="document-results"></div><div data-document-results class="document-results" hidden></div><small>Files stay in this local workspace. PDF, DOCX, and text files can be reviewed immediately; scans use local OCR when it is installed.</small></section></div></section>`;
    dealGrid.querySelector(".document-upload-panel small")?.prepend("Evidence source: files uploaded for this property. ");
    const selectedDocumentDeal = () => dealGrid.querySelector("[data-document-deal]").value;
    const documentStatus = () => dealGrid.querySelector("[data-document-status]");
    const documentResults = () => dealGrid.querySelector("[data-document-results]");
    const documentInventory = () => dealGrid.querySelector("[data-document-inventory]");
    const documentChecklists = () => dealGrid.querySelector("[data-document-checklists]");
    const showDocumentInventory = async () => {
      const response = await fetch(`/deals/${selectedDocumentDeal()}/documents`);
      const result = await response.json().catch(() => ({}));
      const files = result.files || [];
      const deal = eligibleDocumentDeals.find((item) => item.thread_id === selectedDocumentDeal());
      const threadId = selectedDocumentDeal();
      const confirmed = confirmedDocumentLabels(threadId);
      const reviewSummary = documentReviewSummaries[threadId] || {};
      const criticalDocuments = STANDARD_PURCHASE_DOCUMENTS.filter((document) => document.group === "Critical before an offer");
      const uploadedNames = files.map((file) => normalizedDocumentName(file.name));
      const criticalMissing = criticalDocuments.filter((document) => !confirmed.has(document.label) && !document.keywords.some((keyword) => uploadedNames.some((name) => name.includes(normalizedDocumentName(keyword))))).length;
      documentChecklists().innerHTML = `${standardDocumentChecklistMarkup(files, threadId)}${documentChecklistMarkup("Due diligence for this listing", listingSpecificDocuments(deal || {}), files, "", threadId)}`;
      documentInventory().innerHTML = files.length
        ? `<strong>Received & reviewed</strong><p>${criticalMissing} critical missing · ${files.length} uploaded · ${reviewSummary.reviewed || 0} reviewed · ${reviewSummary.unresolved || 0} unresolved questions</p><ul>${files.map((file) => `<li>${escapeHtml(file.name)} <span>${Number(file.bytes).toLocaleString()} bytes</span></li>`).join("")}</ul>`
        : `<strong>Received & reviewed</strong><p>${criticalMissing} critical missing · 0 uploaded · ${reviewSummary.reviewed || 0} reviewed · ${reviewSummary.unresolved || 0} unresolved questions</p><p>Ask the broker for the critical items first.</p>`;
    };
    dealGrid.querySelector("[data-document-upload]")?.addEventListener("click", async () => {
      const files = dealGrid.querySelector("[data-document-files]").files;
      const status = documentStatus();
      if (!files.length) { status.textContent = "Choose at least one document."; return; }
      const body = new FormData(); [...files].forEach((file) => body.append("files", file));
      const response = await fetch(`/deals/${selectedDocumentDeal()}/documents`, { method: "POST", body });
      const result = await response.json();
      status.textContent = response.ok ? `${result.files.length} document(s) saved locally.` : (result.detail || "Upload failed.");
      if (response.ok) showDocumentInventory();
    });
    dealGrid.querySelector("[data-document-deal]")?.addEventListener("change", (event) => {
      selectedDocumentThreadId = event.target.value;
      documentResults().hidden = true;
      documentResults().innerHTML = "";
      showDocumentInventory();
    });
    documentChecklists().addEventListener("click", (event) => {
      const button = event.target.closest("button[data-document-confirm]");
      if (!button) return;
      toggleDocumentConfirmation(selectedDocumentDeal(), button.dataset.documentConfirm);
      showDocumentInventory();
    });
    dealGrid.querySelector("[data-document-review]")?.addEventListener("click", async () => {
      const status = documentStatus();
      status.textContent = "Reviewing saved document facts…";
      const response = await fetch(`/deals/${selectedDocumentDeal()}/documents/review`);
      const review = await response.json();
      if (!response.ok) { status.textContent = review.detail || "Document review failed."; return; }
      const matches = (review.matches || []).length
        ? `<section><strong>Facts that match</strong><ul>${review.matches.map((item) => `<li class="mentioned">${escapeHtml(item.document)}: ${escapeHtml(item.field)} matches the listing.</li>`).join("")}</ul></section>`
        : "<section><strong>Facts that match</strong><p>No directly matching facts were found in the uploaded files yet.</p></section>";
      const discrepancies = (review.needs_clarification || review.discrepancies || []).length
        ? `<section><strong>Needs clarification</strong><ul>${(review.needs_clarification || review.discrepancies).map((item) => `<li class="check">${escapeHtml(item.document)}: ${escapeHtml(item.field)} is ${escapeHtml(item.document_value)}; listing shows ${escapeHtml(item.listing)}.</li>`).join("")}</ul></section>`
        : "<section><strong>Needs clarification</strong><p>No clear contradictions were found in the extracted facts.</p></section>";
      const questions = (review.contract_questions || review.contract_checklist || []).map((item) => `<li class="${item.status || "check"}"><b>${escapeHtml(item.topic)}</b> — ${escapeHtml(item.guidance)}</li>`).join("");
      documentResults().innerHTML = `${matches}${discrepancies}<section><strong>Contract questions</strong><ul>${questions}</ul></section><p>${escapeHtml(review.notice)}</p>`;
      documentResults().hidden = false;
      saveDocumentReviewSummary(selectedDocumentDeal(), {
        reviewed: review.documents.length,
        unresolved: (review.needs_clarification || review.discrepancies || []).length + (review.contract_questions || []).length,
      });
      showDocumentInventory();
      status.textContent = `${review.documents.length} document(s) reviewed.`;
    });
    showDocumentInventory();
    dashboardEmpty.hidden = true;
    if (showWorkspace) dashboardSection.hidden = false;
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
  const cards = visibleDeals.map(dealCard);
  if (activeDealTab === "contact" && visibleDeals.length) {
    const contactImport = document.createElement("section");
    const options = visibleDeals.map((deal) => `<option value="${escapeHtml(deal.thread_id)}">${escapeHtml(deal.state?.property?.title || "Untitled property")}</option>`).join("");
    contactImport.className = "contact-pdf-import";
    contactImport.innerHTML = `<div><p class="eyebrow">Add contact evidence</p><h3>Read contact details from a PDF</h3><p>Select a property, then upload the broker’s exposé or contact document. PropertyScout keeps the file locally and updates only facts and contact details stated in that document.</p></div><label>Property<select data-contact-pdf-deal>${options}</select></label><label>Contact PDF<input type="file" accept="application/pdf,.pdf" data-contact-pdf /></label><button type="button" data-contact-pdf-upload>Read contact PDF</button><p data-contact-pdf-status role="status"></p>`;
    contactImport.querySelector("[data-contact-pdf-upload]")?.addEventListener("click", async () => {
      const file = contactImport.querySelector("[data-contact-pdf]").files?.[0];
      const threadId = contactImport.querySelector("[data-contact-pdf-deal]").value;
      const status = contactImport.querySelector("[data-contact-pdf-status]");
      if (!file) { status.textContent = "Choose a contact PDF first."; return; }
      const action = contactImport.querySelector("[data-contact-pdf-upload]");
      action.disabled = true;
      action.textContent = "Reading PDF…";
      const body = new FormData();
      body.append("file", file);
      try {
        const response = await fetch(`/deals/${threadId}/contact-pdf`, { method: "POST", body });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || "Could not read this PDF.");
        status.textContent = "Contact evidence added to the selected property.";
        await loadDeals();
      } catch (error) {
        status.textContent = error.message;
        action.disabled = false;
        action.textContent = "Read contact PDF";
      }
    });
    cards.unshift(contactImport);
  }
  if (activeDealTab === "analyze") {
    const importCard = document.createElement("section");
    importCard.className = "analyze-pdf-import";
    importCard.innerHTML = `<div><p class="eyebrow">Add a property</p><h3>Start analysis from a PDF exposé</h3><p>Upload one property PDF. We extract stated facts locally, then check for supporting online information when a clear listing can be identified.</p></div><label>Property PDF<input type="file" accept="application/pdf,.pdf" data-analyze-pdf /></label><button type="button" data-analyze-pdf-upload>Analyze PDF</button><p data-analyze-pdf-status role="status"></p>`;
    importCard.querySelector("[data-analyze-pdf-upload]")?.addEventListener("click", async () => {
      const file = importCard.querySelector("[data-analyze-pdf]").files?.[0];
      const status = importCard.querySelector("[data-analyze-pdf-status]");
      if (!file) { status.textContent = "Choose a property PDF first."; return; }
      const action = importCard.querySelector("[data-analyze-pdf-upload]");
      action.disabled = true;
      action.textContent = "Creating analysis…";
      status.textContent = "Reading the PDF and checking available online evidence…";
      const body = new FormData();
      body.append("file", file);
      try {
        const response = await fetch("/deals/import-pdf", { method: "POST", body });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.detail || "Could not add this PDF.");
        status.textContent = "Added to Analyze.";
        await loadDeals();
      } catch (error) {
        status.textContent = error.message;
        action.disabled = false;
        action.textContent = "Analyze PDF";
      }
    });
    cards.unshift(importCard);
  }
  dealGrid.replaceChildren(...cards);
  if (showWorkspace) dashboardSection.hidden = false;
}

async function loadDeals({ showWorkspace = true } = {}) {
  try {
    const response = await fetch("/deals");
    if (!response.ok) throw new Error("Could not load deals.");
    const deals = await response.json();
    renderDashboard(deals, { showWorkspace });
  } catch (error) {
    dealGrid.replaceChildren();
    dashboardEmpty.textContent = error.message;
    dashboardEmpty.hidden = false;
    if (showWorkspace) dashboardSection.hidden = false;
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
document.querySelector("[data-scout-nav]")?.addEventListener("click", () => {
  showScoutWorkspace({ focus: true });
  loadDiscoveries();
});
howItWorksButton?.addEventListener("click", showHowItWorks);
propertyEducationButton?.addEventListener("click", showPropertyEducation);
wireHowItWorksCards();
wireEducationTiles();

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

let currentSearchId = localStorage.getItem("propertyscout-active-discovery") || null;

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


let activeDiscoveryTab = localStorage.getItem("propertyscout-active-discovery-tab") || "validated";
let currentDiscoveryRun = null;

function clearDiscoveryView(message = "No active discovery inventory. Start a property search to scout listings.") {
  currentSearchId = null;
  currentDiscoveryRun = null;
  activeDiscoveryTab = "validated";
  localStorage.removeItem("propertyscout-active-discovery");
  localStorage.removeItem("propertyscout-active-discovery-tab");
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
  localStorage.setItem("propertyscout-active-discovery", currentSearchId);

  const counts = run.counts || {};
  const total = Object.values(counts).reduce(
    (sum, value) => sum + value, 0
  );

  const diagnostics = [
    `${total} discovered item(s)`,
    run.keenable_credits_used == null
      ? "Keenable usage was not recorded for this older search"
      : `${run.keenable_credits_used} Keenable credit(s) used`,
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
        localStorage.setItem("propertyscout-active-discovery-tab", activeDiscoveryTab);
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
function restoreLastWorkspace() {
  if (activeSidebarItem === "property-education") {
    showPropertyEducation();
    return;
  }
  if (activeSidebarItem === "how-it-works") {
    showHowItWorks();
    return;
  }
  if (activeSidebarItem === "scout") {
    showScoutWorkspace();
    return;
  }
  if (["analyze", "contact", "financials", "documents"].includes(activeSidebarItem)) {
    activeDealTab = activeSidebarItem;
    showDealWorkspace();
    return;
  }
  showScoutWorkspace();
}

restoreLastWorkspace();
loadDeals({ showWorkspace: false });
if (activeSidebarItem === "scout") {
  if (currentSearchId) loadDiscoveries(currentSearchId);
  else clearDiscoveryView();
}

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
