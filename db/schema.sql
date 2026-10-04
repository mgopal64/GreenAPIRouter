-- Run once against TigerData:  psql "$TIGER_DSN" -f db/schema.sql

-- Hourly grid carbon + generation-water intensity per region
CREATE TABLE IF NOT EXISTS grid_intensity (
    ts                   TIMESTAMPTZ      NOT NULL,   -- UTC hour
    region               TEXT             NOT NULL,   -- 'westus' | 'northcentralus'
    ba                   TEXT             NOT NULL,   -- EIA balancing authority code
    gco2_per_kwh         DOUBLE PRECISION NOT NULL,
    gen_water_l_per_kwh  DOUBLE PRECISION NOT NULL,   -- off-site water to generate 1 kWh
    total_mwh            DOUBLE PRECISION,
    UNIQUE (ts, region)
);
SELECT create_hypertable('grid_intensity', 'ts', if_not_exists => TRUE);

-- Monthly watershed stress per region (12 rows per region)
CREATE TABLE IF NOT EXISTS water_stress (
    region   TEXT    NOT NULL,
    month    INT     NOT NULL CHECK (month BETWEEN 1 AND 12),
    huc12    TEXT    NOT NULL,
    stress   DOUBLE PRECISION NOT NULL,   -- consumption / supply, clipped to [0, 1]
    sui      DOUBLE PRECISION,            -- USGS supply-and-use index, for cross-checking
    PRIMARY KEY (region, month)
);

-- "Typical" carbon for a given month and UTC hour, used when EIA data lags.
-- Refresh after each backfill:  REFRESH MATERIALIZED VIEW typical_hourly;
CREATE MATERIALIZED VIEW IF NOT EXISTS typical_hourly AS
SELECT
    region,
    EXTRACT(MONTH FROM ts)::INT AS month,
    EXTRACT(HOUR  FROM ts)::INT AS hour_utc,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY gco2_per_kwh)        AS gco2_per_kwh,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY gen_water_l_per_kwh) AS gen_water_l_per_kwh
FROM grid_intensity
GROUP BY 1, 2, 3;

-- Example TigerData query for the dashboard's 24h replay, gap-filled:
-- SELECT time_bucket_gapfill('1 hour', ts) AS hour, region,
--        locf(avg(gco2_per_kwh)) AS gco2_per_kwh
-- FROM grid_intensity
-- WHERE ts > now() - interval '24 hours' AND ts <= now()
-- GROUP BY hour, region ORDER BY hour;