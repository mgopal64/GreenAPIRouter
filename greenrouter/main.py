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

from . import azure_client, grid, picker, router
from .regions import region_names
from .schemas import (
    CompleteRequest,
    CompleteResponse,
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
MAX_LIVE_CALLS_PER_DAY = int(os.getenv("MAX_LIVE_CALLS_PER_DAY", "200"))
MIN_DEMO_TOKEN_LEN = 20
# Number of reverse proxies in front of the app that append to X-Forwarded-For (1 on Render/Railway/Fly).
# 0 means use the socket address. Never trust the header otherwise: clients can forge it.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "0"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refresh live grid data hourly in the background so requests never wait on the grid provider.
    task = asyncio.create_task(grid.refresh_forever(region_names()))
    yield
    task.cancel()


app = FastAPI(
    title="Green AI API Router",
    lifespan=lifespan,
    docs_url="/docs" if IS_DEV else None,
    redoc_url=None,
    openapi_url="/openapi.json" if IS_DEV else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Demo-Token"],
    allow_credentials=False,
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


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/pick-model", response_model=PickModelResponse)
def pick_model(req: PickModelRequest) -> PickModelResponse:
    """PLACEHOLDER output until the teammate-owned picker in picker.py is plugged in."""
    return picker.pick_model(req)


@app.post("/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    return router.route(req)


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
    """Send a real prompt: picker chooses small/large, router chooses the region."""
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

    pick = picker.pick_model(PickModelRequest(prompt=req.prompt))
    size = "large" if pick.complexity == "complex" else "small"
    region = router.choose_region(req.weights)
    try:
        deployment = azure_client.deployment(size)
        output, prompt_tokens, completion_tokens = await azure_client.chat(region, deployment, req.prompt)
    except azure_client.AzureError as e:
        log.warning("Live call failed: %s", e)  # details stay in server logs; prompts are never logged
        raise HTTPException(502, "Model call failed") from None

    return CompleteResponse(
        complexity=pick.complexity,
        deployment=deployment,
        region=region,
        output=output,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
