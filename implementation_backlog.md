# Implementation Backlog

Last reviewed: 2026-04-02

This backlog is based on the current repository state, not on the older estimates in chat.

## 1. Functions To Add In Each New Service

### 1.1 `backend/services/outcome_service.py`

Purpose:

- normalize raw call results into a small set of reliable business outcomes
- decide whether to retry, close, or schedule follow-up
- feed both `CallTask` and campaign advancement logic

Functions to add:

- `normalize_call_outcome(raw_status: str | None, transcript: str | None, interaction: Interaction | None = None) -> str`
  - returns one of:
    - `answered_interested`
    - `answered_not_interested`
    - `answered_callback_requested`
    - `answered_follow_up_needed`
    - `voicemail`
    - `busy`
    - `no_answer`
    - `failed`

- `classify_outcome_from_transcript(llm_service, transcript: str) -> dict`
  - returns:
    - `normalized_outcome`
    - `confidence`
    - `summary`
    - `signals`
    - `suggested_next_action`

- `get_retry_policy(outcome: str, attempt_count: int) -> dict`
  - returns:
    - `should_retry`
    - `retry_after_hours`
    - `max_attempts_reached`

- `apply_call_outcome(session: Session, company_id: int, actor_user_id: int, task_id: int, interaction_id: int | None, raw_status: str | None, transcript: str | None) -> dict`
  - updates:
    - `CallTask.status`
    - `CallTask.last_outcome`
    - next retry scheduling if needed
    - optional campaign recipient progression

- `derive_lead_status_patch(outcome: str) -> dict`
  - maps outcome to lead updates:
    - `status`
    - `qualification_status`
    - `next_action`

Integration targets:

- `backend/main.py`
- `backend/services/outbound_call_service.py`
- `backend/services/campaign_service.py`
- `backend/services/next_action_service.py`

### 1.2 `backend/services/dialer_service.py`

Purpose:

- batch dialing over a lead list
- validate DNC and phone availability before queueing
- create and launch call tasks in sequence
- use outcome service for retries

Functions to add:

- `is_lead_callable(session: Session, company_id: int, lead_id: int) -> tuple[bool, str | None]`
  - checks:
    - lead exists
    - lead has phone
    - lead is not opted out for `call`
    - lead is active/open enough to call

- `create_batch_call_tasks(session: Session, company_id: int, actor_user_id: int, lead_ids: list[int], assigned_user_id: int | None = None, source: str = "batch_dialer") -> dict`
  - creates queued or pending tasks for valid leads
  - skips non-callable leads

- `get_next_queued_task(session: Session, company_id: int) -> CallTask | None`

- `execute_call_task(session: Session, company_id: int, actor_user_id: int, task_id: int) -> dict`
  - loads task
  - loads lead
  - calls telephony initiation path

- `run_batch_dialer(session: Session, company_id: int, actor_user_id: int, limit: int = 20) -> list[dict]`
  - runs next set of queued tasks sequentially

- `schedule_retry_for_task(session: Session, company_id: int, actor_user_id: int, task: CallTask, retry_after_hours: int, reason: str) -> CallTask`

- `opt_out_lead_from_calls(session: Session, company_id: int, actor_user_id: int, lead_id: int, reason: str | None = None) -> OptOut`

Integration targets:

- `backend/routes/call_task.py`
- `backend/routes/telephony.py`
- `backend/services/outbound_call_service.py`
- `backend/services/outcome_service.py`

### 1.3 `backend/services/demand_generation_service.py`

Purpose:

- score new leads
- enrich them
- decide outreach path
- trigger call task or campaign recipient creation

Functions to add:

- `score_lead(session: Session, company_id: int, lead_id: int) -> dict`
  - returns:
    - `score`
    - `reasons`
    - `priority`

- `compute_icp_score(lead: Lead) -> dict`
  - reuse current ICP heuristics and lead fields

- `enrich_lead_if_needed(session: Session, company_id: int, actor_user_id: int, lead_id: int) -> dict`
  - wrapper over existing enrichment logic

- `choose_outreach_strategy(session: Session, company_id: int, lead_id: int, score_payload: dict) -> dict`
  - output:
    - `strategy`
    - `schedule_call`
    - `campaign_id`
    - `delay_minutes`

- `trigger_new_lead_outreach(session: Session, company_id: int, actor_user_id: int, lead_id: int) -> dict`
  - enrich
  - score
  - set lead metadata
  - create `CallTask` or `CampaignRecipient`

- `process_recent_unscored_leads(session: Session, company_id: int, actor_user_id: int, limit: int = 50) -> list[dict]`

Integration targets:

- `backend/routes/crm.py`
- Apollo import / enrichment flow
- `backend/services/outbound_call_service.py`
- `backend/services/campaign_service.py`

### 1.4 `backend/services/tracking_service.py`

Purpose:

- centralize engagement tracking
- handle email opens/clicks
- track quote engagement
- process opt-outs and communication events

Functions to add:

- `record_email_sent(session: Session, company_id: int, actor_user_id: int, lead_id: int, interaction_id: int, tracking_payload: dict) -> dict`

- `record_email_open(session: Session, company_id: int, interaction_id: int) -> dict`

- `record_email_click(session: Session, company_id: int, interaction_id: int, target_url: str) -> dict`

- `record_whatsapp_event(session: Session, company_id: int, interaction_id: int | None, event_type: str, payload: dict) -> dict`
  - event examples:
    - `sent`
    - `delivered`
    - `read`
    - `reply_received`

- `record_quote_event(session: Session, company_id: int, quote_id: int, event_type: str, payload: dict | None = None) -> dict`
  - event examples:
    - `pdf_generated`
    - `emailed`
    - `opened`
    - `accepted`
    - `rejected`

- `unsubscribe_lead(session: Session, company_id: int, actor_user_id: int, lead_id: int, channel: str, reason: str | None = None) -> OptOut`

- `is_lead_opted_out(session: Session, company_id: int, lead_id: int, channel: str) -> bool`

Integration targets:

- `backend/services/communication_service.py`
- `backend/services/quote_service.py`
- `backend/services/dialer_service.py`
- future webhook routes

## 2. DB / Schema Changes Required

These are the minimum schema changes that would improve the current design without rewriting the system.

### 2.1 `Lead`

Current state:

- already has status, qualification, next action, enrichment status
- structured commercial details currently live in `LeadRequirement`

Recommended additions:

- `lead_score: Optional[Decimal | float | int]`
- `lead_score_reasons_json: Optional[dict]`
- `last_enriched_at: Optional[datetime]`
- `last_outreach_at: Optional[datetime]`
- `product_interest: Optional[str]`

Optional additions if you want denormalized access:

- `budget_range: Optional[str]`
- `timeline: Optional[str]`
- `decision_maker: Optional[str]`

Recommendation:

- keep `LeadRequirement` as source of truth
- copy only the most important fields onto `Lead` for filtering/dashboard speed

### 2.2 `CallTask`

Current state:

- has `status`, `attempt_count`, `last_outcome`, scheduling timestamps

Recommended additions:

- `retry_after: Optional[datetime]`
- `max_attempts: int = 3`
- `batch_id: Optional[str]`
- `outcome_confidence: Optional[Decimal | float]`
- `dialer_source: Optional[str]`

### 2.3 `Interaction`

Current state:

- already stores `transcript`, `metadata_json`, `delivery_status`

Recommended additions:

- no new column strictly required
- use `metadata_json` first for:
  - post-call summary
  - provider message ids
  - tracking ids
  - delivery/read/open timestamps

Optional if you want explicit reporting:

- `summary: Optional[str]`
- `external_message_id: Optional[str]`

### 2.4 `Quote`

Current state:

- already has status and `pdf_path`

Recommended additions:

- `opened_at: Optional[datetime]`
- `sent_at: Optional[datetime]`
- `accepted_at: Optional[datetime]`
- `rejected_at: Optional[datetime]`
- `tracking_token: Optional[str]`

### 2.5 Tracking table

Recommended new table:

- `engagement_events`

Suggested fields:

- `id`
- `company_id`
- `lead_id`
- `interaction_id`
- `quote_id`
- `channel`
- `event_type`
- `event_ts`
- `payload`

This is cleaner than overloading everything into `Interaction`.

### 2.6 Indexes / constraints

Recommended:

- index on `CallTask(company_id, status, scheduled_at)`
- index on `CallTask(company_id, retry_after)`
- index on `Lead(company_id, next_action_due_at)`
- index on `OptOut(company_id, lead_id, channel)`
- unique index on `Quote(company_id, tracking_token)` if token added

## 3. Route Changes Required

### 3.1 `routes/call_task.py`

Add:

- `POST /call-tasks/batch`
  - create batch dialer tasks from lead ids

- `POST /call-tasks/run-batch`
  - run next queued tasks for company

- `POST /call-tasks/{task_id}/apply-outcome`
  - apply normalized outcome after call completion

### 3.2 `routes/telephony.py`

Add:

- a provider callback route for outbound call completion status
- a webhook route for WhatsApp status events if provider supports it

Update:

- after call completion, delegate to `outcome_service.apply_call_outcome(...)`

### 3.3 `routes/crm.py`

Update:

- on lead creation, optionally trigger `demand_generation_service.trigger_new_lead_outreach(...)`

Add:

- optional endpoint to rescore / re-enrich a lead
- optional endpoint to opt a lead out from call/email/whatsapp

### 3.4 `routes/campaign.py`

Update:

- call steps should use outcome service to decide whether to advance, retry, or pause recipient

### 3.5 `routes/quote.py`

Add:

- public or tokenized quote-open route if tracking links are used

Update:

- call tracking service on send, accept, reject

### 3.6 New webhook/tracking routes

Recommended new file:

- `backend/routes/tracking.py`

Endpoints:

- `GET /tracking/email/open/{token}`
- `GET /tracking/email/click/{token}`
- `POST /tracking/whatsapp/status`
- `POST /tracking/unsubscribe`
- `GET /tracking/quote/open/{token}`

## 4. Step-By-Step Implementation Order

This order minimizes churn and fits the current architecture.

### Phase 1: Outcome normalization

Goal:

- make call results reliable before adding automation

Tasks:

1. implement `outcome_service.py`
2. define canonical outcome enum strings
3. wire post-call completion in `backend/main.py`
4. update `CallTask.last_outcome` consistently
5. add unit tests for outcome mapping

Deliverable:

- every completed/failed call has a normalized business outcome

### Phase 2: DNC and retry-safe dialing

Goal:

- prevent bad automation and support reattempt logic

Tasks:

1. implement `dialer_service.is_lead_callable`
2. enforce `OptOut(channel="call")`
3. implement batch task creation
4. implement retry scheduling using `retry_after`
5. add routes for batch dial creation and execution

Deliverable:

- a safe batch dialer foundation that will not call opted-out leads

### Phase 3: Demand generation trigger path

Goal:

- turn lead creation into a real workflow

Tasks:

1. implement `demand_generation_service.score_lead`
2. implement enrichment wrapper
3. implement `trigger_new_lead_outreach`
4. call it from lead creation/import flows
5. persist score on lead

Deliverable:

- new leads are scored and scheduled automatically

### Phase 4: Tracking service

Goal:

- make campaigns and quotes measurable

Tasks:

1. implement `tracking_service.py`
2. add engagement event table or metadata strategy
3. instrument email sends
4. instrument quote sends and quote opens
5. add unsubscribe flow

Deliverable:

- measurable engagement across email, quote, and opt-out events

### Phase 5: Campaign and call-task integration cleanup

Goal:

- make existing campaign engine use new services instead of bypassing them

Tasks:

1. route campaign call outcomes through `outcome_service`
2. route batch dialing through `dialer_service`
3. route opt-out checks through `tracking_service` or shared helper
4. ensure campaign recipients advance or retry based on outcome

Deliverable:

- one consistent automation path instead of parallel ad hoc flows

### Phase 6: Reporting and dashboards

Goal:

- expose the new automation state to frontend

Tasks:

1. add API payloads for lead score, retries, last outcome, opt-out state
2. update dashboard and lead detail pages
3. add campaign and quote tracking visualizations

Deliverable:

- frontend shows what the automation did and why

## 5. Recommended Immediate File-Level Task List

### `backend/services/outcome_service.py`

Implement first:

- `normalize_call_outcome`
- `classify_outcome_from_transcript`
- `get_retry_policy`
- `apply_call_outcome`

### `backend/services/dialer_service.py`

Implement second:

- `is_lead_callable`
- `create_batch_call_tasks`
- `run_batch_dialer`
- `schedule_retry_for_task`

### `backend/services/demand_generation_service.py`

Implement third:

- `compute_icp_score`
- `score_lead`
- `enrich_lead_if_needed`
- `trigger_new_lead_outreach`

### `backend/services/tracking_service.py`

Implement fourth:

- `is_lead_opted_out`
- `unsubscribe_lead`
- `record_email_sent`
- `record_quote_event`

## 6. Recommended Test Plan For This Backlog

Minimum tests to add:

- batch dialer skips opted-out leads
- batch dialer creates tasks only for callable leads
- outcome normalization returns retry for `no_answer`
- outcome normalization returns no retry for `answered_not_interested`
- lead creation trigger creates call task for high-score lead
- quote send records engagement event
- unsubscribe blocks future email/whatsapp/call send as appropriate
- company A tracking events cannot be fetched or mutated by company B

## 7. Practical Build Order For The Next Working Session

If implementing immediately, use this exact order:

1. schema changes for `CallTask`, `Lead`, `Quote`, and `engagement_events`
2. implement `outcome_service.py`
3. implement `dialer_service.py`
4. add routes in `call_task.py` and `telephony.py`
5. implement `tracking_service.py`
6. instrument `communication_service.py` and `quote_service.py`
7. implement `demand_generation_service.py`
8. trigger it from lead creation/import paths
9. add tests
10. update frontend
