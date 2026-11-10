-- Electricity price components from Energidataservice.
-- Safe to run more than once. Run after schema.sql.
--
-- Each meter is one price component, stored in DKK/kWh excluding VAT, with
-- timestamps in UTC: hourly before QUARTERLY_FROM (see config.py), per
-- quarter-hour after. The identifier tells the provider what to fetch:
--   spot:<PriceArea>
--   tariff:<GLN_Number>:<ChargeTypeCode>[,<older ChargeTypeCode>...]
-- Charge codes get renamed now and then (Konstant did in March 2026); the
-- first listed code with a valid price wins. Look codes up at
-- https://www.energidataservice.dk/tso-electricity/DatahubPricelist

INSERT INTO utility (name, unit) VALUES ('Electricity price', 'DKK/kWh')
ON CONFLICT (name) DO NOTHING;

INSERT INTO source (name, credential_id) VALUES ('Energidataservice', NULL)
ON CONFLICT (name) DO NOTHING;

-- Meters created by an earlier version of this file
UPDATE meter SET identifier = 'tariff:5790000704842:C_FBTNTR_B,151-NT01T'
WHERE identifier = 'tariff:5790000704842:C_FBTNTR_B';
UPDATE meter SET identifier = 'tariff:5790000704842:C_FBTNTR_R,151-NRA04T'
WHERE identifier = 'tariff:5790000704842:C_FBTNTR_R';

INSERT INTO meter (utility_id, source_id, identifier, resolution)
SELECT u.utility_id, s.source_id, c.identifier, 'quarterly'
FROM (VALUES
    ('spot:DK1'),                                    -- Day-ahead spot price
    ('tariff:5790000704842:C_FBTNTR_B,151-NT01T'),   -- Konstant Net: Nettarif C
    ('tariff:5790000704842:C_FBTNTR_R,151-NRA04T'),  -- Konstant Net: Rabat Nettarif C
    ('tariff:5790000432752:40000'),                  -- Energinet: Transmissions nettarif
    ('tariff:5790000432752:41000'),                  -- Energinet: Systemtarif
    ('tariff:5790000432752:EA-001')                  -- Elafgift
) AS c(identifier)
JOIN utility u ON u.name = 'Electricity price'
JOIN source s ON s.name = 'Energidataservice'
ON CONFLICT (utility_id, source_id, identifier) DO NOTHING;

-- Price per interval (hour or quarter-hour) with full breakdown. Components
-- are excluding VAT.
-- total_incl_vat = components * 1.25 (VAT) + 0.04 (Konstant El markup, which is
-- 4 øre/kWh including VAT). It is NULL when a component is missing.
CREATE OR REPLACE VIEW electricity_price AS
SELECT
    p.*,
    (spot + net_tariff + net_discount + energinet_transmission
        + energinet_system + elafgift) * 1.25 + 0.04 AS total_incl_vat
FROM (
    SELECT
        r.timestamp AS time_utc,
        r.timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Copenhagen' AS time_dk,
        MAX(r.value) FILTER (WHERE m.identifier = 'spot:DK1') AS spot,
        MAX(r.value) FILTER (WHERE m.identifier = 'tariff:5790000704842:C_FBTNTR_B,151-NT01T') AS net_tariff,
        MAX(r.value) FILTER (WHERE m.identifier = 'tariff:5790000704842:C_FBTNTR_R,151-NRA04T') AS net_discount,
        MAX(r.value) FILTER (WHERE m.identifier = 'tariff:5790000432752:40000') AS energinet_transmission,
        MAX(r.value) FILTER (WHERE m.identifier = 'tariff:5790000432752:41000') AS energinet_system,
        MAX(r.value) FILTER (WHERE m.identifier = 'tariff:5790000432752:EA-001') AS elafgift
    FROM reading r
    JOIN meter m ON m.meter_id = r.meter_id
    JOIN source s ON s.source_id = m.source_id
    WHERE s.name = 'Energidataservice'
    GROUP BY r.timestamp
) p;
