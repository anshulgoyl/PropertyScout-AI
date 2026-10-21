const form = document.querySelector("#search-form");
const submitButton = document.querySelector("#submit-button");
const errorBox = document.querySelector("#form-error");
const resultsSection = document.querySelector("#results");
const resultGrid = document.querySelector("#result-grid");
const resultCount = document.querySelector("#result-count");

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

const statusClass = (outcome) => {
  if (outcome?.includes("rejected")) return "rejected";
  if (outcome === "needs_research") return "research";
  return "";
};

const humanize = (value = "in progress") => value.replaceAll("_", " ");

function renderDeals(deals) {
  resultCount.textContent = `${deals.length} listings reviewed`;
  if (deals.length === 0) {
    const empty = document.createElement("article");
    empty.className = "result-card empty-result";
    empty.innerHTML = `
      <div class="result-meta"><span>Live search complete</span></div>
      <h3>No reliable listings found</h3>
      <p>Keenable returned no public purchase pages with enough structured data to validate. Try a broader postcode, price, or size.</p>`;
    resultGrid.replaceChildren(empty);
    resultsSection.hidden = false;
    resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  resultGrid.replaceChildren(...deals.map((deal) => {
    const state = deal.state;
    const property = state.property;
    const outcome = state.outcome || "awaiting review";
    const yieldValue = state.analysis?.metrics?.gross_yield;
    const card = document.createElement("article");
    card.className = "result-card";
    card.innerHTML = `
      <div class="result-meta">
        <span>${property.postal_code || property.city}</span>
        <span class="status ${statusClass(outcome)}">${humanize(outcome)}</span>
      </div>
      <h3>${property.title}</h3>
      <p>${state.scout_assessment?.reasons?.join(" · ") || state.analysis?.thesis || "Criteria match ready for review."}</p>
      <div class="metric">
        <span>${property.room_count ?? "—"} rooms · ${property.living_area_sqm ?? "—"} m²</span>
        <strong>${yieldValue == null ? "—" : `${(yieldValue * 100).toFixed(1)}% yield`}</strong>
      </div>`;
    return card;
  }));
  resultsSection.hidden = false;
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

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
    renderDeals(body.deals);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Start property search";
  }
});
