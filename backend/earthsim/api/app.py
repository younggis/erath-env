"""FastAPI application factory."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import REPO_ROOT, get_settings
from ..catalog import repository as repo
from .routes import router, ApiError, _error, request_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    repo.ensure_migrated()
    # Kick off background ingest for any missing/stale source. Non-blocking:
    # the API is immediately usable and the UI can poll refresh tasks.
    try:
        from ..ingest_tasks import auto_refresh_if_needed
        auto_refresh_if_needed()
    except Exception:
        pass  # never block startup on ingest
    yield


app = FastAPI(title="Earth Environment Simulator", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = request_id.set(rid)
    started = time.time()
    try:
        response = await call_next(request)
    finally:
        request_id.reset(token)
    response.headers["X-Request-Id"] = rid
    response.headers["Server-Timing"] = f"total;dur={(time.time()-started)*1000:.1f}"
    return response


@app.exception_handler(ApiError)
async def handle_api_error(request: Request, exc: ApiError):
    return _error(exc.code, exc.message, exc.status, exc.details)


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    return _error("INTERNAL_ERROR", f"内部错误：{exc}", 500)


# Serve a production build when present; development uses Vite's proxy.
DIST = REPO_ROOT / "apps" / "web" / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="web-assets")


@app.get("/land110m.json", include_in_schema=False)
def basemap():
    path = DIST / "land110m.json"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "basemap not built"})
    return FileResponse(str(path), media_type="application/json")


@app.get("/earth-day.jpg", include_in_schema=False)
def earth_day():
    path = DIST / "earth-day.jpg"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "satellite basemap not built"})
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/earth-night.jpg", include_in_schema=False)
def earth_night():
    path = DIST / "earth-night.jpg"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "night-lights basemap not built"})
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", include_in_schema=False)
def index():
    index_file = DIST / "index.html"
    if index_file.exists():
        return HTMLResponse(index_file.read_text(encoding="utf-8"))
    return HTMLResponse("""<!doctype html><html><head><meta charset='utf-8'><title>EarthSim</title></head>
    <body style="font-family:system-ui;padding:2rem;background:#0a0e17;color:#dce6f2">
    <h1>Earth Environment Simulator</h1>
    <p>前端尚未构建。请在 <code>apps/web</code> 运行 <code>npm install &amp;&amp; npm run build</code>，
    或开发模式下访问 Vite 地址。</p>
    <p>API 正常：<a href="/api/v1/health" style="color:#5ec8ff">/api/v1/health</a></p></body></html>""")
