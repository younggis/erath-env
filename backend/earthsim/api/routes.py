"""REST endpoints. See implementation guide section 5.1."""
from __future__ import annotations

import contextvars
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from ..config import get_settings, REPO_ROOT
from ..catalog import repository as repo
from ..catalog.db import db_path
from ..fields import grid as gmod
from ..fields.timeutil import normalize_lat, normalize_lon, parse_iso, to_iso
from ..fields.wind import describe_wind
from ..fields.units import kelvin_to_c, pa_to_hpa
from ..ingest import gfs as gfs_adapter, metar, dem
from .schemas import SampleResponse

router = APIRouter(prefix="/api/v1")
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

LAYER_INFO: dict[str, dict] = {
    "wind10": {"label": "10 m 风", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "vector"},
    "temp2m": {"label": "2 m 气温", "unit": "K", "display_unit": "°C", "palette": "temperature", "kind": "forecast", "layer_type": "scalar"},
    "rh2m": {"label": "2 m 相对湿度", "unit": "%", "display_unit": "%", "palette": "humidity", "kind": "forecast", "layer_type": "scalar"},
    "mslp": {"label": "海平面气压", "unit": "Pa", "display_unit": "hPa", "palette": "pressure", "kind": "forecast", "layer_type": "scalar"},
    "cloud_total": {"label": "总云量", "unit": "%", "display_unit": "%", "palette": "cloud", "kind": "forecast", "layer_type": "scalar"},
    "visibility_sfc": {"label": "预报能见度", "unit": "m", "display_unit": "km", "palette": "visibility", "kind": "forecast", "layer_type": "scalar"},
    "dewpoint2m": {"label": "2 m 露点", "unit": "K", "display_unit": "°C", "palette": "temperature", "kind": "forecast", "layer_type": "scalar"},
    "precip": {"label": "累计降水", "unit": "mm", "display_unit": "mm", "palette": "precip", "kind": "forecast", "layer_type": "scalar"},
    "snow_depth": {"label": "雪深", "unit": "m", "display_unit": "cm", "palette": "snow", "kind": "forecast", "layer_type": "scalar"},
    "surface_pressure": {"label": "地面气压", "unit": "Pa", "display_unit": "hPa", "palette": "pressure", "kind": "forecast", "layer_type": "scalar"},
    "cape": {"label": "对流有效位能 CAPE", "unit": "J/kg", "display_unit": "J/kg", "palette": "cape", "kind": "forecast", "layer_type": "scalar"},
    "cin": {"label": "对流抑制 CIN", "unit": "J/kg", "display_unit": "J/kg", "palette": "cape", "kind": "forecast", "layer_type": "scalar"},
    "gh500": {"label": "500 hPa 位势高度", "unit": "m2/s2", "display_unit": "gpm", "palette": "height", "kind": "forecast", "layer_type": "scalar"},
    "vvel500": {"label": "500 hPa 垂直速度", "unit": "Pa/s", "display_unit": "Pa/s", "palette": "vvel", "kind": "forecast", "layer_type": "scalar"},
    "wind500": {"label": "500 hPa 高空风丝带", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "vector"},
    "cloud_volume": {"label": "3D 体积云（多层湿度）", "unit": "1", "display_unit": "", "palette": "cloud", "kind": "forecast", "layer_type": "volume"},
    "hrrr_wind10": {"label": "HRRR 3km 10 m 风（高分辨率）", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "vector"},
    "ifs_2t": {"label": "IFS 2m 气温", "unit": "K", "display_unit": "°C", "palette": "temperature", "kind": "forecast", "layer_type": "scalar"},
    "ifs_2d": {"label": "IFS 2m 露点", "unit": "K", "display_unit": "°C", "palette": "temperature", "kind": "forecast", "layer_type": "scalar"},
    "ifs_msl": {"label": "IFS 海平面气压", "unit": "Pa", "display_unit": "hPa", "palette": "pressure", "kind": "forecast", "layer_type": "scalar"},
    "ifs_10u": {"label": "IFS 10m U 风", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "scalar"},
    "ifs_10v": {"label": "IFS 10m V 风", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "scalar"},
    "ifs_tcc": {"label": "IFS 总云量", "unit": "%", "display_unit": "%", "palette": "cloud", "kind": "forecast", "layer_type": "scalar"},
    "ifs_lcc": {"label": "IFS 低云量", "unit": "%", "display_unit": "%", "palette": "cloud", "kind": "forecast", "layer_type": "scalar"},
    "ifs_mcc": {"label": "IFS 中云量", "unit": "%", "display_unit": "%", "palette": "cloud", "kind": "forecast", "layer_type": "scalar"},
    "ifs_hcc": {"label": "IFS 高云量", "unit": "%", "display_unit": "%", "palette": "cloud", "kind": "forecast", "layer_type": "scalar"},
    "ifs_tp": {"label": "IFS 累计降水", "unit": "m", "display_unit": "mm", "palette": "precip", "kind": "forecast", "layer_type": "scalar"},
    "ifs_sd": {"label": "IFS 雪深", "unit": "m", "display_unit": "cm", "palette": "snow", "kind": "forecast", "layer_type": "scalar"},
    "ifs_tcwv": {"label": "IFS 整层水汽", "unit": "kg/m2", "display_unit": "kg/m2", "palette": "humidity", "kind": "forecast", "layer_type": "scalar"},
    "ifs_ssrd": {"label": "IFS 向下短波辐射", "unit": "J/m2", "display_unit": "MJ/m2", "palette": "cape", "kind": "forecast", "layer_type": "scalar"},
    "ifs_100u": {"label": "IFS 100m U 风", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "scalar"},
    "ifs_100v": {"label": "IFS 100m V 风", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "scalar"},
    "wave_height": {"label": "全球有效波高", "unit": "m", "display_unit": "m", "palette": "wave", "kind": "forecast", "layer_type": "scalar"},
    "wave_period": {"label": "全球峰值波周期", "unit": "s", "display_unit": "s", "palette": "waveperiod", "kind": "forecast", "layer_type": "scalar"},
    "wave_direction": {"label": "全球平均波向（来向）", "unit": "degree", "display_unit": "°", "palette": "wavedir", "kind": "forecast", "layer_type": "scalar"},
    "wave_drift": {"label": "全球波浪传播矢量（可视化）", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "vector"},
    "sst": {"label": "全球日海温 OISST", "unit": "degC", "display_unit": "°C", "palette": "temperature", "kind": "forecast", "layer_type": "scalar"},
    "cams_aod": {"label": "CAMS 全球气溶胶光学厚度", "unit": "1", "display_unit": "AOD", "palette": "aod", "kind": "forecast", "layer_type": "scalar"},
    "cams_dust": {"label": "CAMS 全球沙尘浓度", "unit": "ug/m3", "display_unit": "μg/m³", "palette": "dust", "kind": "forecast", "layer_type": "scalar"},
    "cams_pm25": {"label": "CAMS 全球 PM2.5", "unit": "ug/m3", "display_unit": "μg/m³", "palette": "pm25", "kind": "forecast", "layer_type": "scalar"},
    "gefs_wind10_mean": {"label": "GEFS 10m 风集合均值", "unit": "m/s", "display_unit": "m/s", "palette": "wind", "kind": "forecast", "layer_type": "vector"},
    "gefs_wind10_spread": {"label": "GEFS 10m 风集合离散度", "unit": "m/s", "display_unit": "m/s", "palette": "spread", "kind": "forecast", "layer_type": "scalar"},
    "gefs_temp2m_mean": {"label": "GEFS 2m 气温集合均值", "unit": "K", "display_unit": "°C", "palette": "temperature", "kind": "forecast", "layer_type": "scalar"},
    "gefs_temp2m_spread": {"label": "GEFS 2m 气温集合离散度", "unit": "K", "display_unit": "°C", "palette": "spread", "kind": "forecast", "layer_type": "scalar"},
    "gefs_wind_prob": {"label": "GEFS 10m 风>10m/s 概率（高斯近似）", "unit": "%", "display_unit": "%", "palette": "probability", "kind": "forecast", "layer_type": "scalar"},

}


def _info(layer_id: str) -> dict:
    if layer_id in LAYER_INFO:
        return LAYER_INFO[layer_id]
    return {"label": layer_id, "unit": "", "display_unit": "", "palette": "grayscale",
            "kind": "forecast", "layer_type": "scalar"}


def _error(code: str, message: str, status: int, details: dict | None = None):
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "request_id": request_id.get(), "details": details or {}}})


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, details: dict | None = None):
        self.code, self.message, self.status, self.details = code, message, status, details or {}


# --------------------------------------------------------------------------- health
@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0",
            "catalog": str(db_path()), "time": to_iso(datetime.now(timezone.utc))}


@router.get("/sources")
def sources(include_disabled: bool = False) -> dict:
    rows = repo.get_sources()
    if not include_disabled:
        rows = [r for r in rows]
    return {"sources": rows}


@router.get("/data-status")
def data_status() -> dict:
    """Freshness assessment for every dataset."""
    from ..freshness import assess
    return assess()


@router.get("/static/flight-routes")
def static_flight_routes(request: Request) -> Response:
    """Bundled OpenFlights great-circle route network with ETag revalidation."""
    from ..ingest import flight_routes
    asset = flight_routes.read_asset()
    if not asset:
        raise ApiError("NO_ROUTE_DATA", "航线数据缺失", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/static/rivers")
def static_rivers(request: Request) -> Response:
    """Bundled Natural Earth river / lake centreline GeoJSON with ETag."""
    from ..ingest import rivers
    asset = rivers.read_asset()
    if not asset:
        raise ApiError("NO_RIVER_DATA", "水系数据缺失", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/static/power-plants")
def static_power_plants(request: Request) -> Response:
    """Bundled WRI global power plant catalogue with ETag revalidation."""
    from ..ingest import power_plants
    asset = power_plants.read_asset()
    if not asset:
        raise ApiError("NO_POWER_PLANTS", "电厂数据缺失", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/static/shipping-density")
def static_shipping_density(request: Request) -> Response:
    """World Bank shipping-density texture (4096x2048 grayscale) with ETag."""
    from ..ingest import shipping_density
    asset = shipping_density.read_asset()
    if not asset:
        raise ApiError("NO_SHIPPING_TEXTURE", "海运密度纹理缺失", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="image/png", headers=headers)


@router.get("/static/volcanoes")
def static_volcanoes(request: Request) -> Response:
    """Bundled global volcano catalogue with ETag revalidation (offline-safe)."""
    from ..ingest import volcanoes
    asset = volcanoes.read_asset()
    if not asset:
        raise ApiError("NO_VOLCANO_DATA", "火山数据缺失", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/static/tectonic-plates")
def tectonic_plates(request: Request) -> Response:
    """Bundled tectonic plate boundaries with ETag revalidation (offline-safe)."""
    from ..ingest import tectonics
    asset = tectonics.read_asset()
    if not asset:
        raise ApiError("NO_TECTONIC_DATA", "板块边界资产缺失", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=86400"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/infra/cables")
def infra_cables(request: Request, type: str = "cables") -> Response:
    """Cached TeleGeography cable / landing-point GeoJSON with ETag revalidation."""
    from ..ingest import cables
    asset = cables.read_asset(type)
    if not asset:
        raise ApiError("NO_CABLE_DATA", "尚无海缆 GeoJSON；先运行 sources refresh --source telegeography", 404)
    payload, etag = asset
    headers = {"ETag": etag, "Cache-Control": "public, max-age=3600"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=payload, media_type="application/json", headers=headers)


@router.get("/space/tle")
def space_tle(groups: str | None = None, refresh: bool = False) -> dict:
    """Cached CelesTrak GP/TLE sets grouped by stations/weather/starlink."""
    from ..ingest import satellites
    selected = [g.strip() for g in groups.split(",")] if groups else None
    return satellites.get_tles(selected, force=refresh)


@router.get("/obs/air-quality")
def air_quality(limit: int = 3000) -> dict:
    """OpenAQ v3 ground air-quality stations (µg/m³ and PM2.5 AQI)."""
    from ..ingest import openaq
    status = openaq.status()
    if not status["enabled"]:
        return {**status, "count": 0, "stations": []}
    rows = repo.query_stations(None, None, source_id="openaq")
    rows = [r for r in rows if -180 <= r["lon"] <= 180 and -90 <= r["lat"] <= 90]
    return {**status, "count": min(len(rows), limit), "stations": rows[:limit]}


@router.get("/obs/buoys")
def buoys(max_age_minutes: int | None = None, bbox: str | None = None) -> dict:
    """Latest NOAA NDBC buoy observations (SI units, UTC ISO-8601 timestamps)."""
    rows = repo.query_stations(None, None, source_id="noaa_ndbc")
    if bbox:
        try:
            w, s, e, n = (float(x) for x in bbox.split(","))
        except (ValueError, TypeError):
            raise ApiError("BAD_BBOX", "bbox 应为 west,south,east,north", 422)
        rows = [r for r in rows if w <= r["lon"] <= e and s <= r["lat"] <= n]
    age = max_age_minutes if max_age_minutes is not None else get_settings().ndbc_stale_after_minutes
    now = datetime.now(timezone.utc)
    rows = [r for r in rows
            if abs((parse_iso(r["observed_at"]) - now).total_seconds()) <= max(1, age) * 60]
    return {
        "buoys": rows, "count": len(rows), "source_id": "noaa_ndbc",
        "generated_at": to_iso(now),
    }


@router.post("/sources/{source_id}/refresh", status_code=202)
def refresh_source(source_id: str) -> dict:
    """Start a non-blocking background refresh (in-flight requests are reused)."""
    from ..ingest_tasks import request_refresh
    try:
        return request_refresh(source_id)
    except KeyError:
        raise ApiError("UNKNOWN_SOURCE", f"未知源：{source_id}", 404)


@router.get("/sources/refresh/{task_id}")
def refresh_status(task_id: str) -> dict:
    from ..ingest_tasks import get_task
    task = get_task(task_id)
    if not task:
        raise ApiError("TASK_NOT_FOUND", f"任务 {task_id} 不存在", 404)
    return task


# --------------------------------------------------------------------------- layers & frames
def _active_snapshots() -> list[dict]:
    with repo.connect() as con:
        rows = list(con.execute(
            """SELECT a.dataset_id, a.snapshot_id, a.published_at, d.kind, d.source_id, d.attribution, d.license_url
               FROM active_snapshots a JOIN datasets d ON d.dataset_id=a.dataset_id
               ORDER BY d.dataset_id"""))
    return [dict(r) for r in rows]


@router.get("/layers")
def layers(mode: str | None = None, snapshot_id: str | None = None) -> dict:
    out: list[dict] = []
    for act in _active_snapshots():
        snap = repo.get_snapshot(act["snapshot_id"])
        if not snap or snap["state"] != "published":
            continue
        if snapshot_id and snap["snapshot_id"] != snapshot_id:
            continue
        frames = repo.list_frames(snapshot_id=snap["snapshot_id"])
        by_layer: dict[str, list[dict]] = {}
        for f in frames:
            by_layer.setdefault(f["layer_id"], []).append(f)
        for layer_id, fs in by_layer.items():
            if layer_id == 'terrain':
                continue  # DEM is loaded separately by the terrain layer
            info = _info(layer_id)
            kind = info["kind"] if info["kind"] != "forecast" else act["kind"]
            if mode and kind != mode:
                continue
            times = sorted(f["valid_time"] for f in fs)
            out.append({
                "layer_id": layer_id, "label": info["label"], "kind": kind,
                "source_id": act["source_id"],
                "attribution": act["attribution"], "license_url": act["license_url"],
                "unit": info["unit"], "display_unit": info["display_unit"],
                "palette": info["palette"], "layer_type": info["layer_type"],
                "snapshot_id": snap["snapshot_id"], "dataset_id": act["dataset_id"],
                "coverage": {"start": times[0] if times else None, "end": times[-1] if times else None},
                "frame_count": len(fs),
                "state": "published",
            })
    # One entry per layer: prefer a genuine forecast over other kinds.
    best: dict[str, dict] = {}
    for item in out:
        cur = best.get(item["layer_id"])
        if cur is None or (cur["kind"] != "forecast" and item["kind"] == "forecast"):
            best[item["layer_id"]] = item
    out = list(best.values())
    out.sort(key=lambda x: (0 if x["kind"] == "forecast" else 1, x["layer_id"]))
    return {"layers": out}


def _active_for_layer(layer_id: str, snapshot_id: str | None) -> str | None:
    if snapshot_id:
        return snapshot_id
    for act in _active_snapshots():
        if repo.list_frames(layer_id, snapshot_id=act["snapshot_id"], limit=1):
            return act["snapshot_id"]
    return None


@router.get("/layers/{layer_id}/frames")
def frames(layer_id: str, snapshot_id: str | None = None,
           from_: str | None = Query(None, alias="from"), to: str | None = None,
           level: str | None = None, limit: int = 200) -> dict:
    sid = _active_for_layer(layer_id, snapshot_id)
    if not sid:
        raise ApiError("LAYER_NOT_FOUND", f"图层 {layer_id} 无可用快照", 404)
    rows = repo.list_frames(layer_id, sid, from_, to, limit)
    missing = []
    if from_ and to and rows:
        have = {r["valid_time"] for r in rows}
        cur = parse_iso(from_)
        end = parse_iso(to)
        while cur <= end and len(missing) < 200:
            iso = to_iso(cur)
            if iso not in have:
                missing.append(iso)
            cur = __import__("datetime").timedelta(hours=1) + cur
    return {"layer_id": layer_id, "snapshot_id": sid, "frames": rows, "missing_times": missing}


@router.get("/frames/{frame_id}")
def frame_manifest(frame_id: str) -> dict:
    f = repo.get_frame(frame_id)
    if not f:
        raise ApiError("FRAME_NOT_FOUND", f"帧 {frame_id} 不存在", 404)
    manifest = f.get("manifest") or {}
    manifest.setdefault("schema_version", 1)
    manifest.setdefault("frame_id", frame_id)
    manifest.setdefault("valid_time", f["valid_time"])
    manifest.setdefault("grid", f["grid"])
    manifest.setdefault("fields", f["fields"])
    # Ensure the georeferencing bbox reaches the client even if the ingest
    # adapter did not copy it into the manifest (critical for image patches).
    if not manifest.get("bbox") and f.get("bbox"):
        b = f["bbox"]
        # Normalize to [west, south, east, north] for the render client.
        manifest["bbox"] = ([b["west"], b["south"], b["east"], b["north"]]
                            if isinstance(b, dict) and "west" in b else b)
    manifest["assets"] = [{"role": a["role"], "href": f"/api/v1/assets/{a['asset_id']}"} for a in f["assets"]]
    return manifest


@router.get("/assets/{asset_id}")
def asset(asset_id: str, request: Request) -> FileResponse:
    a = repo.get_asset(asset_id)
    if not a:
        raise ApiError("ASSET_NOT_FOUND", f"资产 {asset_id} 不存在", 404)
    path = repo.asset_path(a)
    if not path.exists():
        raise ApiError("ASSET_MISSING", "资产文件缺失", 503)
    etag = a["sha256"] or f"{a['bytes']}-{int(path.stat().st_mtime)}"
    if request.headers.get("if-none-match") == etag:
        return JSONResponse(status_code=304, content={}, headers={"ETag": etag})
    return FileResponse(str(path), media_type=a["media_type"], headers={
        "ETag": etag, "Cache-Control": "public, max-age=31536000, immutable"})


@router.get("/sample", response_model=SampleResponse)
def sample(frame_id: str, lon: float, lat: float) -> dict:
    f = repo.get_frame(frame_id)
    if not f:
        raise ApiError("FRAME_NOT_FOUND", f"帧 {frame_id} 不存在", 404)
    lon, lat = normalize_lon(lon), normalize_lat(lat)
    grid = gmod.GridSpec.from_dict(f["grid"])
    asset = next((a for a in f["assets"] if a["role"] == "grid"), None)
    if not asset:
        raise ApiError("NO_GRID", "该帧没有可采样的格网资产", 422)
    arr = gmod.read_grid_binary(repo.asset_path(asset), grid, len(f["fields"]))
    vals, method = gmod.bilinear_sample(grid, arr, lon, lat)
    out: list[dict] = []
    for field, v in zip(f["fields"], vals):
        item: dict[str, Any] = {"id": field["id"], "unit": field["unit"], "value": v,
                                "display_value": None}
        if v is not None:
            if field["id"] in ("temp", "dewpoint", "ifs_2t", "ifs_2d") and field["unit"] == "K":
                item["display_value"] = round(kelvin_to_c(v), 2)
                item["display_unit"] = "°C"
            elif field["id"] == "mslp" and field["unit"] == "Pa":
                item["display_value"] = round(pa_to_hpa(v), 2)
                item["display_unit"] = "hPa"
            elif field["id"] == "ifs_tp" and field["unit"] == "m":
                item["display_value"] = round(v * 1000, 2)
                item["display_unit"] = "mm"
            elif field["id"] in ("snow", "ifs_sd") and field["unit"] == "m":
                item["display_value"] = round(v * 100, 2)
                item["display_unit"] = "cm"
            elif field["id"] == "ifs_msl" and field["unit"] == "Pa":
                item["display_value"] = round(pa_to_hpa(v), 2)
                item["display_unit"] = "hPa"
            elif field["id"] == "ifs_ssrd" and field["unit"] == "J/m2":
                item["display_value"] = round(v / 1e6, 2)
                item["display_unit"] = "MJ/m2"
            elif field["id"] in ("pres",) and field["unit"] == "Pa":
                item["display_value"] = round(pa_to_hpa(v), 2)
                item["display_unit"] = "hPa"
            elif field["id"] == "gh" and field["unit"] == "m2/s2":
                item["display_value"] = round(v / 9.80665, 1)  # geopotential -> geopotential height
                item["display_unit"] = "gpm"
            else:
                item["display_value"] = round(v, 4)
                item["display_unit"] = field["unit"]
        out.append(item)
    note = None
    if f["layer_id"] == "wind10" and vals[0] is not None and vals[1] is not None:
        desc = describe_wind(vals[0], vals[1])
        out.append({"id": "wind", "unit": "", "value": desc, "display_value": None, "display_unit": ""})
        note = "粒子箭头表示风吹往的方向；文字风向表示来向"
    manifest = f.get("manifest") or {}
    return {"frame_id": frame_id, "lon": lon, "lat": lat, "valid_time": f["valid_time"],
            "values": out, "sampling_method": method,
            "quality": {"in_bounds": method != "out_of_bounds", "has_missing": any(v is None for v in vals),
                        "kind": manifest.get("kind", "")},
            "kind": manifest.get("kind", ""), "note": note}


@router.get("/stations")
def stations(bbox: str | None = None, at: str | None = None,
             max_age_minutes: int = 120, source_id: str | None = None) -> dict:
    box = None
    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            box = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            raise ApiError("BAD_BBOX", "bbox 格式应为 west,south,east,north", 422)
    return {"stations": repo.query_stations(box, at, max_age_minutes, source_id),
            "at": at, "max_age_minutes": max_age_minutes}


# --------------------------------------------------------------------------- real-time events & space weather
@router.get("/realtime/events")
def realtime_events(type: str = "usgs_quake", bbox: str | None = None,
                    limit: int = 3000, max_age_minutes: int = 180) -> dict:
    """Latest real-time point events from USGS / OpenSky / NHC / DONKI."""
    from ..ingest.realtime import EVENT_SOURCES
    if type not in EVENT_SOURCES:
        raise ApiError("BAD_EVENT_TYPE", f"未知事件类型 {type}", 422,
                       {"allowed": list(EVENT_SOURCES)})
    box = None
    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            box = tuple(parts)
        except ValueError:
            raise ApiError("BAD_BBOX", "bbox 格式应为 west,south,east,north", 422)
    rows = repo.query_stations(box, None, max_age_minutes, type)
    if limit > 0 and len(rows) > limit:
        rows = rows[-limit:]
    return {"type": type, "events": rows, "count": len(rows),
            "server_time": to_iso(datetime.now(timezone.utc))}


@router.get("/realtime/aurora")
def realtime_aurora() -> dict:
    """NOAA OVATION aurora probability grid (1° lat/lon, flat row-major)."""
    from ..ingest.realtime import read_realtime
    data = read_realtime("aurora.json")
    if data is None:
        raise ApiError("NO_DATA", "极光数据尚未采集", 404)
    return data


@router.get("/realtime/solar-wind")
def realtime_solar_wind() -> dict:
    """Latest solar-wind speed/density/Bz/Kp + 3-hour history."""
    from ..ingest.realtime import read_realtime
    data = read_realtime("solar_wind.json")
    if data is None:
        raise ApiError("NO_DATA", "太阳风数据尚未采集", 404)
    return data


@router.get("/realtime/tracks")
def realtime_tracks() -> dict:
    """GDACS tropical-cyclone tracks (observed + forecast points)."""
    from ..ingest.realtime import read_realtime
    return read_realtime("gdacs_tracks.json") or {"tracks": [], "received_at": None}


@router.get("/realtime/lightning")
def realtime_lightning(limit: int = 5000) -> dict:
    """Blitzortung lightning strikes within the current time window."""
    from ..ingest import lightning
    return lightning.status(limit)


@router.get("/realtime/fires")
def realtime_fires(limit: int = 6000) -> dict:
    """NASA FIRMS active fire hotspots (EPSG:4326, FRP in MW)."""
    from ..ingest import firms
    status = firms.status()
    if not status["enabled"]:
        return {**status, "count": 0, "fires": []}
    rows = repo.query_stations(None, None, source_id="nasa_firms")
    rows = [r for r in rows if -180 <= r["lon"] <= 180 and -90 <= r["lat"] <= 90]
    return {**status, "count": min(len(rows), limit), "fires": rows[:limit]}


@router.get("/realtime/gdacs/polygons")
def gdacs_polygons() -> dict:
    """Official GDACS impact polygons (GeoJSON rings) with alert levels."""
    from ..ingest import gdacs
    return gdacs.read_polygons()


@router.get("/realtime/summary")
def realtime_summary() -> dict:
    """Compact overview of every real-time feed for UI status."""
    from ..ingest.realtime import ALL_SOURCES, read_realtime
    from ..freshness import assess
    status = {r["source_id"]: r["state"] for r in assess()["datasets"]
              if r["source_id"] in ALL_SOURCES}
    aurora = read_realtime("aurora.json") or {}
    wind = read_realtime("solar_wind.json") or {}
    return {
        "status": status,
        "kp": wind.get("kp", aurora.get("kp")),
        "solar_wind": {k: wind.get(k) for k in ("speed_kms", "density_pcc", "bz_gsm", "time")},
        "aurora_time": aurora.get("observation_time"),
        "server_time": to_iso(datetime.now(timezone.utc)),
    }
