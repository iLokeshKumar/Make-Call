-- v0013_sentiment_events.sql
-- PostgreSQL-backed sentiment pub/sub table.
-- Replaces the in-process asyncio.Queue broadcaster so events work
-- across multiple uvicorn workers. Rows are cleaned up automatically
-- by the automation worker (sentiment_cleanup job, runs hourly).
-- Applied: 2026-04-11

CREATE TABLE IF NOT EXISTS sentiment_events (
    id          SERIAL PRIMARY KEY,
    interaction_id VARCHAR(120) NOT NULL,
    company_id  INT NOT NULL REFERENCES companies(id),
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_sentiment_events_interaction_id ON sentiment_events(interaction_id);
CREATE INDEX IF NOT EXISTS ix_sentiment_events_created_at     ON sentiment_events(created_at);
