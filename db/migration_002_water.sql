-- Run ONCE in the TigerData SQL Editor (your tables from schema.sql already exist).
-- Adds per-fuel plant watershed stress and hourly stress-weighted generation water.

-- 1. Hourly stress-weighted generation water: sum over fuels of
--    (fuel share x fuel water factor x that fuel's plant-basin stress). Filled by eia_ingest.
ALTER TABLE grid_intensity ADD COLUMN IF NOT EXISTS sw_gen_water_l_per_kwh DOUBLE PRECISION;

-- 2. Site watershed: also keep the HUC8 (for the map)
ALTER TABLE water_stress ADD COLUMN IF NOT EXISTS huc8 TEXT;

-- 3. The few plants used to represent each fuel's watersheds (for transparency / dashboard)
CREATE TABLE IF NOT EXISTS power_plants (
    plant_id      INT     NOT NULL,
    region        TEXT    NOT NULL,
    ba            TEXT    NOT NULL,
    fuel          TEXT    NOT NULL,     -- NG | COL | NUC
    name          TEXT,
    lat           DOUBLE PRECISION,
    lon           DOUBLE PRECISION,
    capacity_mw   DOUBLE PRECISION,
    huc8          TEXT,
    huc12         TEXT,
    PRIMARY KEY (plant_id, fuel)
);

-- 4. Monthly stress per fuel per grid = capacity-weighted mean of its top plants' basin stress
CREATE TABLE IF NOT EXISTS fuel_stress (
    region    TEXT NOT NULL,
    fuel      TEXT NOT NULL,
    month     INT  NOT NULL CHECK (month BETWEEN 1 AND 12),
    stress    DOUBLE PRECISION NOT NULL,
    n_plants  INT  NOT NULL,
    PRIMARY KEY (region, fuel, month)
);

-- 5. Rebuild the typical-hour fallback to include the new column
DROP MATERIALIZED VIEW IF EXISTS typical_hourly;
CREATE MATERIALIZED VIEW typical_hourly AS
SELECT
    region,
    EXTRACT(MONTH FROM ts)::INT AS month,
    EXTRACT(HOUR  FROM ts)::INT AS hour_utc,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY gco2_per_kwh)           AS gco2_per_kwh,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY gen_water_l_per_kwh)    AS gen_water_l_per_kwh,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY sw_gen_water_l_per_kwh) AS sw_gen_water_l_per_kwh
FROM grid_intensity
GROUP BY 1, 2, 3;