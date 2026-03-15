"""Sovereign — Status Dashboard.

Lightweight FastAPI server exposing organism vitals.
Runs alongside the main daemon on port 8800.
"""
from __future__ import annotations

import asyncio
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
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        log.warning("FastAPI not installed — dashboard disabled (pip install fastapi uvicorn)")
        return None

    app = FastAPI(title="Sovereign Dashboard", docs_url=None, redoc_url=None)

    @app.get("/api/status")
    async def api_status():
        return JSONResponse(_status_payload())

    @app.get("/api/hands")
    async def api_hands():
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


async def start_dashboard(host: str = "0.0.0.0", port: int = 8800):
    """Start the dashboard as a background task."""
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
