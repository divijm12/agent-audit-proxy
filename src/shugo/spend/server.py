"""FastAPI app: an Anthropic-compatible /v1/messages that enforces budgets.

Point an agent at it with ANTHROPIC_BASE_URL=http://127.0.0.1:8787 and name
the agent with an `x-agent-id` header. The agent's own API key passes through;
the proxy never stores it.
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from shugo import killswitch, paths
from shugo.audit.log import AuditLog
from shugo.spend.budget import BudgetExceeded, BudgetStore
from shugo.spend.config import SpendConfig
from shugo.spend.dashboard import build_router
from shugo.spend.pricing import Price, PriceTable, cost_of_usage
from shugo.spend.sse import UsageTracker

AGENT_HEADER = "x-agent-id"
DEFAULT_AGENT = "default"
# Not forwarded upstream: hop-by-hop, recomputed, or ours.
_DROP_REQUEST_HEADERS = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "accept-encoding", AGENT_HEADER,
}
_DROP_RESPONSE_HEADERS = {"content-length", "content-encoding", "transfer-encoding", "connection"}


def _error(status: int, err_type: str, message: str) -> JSONResponse:
    """Same shape as Anthropic's own errors, so SDKs raise the usual typed exception."""
    return JSONResponse(
        status_code=status, content={"type": "error", "error": {"type": err_type, "message": message}}
    )


def _sse_error(err_type: str, message: str) -> bytes:
    data = json.dumps({"type": "error", "error": {"type": err_type, "message": message}})
    return f"event: error\ndata: {data}\n\n".encode()


def create_app(cfg: SpendConfig, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    prices = PriceTable(cfg.all_prices())
    store = BudgetStore(
        cfg.ledger_path(),
        default_limit=cfg.default_budget_usd,
        limits={a: b.budget_usd for a, b in cfg.agents.items()},
    )
    paths.ensure_layout()
    audit = AuditLog(paths.audit_log())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            base_url=cfg.upstream, transport=transport, timeout=httpx.Timeout(600.0, connect=10.0)
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(title="shugo spend proxy", lifespan=lifespan)
    app.state.store = store
    app.include_router(build_router(store))

    def halted() -> bool:
        return killswitch.is_halted()

    def record(req_id: str, agent: str, meta: dict[str, Any], decision: str, *,
               rule: str | None = None, reason: str | None = None, **extra: Any) -> None:
        audit.append(audit.build(
            request_id=req_id, server="anthropic", tool="messages", args=meta,
            decision=decision, matched_rule_id=rule, reason=reason,
            extra={"kind": "model_call", "agent_id": agent, **extra},
        ))

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "halted": halted()}

    @app.get("/spend/status")
    async def spend_status() -> dict[str, Any]:
        return {"halted": halted(), "agents": store.status()}

    @app.post("/v1/messages")
    async def messages(request: Request) -> Response:
        started = time.perf_counter()
        req_id = uuid.uuid4().hex
        agent = request.headers.get(AGENT_HEADER) or DEFAULT_AGENT
        body = await request.body()
        try:
            payload = json.loads(body)
        except ValueError:
            return _error(400, "invalid_request_error", "request body is not valid JSON")
        model = str(payload.get("model", ""))
        stream = bool(payload.get("stream"))
        meta = {"model": model, "stream": stream, "max_tokens": payload.get("max_tokens")}

        # 1. Kill switch
        if halted():
            record(req_id, agent, meta, "deny", rule="kill-switch", reason="halted by kill switch")
            return _error(403, "permission_error", "halted by kill switch: all agent calls are frozen")

        # 2. Price + budget
        price: Price | None = prices.lookup(model)
        if price is None:
            if cfg.unknown_model == "deny":
                reason = f"model '{model}' is not in the price table, so it can't be budgeted"
                record(req_id, agent, meta, "deny", rule="unknown-model", reason=reason)
                return _error(403, "permission_error", reason)
            price = prices.most_expensive()
        try:
            res = store.reserve(agent, prices.estimate_input_cost(price, body))
        except BudgetExceeded as e:
            record(req_id, agent, meta, "deny", rule="budget", reason=str(e),
                   spent_usd=round(e.spent, 6), budget_usd=e.limit)
            return _error(402, "billing_error", str(e))

        # 3. Forward
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS}
        headers["accept-encoding"] = "identity"
        client: httpx.AsyncClient = request.app.state.client

        def finish(usage: dict[str, Any], status: int, *, model_used: str | None = None,
                   note: str | None = None) -> None:
            cost = cost_of_usage(prices.lookup(model_used or model) or price, usage) if usage else 0.0
            total = store.settle(res, cost)
            record(req_id, agent, meta, "allow", reason=note, upstream_status=status,
                   usage=usage, cost_usd=round(cost, 6), spent_usd=round(total, 6),
                   latency_ms=round((time.perf_counter() - started) * 1000, 1))

        try:
            upstream_req = client.build_request("POST", "/v1/messages", headers=headers, content=body)
            upstream = await client.send(upstream_req, stream=stream)
        except httpx.HTTPError as e:
            finish({}, 502, note=f"upstream unreachable: {e.__class__.__name__}")
            return _error(502, "api_error", f"spend proxy could not reach upstream: {e}")

        out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}

        if not stream or upstream.status_code != 200:
            content = upstream.content if not stream else await upstream.aread()
            if stream:
                await upstream.aclose()
            usage: dict[str, Any] = {}
            model_used = None
            if upstream.status_code == 200:
                try:
                    data = json.loads(content)
                    usage, model_used = data.get("usage") or {}, data.get("model")
                except ValueError:
                    pass
            finish(usage, upstream.status_code, model_used=model_used)
            return Response(content=content, status_code=upstream.status_code, headers=out_headers)

        tracker = UsageTracker()

        async def relay() -> AsyncIterator[bytes]:
            note = None
            try:
                async for chunk in upstream.aiter_raw():
                    if halted():  # kill switch closes open streams too
                        note = "stream cut by kill switch"
                        yield _sse_error("permission_error", "halted by kill switch: stream closed")
                        break
                    tracker.feed(chunk)
                    yield chunk
            finally:
                # Record first: if the agent disconnected, the await below can be
                # cancelled, and the spend must not be lost with it.
                finish(tracker.usage, upstream.status_code, model_used=tracker.model, note=note)
                await upstream.aclose()

        return StreamingResponse(relay(), status_code=200, headers=out_headers)

    @app.api_route("/v1/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def passthrough(rest: str, request: Request) -> Response:
        """Everything else (count_tokens, models, ...) is forwarded untouched but still
        respects the kill switch. Nothing here is billed per token."""
        if halted():
            return _error(403, "permission_error", "halted by kill switch: all agent calls are frozen")
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST_HEADERS}
        headers["accept-encoding"] = "identity"
        client: httpx.AsyncClient = request.app.state.client
        upstream = await client.request(
            request.method, f"/v1/{rest}", params=request.query_params, headers=headers,
            content=await request.body(),
        )
        out = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}
        return Response(content=upstream.content, status_code=upstream.status_code, headers=out)

    return app
