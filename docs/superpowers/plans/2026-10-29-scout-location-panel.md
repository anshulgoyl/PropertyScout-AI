# Scout Selection and Financial Location Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep investors in Scout after selecting a listing and add a trustworthy postcode-level location panel below Financial Estimates negotiation guidance.

**Architecture:** Extend the local postcode coordinate index with a read-only lookup and expose it through the existing FastAPI application. The browser renders an OpenStreetMap iframe from the local postcode centroid and a short evidence-bound location note; it never geocodes an address. Scout selection retains the Scout workspace while the new deal is created and refreshes the deal counts in the background.

**Tech Stack:** Python, FastAPI, Pydantic, vanilla JavaScript, CSS, OpenStreetMap browser embed, pytest.

**Spec:** `docs/superpowers/specs/2026-10-29-scout-location-design.md`

## Global Constraints

- No live Keenable calls.
- Never infer a street address, parcel boundary, neighbourhood rating, commute estimate, or investment recommendation.
- Do not geocode or send a listing address to an external service.
- Map tiles load only in the investor’s browser.
- Preserve current deal actions, financial calculations, and source evidence.

## Review Focus

- A known postcode returns its local coordinate pair; an unknown postcode returns a clear not-found response.
- A listing with an explicit address displays the address as listing evidence but retains a postcode-level map marker unless direct coordinates exist.
- A listing without an address still displays city and postcode with a clearly labelled postcode-area map.
- A listing with neither postcode nor usable local coordinates shows an honest unavailable state rather than a guessed map.
- Selecting Scout listings does not switch the active workspace, while API errors restore the button and show the error in the originating card.

### Task 1: Expose local postcode coordinates safely

**Files:**
- Modify: `src/propertyscout/postcode_proximity.py`
- Modify: `src/propertyscout/api.py`
- Modify: `tests/test_postcode_proximity.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `PostcodeCoordinateIndex.coordinates_for(postcode: str | None) -> tuple[float, float] | None`.
- Produces: `GET /locations/postcodes/{postcode}` returning `{"postcode": str, "latitude": float, "longitude": float}` or HTTP 404.
- Consumes: the already-loaded `resolved_postcode_index` inside `create_app`.

- [ ] **Step 1: Write failing coordinate lookup tests**

```python
assert index.coordinates_for("10000") == (52.0, 13.0)
assert index.coordinates_for("99999") is None
```

- [ ] **Step 2: Run the postcode test to verify it fails**

Run: `./.venv/bin/pytest -q tests/test_postcode_proximity.py`

Expected: FAIL because `coordinates_for` does not exist.

- [ ] **Step 3: Add `coordinates_for` to `PostcodeCoordinateIndex`**

Return the stored coordinate tuple for an exact postcode and `None` when unknown or missing; do not alter nearby-postcode behaviour.

- [ ] **Step 4: Write failing API tests for known and unknown postcodes**

```python
response = client.get("/locations/postcodes/50667")
assert response.json() == {"postcode": "50667", "latitude": 50.0, "longitude": 6.0}
assert client.get("/locations/postcodes/99999").status_code == 404
```

- [ ] **Step 5: Add the read-only location endpoint**

Use `coordinates_for`; return only the postcode and its local centroid coordinates. Do not persist or enrich listing data.

- [ ] **Step 6: Run the focused API and postcode tests**

Run: `./.venv/bin/pytest -q tests/test_postcode_proximity.py tests/test_api.py -k "postcode or location"`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/propertyscout/postcode_proximity.py src/propertyscout/api.py tests/test_postcode_proximity.py tests/test_api.py
git commit -m "Expose local postcode coordinates for maps"
```

### Task 2: Keep Scout visible after selecting a listing

**Files:**
- Modify: `sites/propertyscout-ui/dist/app.js:2231-2255`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `startDiscoveryDeal(card: HTMLElement, url: string) -> Promise<void>`.
- Produces: a Scout-local confirmation message and background `loadDeals()` refresh without changing `activeWorkspace` or `activeDealTab`.

- [ ] **Step 1: Write a failing dashboard asset test**

Assert the Scout selection handler no longer contains `updateWorkflowStage("analysis")` and includes the investor-facing confirmation `Added to Analyze`.

- [ ] **Step 2: Run the focused dashboard test to verify it fails**

Run: `./.venv/bin/pytest -q tests/test_api.py -k ui_dashboard_section_is_served`

Expected: FAIL because the current handler forces the Analyze stage.

- [ ] **Step 3: Update `startDiscoveryDeal`**

Remove the stage switch and workflow focus call. On successful creation, retain the Scout view, display `Added to Analyze — you can keep reviewing this search.`, and refresh deal data only.

- [ ] **Step 4: Run the focused dashboard test**

Run: `./.venv/bin/pytest -q tests/test_api.py -k ui_dashboard_section_is_served`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sites/propertyscout-ui/dist/app.js tests/test_api.py
git commit -m "Keep Scout visible after listing selection"
```

### Task 3: Render an evidence-bound financial location panel

**Files:**
- Modify: `sites/propertyscout-ui/dist/app.js:963-1005`
- Modify: `sites/propertyscout-ui/dist/styles.css`
- Modify: `sites/propertyscout-ui/dist/index.html`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `locationPanel(deal: DealView) -> string` and `loadLocationPanel(panel: HTMLElement, property: PropertyListing) -> Promise<void>`.
- Consumes: `/locations/postcodes/{postcode}` and `property.address`, `property.city`, `property.postal_code`.

- [ ] **Step 1: Write failing dashboard asset tests**

Assert the client includes `Property location`, `Postcode-area location`, `Confirm the exact position with the seller or broker`, `/locations/postcodes/`, and `openstreetmap.org`.

- [ ] **Step 2: Run the focused dashboard test to verify it fails**

Run: `./.venv/bin/pytest -q tests/test_api.py -k ui_dashboard_section_is_served`

Expected: FAIL because no location panel exists.

- [ ] **Step 3: Add `locationPanel` and its loader**

Insert the panel immediately after `negotiationTactic(deal)`. Show city and postcode first; show `Listing address` only when present. Fetch only local postcode coordinates, label the marker `Postcode-area location`, and render an honest unavailable state when no postcode/coordinates exist. Build the OpenStreetMap iframe URL from latitude/longitude only.

- [ ] **Step 4: Style the panel as a compact financial follow-on**

Use a responsive two-column map/note layout above 900px and a single-column layout below it. Give the map a fixed, modest height and keep the precision label prominent.

- [ ] **Step 5: Bump the CSS and JavaScript cache query versions**

Update `index.html` and the corresponding static asset assertions in `tests/test_api.py`.

- [ ] **Step 6: Run focused dashboard tests**

Run: `./.venv/bin/pytest -q tests/test_api.py -k ui_dashboard_section_is_served`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sites/propertyscout-ui/dist/app.js sites/propertyscout-ui/dist/styles.css sites/propertyscout-ui/dist/index.html tests/test_api.py
git commit -m "Add evidence-bound property location panel"
```

### Task 4: Full verification

**Files:**
- Modify: none expected

- [ ] **Step 1: Run the complete offline suite**

Run: `./.venv/bin/pytest -q`

Expected: all tests pass, with any pre-existing skipped test reported.

- [ ] **Step 2: Inspect the final diff**

Run: `git diff --check` and `git status --short`

Expected: no whitespace errors; the three pre-existing untracked inspection files remain excluded.

- [ ] **Step 3: Push reviewed commits**

```bash
git push origin main
```

## Self-review

- Spec coverage: Task 2 covers the Scout behaviour; Task 1 provides local coordinates; Task 3 covers the map, precision label and evidence-bound note; Task 4 covers verification and push.
- Type consistency: `coordinates_for` is the only backend coordinate interface; the frontend receives its `latitude` and `longitude` fields from the named route.
- Review focus: each of the five identified failure modes has an explicit test step in Tasks 1–3.
- Proportion: four tasks match the three small implementation areas without restructuring existing application layers.
