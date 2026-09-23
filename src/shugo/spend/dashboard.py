"""Dashboard: one page with the STOP button, spend bars, and recent audit rows."""
from __future__ import annotations

from importlib import resources
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from shugo import killswitch, paths
from shugo.audit.log import AuditLog
from shugo.spend.budget import BudgetStore

# Buttons must send this header. Browsers won't let another site add a custom
# header to a cross-origin request without a CORS preflight, which we never
# approve, so a malicious page can't press STOP/RESUME on your behalf.
CSRF_HEADER = "x-shugo-dashboard"
RECENT_ROWS = 50


def build_router(store: BudgetStore) -> APIRouter:
    router = APIRouter()
    page = resources.files("shugo.spend").joinpath("dashboard.html").read_text("utf-8")

    def state() -> dict[str, Any]:
        rows = AuditLog(paths.audit_log()).tail(RECENT_ROWS)
        return {**killswitch.status(), "agents": store.status(), "audit": rows[::-1]}

    def guarded(request: Request) -> JSONResponse | None:
        if request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse(status_code=403, content={"error": f"missing {CSRF_HEADER} header"})
        return None

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> str:
        return page

    @router.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return state()

    @router.post("/api/stop")
    async def stop(request: Request) -> Any:
        if (denied := guarded(request)) is not None:
            return denied
        killswitch.halt(by="dashboard")
        return state()

    @router.post("/api/resume")
    async def resume(request: Request) -> Any:
        if (denied := guarded(request)) is not None:
            return denied
        killswitch.resume(by="dashboard")
        return state()

    return router
