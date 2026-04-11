-- v0015_login_history_location.sql
-- Add location column to login_history for approximate IP geolocation.
-- Populated asynchronously after login via ip-api.com (no API key required).
-- Applied: 2026-04-11

ALTER TABLE login_history
    ADD COLUMN IF NOT EXISTS location VARCHAR(200);
