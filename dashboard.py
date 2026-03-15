"""Sovereign — Status Dashboard.

Lightweight FastAPI server exposing organism vitals.
Runs alongside the main daemon on port 8800.

Security:
- Binds to 127.0.0.1 only (no network exposure)
- Bearer token auth via SOVEREIGN_DASHBOARD_TOKEN env var
- No docs/redoc endpoints exposed
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

log = logging.getLogger("sovereign.dashboard")

# Organism references — injected by daemon at startup
_heartbeat = None
_proprioception = None
_hands = None
_store = None
_boot_time = time.time()


def wire(heartbeat=None, proprioception=None, hands=None, store=None):
    """Called by daemon to inject organism references."""
    global _heartbeat, _proprioception, _hands, _store
    _heartbeat = heartbeat
    _proprioception = proprioception
    _hands = hands
    _store = store


def _status_payload() -> dict:
    """Build the full status JSON payload."""
    data = {
        "uptime_seconds": round(time.time() - _boot_time, 1),
        "heartbeat": {},
        "body": {},
        "hands": {},
        "memory": {},
    }

    if _heartbeat:
        data["heartbeat"] = _heartbeat.status()

    if _proprioception:
        try:
            body = _proprioception.body_state
            data["body"] = {
                "cpu_percent": round(body.cpu_percent, 1),
                "memory_percent": round(body.memory_percent, 1),
                "disk_percent": round(body.disk_percent, 1),
                "disk_free_gb": round(body.disk_free_gb, 1),
                "load_average": round(body.load_average, 2),
                "process_count": body.process_count,
                "uptime_hours": round(body.uptime_hours, 1),
                "feelings": [
                    {"system": f.system, "level": f.level, "desc": f.description}
                    for f in (body.feelings or [])
                ],
            }
        except Exception:
            pass

    if _hands:
        data["hands"] = {
            "total": len(_hands),
            "registered": list(_hands.keys()),
        }

    if _store:
        try:
            data["memory"]["total"] = _store.count_memories()
        except Exception:
            data["memory"]["total"] = -1

    return data


_STATIC_DIR = Path(__file__).parent / "static"


def create_app():
    """Create the FastAPI app."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        log.warning("FastAPI not installed — dashboard disabled (pip install fastapi uvicorn)")
        return None

    app = FastAPI(title="Sovereign Dashboard", docs_url=None, redoc_url=None)

    # Dashboard auth token (optional but recommended)
    _DASH_TOKEN = os.environ.get("SOVEREIGN_DASHBOARD_TOKEN", "")

    def _check_auth(request) -> bool:
        """Validate bearer token if SOVEREIGN_DASHBOARD_TOKEN is set."""
        if not _DASH_TOKEN:
            return True  # no token configured — allow (localhost only anyway)
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return hmac.compare_digest(auth[7:], _DASH_TOKEN)
        # Also check query param for browser access
        token = request.query_params.get("token", "")
        return hmac.compare_digest(token, _DASH_TOKEN) if token else False

    @app.get("/api/status")
    async def api_status(request: Request):
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return JSONResponse(_status_payload())

    @app.get("/api/hands")
    async def api_hands(request: Request):
        if not _check_auth(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not _hands:
            return JSONResponse({"hands": []})
        return JSONResponse({
            "hands": [
                {"name": k, "class": type(v).__name__}
                for k, v in _hands.items()
            ]
        })

    @app.get("/")
    async def index():
        html_path = _STATIC_DIR / "dashboard.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text())
        return HTMLResponse("<h1>Sovereign Dashboard</h1><p>dashboard.html not found</p>")

    return app


async def start_dashboard(host: str = "127.0.0.1", port: int = 8800):
    """Start the dashboard as a background task.

    Binds to 127.0.0.1 only — never exposed to network.
    Set SOVEREIGN_DASHBOARD_TOKEN for bearer auth.
    """
    app = create_app()
    if app is None:
        return

    try:
        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        log.info("Dashboard starting on http://%s:%d", host, port)
        await server.serve()
    except ImportError:
        log.warning("uvicorn not installed — dashboard disabled")
    except Exception as e:
        log.error("Dashboard failed: %s", e)
