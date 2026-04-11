-- v0006: Add catalog/classification fields to products table
-- Supports brand hierarchies (e.g. Samsung > Mobile > Galaxy S > S24 Ultra)

ALTER TABLE products
    ADD COLUMN IF NOT EXISTS brand           VARCHAR(100),
    ADD COLUMN IF NOT EXISTS category        VARCHAR(100),
    ADD COLUMN IF NOT EXISTS subcategory     VARCHAR(100),
    ADD COLUMN IF NOT EXISTS product_line    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS model_number    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS description     TEXT,
    -- pricing tiers
    ADD COLUMN IF NOT EXISTS mrp             NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS cost_price      NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS min_price       NUMERIC(12,2),
    -- tax / compliance
    ADD COLUMN IF NOT EXISTS hsn_code        VARCHAR(20),
    ADD COLUMN IF NOT EXISTS tax_rate        NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS unit            VARCHAR(30),
    -- logistics
    ADD COLUMN IF NOT EXISTS reorder_level   INTEGER,
    ADD COLUMN IF NOT EXISTS warranty_months INTEGER,
    -- media & extras
    ADD COLUMN IF NOT EXISTS image_url       VARCHAR(500),
    ADD COLUMN IF NOT EXISTS attributes      JSONB;
