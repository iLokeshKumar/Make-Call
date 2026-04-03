# Overall Architecture And Completion Matrix

Last reviewed: 2026-04-02

## 1. Current System Shape

This codebase is already a multi-tenant CRM + AI sales platform, not just a prototype.

Primary layers:

- `frontend/`: Next.js dashboard for auth, leads, calls, analytics, inventory, settings, company profile
- `backend/main.py`: FastAPI app entrypoint and router composition
- `backend/models/models.py`: tenant-aware SQLModel schema
- `backend/auth.py`: JWT auth + permission gate
- `backend/routes/`: API surface
- `backend/services/`: business logic
- `backend/pipelines/voice_pipeline.py`: real-time voice orchestration
- `backend/mcp_server.py` and `backend/tool_adapter.py`: tenant-safe tool execution for the agent

Tenant model:

- `company_id` is the tenant boundary
- most business tables are company-scoped
- JWT includes `company_id`
- route and service lookups usually filter by `company_id`

## 2. Core Runtime Architecture

### 2.1 Request/CRUD path

Flow:

1. Frontend calls FastAPI route
2. Route resolves authenticated user through `auth.get_current_user`
3. Permission gate is applied with `PermissionChecker(...)` or permission helper checks
4. Route delegates to service layer or runs thin CRUD logic
5. SQLModel persists tenant-scoped records

Main route groups:

- `routes/auth.py`
- `routes/admin.py`
- `routes/crm.py`
- `routes/campaign.py`
- `routes/call_task.py`
- `routes/quote.py`
- `routes/requirement.py`
- `routes/templates.py`
- `routes/telephony.py`
- `routes/analytics.py`

### 2.2 Voice call path

Flow:

1. `/make-call` starts an outbound Twilio call
2. `/outgoing-call` returns TwiML and opens media stream
3. `/media-stream` or `/exotel-media-stream` enters `run_media_stream()` in `backend/main.py`
4. `VoicePipeline` handles STT -> LLM -> tools -> TTS
5. transcript is buffered during call
6. `flush_transcript()` writes final transcript to `Interaction`
7. post-call extraction runs through `extract_and_save_requirements()`
8. `dispatch_next_action()` may create quote, follow-up email, follow-up call, or appointment

### 2.3 Campaign path

Flow:

1. admin creates `Campaign`
2. admin creates ordered `CampaignStep` rows
3. leads are enrolled as `CampaignRecipient`
4. launch activates recipients
5. `run_due_campaign_recipients()` executes due steps
6. email/whatsapp steps send immediately
7. call steps create `CallTask` records
8. recipient advances to later steps using `delay_hours`

### 2.4 Quote path

Flow:

1. quote created through route or next-action automation
2. items stored as `QuoteItem`
3. totals recalculated
4. PDF generated through ReportLab
5. quote sent through email and/or WhatsApp
6. quote status updated to sent / accepted / rejected

## 3. Data Model Summary

Key tenant-safe entities already present:

- `Company`
- `User`
- `Role`
- `Permission`
- `UserRole`
- `Invite`
- `Lead`
- `Interaction`
- `Campaign`
- `CampaignStep`
- `CampaignRecipient`
- `CallTask`
- `Product`
- `LeadRequirement`
- `Appointment`
- `Outcome`
- `Quote`
- `QuoteItem`
- `CompanySetting`
- `UserSetting`
- `OptOut`
- `AuditLog`

Important observations:

- `LeadRequirement` already stores structured post-call fields like `budget_range`, `timeline`, `decision_maker`, `required_products`
- `Quote` and `QuoteItem` already exist, so quote generation is not a greenfield area
- `OptOut` exists and should become the basis for DNC / unsubscribe enforcement

## 4. What Is Already Completed

### 4.1 Multi-tenant foundation

Completed:

- company-scoped schema
- company registration
- login with JWT
- invite flow
- default roles and permissions
- admin role assignment and user management
- tenant-safe leads/products/settings/integrations

Partial:

- tenant isolation is mostly in code, but not comprehensively proven by tests
- analytics has at least one raw SQL path that should be rechecked for tenant filtering

### 4.2 Outbound cold calling

Completed:

- manual outbound call endpoint
- `CallTask` model
- call-task CRUD/state flow
- campaign call-step integration

Partial:

- no true batch dialer worker
- no normalized outcome engine
- no retry scheduler

Missing:

- DNC enforcement in dial path
- batch list execution
- auto-retry policy engine

### 4.3 Demand generation

Completed:

- Apollo-related enrichment code exists
- ICP qualification tool exists
- leads already have `enrichment_status`

Partial:

- enrichment is not yet an orchestrated background pipeline
- ICP is not yet used as a durable lead-score system

Missing:

- lead scoring
- event-driven auto outreach on lead creation
- demand generation worker/service

### 4.4 Requirement gathering

Completed:

- transcript capture
- post-call extraction
- structured storage in `LeadRequirement`
- lead updates from extracted structure
- next-action dispatch after call

Partial:

- structured requirement fields are not direct columns on `Lead`
- no explicit saved AI summary on `Interaction`

### 4.5 WhatsApp campaigns

Completed:

- WhatsApp send primitive
- campaign engine supports whatsapp steps
- message templates exist

Partial:

- no inbound WhatsApp reply handling
- no delivered/read tracking
- no dedicated WhatsApp tracking worker

### 4.6 Email campaigns

Completed:

- SMTP send
- campaign engine supports email steps
- message templates exist

Partial:

- no opens/clicks tracking
- no unsubscribe flow

### 4.7 Quotation generation

Completed:

- `Quote` and `QuoteItem` models
- quote creation
- line item pricing
- PDF generation
- send via email/whatsapp
- accept/reject status APIs
- auto-quote creation from next-action flow

Partial:

- quote generation is not fully LLM-driven from transcript/context
- quote engagement tracking is missing

## 5. Status Of The Newly Created Service Files

These files exist but are currently empty scaffolds:

- `backend/services/dialer_service.py`
- `backend/services/outcome_service.py`
- `backend/services/demand_generation_service.py`
- `backend/services/tracking_service.py`

That means they should be treated as new integration points, not as completed features.

## 6. Recommended Ownership Of New Services

### `dialer_service.py`

Should own:

- batch dialing over a lead list
- sequential execution rules
- skip logic for invalid numbers / inactive leads / DNC
- retry scheduling requests
- bridge from batch jobs to `telephony.make_call`

Should reuse:

- `outbound_call_service.py`
- `routes/telephony.py`
- `models.CallTask`
- `models.OptOut`

### `outcome_service.py`

Should own:

- normalized call outcome taxonomy
- transcript + telephony signal interpretation
- mapping to `answered`, `no_answer`, `busy`, `voicemail`, `interested`, `not_interested`, `callback_requested`
- retry recommendation logic
- `CallTask.last_outcome` standardization

Should reuse:

- `post_call_service.py`
- `main.py` post-call hook
- `Interaction.transcript`
- `CallTask`

### `demand_generation_service.py`

Should own:

- lead scoring
- ICP scoring pipeline
- enrichment orchestration
- trigger-based outreach after lead creation/import
- auto-creation of `CallTask` or campaign recipient

Should reuse:

- `agent_tool_service.check_icp_qualification`
- `enrichment_service.py`
- `routes/crm.py` lead creation path
- `CallTask`
- `CampaignRecipient`

### `tracking_service.py`

Should own:

- email open tracking
- email click tracking
- WhatsApp delivery/read event handling when provider supports it
- unsubscribe / opt-out updates
- quote engagement tracking
- writing tracking signals back into `Interaction`, `OptOut`, or future tracking tables

Should reuse:

- `communication_service.py`
- `Quote`
- `Interaction`
- `OptOut`

## 7. Recommended End-State Architecture

### 7.1 Service map

- `auth_service.py`: roles, permissions, tenant-safe authorization helpers
- `communication_service.py`: send email/whatsapp primitives
- `campaign_service.py`: campaign orchestration
- `outbound_call_service.py`: call task lifecycle
- `dialer_service.py`: batch execution and retry orchestration
- `outcome_service.py`: call result classification
- `post_call_service.py`: transcript extraction
- `demand_generation_service.py`: scoring/enrichment/auto-trigger workflow
- `quote_service.py`: quote and PDF logic
- `tracking_service.py`: engagement and delivery event processing

### 7.2 Background job layer

The codebase now needs a real job runner for:

- due campaign execution
- batch dialing
- retry scheduling
- lead enrichment
- auto-triggered outreach
- tracking callback ingestion if async processing is needed

Without a job runner, these workflows remain only partially complete.

### 7.3 Event flow target

Desired event chain:

1. lead created/imported
2. demand generation service scores and enriches lead
3. outreach plan chosen
4. call task or campaign recipient scheduled
5. dialer executes call
6. outcome service classifies result
7. post-call service extracts structured needs
8. next-action service creates quote / follow-up / appointment
9. tracking service records engagement

## 8. Priority Backlog

### Priority 1

- implement `outcome_service.py`
- implement `dialer_service.py`
- enforce DNC using `OptOut`

### Priority 2

- implement `tracking_service.py`
- add email open/click tracking
- add WhatsApp delivery/reply event ingestion

### Priority 3

- implement `demand_generation_service.py`
- trigger workflow on new lead creation/import
- add lead scoring persistence

### Priority 4

- add tenant-isolation tests
- harden analytics tenant filtering
- close remaining Google integration stubs

## 9. Realistic Completion Snapshot

Current feature completeness based on code present today:

- multi-tenant foundation: 85%
- outbound cold calling: 50%
- demand generation: 25%
- requirement gathering: 80%
- WhatsApp campaigns: 60%
- email campaigns: 65%
- quotation generation: 70%

Overall platform maturity:

- core platform and schema: strong
- workflow orchestration: medium
- tracking/automation/hardening: incomplete

## 10. Final Engineering Conclusion

This repository already contains the hard part of the platform foundation:

- tenant-safe schema
- auth and RBAC
- CRM entities
- real-time voice path
- call task model
- campaign model
- post-call extraction
- quote model and PDF generation

The main remaining work is not CRUD. It is orchestration:

- workers
- normalized outcomes
- retry logic
- engagement tracking
- automatic demand-generation triggers
- stronger tests and tenant hardening
