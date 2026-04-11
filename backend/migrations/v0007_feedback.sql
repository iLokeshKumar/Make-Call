-- v0007: Feedback system — post-call reviews, CSAT, general feedback

CREATE TABLE IF NOT EXISTS feedback (
    id                    SERIAL PRIMARY KEY,
    company_id            INTEGER NOT NULL REFERENCES companies(id),
    lead_id               INTEGER REFERENCES leads(id),
    interaction_id        INTEGER REFERENCES interactions(id),
    submitted_by_user_id  INTEGER REFERENCES users(id),

    feedback_type         VARCHAR(50)  NOT NULL DEFAULT 'general',
    source                VARCHAR(20)  NOT NULL DEFAULT 'internal',

    rating                SMALLINT,
    comment               TEXT,
    disposition           VARCHAR(50),
    tags                  JSONB,

    -- CSAT public link
    token                 VARCHAR(100) UNIQUE,
    token_expires_at      TIMESTAMPTZ,
    responded_at          TIMESTAMPTZ,
    status                VARCHAR(20)  NOT NULL DEFAULT 'submitted',

    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by            INTEGER REFERENCES users(id),
    updated_by            INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS ix_feedback_company_id    ON feedback(company_id);
CREATE INDEX IF NOT EXISTS ix_feedback_lead_id       ON feedback(lead_id);
CREATE INDEX IF NOT EXISTS ix_feedback_interaction_id ON feedback(interaction_id);
CREATE INDEX IF NOT EXISTS ix_feedback_token         ON feedback(token);
