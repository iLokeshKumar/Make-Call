-- 1. Add the new user_id column to the SystemSettings table
ALTER TABLE systemsettings ADD COLUMN user_id INTEGER;

-- 2. Create a foreign key constraint linking it to the user table (optional but good practice)
ALTER TABLE systemsettings ADD CONSTRAINT fk_systemsettings_user_id FOREIGN KEY (user_id) REFERENCES "user" (id) ON DELETE CASCADE;

-- 3. Create an index for faster lookups
CREATE INDEX ix_systemsettings_user_id ON systemsettings (user_id);

-- 4. (Optional Migration Step) 
-- If you want all current global settings to belong to Admin User ID 1, run this:
-- UPDATE systemsettings SET user_id = 1 WHERE user_id IS NULL;
