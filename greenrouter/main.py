import asyncio
import datetime
import hmac
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi import FastAPI, Header, HTTPException, Query, Request
from . import accounting, azure_client, dashboard, picker, router

from . import accounting, azure_client, picker, router
from .regions import REGIONS
from .schemas import (
    CompleteRequest,
    CompleteResponse,
    PickModelBatchRequest,
    PickModelBatchResponse,
    PickModelRequest,
    PickModelResponse,
    RouteRequest,
    RouteResponse,
)

log = logging.getLogger(__name__)

# Fail closed: production behavior unless GREENROUTER_ENV=dev is set explicitly.
# Secrets (API keys, DEMO_TOKEN) are read from the environment only, never from code.
IS_DEV = os.getenv("GREENROUTER_ENV") == "dev"
# Comma-separated list of frontend origins allowed to call the API from a browser.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if o.strip()
]
MAX_BODY_BYTES = 64 * 1024
RATE_LIMIT = 60  # requests per client IP per window
RATE_WINDOW_S = 60
MAX_TRACKED_IPS = 10_000
# Live model calls spend real credits, so /complete has its own, much tighter limits.
COMPLETE_RATE_LIMIT = 5  # per client IP per window
# /pick-model runs a ~180M-parameter classifier on CPU, so it gets a tighter limit than the global one.
PICK_RATE_LIMIT = 30  # per client IP per window
# One batch scores up to 50 prompts, so batches get their own, much smaller allowance.
PICK_BATCH_RATE_LIMIT = 6  # per client IP per window
MAX_LIVE_CALLS_PER_DAY = int(os.getenv("MAX_LIVE_CALLS_PER_DAY", "200"))
MIN_DEMO_TOKEN_LEN = 20
# Number of reverse proxies in front of the app that append to X-Forwarded-For (1 on Render/Railway/Fly).
# 0 means use the socket address. Never trust the header otherwise: clients can forge it.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the picker model in the background so the first real request doesn't wait on it.
    warm = asyncio.create_task(_warm_picker())
    yield
    warm.cancel()


async def _warm_picker() -> None:
    try:
        await asyncio.to_thread(picker.pick_model, PickModelRequest(prompt="warm up"))
    except Exception:
        log.exception("Picker warm-up failed; it will retry on the first request")


app = FastAPI(
    title="Green AI API Router",
    lifespan=lifespan,
    docs_url="/docs" if IS_DEV else None,
    redoc_url=None,
    openapi_url="/openapi.json" if IS_DEV else None,
)



@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Don't echo the rejected input back: it can be large, and NaN/Infinity can't be serialized.
    errors = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)


_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Real client IP. Behind N trusted proxies, the client is the Nth entry from the right of X-Forwarded-For;
    entries further left are client-supplied and can be forged."""
    if TRUSTED_PROXY_HOPS > 0:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        if len(hops) >= TRUSTED_PROXY_HOPS:
            return hops[-TRUSTED_PROXY_HOPS]
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str, limit: int = RATE_LIMIT) -> bool:
    """In-memory sliding-window limit per client key. Fine for a single instance."""
    now = time.monotonic()
    if len(_hits) > MAX_TRACKED_IPS:
        # Drop idle clients so the table can't grow without bound.
        for k in [k for k, q in _hits.items() if not q or now - q[-1] > RATE_WINDOW_S]:
            del _hits[k]
    q = _hits[ip]
    while q and now - q[0] > RATE_WINDOW_S:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


@app.middleware("http")
async def guard(request: Request, call_next):
    if _rate_limited(_client_ip(request)):
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    if not IS_DEV:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class BodySizeLimit:
    """Outermost ASGI layer: caps request bodies, including chunked ones with no Content-Length."""

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        too_large = JSONResponse({"detail": "Request body too large"}, status_code=413)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
            return await too_large(scope, receive, send)

        # Buffer the body (at most max_bytes), stopping as soon as it goes over the cap.
        chunks, received, more_body = [], 0, True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                return  # client disconnected
            body = message.get("body", b"")
            received += len(body)
            if received > self.max_bytes:
                return await too_large(scope, receive, send)
            chunks.append(body)
            more_body = message.get("more_body", False)

        replayed = False

        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


app.add_middleware(BodySizeLimit, max_bytes=MAX_BODY_BYTES)

# Added last so it's the outermost layer: early responses from the guards above (429, 413) still get CORS
# headers, and the browser shows "Too many requests" instead of a misleading "Can't reach the server".
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS + ["https://green-router-tau.vercel.app"],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/pick-model", response_model=PickModelResponse)
def pick_model(req: PickModelRequest, request: Request) -> PickModelResponse:
    if _rate_limited(f"pick:{_client_ip(request)}", PICK_RATE_LIMIT):
        raise HTTPException(429, "Too many requests")
    return picker.pick_model(req)


@app.post("/pick-model/batch", response_model=PickModelBatchResponse)
def pick_model_batch(req: PickModelBatchRequest, request: Request) -> PickModelBatchResponse:
    if _rate_limited(f"pickbatch:{_client_ip(request)}", PICK_BATCH_RATE_LIMIT):
        raise HTTPException(429, "Too many requests")
    reqs = [
        PickModelRequest(prompt=p, user_preference=req.user_preference, simplification_mode=req.simplification_mode)
        for p in req.prompts
    ]
    return PickModelBatchResponse(results=picker.pick_models(reqs))


@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    return router.route(req)

# --- Read-only dashboard data (TigerData only; no Azure calls) ---

@app.get("/summary")
def summary(hours: int = Query(24, ge=1, le=24 * 30)) -> dict:
    """Totals from logged /complete calls over the last `hours`: actual vs. naive baseline."""
    return dashboard.summary(hours)


@app.get("/regions")
def regions() -> list[dict]:
    """Per-region snapshot for the map: carbon, stress-weighted water, watershed, plants."""
    return dashboard.regions()


@app.get("/replay")
def replay(hours: int = Query(24, ge=1, le=24 * 7)) -> dict:
    """Hourly carbon and stress-weighted water per region, plus the winner each hour."""
    return dashboard.replay(hours)

_live_calls = {"day": None, "count": 0}


def _take_live_call() -> bool:
    """Global daily budget for live model calls, shared by all users. Resets at UTC midnight."""
    today = datetime.datetime.now(datetime.timezone.utc).date()
    if _live_calls["day"] != today:
        _live_calls.update(day=today, count=0)
    if _live_calls["count"] >= MAX_LIVE_CALLS_PER_DAY:
        return False
    _live_calls["count"] += 1
    return True


@app.post("/complete", response_model=CompleteResponse)
async def complete(
    req: CompleteRequest, request: Request, x_demo_token: str | None = Header(default=None)
) -> CompleteResponse:
    """Send a real prompt: picker chooses small/large, router chooses the region,
    then the call's impact is computed and logged against the naive baseline."""
    expected = os.getenv("DEMO_TOKEN", "")
    if len(expected) < MIN_DEMO_TOKEN_LEN:
        # Fail closed if no token is configured, or it's too short to resist guessing.
        log.warning("/complete disabled: DEMO_TOKEN missing or shorter than %d chars", MIN_DEMO_TOKEN_LEN)
        raise HTTPException(503, "Live calls are disabled")
    # Rate-limit before checking the token so wrong guesses count too (slows brute force).
    if _rate_limited(f"complete:{_client_ip(request)}", COMPLETE_RATE_LIMIT):
        raise HTTPException(429, "Too many live calls; slow down")
    if not x_demo_token or not hmac.compare_digest(x_demo_token.encode(), expected.encode()):
        raise HTTPException(401, "Invalid demo token")
    if not _take_live_call():
        raise HTTPException(429, "Daily live-call limit reached")

    # Model inference is CPU-bound; run it in a thread so it doesn't block the event loop.
    pick = await asyncio.to_thread(
        picker.pick_model,
        PickModelRequest(
            prompt=req.prompt,
            user_preference=req.user_preference,
            simplification_mode=req.simplification_mode,
        ),
    )
    size = "large" if pick.complexity == "complex" else "small"
    # Routing may query TigerData (blocking I/O); keep it off the event loop like the picker.
    region = await asyncio.to_thread(router.choose_region, req.weights)

    # Try the best region; if it fails (e.g. 429 rate limit), fall back to the other one.
    fallback = next(r.name for r in REGIONS["azure"] if r.name != region)
    t0 = time.time()
    for attempt_region in (region, fallback):
        try:
            deployment = azure_client.deployment(size)
            output, prompt_tokens, completion_tokens = await azure_client.chat(
                attempt_region, deployment, req.prompt)
            region = attempt_region
            break
        except azure_client.AzureError as e:
            # Details stay in server logs; prompts are never logged.
            log.warning("Live call failed in %s: %s", attempt_region, e)
    else:
        raise HTTPException(502, "Model call failed")
    latency_ms = int((time.time() - t0) * 1000)

    # Impact of this call vs. naive baseline; logged to TigerData in the background.
    impact = None
    try:
        # Impact math reads scoring data (may hit TigerData on a cold cache), so run it off the event loop too.
        acc = await asyncio.to_thread(
            accounting.account_and_log,
            prompt="",  # prompts are never logged
            complexity=pick.complexity, deployment=deployment, region=region,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, latency_ms=latency_ms,
        )
        impact = accounting.to_schema(acc)
    except Exception as e:  # accounting must never break a live call
        log.warning("Accounting failed: %s", e)

    return CompleteResponse(
        complexity=pick.complexity,
        deployment=deployment,
        region=region,
        output=output,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        impact=impact,
    )