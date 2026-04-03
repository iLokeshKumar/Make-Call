from sqlalchemy import text

from database import engine


DDL_STATEMENTS = [
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_score NUMERIC(5, 2)",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_score_reasons_json JSON",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_enriched_at TIMESTAMPTZ",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS last_outreach_at TIMESTAMPTZ",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS product_interest TEXT",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS budget_range VARCHAR(100)",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS timeline VARCHAR(100)",
    "ALTER TABLE leads ADD COLUMN IF NOT EXISTS decision_maker VARCHAR(200)",
    "ALTER TABLE call_tasks ADD COLUMN IF NOT EXISTS retry_after TIMESTAMPTZ",
    "ALTER TABLE call_tasks ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3",
    "ALTER TABLE call_tasks ADD COLUMN IF NOT EXISTS batch_id VARCHAR(100)",
    "ALTER TABLE call_tasks ADD COLUMN IF NOT EXISTS outcome_confidence NUMERIC(5, 2)",
    "ALTER TABLE call_tasks ADD COLUMN IF NOT EXISTS dialer_source VARCHAR(100)",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ",
    "ALTER TABLE quotes ADD COLUMN IF NOT EXISTS tracking_token VARCHAR(255)",
    """
    CREATE TABLE IF NOT EXISTS engagement_events (
        id SERIAL PRIMARY KEY,
        company_id INTEGER NOT NULL REFERENCES companies(id),
        lead_id INTEGER NULL REFERENCES leads(id),
        interaction_id INTEGER NULL REFERENCES interactions(id),
        quote_id INTEGER NULL REFERENCES quotes(id),
        channel VARCHAR(50),
        event_type VARCHAR(100) NOT NULL,
        payload JSON,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_call_tasks_company_status_scheduled_at ON call_tasks (company_id, status, scheduled_at)",
    "CREATE INDEX IF NOT EXISTS ix_call_tasks_company_retry_after ON call_tasks (company_id, retry_after)",
    "CREATE INDEX IF NOT EXISTS ix_leads_company_next_action_due_at ON leads (company_id, next_action_due_at)",
    "CREATE INDEX IF NOT EXISTS ix_opt_outs_company_lead_channel ON opt_outs (company_id, lead_id, channel)",
    "CREATE INDEX IF NOT EXISTS ix_engagement_events_company_created_at ON engagement_events (company_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_engagement_events_interaction_id ON engagement_events (interaction_id)",
    "CREATE INDEX IF NOT EXISTS ix_engagement_events_quote_id ON engagement_events (quote_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_quotes_company_tracking_token ON quotes (company_id, tracking_token) WHERE tracking_token IS NOT NULL",
]


def migrate() -> None:
    with engine.begin() as connection:
        for statement in DDL_STATEMENTS:
            print(f"Running: {statement}")
            connection.execute(text(statement))
    print("Phase 1/2 schema migration completed.")


if __name__ == "__main__":
    migrate()
