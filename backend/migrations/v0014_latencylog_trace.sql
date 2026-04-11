-- v0014_latencylog_trace.sql
-- Extend latencylog with per-turn trace context so all turns in a single
-- call can be linked together for waterfall analysis.
--
-- Fields:
--   trace_id    — UUID hex shared across all turns in one call
--   span_id     — UUID hex unique per turn
--   turn_index  — 0-based turn counter within the call
--   span_status — ok | error | timeout
--
-- All nullable; existing save_latency() writes still work with NULL values.
-- Applied: 2026-04-11

ALTER TABLE latencylog
    ADD COLUMN IF NOT EXISTS trace_id    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS span_id     VARCHAR(32),
    ADD COLUMN IF NOT EXISTS turn_index  INT,
    ADD COLUMN IF NOT EXISTS span_status VARCHAR(30);

CREATE INDEX IF NOT EXISTS ix_latencylog_trace_id ON latencylog(trace_id);
