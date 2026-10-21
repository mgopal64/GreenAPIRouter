-- calls: one row per live /complete call, with impact vs. the naive baseline.
-- Created by hand during MHacks; captured here so the repo can rebuild the DB.
CREATE TABLE IF NOT EXISTS calls (
  ts                   timestamptz NOT NULL DEFAULT now(),
  complexity           text,
  deployment           text,
  region               text,
  prompt_tokens        integer,
  completion_tokens    integer,
  latency_ms           integer,
  grid_source          text,
  energy_wh            double precision,
  co2_g                double precision,
  water_ml             double precision,
  water_stress_ml      double precision,
  cost_usd             double precision,
  base_deployment      text,
  base_region          text,
  base_energy_wh       double precision,
  base_co2_g           double precision,
  base_water_ml        double precision,
  base_water_stress_ml double precision,
  base_cost_usd        double precision,
  prompt_preview       text
);
SELECT create_hypertable('calls', 'ts', if_not_exists => TRUE);
