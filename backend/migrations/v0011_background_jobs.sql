-- v0011_background_jobs.sql
-- Persistent job queue for crash-safe background processing.
-- Applied: 2026-04-09

-- Claim-lock column on campaign_recipients prevents double-send when the
-- automation worker crashes mid-step and restarts before the next cycle.
ALTER TABLE campaign_recipients
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ;

-- Background job queue: survives FastAPI process restarts.
CREATE TABLE IF NOT EXISTS background_jobs (
    id            SERIAL PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    job_type      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    payload       JSONB NOT NULL DEFAULT '{}',
    attempts      INTEGER NOT NULL DEFAULT 0,
    max_attempts  INTEGER NOT NULL DEFAULT 3,
    run_after     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial index — only live rows, keeps the index small as done/failed accumulate.
CREATE INDEX IF NOT EXISTS ix_background_jobs_company_status_run_after
    ON background_jobs (company_id, status, run_after)
    WHERE status IN ('pending', 'running');
