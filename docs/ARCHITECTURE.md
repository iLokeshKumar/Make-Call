# Rio CRM — ISM Agent Architecture

> Flow diagrams, module map, and the rules that make the system safe to operate. Read before touching agent-layer code.

---

## The big picture

```
   ┌──────────────────────────────────────────────────────────────────┐
   │                   External triggers                              │
   │  Webhook from Twilio/SendGrid/WhatsApp                           │
   │  Cron tick (poll-fallback)                                       │
   │  User click in UI                                                │
   │  Inbound carrier event (call-status, message delivery, quote     │
   │  open/accept/reject)                                             │
   └───────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │            create_agent_task(idempotency_key=…)                  │
   │                                                                  │
   │  Writes one row to AgentTask with status=pending. Same           │
   │  transaction as any source-of-truth change (e.g. a Lead or       │
   │  CallTask row). pg_notify fires on COMMIT so the worker wakes    │
   │  within ~1ms of the enqueue.                                     │
   └───────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │              Worker loop (automation_worker_service)             │
   │                                                                  │
   │  Per-company pg_try_advisory_lock (serialises one company at a   │
   │  time across N worker containers). LISTEN agent_task_ready +     │
   │  60s poll fallback. On NOTIFY, runs a targeted single-company    │
   │  cycle; on tick, full multi-company cycle.                       │
   └───────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │              run_agent_tasks(session, company_id)                │
   │                                                                  │
   │  Claims up to 10 pending tasks ordered by (priority, created_at) │
   │                                                                  │
   │  For each task:                                                  │
   │    requires_approval? → create AgentApproval row,                │
   │                         status='awaiting_approval'               │
   │                         (parked until operator acts)             │
   │    else → orchestrator.run_agent(                                │
   │             agent_name=task.assigned_agent,                      │
   │             **task.input_json                                    │
   │           )                                                      │
   └───────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  agents.send         agents.webhook_sink    agents.ism, …        │
   │                      ( no-op)               (pre-existing)       │
   │                                                                  │
   │  send.run dispatches on task_type → services.communication       │
   │  webhook_sink.run is a no-op that acknowledges the audit row     │
   │  other agents keep doing LLM-driven work as before               │
   └───────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                    Side effects + state writes                   │
   │  Interaction row, EmailOutbox row, CallTask update, Quote state, │
   │  EngagementEvent, LatencyLog, AgentTask.output_json              │
   └──────────────────────────────────────────────────────────────────┘
```

---

## Module map

```
backend/
├── agents/
│   ├── ism_orchestrator.py   run_ism_cycle — pure, testable stage machine
│   │                         _pick_channel reads LeadRequirement
│   │                         _dispatch_whatsapp / _dispatch_email route
│   │                           through AgentTask queue
│   ├── send.py               send_email / send_whatsapp /
│   │                         send_quote executor — dispatches to
│   │                         communication_service based on task_type
│   ├── webhook_sink.py       no-op executor for webhook_audit
│   │                         tasks (Adds real handlers per
│   │                         event_type)
│   ├── orchestrator.py       registry of _AGENT_MODULES — added "send"
│   │                         and "webhook_sink"
│   └── (ism.py, post_call.py, quote.py, researcher.py, coach.py,
│       campaign.py, analytics.py, knowledge.py, enrichment.py,
│       supervisor.py — pre-existing LangGraph agents)
│
├── services/agent/
│   ├── agent_task_service.py           claim / complete / fail / retry
│   │                                   semantics for AgentTask rows
│   ├── dispatch_service.py             enqueue_send_email /
│   │                                   enqueue_send_whatsapp /
│   │                                   enqueue_send_quote helpers
│   ├── webhook_audit_service.py        enqueue_webhook_audit
│   │                                   — never-raises audit helper
│   └── agent_approval_service.py       HITL queue
│
├── services/
│   ├── automation_worker_service.py    worker loop + _safe_run_cycle
│   │                                   ; per-company NOTIFY
│   │                                   targeting (Week 1 follow-up)
│   ├── notify_listener.py              Postgres LISTEN/NOTIFY helper
│   └── communication/
│       └── communication_service.py    low-level senders
│                                       (send_email_to_lead,
│                                        send_whatsapp_to_lead,
│                                        send_quote_to_lead)
│                                       — NOT called directly by
│                                       production code anymore;
│                                       everything goes through
│                                       dispatch_service enqueue helpers
│                                       OR the send.py executor
│
└── csrf.py, auth.py                    cookie + CSRF + OAuth
```

---

## Invariants

### Queue integrity
| Invariant | Test file |
|---|---|
| Same `idempotency_key` returns the same AgentTask row, never two | `test_agent_task_queue.py` + `test_send_dispatch.py` + `test_webhook_audit.py` |
| Backoff schedule is exactly `[2, 10, 30]` minutes | `test_agent_task_queue.py` |
| `requires_approval=True` parks the task; orchestrator is never invoked until approved | `test_agent_task_queue.py` |
| `attempts >= max_attempts` → `status='failed'`, terminal | `test_agent_task_queue.py` |
| `pg_notify` fails silently on non-Postgres engines (sqlite tests pass) | `test_agent_task_queue.py` |

### Channel selection
| Invariant | Test file |
|---|---|
| Budget ≥ $10k (or INR ≥ ~₹8L) → prefer `call` | `test_ism_requirement_routing.py` |
| Urgent timeline → prefer `whatsapp` | `test_ism_requirement_routing.py` |
| Both → `call` wins over `whatsapp` | `test_ism_requirement_routing.py` |
| No LeadRequirement row → stage default (behavior intact) | `test_ism_requirement_routing.py` |
| Latest LeadRequirement wins when multiple exist | `test_ism_requirement_routing.py` |
| Requirement override respects opt-out / cooldown / missing-contact guards | `test_ism_requirement_routing.py` |

### Send dispatch
| Invariant | Test file |
|---|---|
| `enqueue_send_email` creates AgentTask with `assigned_agent='send'`, correct payload | `test_send_dispatch.py` |
| `USE_AGENT_TASK_QUEUE=0` bypasses queue → synchronous direct send | `test_send_dispatch.py` |
| `send_email` and `send_quote` default to `requires_approval=True` (HITL) | `test_send_dispatch.py` |
| `send_whatsapp` (single) does NOT require approval (bulk does) | `test_send_dispatch.py` |
| Idempotency key fits the 200-char DB column | `test_send_dispatch.py` |

### Webhook audit
| Invariant | Test file |
|---|---|
| Audit creates AgentTask with `task_type='webhook_audit'`, `assigned_agent='webhook_sink'` | `test_webhook_audit.py` |
| Replay of same event dedupes; different `extra` creates new row | `test_webhook_audit.py` |
| `enqueue_webhook_audit` returns None on internal error — never raises | `test_webhook_audit.py` |
| `webhook_sink.run` is a no-op that returns `{ok: true}` | `test_webhook_audit.py` |

### Security (Week 1 baseline, still enforced)
| Invariant | Test file |
|---|---|
| CSRF double-submit: state-changing cookie-auth requests without matching `X-CSRF-Token` → 403 | `test_csrf.py` |
| Safe methods (GET/HEAD/OPTIONS), bypass paths, and bearer-only clients skip CSRF | `test_csrf.py` |
| Session cookie + CSRF cookie set on login/register; cleared on logout | `test_csrf.py` |

---

## Feature flags

| Env var | Default | Effect |
|---|---|---|
| `USE_AGENT_TASK_QUEUE` | `"1"` | Route send operations through AgentTask queue (Week 2 default). `"0"` → synchronous direct send (for emergency rollback) |
| `WORKER_LISTEN_NOTIFY` | `"1"` | Worker uses LISTEN/NOTIFY on Postgres. `"0"` → pure polling (sqlite, or debug) |
| `AGENT_APPROVAL_ACTIONS` | (unset → use defaults) | Comma-separated override of which task types require human approval. Default: `send_email,send_quote,send_whatsapp_bulk` |
| `COOKIE_SECURE` | `"1"` | Cookie `Secure` flag. `"0"` for local HTTP dev |
| `COOKIE_SAMESITE` | `"lax"` | Cookie SameSite attribute |
| `COOKIE_DOMAIN` | (unset) | Cookie domain. **Never set to a placeholder like `.yourdomain.com` on localhost** |
| `ALLOWED_ORIGINS` | `"http://localhost:3006"` | CORS allowlist — comma-separated. No wildcards (credentials + cookies require specific origins) |

---

## The request-to-response journeys

### Inbound WhatsApp reply

```
POST /tracking/whatsapp/inbound  (Twilio)
   │
   │  1. Handler validates signature, parses payload
   │  2. Handler calls enqueue_webhook_audit(...) with idempotency_key
   │     based on MessageSid
   │  3. Handler returns 200
   │
   ▼
AgentTask (task_type=webhook_audit, assigned_agent=webhook_sink)
   │  NOTIFY agent_task_ready fires
   │
   ▼
Worker wakes, claims the task
   │
   │  webhook_sink.run is a no-op, task
   │  completes with ok=true. Audit row lives forever as evidence.
   │
   │  webhook_sink routes by event_type:
   │  twilio_whatsapp_inbound → updates Interaction, runs reply
   │                            classifier, may enqueue next ISM cycle
   │  twilio_call_status      → runs apply_call_outcome,
   │                            advances lead stage
   │  quote_accept            → updates Quote, transitions ISM
   │                            stage to closed_won or negotiation
   │
   ▼
Interaction / Lead / Quote state updates + enqueue of next agent task
```

### ISM scheduled outreach (Week 2 current)

```
Worker tick / NOTIFY
   │
   ▼
run_worker_cycle(session, company_id)
   │
   ▼
run_ism_for_company(session, company_id, actor_user_id)
   │  For each lead in non-terminal stage:
   │
   ▼
run_ism_cycle(session, company_id, lead_id, actor_user_id)
   │
   ├── _pick_channel(session, company_id, lead, stage)
   │   ├── _requirement_preferred_channels → reads LeadRequirement
   │   ├── _STAGE_CHANNEL_PREFERENCE fallback
   │   └── guards: opt-out, cooldown, exhaustion, contact-field
   │
   └── _dispatch_{call,whatsapp,email}(session, …)
       │
       │  call   → create_call_task (CallTask queue, unchanged)
       │  whatsapp → enqueue_send_whatsapp
       │  email    → enqueue_send_email
       │
       ▼
   AgentTask row, may be awaiting_approval (send_email, send_quote)
   │
   ▼
Worker claims → send.run(task_type='send_email', …)
   │
   ▼
send.py handler calls communication_service.send_email_to_lead
   │
   ▼
Interaction row + EmailOutbox row (actual send happens via outbox loop)
```

---

## 6. Operational runbook

### Deployment order matters
When rolling out Week 2 to production:
1. Deploy backend with `USE_AGENT_TASK_QUEUE=0` first (all code paths in place, queue path disabled)
2. Verify worker is running and can claim the existing `BackgroundJob` queue cleanly
3. Flip `USE_AGENT_TASK_QUEUE=1` for one company via `CompanySetting.AGENT_APPROVAL_ACTIONS` → shadow mode
4. Monitor `AgentTask.status='failed'` counts for 24h
5. Roll out to all companies

### Emergency rollback
```
# Turn off the queue — back to synchronous direct sends
export USE_AGENT_TASK_QUEUE=0
# Restart all backend containers
```
In-flight AgentTask rows keep their status; the worker picks them up normally. The direct-send path doesn't reset them.

### Worker health check
`python run_automation_worker.py --once` runs exactly one cycle and prints the result. Use for smoke tests. The `/automation/health` HTTP endpoint returns rolling cycle metrics.

### Stuck tasks
```sql
-- Find tasks stuck in running for > 10 minutes (worker crashed mid-claim)
SELECT * FROM agent_tasks
WHERE status = 'running'
  AND started_at < now() - interval '10 minutes';
```
The worker's `_reset_stale_running_jobs` path handles this automatically at the start of each cycle — it resets to `pending` so they retry.

### Dead-letter alerts
`automation_worker_service._check_dead_letter_threshold` emails admins when `BackgroundJob + EmailOutbox + CallTask` permanently-failed rows exceed 3 per hour. Adjust via `DEAD_LETTER_THRESHOLD` env var.

---

## 7. What's NOT in Week 2 (Phase 2 and beyond)

| Deferred to | What |
|---|---|
| **Week 3** | Approvals Inbox UI (operators can see + act on `awaiting_approval` rows) |
| **Week 3** | Webhook handler migration (move inline state mutations into real executors — audit payload is already durable) |
| **Week 3** | Rules engine table + pure evaluator (`IsmRule`) |
| **Week 4** | Rules admin UI, Agent Performance Dashboard, LLM cost tracking in `AgentTask.output_json` |
| **Week 5** | Quote PDFs to S3, Alembic, structured JSON logs, secrets vault |
| **Week 6** | TanStack Query + shadcn/ui frontend pass |
| **Week 7** | Researcher + Closer agent split (complete the 3-agent ISM vision) |
| **Week 8** | Voice latency budget, SLOs, horizontal-scale worker test |
| **Week 9** | Self-service onboarding, Stripe wiring, autonomy governor |

Full roadmap at `docs/ROADMAP.md`.

---

## 8. Conventions to follow

1. **Every external action goes through AgentTask** (send_email, send_whatsapp, send_quote). No new direct calls to `communication_service.send_*` from production code. The live voice-call pipeline is the documented exception.
2. **Every webhook gets an `enqueue_webhook_audit` call** alongside its inline work. Cheap durability insurance.
3. **Every `create_agent_task` call takes an `idempotency_key`.** Webhook replays, worker restarts, UI double-clicks should all dedupe.
4. **HITL default is on for send actions.** `requires_approval=False` is the override, not the default. Callers who legitimately don't want approval document why.
5. **Tests live next to what they test.** `agents/send.py` → `test/test_send_dispatch.py`. One test file per production module where practical.
6. **Pure functions over coupled ones.** The CSRF invariants, budget parser, and timeline parser all live in modules with no DB / network / framework imports. They're free to test, free to audit.
7. **Feature-flag big changes.** `USE_AGENT_TASK_QUEUE`, `WORKER_LISTEN_NOTIFY`, `AGENT_APPROVAL_ACTIONS` — all reversible in one env var.

---

*Written at end of Week 2. 241 tests passing. Nothing pushed to GitHub.*
