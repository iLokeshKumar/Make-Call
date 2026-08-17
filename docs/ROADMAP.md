# Rio CRM — ISM Agent Roadmap (Weeks 2–9)

> Handoff document. A fresh chat / engineer can pick up from here.
> Everything below week 1 is **pending**.

---

## 0. Product context (one-minute orientation)

**Rio** is an Intelligent Sales-Motion (ISM) agent for Yexis/Talentrus — an autonomous
AI inside-sales manager that handles:

1. Outbound cold calling (voice pipeline: Gemini/Mistral + Deepgram + ElevenLabs + Twilio/EnableX)
2. Demand gen (Apollo.io enrichment → campaign enrollment)
3. Requirement gathering (`LeadRequirement` table, extracted from call transcripts)
4. WhatsApp campaigns (Twilio WhatsApp API)
5. Email campaigns (SMTP + IMAP inbound)
6. Quotation generation (`voice_quote_service` → PDF → `/q/{token}` public link)

Architecture: FastAPI + SQLModel + Postgres (with RLS) / Next.js 16 App Router / LangGraph agent layer /
Postgres-native durable queue (`AgentTask`, `BackgroundJob`, `EmailOutbox`).

## 1. Repo layout + running

```
E:\something_new\
├── backend\                    FastAPI app
│   ├── main.py                 entry, middleware registration
│   ├── auth.py                 JWT + cookie helpers
│   ├── csrf.py                 pure CSRF invariants (stdlib only)
│   ├── database.py             SQLModel engine + RLS ContextVar
│   ├── models\models.py        1,433 lines, ~50 tables
│   ├── agents\                 21 LangGraph-based agent modules
│   │   ├── ism_orchestrator.py pure-function ISM stage machine
│   │   ├── graph.py            live voice-call ReAct loop
│   │   ├── post_call_graph.py
│   │   └── orchestrator.py     run_agent(agent_name, …) dispatcher
│   ├── services\
│   │   ├── agent\              AgentTask + AgentApproval + agent_tool
│   │   ├── automation_worker_service.py  worker cycle (per-company advisory lock)
│   │   ├── campaign\
│   │   ├── communication\      email + whatsapp + inbound
│   │   ├── call\
│   │   └── notify_listener.py  LISTEN/NOTIFY helper
│   ├── routes\                 25 routers
│   ├── test\                   backend/test/ (pytest.ini points here)
│   ├── pyproject.toml          ruff config
│   └── .env                    NOT committed — see "known gotchas" below
│
├── frontend\                   Next 16 App Router + Tailwind
│   └── src\
│       ├── app\                19 pages
│       ├── context\AuthContext.tsx  cookie-auth-only (Week 1 migration)
│       ├── utils\apiFetch.ts   cookie + CSRF-aware fetch wrapper
│       └── components\
│
└── .github\workflows\ci.yml    backend + frontend PR gate
```

**Run locally:**
```bash
# Backend
cd backend
python run_automation_worker.py    # worker (event-driven on Postgres)
uvicorn main:app --port 6060 --reload

# Frontend
cd frontend
npm run dev                         # port 3006
```

## 2. Week 1 recap — DONE ✅

**All local, nothing pushed to GitHub yet. User handles git sync themselves.**

| Task | Artifact | Tests |
|---|---|---|
| CI workflow | `.github/workflows/ci.yml` (backend: ruff + pytest; frontend: tsc + build + knip) | — |
| Ruff config (bug-finding only) | `backend/pyproject.toml` (F-rules) | — |
| Queue invariant tests | `backend/test/test_agent_task_queue.py` | **19** tests |
| LISTEN/NOTIFY worker | `backend/services/notify_listener.py` + `automation_worker_service.run_worker_forever` rewrite | — |
| Per-company NOTIFY targeting | Worker runs targeted cycle per `company_id` on wake; full cycle only on tick | — |
| CORS allowlist + httpOnly cookie | `backend/main.py` env-based CORS; `backend/auth.py` cookie helpers; dual-mode get_current_user (cookie OR header) | — |
| CSRF double-submit | `backend/csrf.py` pure module; `_CSRFMiddleware` in main.py; `set_csrf_cookie` on login/register; /auth/logout clears both | **47** tests |
| Frontend bearer→cookie sweep | 40 files migrated; `apiFetch.ts` helper; localStorage auth removed | — |

**Test suite total: 164 passing.**

**Three real bugs ruff caught and I fixed:**
- `utils/date_normalizer.py` — missing `timedelta` import (would NameError at runtime)
- `db_crud_operation/migrate_google_meet.py` — wrong function name
- `communicators/exotel.py` + `google_calendar_service.py` — duplicate imports

## 3. Known gotchas (important — read before continuing)

### Git state is messy
`git status` shows ~150 files as "deleted" and the same names as "untracked" at the repo root.
Local clone was **6 commits behind** `origin/feature/systemsettings_cache` at session start.
Appears to be a mid-flight directory restructure (files moved from `backend/…` to repo root).

**Do NOT `git pull`, `git push`, `git commit`, or `git reset --hard` without explicit user
direction.** The user plans to sort this manually.

### `.env` has placeholder traps
Two values were copy-pasted as placeholders from an example I gave and bit us:
- `COOKIE_SECURE` — must be `0` for HTTP localhost (fixed)
- `COOKIE_DOMAIN` — must be **commented out or empty** for localhost (fixed; set to a real subdomain wildcard only in production)

**Current correct `.env` block:**
```
ALLOWED_ORIGINS=http://localhost:3006
COOKIE_SECURE=0
COOKIE_SAMESITE=lax
# COOKIE_DOMAIN=.example.com       # prod only; omit for localhost
WORKER_LISTEN_NOTIFY=1
```

### Frontend port
Next.js runs on **3006** (from `frontend/package.json` `"dev": "next dev -p 3006"`), not the default 3000. `ALLOWED_ORIGINS` must match.

### Tests — DB-dependent ones skip silently
`test/test_rls_isolation.py` needs `DATABASE_URL` set (real Postgres); otherwise pytest.mark.skipif skips them. CI currently does NOT pass `DATABASE_URL`, so RLS tests don't run in CI. Fix in Week 5 or 6 by adding a postgres service container to the workflow.

### `test/test_auth.py` is broken (pre-existing, not ours)
References an undefined `client` fixture. CI pytest is invoked with `--ignore=test/test_auth.py` to work around it. Fix or delete it when you get to testing-focused weeks.

### What the `create_agent_task` pipeline currently looks like
- Table + service + 19 tests: **built (Week 1)**
- Called from real production paths: **no (as of end of Week 1)** — Week 2's main job
- HITL approval queue has a backend service, no frontend UI: **build in Week 3**

---

## 4. Week 2 — Wire AgentTask + Webhooks + LeadRequirement

**Goal:** every external action goes through the durable queue; webhooks react in ~50ms; ISM uses extracted requirements to pick channel.

### 2.1 — LeadRequirement drives `_pick_channel()`  (½ day)
File: `backend/agents/ism_orchestrator.py`

Current `_pick_channel()` uses stage-based preference only. Extend to:
- `budget_range` indicates high-ticket (parse ~$10k/₹5L threshold) → prefer `call`
- `timeline` in {"immediate", "this_week", "urgent"} → prefer `whatsapp`
- Otherwise → current stage default

Parse helpers: `_budget_is_high_ticket(s: str) -> bool`, `_timeline_is_urgent(s: str) -> bool`. Both strictly defensive — any unparseable value falls through to stage default.

**Tests (`test_ism_transition.py`):** 4 new — high budget, urgent timeline, both, neither.

### 2.2 — Route send-email / send-whatsapp / send-quote through AgentTask  (2 days)

New files:
- `backend/agents/send_actions.py` — executors: `execute_send_email`, `execute_send_whatsapp`, `execute_send_quote`. Registered in `agents/orchestrator.py`'s registry so the worker can invoke them via `run_agent(agent_name=...)`.
- `backend/services/agent/dispatch_service.py` — enqueue helpers: `enqueue_send_email(session, company_id, lead_id, template_id, trigger_event, …)`. Builds idempotency_key like `send_email:{lead_id}:{template_id}:{trigger_event_id}`.

Migrate existing callers to use enqueue helpers (NOT direct calls):
- `agents/ism_orchestrator.py` `_dispatch_whatsapp` + `_dispatch_email` + `_dispatch_call`
- `services/campaign/campaign_service.py` `execute_campaign_recipient_step`
- `agents/post_call_nurture.py`
- `agents/quote.py`
- `routes/interactions.py` (manual user-triggered sends)

Leave unchanged: `services/communication/communication_service.py` — it's the actual sender. The worker's executor calls it.

**Live voice-call path stays direct** — the `VoicePipeline` inside an active call needs sub-second latency, can't tolerate queue hop. That's correct.

**Feature flag:** `USE_AGENT_TASK_QUEUE=1` in `.env` (default 1). `0` reverts to direct dispatch.

**Tests:** new `test/test_send_dispatch.py` — ~10 tests covering:
- `enqueue_send_email` creates AgentTask with correct idempotency_key
- Duplicate enqueue dedupes (returns existing row)
- Executor run path updates Interaction + EmailOutbox correctly
- HITL gate: `send_email` is in default approval set → status=awaiting_approval until approved
- Approval → execute transition works

### 2.3 — Webhook handlers with idempotency  (1½ days)

Four handlers become 5-liners that enqueue and return 200:

| Endpoint | Task type | Idempotency key |
|---|---|---|
| `POST /tracking/whatsapp/inbound` | `process_inbound_whatsapp` | `MessageSid` |
| `POST /tracking/email/webhook` | `process_inbound_email` | `Message-Id` header |
| `POST /telephony/twilio/status-callback` | `process_call_status` | `{CallSid}:{CallStatus}` |
| `POST /tracking/quote/{action}/{token}` | `process_quote_event` | `{quote_id}:{action}:{epoch_minute}` |

New file: `backend/agents/webhook_handlers.py` — one executor per task type. Each pulls the heavy logic (`ingest_whatsapp_webhook_event`, email parsing, etc.) out of the route handler.

Route handler shape:
```python
@router.post("/whatsapp/inbound")
async def whatsapp_inbound_webhook(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    payload = {k: v for k, v in form.items()}
    guard_response = _whatsapp_webhook_guard(request, session, payload)
    if guard_response is not None:
        return guard_response
    company_id = resolve_company_from_twilio_payload(session, payload)
    create_agent_task(
        session=session,
        company_id=company_id,
        task_type="process_inbound_whatsapp",
        assigned_agent="webhook",
        input_json={"payload": payload},
        idempotency_key=f"wa_inbound:{payload.get('MessageSid')}",
        requires_approval=False,
    )
    return {"status": "queued"}
```

**Tests:** new `test/test_webhook_idempotency.py` — ~8 tests:
- Fake payload → AgentTask created with correct key
- Replay of same payload (same MessageSid) → dedupes, no second row
- Missing key field → task still created but with a fallback key (so we don't DoS ourselves)
- Executor run path updates Interaction state correctly

### 2.4 — End-to-end integration test  (½ day)

File: `backend/test/test_e2e_ism.py`. Single test exercises:
```
Fake /tracking/whatsapp/inbound POST
  → AgentTask created
  → worker claims (via run_agent_tasks with mocked orchestrator)
  → Interaction row recorded
  → ISM stage advances from "contacted" → "engaged"
  → run_ism_cycle called next
  → _pick_channel returns "email" (based on lead's requirements)
  → enqueue_send_email creates a new AgentTask
  → status=awaiting_approval (HITL gate fires because send_email is in default list)
```

Uses in-memory SQLite with the same pattern as `test_agent_task_queue.py`.

### 2.5 — Architecture doc  (½ day)
New file: `docs/ARCHITECTURE.md`. One-page ASCII diagram:
```
external event (webhook / UI / cron)
  ↓
create_agent_task(idempotency_key=...) + pg_notify
  ↓
AgentTask row (Postgres, with status=pending)
  ↓
worker LISTENs, runs run_agent_tasks(company_id)
  ↓
requires_approval? → AgentApproval row, status=awaiting_approval
                  ↓ (operator approves in UI, Week 3)
                  status=pending again
  ↓
orchestrator.run_agent(assigned_agent, …)
  ↓
executor updates DB state, logs EngagementEvent
  ↓
ISM re-evaluates, may enqueue next action
```

Plus a table of agents + their executors + default approval settings.

### 2.6 — Acceptance at end of Week 2
- Every external send in production flows through `create_agent_task` (grep confirms no direct `send_email_to_lead` calls outside `execute_send_email` and the voice pipeline)
- Webhooks return 200 in <100ms
- ~25 new tests; total suite ~190 passing
- E2E test green
- Feature-flag kill switch exists for the biggest migration

---

## 5. Week 3 — Approvals Inbox (frontend) + Rules Engine foundation

**Goal:** operators can see and act on the HITL queue; stage transitions become DB-configurable instead of code-configurable.

### 3.1 — Approvals Inbox UI  (2 days)
New page: `frontend/src/app/agents/approvals/page.tsx`.

Lists `AgentApproval` rows where `status='pending'`. For each: action_summary, action_payload (pretty-printed JSON), lead context, approve/reject buttons, reviewer_note textarea. Real-time via WS (extend existing WebSocket broadcaster with an `approval.created` / `approval.reviewed` channel).

Backend:
- New `backend/routes/agent_approvals.py` — `GET /approvals?status=pending`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`. Already have `agent_approval_service`.
- WebSocket broadcast channel — extend `call_status_broadcaster.py` pattern.

### 3.2 — Structured enrichment of approval payloads  (1 day)
Currently `action_payload` is raw input JSON. Make it human-readable:
- `send_email` → show rendered subject + preview of body, not the template_id + variables_schema
- `send_quote` → show line items, total, customer name
- `send_whatsapp` → show rendered message

Helper: `backend/services/agent/approval_presenter.py` — maps task_type + input_json → presentation dict.

### 3.3 — Rules engine — table + pure evaluator  (2 days)
Goal: ops configure `ISM_RULES` via DB rows; ISM picks action based on first matching rule.

New table in `models/models.py`:
```python
class IsmRule(AuditMixin, table=True):
    id: int
    company_id: int
    name: str
    priority: int = 10            # lower = higher priority
    when_json: dict               # e.g. {"stage": "engaged", "budget_usd_min": 10000}
    then_action: str              # "advance_to:negotiation" | "dispatch:send_quote" | "handoff_to_human"
    is_active: bool = True
```

New file: `backend/agents/ism_rules_engine.py` — `evaluate_rules(session, company_id, lead) → Rule | None`. Pure function, testable.

Integrate into `run_ism_cycle`: before `_pick_channel`, check rules. If a matching rule says `advance_to:X`, call `advance_ism_stage(lead, X)`. If `dispatch:Y`, enqueue that send task. If `handoff_to_human`, enqueue `AgentTask(task_type="handoff", requires_approval=True)`.

**Tests (`test/test_ism_rules.py`):** ~15 tests — empty rule set, priority ordering, JSON matching operators (eq / gte / lte / in / contains), unknown action name (fail safe → skip), inactive rules ignored.

### 3.4 — Acceptance at end of Week 3
- An operator can approve/reject a pending AgentApproval in the UI
- Ops can insert a row into `ism_rules` via DB console and see behavior change without redeploy (UI to come in Week 4)
- ~15 new rules tests; total ~205

---

## 6. Week 4 — Rules UI + Agent Performance Dashboard + `EngagementEvent` buildout

### 4.1 — Rules admin UI  (2 days)
`frontend/src/app/agents/rules/page.tsx`. Table view: priority, name, when-JSON (with syntax highlighting), then-action, toggle is_active. Create/edit modal with a simple JSON schema validator.

### 4.2 — Agent Performance Dashboard  (2 days)
`frontend/src/app/agents/performance/page.tsx`.

Query backend: aggregations over `EngagementEvent` + `AgentTask` + `CompanyUsage`:
1. Dispatches/day by channel (stacked bar, 30d window)
2. Channel outcome funnel (dispatched → delivered → replied → converted)
3. Avg LLM cost per lead per stage (rolling 7d)
4. P50/P95 latency per `task_type` (from `LatencyLog` for voice, `AgentTask` timestamps for others)

Backend: new `backend/routes/agent_analytics.py` — 4 endpoints, one per chart. Pre-aggregate server-side, return small JSON.

### 4.3 — Wire cost + latency into `AgentTask.output_json`  (½ day)
Every executor that calls an LLM should write `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms` into `task.output_json`. This is the backbone of (4.2) chart 3 + 4.

Helper: `backend/services/agent/task_metrics.py` — `record_llm_usage(task, response)` called from executors.

### 4.4 — Acceptance at end of Week 4
- Non-engineer can author an ISM rule from the UI
- The performance page shows real data, refreshes in ~1s
- LLM cost per company is visible per-lead and per-stage (billing-ready)

---

## 7. Week 5 — Quote PDFs to S3 + Alembic + Structured logs + Secrets vault

Hardening week. Nothing user-facing changes; operational surface improves materially.

### 5.1 — PDFs to S3-compatible storage  (1½ days)
Current: `Quote.pdf_path` is a local filesystem path. Container restart = dead link.

- Add `pdf_s3_key`, `pdf_sha256` columns (migration)
- `backend/services/quote/pdf_storage.py` — `upload(local_path) → s3_key`, `signed_url(s3_key, ttl) → str`
- Use MinIO for local dev (add to `docker-compose.yml`), S3 / R2 / Spaces in prod
- Env: `PDF_STORAGE_BACKEND=s3|local` (default `local`), `S3_BUCKET`, `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- Email template changes: `{{quote_pdf_url}}` becomes a signed URL with 30-day TTL instead of a public URL
- Quote is **immutable once sent** — once `Quote.sent_at` is set, PDF cannot be regenerated (legal boundary)

### 5.2 — Adopt Alembic  (1½ days)
Current migrations are ad-hoc scripts in `backend/migrations/`. Replace with Alembic.

- `alembic init backend/alembic`
- Snapshot current schema as baseline: `alembic revision --autogenerate -m "baseline"`
- Port the existing `apply_rls.py` + sql snippets as one-off data migrations referenced from the Alembic migration `op.execute(…)`
- Update `database.init_db()` to NOT do `create_all` in prod — use `alembic upgrade head` instead; keep `create_all` behind `INIT_MODE=dev`

### 5.3 — Structured JSON logs end-to-end  (1 day)
Already partially structured (`logger.info(..., extra={"event": "..."})`). Make it consistent:
- All logs emit JSON
- Every log line includes `request_id`, `company_id` (when known), `user_id` (when known), `task_id` (when known)
- Add a `logging_middleware.py` that sets all four on the `ContextVar` and a JSON formatter picks them up
- Ship to Grafana Cloud / Datadog / Loki via container stdout — no file destination

### 5.4 — Secrets vault  (1 day)
`.env` in prod is a staging tool, not a prod tool. Move provider keys (Twilio, Gemini, Apollo, etc.) to one of:
- Doppler (simplest)
- AWS Secrets Manager / GCP Secret Manager (if already using a cloud)
- HashiCorp Vault (overkill for one app, good for platform team)

`.env` keeps non-secret settings only (ALLOWED_ORIGINS, feature flags, etc.).

### 5.5 — Acceptance at end of Week 5
- Quote sent today is visible 60 days from now even after 5 container restarts
- DB schema change goes through `alembic revision` + `alembic upgrade`; review-able per PR
- Logs are queryable by `request_id`, `company_id`, `task_id`
- `git grep` returns zero production secrets in the repo

---

## 8. Week 6 — Frontend UX sweep (TanStack Query, shadcn/ui, Lead 360 panels)

### 6.1 — TanStack Query on hottest pages  (2 days)
Install, wrap three pages:
- `/leads/kanban` (highest-traffic, benefits most from caching)
- `/call-monitor` (real-time; WS events invalidate queries)
- `/agents/approvals` (built in Week 3)

Pattern: keep the page's render logic, replace `useState + useEffect + fetch` with `useQuery({ queryKey: [...], queryFn: () => apiFetch(...).then(r=>r.json()) })`. Mutations become `useMutation` with optimistic updates.

### 6.2 — shadcn/ui on those same 3 pages  (1½ days)
Install shadcn (Tailwind already there). Migrate:
- Dialogs/Drawers (used in Lead 360, Kanban edit-lead, Approvals payload view)
- Tables (Leads list, Approvals queue)
- Form primitives (labels, selects, radios, toasts)

Accessibility improves for free.

### 6.3 — Lead 360 panels for existing hidden data  (1½ days)
`frontend/src/app/leads/[id]/page.tsx` — add three panels surfacing data we already collect:
- **Requirements panel** — renders `LeadRequirement` (editable, confidence per field)
- **Agent actions timeline** — joins `AgentTask + EngagementEvent + Interaction` filtered by lead_id; shows every autonomous action with an undo / take-over button
- **Explain next action** — when ISM has a rule-based answer, show which rule fired and why (`"WhatsApp scheduled for engaged stage with budget >10k: rule #14"`)

### 6.4 — Acceptance at end of Week 6
- Top 3 pages use TanStack Query + shadcn/ui
- Lead 360 shows the data the backend already collects but didn't render before
- Lighthouse a11y ≥ 90 on `/leads`, `/quotes`, `/agents/approvals`

---

## 9. Week 7 — Researcher + Closer agents (complete the three-agent ISM pattern)

ISM Orchestrator is one big loop today. Factor into three focused LangGraph agents, each with its own queue name.

### 7.1 — `researcher` agent  (1½ days)
Triggered on: new Lead row inserted.

Does: Apollo enrichment + web scrape + lead-score computation + initial requirements from public signals (company website, job posting, news).

Ends by: either enqueuing `qualify_lead` (if score ≥ threshold) or marking `qualification_status=disqualified`.

Files: `backend/agents/researcher.py` (partially exists — extend). Register task_type `enrich_lead` → this agent.

### 7.2 — `outreacher` agent  (1½ days)
Triggered on: qualified lead OR reply-classifier saying "continue engaging".

Does: the existing ISM orchestrator's channel selection + dispatch — now factored out as its own agent, invoked through `AgentTask`.

### 7.3 — `closer` agent  (2 days)
Triggered on: quote was sent AND lead replied OR 3 days silent.

Does: follow-up cadence, negotiation handling, objection parrying using `ObjectionEntry` + `CompetitorMention` from the knowledge base. Produces either `close_won` (deal done) or `handoff_to_human` (AI doesn't know how to close this one) — never silently drops a lead.

### 7.4 — Reply classifier  (½ day)
Small LangGraph node. Triggered on inbound whatsapp/email webhook → classifies reply as {interested, objection, unsubscribe, question, noise} → enqueues the appropriate next agent.

File: `backend/agents/reply_classifier.py`. Called from the webhook executors built in Week 2.

### 7.5 — Acceptance at end of Week 7
- A fresh lead flows end-to-end through all three agents without code change
- Each agent has ≥ 10 tests for its state machine
- Handoff to human creates an `AgentTask(task_type="handoff", requires_approval=True)` with clear context

---

## 10. Week 8 — Performance, SLOs, Monitoring

### 8.1 — Voice pipeline latency budget  (2 days)
Sample `LatencyLog` — current STT + LLM + TTS p95 is probably in the 1.5–2.5s range for most providers. Aim for sub-800ms p95 perceived turn-taking latency.

Levers:
- Speculative LLM warm-up on first user utterance detection (parallel to STT finalization)
- TTS streaming with prefix-emit at phrase boundaries
- Provider selection per-company by measured p95 (data already in `LatencyLog`)

### 8.2 — SLOs + alerting  (1 day)
Define 4 SLOs in a `docs/SLOs.md`:
1. API availability ≥ 99.5% (30-day window)
2. Login → dashboard latency p95 ≤ 2s
3. Voice call turn-taking p95 ≤ 800ms
4. Agent-task dead-letter rate ≤ 0.5%

Configure alerting (Grafana / PagerDuty / Slack webhook) on each. Dashboards show rolling SLO burn-rate.

### 8.3 — Observability polish  (1 day)
- Add `trace_id` propagation from HTTP request → AgentTask → executor → sub-tasks. Currently `trace_id` exists on `LatencyLog` only.
- Request-id in all email outgoing messages (for support ticket traceability)
- `/health` endpoint returns DB/Redis/worker status with JSON body (not just 200)

### 8.4 — Worker horizontal scale test  (1 day)
Run 3 worker containers against staging. Verify:
- Per-company advisory lock holds (no double-dispatch)
- NOTIFY fans out correctly
- No deadlocks over 30-min load test at 10x production traffic

### 8.5 — Acceptance at end of Week 8
- Voice turn-taking p95 ≤ 800ms
- SLO dashboards live, alerts verified
- Worker runs 3+ replicas cleanly

---

## 11. Week 9 — Multi-customer readiness: onboarding + billing + self-service

ISM agent is production-ready for Yexis/Talentrus. Week 9 makes it sellable as a product.

### 9.1 — Self-service onboarding flow  (2 days)
From `/companies/register`:
1. Company info form
2. Billing tier selection (tied to `CompanyFeatureFlag` and `CompanyUsage` limits that already exist)
3. Connect providers (Apollo, Twilio, SendGrid keys) — UI in `/settings/integrations`
4. Upload products.csv (already supported — make it first-class in the wizard)
5. Pick voice + voice style (`CompanySetting` keys `LLM_PROVIDER`, `TTS_PROVIDER`, etc.)
6. Wizard ends with a "Test call to me" button that dials the admin's phone number with the agent — proves the wiring end-to-end

### 9.2 — Billing wiring  (2 days)
`CompanyUsage` already aggregates calls_made / emails_sent / whatsapp_sent per month. Wire to Stripe (or whichever billing provider):
- `backend/services/billing/stripe_service.py`
- `CompanyUsage` diff per month → Stripe usage record
- Plan upgrade/downgrade via webhook
- Overage handling: `CompanyFeatureFlag` auto-disabled when limit exceeded

### 9.3 — Per-company safety limits (autonomy governor)  (1 day)
Add to `CompanySetting` keys:
- `AUTONOMY_LEVEL` = `observe | suggest | act` (default `suggest` for new companies)
- `MAX_LLM_COST_USD_PER_LEAD_PER_DAY` (default $2)
- `MAX_SENDS_PER_LEAD_PER_DAY` (default 3)

`observe` = agent does nothing, only logs what it would do. `suggest` = enqueues AgentTasks with requires_approval=True on everything. `act` = requires_approval only on defaults (send_email, send_quote, send_whatsapp_bulk).

### 9.4 — Acceptance at end of Week 9
- A new company self-serves from register → first test call in under 15 minutes
- Billing shows correct per-month usage within 5% of `CompanyUsage` DB rows
- Autonomy governor blocks agent from runaway sends on a new tenant

---

## 12. Cross-cutting concerns (every week)

### Tests
- Target **200+ tests by end of Week 2**, **300+ by Week 9**
- Any new module gets tests in the same PR (CI enforces via coverage threshold after Week 5)
- Every executor (send_email, webhook handlers, etc.) needs both a pure-function unit test AND an integration test that goes through `run_agent_tasks`

### Commits
User handles git. Don't `git push` or `git commit` without explicit approval.
Suggested commit boundaries: one commit per 2.X / 3.X subsection.

### Deployment
No deployment happens within the 9 weeks as written — Week 9 is "product-ready", not "deployed". User's deployment target isn't specified; when identified, add a Week 9.5 or Week 10 for rollout playbook.

---

## 13. How to continue in a fresh chat

### First five commands
```bash
cd backend
ruff check .                                  # expect: all checks passed
pytest --ignore=test/test_auth.py -q         # expect: 164 passed (Week 1 baseline)
cd ../frontend
npx tsc --noEmit                              # expect: clean
npm run build                                 # expect: green (~1.5 min)
```

If any of those fail, **stop and investigate** — Week 1 baseline is broken and no further work should proceed until it's restored.

### Prompt to paste into the fresh chat

> I'm continuing Rio CRM work. Week 1 is done — see `docs/ROADMAP.md` for the full plan and Week 1 recap.
>
> Start with **Week 2.1** (LeadRequirement → `_pick_channel()`). Read the roadmap first, confirm the Week 1 baseline (commands above), then propose a plan before coding.
>
> Critical: everything stays local; do NOT `git push` / `git commit` / `git pull`. User handles git.

### Key instructions for the new Claude
- Follow the patterns from Week 1 (pure-function testability, SQLite in-memory for DB tests, `secrets.compare_digest` for comparisons, etc.)
- Don't push to GitHub under any circumstance — user sync is manual
- Keep ruff + tsc green after every subsection
- When in doubt, prefer a feature flag (`USE_*_QUEUE`, `AUTONOMY_LEVEL`) for rollback safety
- Ask before destructive changes (dropping columns, force-pushing branches, etc.)

---

## 14. Out of scope for weeks 2–9 (explicit)

These are valuable but deferred beyond week 9:
- Voice agent in languages beyond the current 10 Indian languages + English
- Mobile app (field sales native)
- AI fine-tuning on customer transcripts (Rio-specific model)
- Multi-region deployment
- Customer-facing changelog / what's-new UI
- External API for partners (REST + webhooks for third-party integrators)

Capture these in a backlog doc when Week 9 closes.

---

*Generated at end of Week 1 session. 164 tests passing. All changes local. No git operations performed.*
