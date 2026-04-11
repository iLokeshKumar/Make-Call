-- v0012_soft_delete.sql
-- Soft delete for leads and interactions + campaign_recipient uniqueness guard.
-- Applied: 2026-04-11

-- Soft delete: leads
ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Soft delete: interactions
ALTER TABLE interactions
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Unique constraint on campaign_recipients (already in model, add to DB if missing)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_campaign_recipient'
    ) THEN
        ALTER TABLE campaign_recipients
            ADD CONSTRAINT uq_campaign_recipient UNIQUE (campaign_id, lead_id);
    END IF;
END $$;
