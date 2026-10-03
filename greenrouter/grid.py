"""Grid carbon intensity, refreshed hourly from a live source with static fallback values.

The API key is read only from the server environment (GRID_API_KEY) and is never sent to clients.
Requests never trigger outbound calls: a background task refreshes the cache once an hour.
"""
import asyncio
import logging
import math
import os
import time

log = logging.getLogger(__name__)

REFRESH_S = 3600
MAX_AGE_S = 3 * 3600  # live values older than this are ignored in favor of the fallback

_live: dict[str, tuple[float, float]] = {}  # region -> (gCO2/kWh, fetched_at)


async def fetch_live(region: str) -> float | None:
    """Return the current gCO2/kWh for an Azure region, or None if unavailable.

    TODO: implement once the team picks a provider (e.g. Electricity Maps or WattTime).
    Use a fixed provider URL, a short timeout, and os.environ["GRID_API_KEY"].
    """
    return None


def _valid(value) -> bool:
    # Never trust outside data blindly: reject non-numbers, NaN/Infinity and implausible values.
    return isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 2000


async def refresh(regions: list[str]) -> None:
    if not os.getenv("GRID_API_KEY"):
        return
    for region in regions:
        try:
            value = await fetch_live(region)
        except Exception:
            log.warning("Live grid fetch failed for %s; using fallback", region)
            continue
        if _valid(value):
            _live[region] = (float(value), time.time())


async def refresh_forever(regions: list[str]) -> None:
    while True:
        await refresh(regions)
        await asyncio.sleep(REFRESH_S)


def carbon(region: str, fallback: float) -> float:
    """Latest live gCO2/kWh for a region, or the fallback if live data is missing or stale."""
    entry = _live.get(region)
    if entry and time.time() - entry[1] <= MAX_AGE_S:
        return entry[0]
    return fallback
