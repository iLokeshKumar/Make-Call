-- v0010: Feedback close-loop fields + public CSAT audit table

ALTER TABLE feedback
    ADD COLUMN IF NOT EXISTS assignee_user_id INTEGER REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS close_loop_status VARCHAR(30) NOT NULL DEFAULT 'none',
    ADD COLUMN IF NOT EXISTS status_note TEXT,
    ADD COLUMN IF NOT EXISTS follow_up_task_id INTEGER REFERENCES call_tasks(id);

CREATE INDEX IF NOT EXISTS ix_feedback_assignee_user_id ON feedback(assignee_user_id);
CREATE INDEX IF NOT EXISTS ix_feedback_follow_up_task_id ON feedback(follow_up_task_id);

CREATE TABLE IF NOT EXISTS feedback_public_audit (
    id           SERIAL PRIMARY KEY,
    company_id   INTEGER REFERENCES companies(id),
    feedback_id  INTEGER REFERENCES feedback(id),
    action       VARCHAR(30) NOT NULL,
    status       VARCHAR(30) NOT NULL,
    token_key    VARCHAR(120),
    ip_address   VARCHAR(64),
    user_agent   TEXT,
    rating       SMALLINT,
    detail       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by   INTEGER REFERENCES users(id),
    updated_by   INTEGER REFERENCES users(id)
);

ALTER TABLE feedback_public_audit
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS updated_by INTEGER REFERENCES users(id);

CREATE INDEX IF NOT EXISTS ix_feedback_public_audit_created_at ON feedback_public_audit(created_at);
CREATE INDEX IF NOT EXISTS ix_feedback_public_audit_token ON feedback_public_audit(token_key);
