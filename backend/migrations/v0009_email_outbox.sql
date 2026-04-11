-- v0009: Email outbox queue for reliable background delivery with retries

CREATE TABLE IF NOT EXISTS email_outbox (
    id               SERIAL PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES companies(id),
    actor_user_id    INTEGER REFERENCES users(id),
    feedback_id      INTEGER REFERENCES feedback(id),
    dedupe_key       VARCHAR(200) UNIQUE,
    to_email         VARCHAR(500) NOT NULL,
    subject          VARCHAR(500) NOT NULL,
    body             TEXT NOT NULL,
    html_body        TEXT,
    company_name     VARCHAR(200),
    status           VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts         INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 5,
    next_attempt_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at          TIMESTAMPTZ,
    last_issue       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by       INTEGER REFERENCES users(id),
    updated_by       INTEGER REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS ix_email_outbox_company_id ON email_outbox(company_id);
CREATE INDEX IF NOT EXISTS ix_email_outbox_actor_user_id ON email_outbox(actor_user_id);
CREATE INDEX IF NOT EXISTS ix_email_outbox_feedback_id ON email_outbox(feedback_id);
CREATE INDEX IF NOT EXISTS ix_email_outbox_status_next ON email_outbox(status, next_attempt_at);
