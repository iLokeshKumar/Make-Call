# Multi-Tenant CRM Plan

## Goal
Build the portal as a multi-tenant SaaS where multiple companies use the same system, but each company can access only its own data.

## Core Rules
- One user belongs to exactly one company.
- One email belongs to exactly one company.
- `company_id` is the tenant boundary.
- Every business table must include `company_id`.
- Every query must filter by `company_id`.
- Company admins manage shared company settings, products, and integrations.
- Roles are company-specific and permission-based.
- Companies can self-register now; later onboarding will move to invite-first.

## Tech Direction
- Database: PostgreSQL
- ORM: SQLModel
- Auth: JWT
- Access Control: RBAC with custom company roles

## Main Tables
- `companies`
- `users`
- `roles`
- `permissions`
- `role_permissions`
- `user_roles`
- `invites`
- `leads`
- `interactions`
- `products`
- `appointments`
- `outcomes`
- `company_settings`
- `user_settings`
- `audit_logs`

## Tenant Isolation Rule
Every business row must belong to one company.

Examples:
- `leads.company_id`
- `products.company_id`
- `appointments.company_id`
- `outcomes.company_id`
- `company_settings.company_id`

Never fetch records only by `id`.
Always fetch with:
- `id`
- `company_id`

## Role Model
Roles are company-specific.

Default roles created for each new company:
- `company_owner`
- `company_admin`
- `sales_representative`

Roles are linked to permissions through:
- `role_permissions`

Users are linked to roles through:
- `user_roles`

## Default Permissions
- `lead.read_own`
- `lead.read_company`
- `lead.create`
- `lead.update_own`
- `lead.update_company`
- `lead.delete_own`
- `lead.delete_company`
- `interaction.read_own`
- `interaction.read_company`
- `product.read`
- `product.manage`
- `appointment.read`
- `appointment.manage`
- `outcome.read`
- `outcome.manage`
- `user.invite`
- `user.read`
- `user.manage`
- `role.read`
- `role.manage`
- `settings.read_company`
- `settings.manage_company`
- `integrations.read_company`
- `integrations.manage_company`
- `analytics.read_company`

## Config Model
Split config into:
- `company_settings`: shared company settings
- `user_settings`: personal UI/user preferences

Secret integration values are stored in `company_settings` with `is_secret = true`.

Examples of company settings:
- `COMPANY_DISPLAY_NAME`
- `COMPANY_WEBSITE`
- `PRIMARY_COLOR`
- `SYSTEM_PROMPT`

Examples of integrations:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `OPENAI_API_KEY`
- `SMTP_PASSWORD`

## Phase 1 Route Structure

### `routes/auth.py`
- `POST /companies/register`
- `POST /token`
- `POST /invites`
- `POST /invites/accept`
- `GET /users/me`

### `routes/admin.py`
- list users
- list permissions
- list roles
- create role
- update role
- assign role to user
- remove role from user
- activate/deactivate user

### `routes/crm.py`
- leads
- products
- company settings
- integrations

## Phase 1 Implementation Order
1. `models.py`
2. `database.py`
3. `main.py`
4. `auth.py`
5. `routes/auth.py`
6. `routes/admin.py`
7. `routes/crm.py`

## Build Order Detail
1. Finalize new SQLModel models
2. Reset PostgreSQL schema
3. Recreate tables with `SQLModel.metadata.create_all(engine)`
4. Seed master permissions
5. Implement company registration
6. Implement login
7. Implement invite flow
8. Implement role and user admin routes
9. Implement leads
10. Implement products
11. Implement company settings and integrations

## Reset Strategy
There is very little existing data and a backup exists.
Preferred approach:
- reset database
- start clean with the new schema
- do not spend time on migration logic

## Security Rules
- Never rely only on frontend role hiding.
- Backend must enforce permissions.
- Backend must enforce `company_id` on every query.
- Secret values must never be returned raw in normal API responses.
- Return `404` for cross-company records instead of leaking existence.

## Minimum Tests
- Company A cannot read Company B users
- Company A cannot read Company B leads
- Company A cannot read Company B products
- Company A cannot read Company B settings
- Sales user cannot access admin endpoints
- Invite from one company cannot attach a user to another company
- Same phone number can exist in different companies
- Same SKU can exist in different companies

## Deferred Modules
Do not build these until phase 1 is stable:
- appointments
- outcomes
- calling
- analytics
- dashboards
- advanced workflows

## Final Principle
First make the tenant boundary correct.
Then add features on top of it.
Do not build advanced modules on top of weak tenant isolation.

# Multi-Tenant CRM Engineering Plan

## 1. Objective
Rebuild the backend foundation so the portal safely supports multiple companies on one shared platform.

This system must ensure:
- one company cannot read or modify another company’s data
- each company can have one or many admins
- each company can define custom roles later
- company-wide settings, products, and integrations are controlled centrally by authorized users
- the backend, not the frontend, is the source of truth for permissions and tenant isolation

This plan intentionally avoids advanced modules until the tenant foundation is correct.

---

## 2. Final Operating Model

### 2.1 Tenant model
The application is a multi-tenant SaaS.

The tenant is:
- `Company`

Every business record belongs to exactly one company:
- leads
- products
- interactions
- appointments
- outcomes
- company settings
- audit logs
- future documents/uploads

The backend must always scope reads and writes by:
- authenticated `user_id`
- authenticated `company_id`

### 2.2 User model
Rules agreed:
- one email belongs to only one company
- one user belongs to only one company
- no cross-company account switching for now

Implication:
- `users.email` can remain globally unique
- `users.company_id` is required and stable

### 2.3 Access model
Authorization is company-scoped RBAC.

Each company gets:
- system roles created automatically at registration
- ability to create custom roles later

Default system roles:
- `company_owner`
- `company_admin`
- `sales_representative`

Permissions are stored as master records and assigned to roles.

Users receive access through:
- `user_roles`

---

## 3. System Design Principles

### 3.1 Tenant isolation
Tenant isolation is the highest priority rule.

Every protected business query must include:
- record id
- `company_id == current_user.company_id`

Never fetch tenant data using only primary key.

Correct:
```sql
select * from leads where id = :lead_id and company_id = :company_id;

Wrong:

select * from leads where id = :lead_id;

### 3.2 Permission enforcement

Frontend visibility is not security.

All authorization must be enforced by backend route dependencies and backend query logic.

### 3.3 Company-shared vs user-personal data

Company-shared:

- products
- company settings
- company integrations
- role definitions
- invites
- company-wide analytics

User-personal:

- optional personal preferences only
- future UI preferences
- future personal notification preferences

### 3.4 Simplicity first

Do not build telephony, analytics, dashboards, or advanced CRM flows on top of weak tenant boundaries.
The backend foundation must be stable first.

———

## 4. Data Model

### 4.1 Core tables

The clean foundation contains these tables:

- companies
- users
- roles
- permissions
- role_permissions
- user_roles
- invites
- leads
- interactions
- products
- appointments
- outcomes
- company_settings
- user_settings
- audit_logs

### 4.2 Company

Purpose:

- root tenant entity

Key fields:

- id
- name
- slug
- status
- subscription_tier
- max_users
- audit fields

### 4.3 User

Purpose:

- authenticated identity within one company

Key fields:

- id
- company_id
- email unique globally
- username optional
- password_hash
- is_active
- email_verified
- mfa_enabled
- token_version
- audit fields

### 4.4 Role

Purpose:

- company-scoped role definition

Key fields:

- id
- company_id
- name
- description
- is_system

Constraint:

- unique role name inside company

### 4.5 Permission

Purpose:

- master permission catalog

Examples:

- lead.read_own
- lead.read_company
- lead.create
- product.manage
- user.invite
- role.manage
- integrations.manage_company

### 4.6 RolePermission

Purpose:

- attach permissions to roles

### 4.7 UserRole

Purpose:

- attach roles to users

### 4.8 Invite

Purpose:

- invite-based onboarding into an existing company

Fields:

- company_id
- email
- role_id
- token
- status
- expires_at
- invited_by
- accepted_by

### 4.9 Lead

Purpose:

- tenant-safe CRM lead record

Important rule:

- phone uniqueness must be company-scoped, not global

Constraint:

- unique (company_id, normalized_phone)

### 4.10 Product

Purpose:

- company-managed product catalog

Constraint:

- unique (company_id, sku) if SKU is used

### 4.11 CompanySetting

Purpose:

- company-wide configuration and integration storage

Includes:

- non-secret business settings
- secret integration values

Constraint:

- unique (company_id, key)

### 4.12 UserSetting

Purpose:

- user-specific preferences only

### 4.13 AuditLog

Purpose:

- record sensitive changes and security events

———

## 5. Routing Strategy

### 5.1 routes/auth.py

Initial endpoints:

- POST /companies/register
- POST /token
- POST /invites
- POST /invites/accept
- GET /users/me

Responsibilities:

- create a new company
- create first owner user
- authenticate user
- create invite
- accept invite
- return current authenticated user

### 5.2 routes/admin.py

Initial endpoints:

- list users
- list permissions
- list roles
- create role
- update role
- assign role to user
- remove role from user
- activate/deactivate user

Responsibilities:

- company admin management
- role and permission administration
- user lifecycle inside tenant

### 5.3 routes/crm.py

Initial endpoints:

- leads
- products
- company settings
- integrations

Responsibilities:

- tenant-safe business CRUD
- company-managed shared settings
- masked integration reads
- encrypted integration writes

———

## 6. Auth and Authorization Architecture

### 6.1 JWT contents

The access token should contain:

- user_id
- company_id
- token_version
- expiry

This avoids repeated identity ambiguity and lets the backend verify tenant ownership quickly.

### 6.2 Current user dependency

The get_current_user dependency must:

1. decode JWT
2. fetch user by user_id
3. ensure user.company_id matches token company_id
4. ensure token_version matches DB
5. ensure user is active

### 6.3 Permission dependency

A PermissionChecker("permission.key") dependency must:

1. load user roles
2. load user permissions from role assignments
3. deny request if permission missing

### 6.4 Future rule

Later, when stable, add PostgreSQL Row Level Security as a second protection layer.
Do not start with RLS first. First make app-level isolation correct and testable.

———

## 7. Company Registration Flow

### 7.1 Self-registration

For now, companies can self-register.

Sequence:

1. validate company slug uniqueness
2. validate admin email uniqueness
3. create company
4. create admin user in that company
5. seed master permissions if not already seeded
6. create default system roles for that company
7. assign all owner permissions to first user
8. issue JWT token

### 7.2 Invite-based onboarding

Later onboarding path:

1. admin creates invite with email + role
2. system stores invite token and expiry
3. invited user accepts invite
4. backend verifies token is valid and email matches invite
5. create user with invite company
6. assign invited role
7. mark invite accepted

Both flows can coexist. Later, self-registration can be disabled without redesigning the system.

———

## 8. Role and Permission Design

### 8.1 Default system roles

Each new company should receive:

#### company_owner

Purpose:

- full access inside company
- responsible for company administration

#### company_admin

Purpose:

- operational administration
- manages users, settings, products, roles depending on policy

#### sales_representative

Purpose:

- limited CRM access
- usually owns and manages only their assigned leads

### 8.2 Suggested default permission mapping

#### company_owner

- all permissions

#### company_admin

- lead.read_company
- lead.create
- lead.update_company
- lead.delete_company
- interaction.read_company
- product.read
- product.manage
- appointment.read
- appointment.manage
- outcome.read
- outcome.manage
- user.invite
- user.read
- user.manage
- role.read
- role.manage
- settings.read_company
- settings.manage_company
- integrations.read_company
- integrations.manage_company
- analytics.read_company

#### sales_representative

- lead.read_own
- lead.create
- lead.update_own
- interaction.read_own
- product.read
- appointment.read

### 8.3 Custom roles

Company admins should later be able to create custom roles like:

- sales_manager
- support_agent
- call_operator

Each custom role is isolated to its own company through company_id.

———

## 9. CRM Data Access Rules

### 9.1 Leads

Rules:

- every lead belongs to a company
- each lead has optional owner user
- duplicate phone numbers allowed across companies, not within same company

Permission behavior:

- lead.read_own: user can view only leads they own
- lead.read_company: user can view all company leads
- lead.update_own: only owned leads
- lead.update_company: all company leads
- same for delete permissions

### 9.2 Products

Rules:

- products are company-wide shared catalog entries
- visible to users with product.read
- managed only by users with product.manage

### 9.3 Company settings

Rules:

- non-secret business configuration lives in company settings
- readable by users with settings.read_company
- writable by users with settings.manage_company

### 9.4 Integrations

Rules:

- stored under same company setting table or company credential table
- secret values encrypted at rest
- normal read endpoints return masked values only
- only users with integration permissions can access these endpoints

———

## 10. Build Plan

### Phase 0: Prepare clean baseline

Because current data volume is tiny and backup exists, do not migrate old business records.

Tasks:

1. backup current database
2. reset PostgreSQL schema
3. remove dependence on old mixed models
4. rebuild cleanly from scratch

### Phase 1: Data layer

Deliverables:

- finalized models.py
- finalized database.py
- init_db() creates all tables
- master permissions seeded

Success criteria:

- application starts
- PostgreSQL tables are created cleanly
- permission seed is present

### Phase 2: Auth layer

Deliverables:

- POST /companies/register
- POST /token
- GET /users/me
- JWT generation and validation
- get_current_user dependency
- PermissionChecker

Success criteria:

- new company can register
- owner can log in
- token includes and validates company_id

### Phase 3: Invite flow

Deliverables:

- POST /invites
- POST /invites/accept

Success criteria:

- admin can invite user into same company
- invited user joins correct company only
- invite email mismatch is blocked
- invite expiry works

### Phase 4: Admin layer

Deliverables:

- list users
- list roles
- list permissions
- create/update role
- assign/remove user role
- activate/deactivate user

Success criteria:

- company admin can manage only its own company users and roles
- custom role creation works
- roles from another company cannot be assigned

### Phase 5: CRM leads

Deliverables:

- create lead
- list leads
- get lead
- update lead
- delete lead

Success criteria:

- own/company lead permissions work
- company A cannot access company B leads
- same phone number can be reused across companies

### Phase 6: CRM products

Deliverables:

- create/list/get/update/delete products

Success criteria:

- products are isolated by company
- SKU uniqueness is company-scoped
- read vs manage permissions work

### Phase 7: Company settings and integrations

Deliverables:

- read/update company settings
- masked read for integrations
- encrypted write for integrations

Success criteria:

- non-admin users cannot manage company integrations
- secret values are never returned raw
- settings are isolated by company

———

## 11. Code Structure

Recommended backend structure:

- backend/main.py
- backend/database.py
- backend/auth.py
- backend/models/models.py
- backend/routes/auth.py
- backend/routes/admin.py
- backend/routes/crm.py
- backend/services/authz_service.py

Responsibilities:

- models.py: schema and request models
- database.py: engine, session, permission seed
- auth.py: JWT, current user, permission dependency
- authz_service.py: role/permission helpers
- route files: only endpoint orchestration

Keep business logic out of route files where possible.

———

## 12. Reset Strategy

Because there is almost no useful data, the safest path is a clean reset.

Recommended reset:

DROP SCHEMA public CASCADE;
CREATE SCHEMA public;

Then:

- start app
- run init_db()
- create first company through API

Do not maintain old and new models side by side unless absolutely necessary.

———

## 13. Testing Plan

### 13.1 Authentication tests

- company registration creates company and owner
- owner login returns valid token
- inactive user cannot log in
- token with wrong company data is rejected

### 13.2 Invite tests

- admin can create invite
- invite accept creates user in correct company
- invite email mismatch is rejected
- expired invite is rejected

### 13.3 Tenant isolation tests

- company A cannot read company B users
- company A cannot read company B leads
- company A cannot read company B products
- company A cannot read company B settings
- company A cannot update or delete company B rows

### 13.4 Permission tests

- sales rep cannot access role management
- sales rep cannot update company settings
- sales rep can read own leads only
- admin can read all company leads
- admin can manage products

### 13.5 Data integrity tests

- duplicate lead phone inside same company is blocked
- same lead phone across different companies is allowed
- duplicate role name inside same company is blocked
- same role name across different companies is allowed
- duplicate SKU inside same company is blocked if SKU is used

———

## 14. Deferred Work

Do not build these until the above phases are stable:

- telephony pipeline
- appointments module
- outcomes/pipeline module
- dashboards
- analytics
- RAG isolation
- file uploads by company
- audit UI
- PostgreSQL Row Level Security
- MFA hardening
- billing/plan enforcement

These should be added only after the tenant-safe base is working.

———

## 15. Final Engineering Rule

Do not optimize for speed of feature delivery before tenant isolation is correct.

The correct build order is:

1. tenant-safe schema
2. auth
3. RBAC
4. core CRM
5. shared settings/integrations
6. everything else