# Trust-First Beta Implementation Plan

> **For the implementation team:** execute this plan using the `superpowers:executing-plans` workflow, task by task. Keep all external enrichment opt-in and do not send broker documents to external services.

## Objective

Turn PropertyScout AI into a decision-support product that makes every investment recommendation explainable, actionable, and appropriately cautious. The beta prioritises trust in existing single-workspace flows before introducing accounts or public sharing.

## Current-state findings

- The application is a FastAPI service with a static client in `sites/propertyscout-ui/dist/`.
- Deal state is held in SQLite and files are stored locally under `data/documents/<thread-id>/`.
- The frontend already includes score explanations, financial scenarios, negotiation guidance, document upload/review, comparison, workflow education, and property education, but the evidence model is inconsistent and most information is implicit.
- `analyse_property()` calculates score components in `src/propertyscout/analyst.py`; `/deals` and `/deals/{thread_id}` are assembled in `src/propertyscout/api.py`; most UI rendering is consolidated in `app.js`.
- The product is currently single-user and local-only. Do not describe it as safely shareable until Phase 7 is complete.

## Product decisions

1. **Evidence must never be invented.** Missing data stays missing and is explicitly labelled.
2. **Confidence describes evidence quality, not investment quality.** It must never imply a guaranteed outcome.
3. **Financial assumptions are user-editable and separate from listing facts.** Defaults may be derived from stated facts, but the UI makes that provenance visible.
4. **No broker document leaves the local workspace without an explicit, future opt-in.** The beta continues current local extraction.
5. **A deal has one clearly prioritised next action.** Statuses reflect workflow state, not vague system internals.

## Delivery sequence

### Phase 0 — Baseline and quality guardrails

**Goal:** establish objective quality signals before modifying the investor experience.

1. Add deterministic fixtures for: complete listing, incomplete listing, PDF-imported listing, broker listing, private listing, a rejected listing, and a document discrepancy.
2. Add a browser-level smoke-test approach (Playwright if compatible; otherwise stable API/unit tests plus a manual QA checklist) covering Scout, Analyze, Contact, Financial Estimates, Documents & Contract, Education, and How It Works.
3. Create `docs/trust-first-beta-qa.md` with the acceptance checklist below and a dated review-log template.
4. Add a lightweight feedback event interface only if the app has a storage destination; otherwise record usability feedback in the QA document rather than pretending analytics exist.

**Files:** `tests/test_api.py`, `tests/test_analyst.py`, fixtures, `docs/trust-first-beta-qa.md`, optional frontend test configuration.

**Acceptance:** all existing offline tests still pass; each phase below has a repeatable regression check.

### Phase 1 — Evidence, confidence, and Deal Score transparency

**Goal:** make the dashboard’s most important claims understandable at a glance.

1. Define a small shared evidence schema in `src/propertyscout/schemas.py`:
   - `source_kind`: `listing`, `uploaded_document`, `comparable_estimate`, `user_assumption`, `missing`, `manual_confirmation`
   - `confidence`: `high`, `medium`, `low`, `unknown`
   - optional `reason` and `updated_at`.
2. Extend the deal view from `api.py` with an evidence summary and field-level provenance for asking price, area, rooms, build year, energy class, listing type, valuation, and rent where available. Preserve existing response fields.
3. Add a deterministic confidence helper in `analyst.py`:
   - valuation confidence considers comparable count, location match, usable living area, and price data;
   - score confidence considers valuation confidence plus completeness of rent, building, and energy information;
   - never calculate a false “high” confidence when key data are missing.
4. Normalize the score explanation into exactly five visible investor drivers:
   - price versus market estimate;
   - comparable evidence quality;
   - rent evidence;
   - building and energy risk;
   - data completeness.
   Map existing deterministic components to these drivers and preserve scoring logic unless a documented correction is needed.
5. Add compact Source/Confidence treatments to deal cards and an evidence ledger in expanded deal review. Use clear language: “From listing”, “Comparable estimate”, “Your assumption”, “Needs confirmation”.
6. Apply the same source and confidence treatment to financial outputs, negotiation tactic, and document review results.

**Files:** `src/propertyscout/schemas.py`, `src/propertyscout/analyst.py`, `src/propertyscout/api.py`, `sites/propertyscout-ui/dist/app.js`, `sites/propertyscout-ui/dist/styles.css`, `tests/test_analyst.py`, `tests/test_api.py`.

**Acceptance:** complete and incomplete listings return distinct confidence values with explicit reasons; every displayed score/valuation/default/review result identifies its origin; the score panel identifies all five drivers without claiming an appraisal or recommendation.

### Phase 2 — Actionable workflow and investor-facing status model

**Goal:** remove ambiguity about what the investor should do next.

1. Introduce a presentation-only status mapper in `api.py` or a dedicated workflow module. Preserve existing graph states and map them to: New in Scout, Ready to Analyze, Needs Your Review, Research in Progress, Needs Broker Info, Ready for Financial Estimate, Ready for Document Review, Paused, and Not Progressing.
2. Implement a deterministic `next_best_action` function consuming workflow status plus missing critical data. It returns one action label, one explanation, and a destination stage. Examples: request rent schedule; review price evidence; build financial estimate; request land-register extract.
3. Add Next best action to each expanded deal card and relevant stage details. It is more prominent than secondary actions but not the deal summary.
4. Rename UI actions while retaining API semantics:
   - Approve → Move to Contact Research
   - Reject → Stop Reviewing
   - Request revision → Ask for More Information
   - Prepare Financials → Build Financial Estimate
   - Documents & contracts → Start Document Review
   - Open decision review → Open Deal Details
5. Ensure only the current content view is highlighted in left navigation, including Education and How It Works. Refresh preserves current view and active highlight.

**Files:** `src/propertyscout/api.py`, possibly `src/propertyscout/nodes.py` or new `workflow.py`, `sites/propertyscout-ui/dist/app.js`, `sites/propertyscout-ui/dist/styles.css`, `tests/test_api.py`, `tests/test_graph.py`.

**Acceptance:** each deal has at most one primary next action; a missing rent schedule leads to Needs Broker Info; refreshing Scout, Education, or How It Works neither changes the current view nor loses persisted discovery results.

### Phase 3 — Financial decision integrity and negotiation guidance

**Goal:** distinguish facts, assumptions, and outcomes so the 10-year model is credible.

1. Refactor the financial panel into Property facts (read-only, sourced), Your assumptions (editable, sourced/defaulted), and Investment outcome (calculated).
2. Persist assumptions per deal/scenario in local storage with a versioned migration guard and explicit reset to listing-derived defaults.
3. Add validation and contextual prompts for annual rent, service-charge allocation, financing rate, equity ratio, vacancy, maintenance reserve, purchase costs, and tax rate. Explain why each is needed; never block review when a conservative fallback is clearly marked.
4. Keep the existing red, bold reminder above the editable assumptions: “Review & adjust the assumptions below with the seller or broker. Keep them conservative.” Ensure accessible contrast.
5. Replace the negotiation card with opening price, target price, maximum defensible price, comparable reference/count, broker rationale, missing information, confidence, and limitations. Without valuation data, show “Build the evidence first.”
6. Ensure financial defaults use property-specific listing facts and current valuation, not global-looking defaults.

**Files:** `sites/propertyscout-ui/dist/app.js`, `sites/propertyscout-ui/dist/styles.css`, `src/propertyscout/api.py` only if assumptions/outcomes move beyond local storage, `tests/test_api.py`, frontend/manual regression coverage.

**Acceptance:** facts cannot be edited as assumptions; users can inspect a default’s basis, adjust it, and reset; missing rent/valuation lowers confidence and changes negotiation guidance.

### Phase 4 — Document and contract review workflow

**Goal:** turn paperwork into a prioritised buyer checklist.

1. Replace the two generic checklist groups with: Critical before an offer, Needed for financing, Due diligence, and Received & reviewed.
2. Extend checklist metadata with purpose, urgency, applicability, and expected filename/keywords. Automatic filename matches are suggestions; users can manually confirm or unconfirm items.
3. Update `review_deal_documents()` to return: Matches available information, Needs clarification, Contract question, plus a concise non-legal summary and explicit “not legal advice” boundary.
4. Add a review dashboard summary: critical missing, uploaded, reviewed, unresolved questions. Keep documents scoped to deals explicitly moved to Documents & Contract.
5. Preserve local-only storage, file validation, path sanitization, and limits. Add tests for duplicate names, unsupported files, missing folders, and clear discrepancies.

**Files:** `src/propertyscout/api.py`, `sites/propertyscout-ui/dist/app.js`, `sites/propertyscout-ui/dist/styles.css`, `tests/test_api.py`, document fixtures/tests.

**Acceptance:** selection changes both checklist and inventory; critical missing documents are distinct; results state their document basis and avoid legal conclusions.

### Phase 5 — Contextual investor learning and shortlist comparison

**Goal:** help users understand decisions without forcing a separate learning experience.

1. Keep Property Investment Education as a distinct left-navigation section with six or more clickable topics and practical guidance plus reputable, clearly external links.
2. Link education topics to current deal evidence where available—price per m², energy, rent, WEG documents, financing, and tax—with “See this in your selected deal”.
3. Update How It Works to be completely investor-facing. Each workflow tile opens a feature explanation for that stage and lists all implemented user capabilities, not internal API/credit mechanics.
4. Improve shortlist comparison (max four) with price, area, price per m², score + confidence, valuation gap + confidence, rent evidence, energy/building facts, workflow status, and next action. Flag non-comparable data instead of aligning misleading blanks.
5. Add print-first one-page deal summary: listing facts, uncertainty, score drivers, market estimate, financial scenario, next action, negotiation range, and document gaps. Use browser print CSS in beta.

**Files:** `sites/propertyscout-ui/dist/index.html`, `sites/propertyscout-ui/dist/app.js`, `sites/propertyscout-ui/dist/styles.css`, optionally `src/propertyscout/api.py`, manual QA checklist.

**Acceptance:** navigation highlights Education/How It Works accurately; a novice can jump from a concept to live evidence; printed summary fits one readable page without controls.

### Phase 6 — Professional visual system and accessibility pass

**Goal:** make the product feel like a coherent professional desk, not a collection of cards.

1. Establish semantic design tokens in `styles.css`: canvas, surface, border, text, muted, primary, information, success, warning, danger, focus, shadow, radius, spacing. Never use colour alone for source, confidence, or status.
2. Normalize sidebar, header, headings, cards, actions, controls, mobile breakpoints, and empty states to one spacing/grid system.
3. Preserve left-aligned learning navigation; align lower navigation precisely with workflow navigation at desktop and smaller widths.
4. Add visible keyboard focus, labels, `aria-expanded`, semantic headings, and contrast checks for the red reminder and status pills.
5. Remove stale/duplicate card descriptions and ensure collapse actions do not change deal state.

**Files:** `sites/propertyscout-ui/dist/styles.css`, `sites/propertyscout-ui/dist/app.js`, `sites/propertyscout-ui/dist/index.html`.

**Acceptance:** no overflow at 1280px, 1024px, 768px, 390px; keyboard can operate all actions; sidebar alignment is consistent.

### Phase 7 — Secure external beta foundation (separate release gate)

**Goal:** prepare for genuine external use without weakening local privacy.

1. Write an architecture decision record before code: identity provider, session model, database migration from SQLite, object storage, encryption, deletion/retention, incident handling, and EU hosting/data-processing assumptions.
2. Add authenticated users and workspace ownership. Scope every deal, document, discovery result, financial scenario, and audit record by workspace ID on the server—not only UI.
3. Add owner, collaborator, and viewer roles. Define invite/edit/enrichment/document/export/delete capabilities.
4. Replace public/static document access with authorization-checked opaque IDs and signed short-lived downloads. Add upload rate/size limits and a malware-scanning policy.
5. Record auditable events: login, invite, state change, upload/view/delete, export, enrichment. Obtain consent before any external service receives listing or document-derived data.
6. Add authorization/isolation/file-access/destructive-action tests. Run an independent security review before distributing a public URL.

**Files:** new auth/workspace modules/migrations; substantial `api.py` changes; frontend session handling; security/deployment docs; end-to-end tests.

**Acceptance:** no cross-workspace data access via URL, API ID, cache, or file path; files require authorization; public sharing remains disabled until security gates pass.

## Cross-phase rules

- Work in a feature branch/worktree and preserve existing user changes.
- Start each backend behavior change with a failing test; do not use live Keenable calls in tests.
- Mock external clients and use fixtures for enrichment regressions.
- Bump the cache version in `sites/propertyscout-ui/dist/index.html` whenever `app.js` or `styles.css` changes.
- Do not change rejection decisions merely to improve UI presentation.
- Do not modify source CSVs or agent logic unless a phase explicitly needs a backward-compatible evidence/status field.
- For each phase: run targeted tests, full offline suite, and responsive visual QA.

## Release checkpoints

1. **Internal trust release:** Phases 0–2; 5–10 moderated users with non-sensitive real listings.
2. **Decision beta:** Phases 3–4; test broker conversation and document workflows.
3. **Polished beta:** Phases 5–6; stable navigation, printable summaries, moderated feedback.
4. **External/private beta:** Phase 7 complete and independently security-reviewed.

## Out of scope

- Automated legal advice or contract approval.
- Guarantees of returns, valuation accuracy, financing approval, or suitability.
- Sending broker documents to Keenable or any third party without a future explicit-consent design.
- Public launch before workspace isolation and security controls.
