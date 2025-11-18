CREATE TYPE auth_type AS ENUM ('usernamepassword', 'refreshtoken');

CREATE TABLE credential (
	credential_id SERIAL PRIMARY KEY,
	authtype auth_type NOT NULL,
	username text,
	password text,
	refreshtoken text,
	expirationdate date,
	access_token text,
	access_token_duration interval,
	access_expiration timestamp with time zone
);

CREATE TABLE utility (
    utility_id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,  -- e.g. "Electricity", "Heating"
    unit VARCHAR(20) NOT NULL          -- e.g. "kWh", "m³", "GJ"
);
CREATE TABLE source (
    source_id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE   -- e.g. "Eloverblik", "Techem"
    credential_id INT REFERENCES credential(credential_id)
);
CREATE TABLE meter (
    meter_id SERIAL PRIMARY KEY,
    utility_id INT NOT NULL REFERENCES utility(utility_id),
    source_id INT NOT NULL REFERENCES source(source_id),
    identifier VARCHAR(100) NOT NULL,   -- provider-specific meter ID
    resolution VARCHAR(20) NOT NULL,    -- "hourly" or "daily"
    UNIQUE (utility_id, source_id, identifier)
);
CREATE TABLE reading (
    reading_id BIGSERIAL PRIMARY KEY,
    meter_id INT NOT NULL REFERENCES meter(meter_id),
    timestamp TIMESTAMP NOT NULL,        -- start of the interval
    value DECIMAL(12,4) NOT NULL,        -- consumption value
    UNIQUE (meter_id, timestamp)
);

INSERT INTO credential (authtype, username, password, access_token_duration) VALUES 
	('usernamepassword', 'YYY', 'ZZZ', '15 min');
INSERT INTO credential (authtype, expirationdate, access_token_duration, refreshtoken) VALUES 
	('refreshtoken', '2026-10-25', '12 hours', 
	'XXXXX');

INSERT INTO utility (name, unit) VALUES 
    ('Electricity', 'kWh'),
    ('Heating', 'm³'),
    ('Hot water', 'm³'),
    ('Cold water', 'm³');

INSERT INTO source (name, credential_id) VALUES
    ('Eloverblik', 1),
    ('Techem', 2);


INSERT INTO meter (utility_id, source_id, identifier, resolution) 
SELECT 
    u.utility_id,
    s.source_id,
    meter_data.identifier,
    meter_data.resolution
FROM (VALUES
    ('Electricity', 'Eloverblik', 'EL-12345', 'hourly'),
    ('Heating', 'Techem', 'HE-12345', 'daily'),
    ('Hot water', 'Techem', 'HW-12345', 'daily'),
    ('Cold water', 'Techem', 'CW-12345', 'daily')
) AS meter_data(utility_name, source_name, identifier, resolution)
JOIN utility u ON u.name = meter_data.utility_name
JOIN source s ON s.name = meter_data.source_name;