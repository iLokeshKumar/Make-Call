-- v0008: Add nature_of_business, vat_number, cin_number to companies

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS nature_of_business  VARCHAR(200),
    ADD COLUMN IF NOT EXISTS vat_number          VARCHAR(50),
    ADD COLUMN IF NOT EXISTS cin_number          VARCHAR(50);
