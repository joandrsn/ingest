-- Car usage from ConnectedCars (the dongle behind the Min Volkswagen app).
-- Safe to run more than once. Run after schema.sql.
--
-- These tables are owned by the ConnectedCars provider, which upserts them on
-- every run. Data from other sources (e.g. logged fill-ups) belongs in its own
-- tables and is combined with these in views.

-- Credentials: set the email and password of your ConnectedCars account with
--   UPDATE credential SET username = '...', password = '...'
--   WHERE credential_id = (SELECT credential_id FROM source WHERE name = 'ConnectedCars');
WITH new_credential AS (
    INSERT INTO credential (authtype, username, password, access_token_duration)
    SELECT 'usernamepassword', 'your_email', 'your_password', '1 hour'
    WHERE NOT EXISTS (SELECT 1 FROM source WHERE name = 'ConnectedCars')
    RETURNING credential_id
)
INSERT INTO source (name, credential_id)
SELECT 'ConnectedCars', credential_id FROM new_credential;

-- Vehicles are created and updated by the provider from the account.
CREATE TABLE IF NOT EXISTS vehicle (
    vehicle_id    SERIAL PRIMARY KEY,
    source_id     INT NOT NULL REFERENCES source(source_id),
    external_id   TEXT NOT NULL,              -- the provider's vehicle id
    vin           TEXT,
    license_plate TEXT,
    make          TEXT,
    model         TEXT,
    year          INT,
    fuel_type     TEXT,
    UNIQUE (source_id, external_id)
);

-- One row per completed trip. Zero-distance trips are not fetched.
CREATE TABLE IF NOT EXISTS car_trip (
    trip_id           BIGSERIAL PRIMARY KEY,
    vehicle_id        INT NOT NULL REFERENCES vehicle(vehicle_id),
    external_id       TEXT NOT NULL,          -- the provider's trip id
    start_time        TIMESTAMPTZ NOT NULL,
    end_time          TIMESTAMPTZ NOT NULL,
    duration_min      INT,
    idle_time_s       INT,
    mileage_km        NUMERIC(8,1),
    start_odometer_km NUMERIC(9,1),
    end_odometer_km   NUMERIC(9,1),
    fuel_used_l       NUMERIC(8,3),           -- the dongle's estimate, not pump litres
    start_address     TEXT,
    end_address       TEXT,
    start_latitude    NUMERIC(9,6),
    start_longitude   NUMERIC(9,6),
    end_latitude      NUMERIC(9,6),
    end_longitude     NUMERIC(9,6),
    -- The trip as the API returned it, minus the route: also holds structured
    -- addresses, CO2 and the acceleration/brake/turn events.
    raw               JSONB NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vehicle_id, external_id)
);
CREATE INDEX IF NOT EXISTS car_trip_vehicle_start ON car_trip (vehicle_id, start_time);

-- The route of a trip: a point roughly every 7-9 seconds.
CREATE TABLE IF NOT EXISTS car_trip_position (
    trip_id   BIGINT NOT NULL REFERENCES car_trip(trip_id) ON DELETE CASCADE,
    time      TIMESTAMPTZ NOT NULL,
    latitude  NUMERIC(9,6) NOT NULL,
    longitude NUMERIC(9,6) NOT NULL,
    speed_kmh SMALLINT,
    direction SMALLINT,                        -- compass heading in degrees
    PRIMARY KEY (trip_id, time)
);

-- Refuels as detected from the fuel gauge: whole litres, and the gauge tops
-- out before the tank is full. Good for when and where, not for how much.
CREATE TABLE IF NOT EXISTS car_refuel_event (
    refuel_event_id BIGSERIAL PRIMARY KEY,
    vehicle_id      INT NOT NULL REFERENCES vehicle(vehicle_id),
    external_id     TEXT NOT NULL,            -- the provider's event id
    time            TIMESTAMPTZ NOT NULL,
    liters_before   INT,
    liters_after    INT,
    address         TEXT,
    latitude        NUMERIC(9,6),
    longitude       NUMERIC(9,6),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vehicle_id, external_id)
);

-- Usage per vehicle per month (Danish time).
CREATE OR REPLACE VIEW car_usage_monthly AS
SELECT
    t.vehicle_id,
    date_trunc('month', t.start_time AT TIME ZONE 'Europe/Copenhagen')::date AS month,
    count(*)                                          AS trips,
    sum(t.mileage_km)                                 AS mileage_km,
    round(sum(t.duration_min) / 60.0, 1)              AS hours_driven,
    round(sum(t.fuel_used_l), 1)                      AS fuel_used_l,
    round(sum(t.mileage_km) / nullif(sum(t.fuel_used_l), 0), 1) AS km_per_liter,
    count(*) FILTER (WHERE t.mileage_km >= 100)       AS trips_over_100_km,
    max(t.mileage_km)                                 AS longest_trip_km
FROM car_trip t
GROUP BY 1, 2;
