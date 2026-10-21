# PropertyScout AI requirements

## 1. Goal

Help an investor move a property from discovery to a prepared broker meeting while keeping consequential decisions and external communication under human control.

The first release is a decision-support system. It does not purchase property, make binding offers, provide legal advice, or send unapproved initial outreach.

## 2. Users

- **Investor:** defines acquisition criteria and approves consequential actions.
- **Operator:** investigates failures, corrects data, and resumes paused workflows. In the MVP, the investor and operator may be the same person.

## 3. Functional requirements

### FR-1: Investment criteria

The system must capture structured criteria including location, budget, property type, minimum yield, strategy, and optional risk preferences. Criteria remain editable by the user and are stored with each workflow run.

### FR-2: Property discovery

The Market Scout must ingest candidate listings, normalize their data, remove duplicates, record source provenance, and assess whether each candidate meets the search criteria.

The MVP may use fixture data. Live marketplace integrations are a later milestone.

### FR-3: Investment analysis

The Investment Analyst must produce a structured analysis with assumptions, financial metrics, risks, missing information, supporting evidence, a score, and a recommendation.

The score must not hide missing critical data. A property with insufficient information must be routed to research or review rather than presented as confidently investable.

### FR-4: Shortlist decision

The orchestrator must route rejected properties to an archived state and promising properties to a human shortlist approval step. The user must be able to approve, reject, or request more analysis.

### FR-5: Contact research

For an approved property, the Contact Researcher must find candidate broker or seller contacts, retain source and confidence information, and flag ambiguous results for human resolution.

### FR-6: Outreach

The Outreach Agent must draft a personalized initial message using approved property and contact data. It may request missing documents or information.

The initial message must not be sent until the user approves its exact content and recipient.

### FR-7: Reply monitoring and scheduling

The Scheduling Agent must track conversation status, detect replies, suggest times from allowed availability, and create a meeting only within the user's approved scheduling policy. Anything outside that policy requires approval.

### FR-8: Meeting preparation

After a meeting is confirmed, Meeting Intelligence must generate a concise briefing containing the investment summary, open questions, risks, negotiation points, and supporting evidence.

### FR-9: Workflow control

The orchestrator must persist current state, select the next node from explicit routing rules, pause for approvals, resume after interruption, retry transient failures, and expose terminal outcomes.

### FR-10: Traceability

Every material conclusion and external action must be traceable to the agent, source evidence, tool call, model configuration, timestamp, and approval that produced it.

## 4. Human approval policy

Approval is required for:

1. Adding a property to the active shortlist.
2. Choosing between ambiguous contacts.
3. Sending the first outbound message or materially changed recipient/content.
4. Booking outside predefined calendar availability.
5. Any future binding offer, legal representation, or financial commitment.

Read-only research, calculations, deduplication, scoring, and draft preparation may run autonomously within configured limits.

## 5. Non-functional requirements

- **Structured outputs:** agent results use validated schemas rather than free-form handoffs.
- **Idempotency:** retrying a node must not duplicate emails, meetings, or stored records.
- **Durability:** a workflow can pause for days and resume from persisted state.
- **Explainability:** scores include component reasoning, assumptions, and evidence.
- **Security:** secrets stay outside prompts and source control; agents receive least-privilege tools.
- **Privacy:** personal contact data is stored only when relevant and with recorded provenance.
- **Observability:** each node records status, latency, errors, and important tool activity.
- **Testability:** routing and calculations can be tested without live LLM or external-service calls.
- **Configurability:** market, currency, scoring weights, and approval policies are configuration, not prompt constants.

## 6. Current vertical-slice boundaries

The current vertical slice stops after producing a broker-call brief:

1. Load user criteria.
2. Search public listing pages through the configured discovery provider.
3. Normalize and filter candidates.
4. Analyse and score each candidate.
5. Route candidates to reject, research, or approval.
6. Pause and accept a human shortlist decision.
7. Resolve a fixture-backed broker contact.
8. Approve and fake-send personalized outreach.
9. Accept and classify a simulated inbound reply.
10. Auto-book an in-policy time or request exception approval.
11. Generate a structured brief from verified workflow state.
12. Persist and display the resulting state and audit events.

Live marketplace search, contact enrichment, real email/calendar integrations,
follow-up automation, and document retrieval/RAG remain outside this slice.

## 7. Success criteria for the current vertical slice

- A valid criteria object starts a run.
- Deterministic fixtures exercise approve, reject, and missing-data routes in tests.
- Live discoveries retain their source URL, retrieval time, and evidence excerpt.
- The same input produces deterministic routing when LLM outputs are mocked.
- Invalid agent output fails schema validation and is recorded as an error.
- A paused approval run resumes without repeating prior nodes.
- The final state contains the property, analysis, decision, and audit history.
- Replies from an unexpected sender are rejected.
- Out-of-policy meeting times require an explicit human decision.
- Repeating an email or calendar side effect uses a stable idempotency key.
- A confirmed meeting produces a validated brief containing evidence, risks,
  questions, and negotiation points.
