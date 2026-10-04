"""End-to-end smoke test for the running GreenAPIRouter server.

Start the server in one terminal:
  uvicorn greenrouter.main:app --reload --env-file .env
Then in another (venv active, repo root):
  python tools/smoke_test.py                 # all checks, 2 live calls
  python tools/smoke_test.py --no-live       # skip /complete (no Azure credits)
  python tools/smoke_test.py --url http://localhost:8000
"""
import argparse
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def post(url, path, body, headers=None):
    t0 = time.time()
    r = requests.post(url + path, json=body, headers=headers or {}, timeout=120)
    return r, int((time.time() - t0) * 1000)


def calls_count():
    dsn = os.environ.get("TIGER_DSN")
    if not dsn:
        return None
    import psycopg
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT count(*) FROM calls").fetchone()[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--no-live", action="store_true")
    a = p.parse_args()
    url = a.url.rstrip("/")

    # 1. Server is up
    r = requests.get(url + "/health", timeout=10)
    check("GET /health", r.status_code == 200 and r.json().get("ok") is True, r.text[:80])

    # 2. /route uses real grid data and responds to weights
    winners = {}
    for label, w in [("carbon-only", {"carbon": 1, "water": 0}),
                     ("balanced", {"carbon": 0.5, "water": 0.5}),
                     ("water-only", {"carbon": 0, "water": 1})]:
        r, ms = post(url, "/route", {"num_calls": 1000, "weights": w})
        if r.status_code != 200:
            check(f"POST /route {label}", False, f"{r.status_code} {r.text[:120]}"); continue
        d = r.json()
        dist = d["distribution"]
        best = max(dist, key=lambda x: x["share"])
        winners[label] = best["region"]
        sources = {x["region"]: x.get("grid_source") for x in dist}
        shares_ok = abs(sum(x["share"] for x in dist) - 1) < 1e-3
        check(f"POST /route {label}", shares_ok, f"best={best['region']} {best['share']:.0%}, "
              f"grid_source={sources}, {ms} ms")
        print(f"      CO2 saved {d['savings']['pct_co2']}% | stress-water saved "
              f"{d['savings'].get('pct_water_stress', 'n/a')}% | "
              + " | ".join(f"{x['region']}: {x['grid_carbon_gco2_kwh']} g/kWh, site stress "
                           f"{x.get('site_stress')}, sw {x.get('stress_weighted_l_per_kwh')} L/kWh"
                           for x in dist))
    if winners:
        real_data = all(s != "static" for s in sources.values())
        check("Grid data comes from TigerData (not static fallback)", real_data, str(sources))
        flips = winners.get("carbon-only") != winners.get("water-only")
        print(f"INFO  winner flips between carbon-only and water-only: {flips} {winners}")

    # 3. /pick-model
    for prompt in ["Classify this ticket: my order arrived broken",
                   "Write a Python function that finds the longest palindromic substring and explain its complexity"]:
        r, ms = post(url, "/pick-model", {"prompt": prompt})
        ok = r.status_code == 200
        check("POST /pick-model", ok, (f"{r.json()['complexity']} -> {r.json()['recommended_model']}, {ms} ms"
                                       if ok else f"{r.status_code} {r.text[:120]}"))

    if a.no_live:
        return summary()

    # 4. /complete: real Azure calls with impact accounting
    token = os.environ.get("DEMO_TOKEN", "")
    r, _ = post(url, "/complete", {"prompt": "hi"}, {"X-Demo-Token": "wrong-token-wrong-token"})
    check("POST /complete rejects bad token", r.status_code in (401, 503), str(r.status_code))

    before = calls_count()
    for prompt in ["Classify this ticket: my order arrived broken",
                   "Prove that the square root of 2 is irrational, step by step."]:
        r, ms = post(url, "/complete", {"prompt": prompt}, {"X-Demo-Token": token})
        if r.status_code != 200:
            check("POST /complete", False, f"{r.status_code} {r.text[:200]}"); continue
        d = r.json()
        imp = d.get("impact")
        check("POST /complete", bool(d.get("output")),
              f"{d['complexity']} -> {d['deployment']} in {d['region']}, "
              f"{d['prompt_tokens']}+{d['completion_tokens']} tokens, {ms} ms")
        check("  impact block present", imp is not None)
        if imp:
            act, base = imp["actual"], imp["baseline"]
            print(f"      actual: {act['energy_wh']:.4f} Wh, {act['co2_g']:.4f} g CO2, "
                  f"{act['water_ml']:.3f} mL, {act['water_stress_ml']:.3f} mL stress-weighted")
            print(f"      baseline ({imp['baseline_deployment']} in {imp['baseline_region']}): "
                  f"{base['co2_g']:.4f} g CO2 | saved {imp['pct_saved']} | grid {imp['grid_source']}")

    time.sleep(2)  # logging runs on a background thread
    after = calls_count()
    if before is None:
        print("SKIP  calls table check (no TIGER_DSN in .env)")
    else:
        check("Rows logged to TigerData calls table", after > before, f"{before} -> {after}")
    summary()


def summary():
    print(f"\n{sum(results)}/{len(results)} checks passed")


if __name__ == "__main__":
    main()