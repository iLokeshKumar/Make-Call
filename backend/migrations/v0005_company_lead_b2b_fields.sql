-- v0005: Add B2B contact/address/tax fields to companies and leads
-- These fields are used on quotes, PDF generation, and invoices.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS contact_email  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS phone          VARCHAR(30),
    ADD COLUMN IF NOT EXISTS address        VARCHAR(400),
    ADD COLUMN IF NOT EXISTS city           VARCHAR(100),
    ADD COLUMN IF NOT EXISTS state          VARCHAR(100),
    ADD COLUMN IF NOT EXISTS country        VARCHAR(100),
    ADD COLUMN IF NOT EXISTS pincode        VARCHAR(20),
    ADD COLUMN IF NOT EXISTS gst_number     VARCHAR(50),
    ADD COLUMN IF NOT EXISTS pan_number     VARCHAR(20);

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS billing_address  VARCHAR(400),
    ADD COLUMN IF NOT EXISTS pincode          VARCHAR(20),
    ADD COLUMN IF NOT EXISTS gst_number       VARCHAR(50);
