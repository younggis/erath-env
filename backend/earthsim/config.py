"""Configuration loading for the Earth Environment Simulator.

Values are resolved in this order (later wins):
  1. config/defaults.toml
  2. .env file at the repository root
  3. real environment variables

The storage root is special: when ``EARTHSIM_STORAGE_ROOT`` points at the
container path ``/data`` and that path is not available (e.g. running the CLI
directly on the Windows host), it falls back to ``EARTHSIM_LOCAL_DATA_DIR``
relative to the repository root so the same code runs inside and outside Docker.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:  # Python 3.11+ ships tomllib
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def find_repo_root(start: Path | None = None) -> Path:
    p = start or Path(__file__).resolve()
    for parent in [p, *p.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root()


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _env(name: str, default: Any, cast: type) -> Any:
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    if cast is bool:
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return cast(val)


@dataclass
class Settings:
    data_mode: str = "fixture"
    http_port: int = 8080
    server_host: str = "127.0.0.1"
    ui_timezone: str = "local"
    storage_root: str = "/data"
    local_data_dir: str = ".local-data"

    gfs_poll_seconds: int = 900
    gfs_lead_max_hours: int = 36
    volume_lead_max_hours: int = 3  # 3D cloud volume timeline (f000..f003)
    wave_lead_max_hours: int = 3    # GFS-Wave timeline (f000..f003)
    gefs_lead_max_hours: int = 6    # GEFS ensemble timeline (f000/f003/f006)
    gfs_stale_after_hours: int = 13
    oisst_stale_after_hours: int = 480  # AVHRR-only analysis lags ~2 weeks
    cams_stale_after_hours: int = 24
    firms_min_frp_mw: float = 10.0
    lightning_window_minutes: int = 20
    lightning_max_strikes: int = 5000
    lightning_poll_seconds: int = 30
    lightning_timeout_seconds: float = 8.0
    openaq_api_key: str = ""
    openaq_page_size: int = 100
    openaq_max_pages: int = 20
    openaq_stale_after_hours: int = 6
    tle_cache_ttl_seconds: int = 7200
    ndbc_stale_after_minutes: int = 240
    satellite_poll_seconds: int = 300
    satellite_stale_after_minutes: int = 45
    satellite_initial_frames: int = 6
    metar_poll_seconds: int = 300
    metar_stale_after_minutes: int = 120
    realtime_poll_seconds: int = 180
    firms_map_key: str = ""
    keep_gfs_cycles: int = 2
    derived_cache_budget_gib: int = 12
    min_free_disk_gib: int = 8
    http_timeout_seconds: int = 30
    max_download_bytes: int = 268435456

    # Resolved at runtime, not from env.
    data_root: Path = field(default_factory=Path, repr=False)

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        toml_path = REPO_ROOT / "config" / "defaults.toml"
        toml: dict[str, Any] = {}
        if toml_path.exists():
            with toml_path.open("rb") as fh:
                toml = tomllib.load(fh)

        dotenv = _load_dotenv(env_file or (REPO_ROOT / ".env"))
        # Merge into os.environ view without mutating the real environment.
        def get(name: str) -> str | None:
            return os.environ.get(name, dotenv.get(name))

        def g(name: str, default: Any, cast: type) -> Any:
            val = get(name)
            if val is None or val == "":
                return default
            if cast is bool:
                return val.strip().lower() in {"1", "true", "yes", "on"}
            return cast(val)

        srv = toml.get("server", {})
        ing = toml.get("ingest", {})
        sto = toml.get("storage", {})

        s = cls(
            data_mode=str(g("EARTHSIM_DATA_MODE", "fixture", str)),
            http_port=int(g("EARTHSIM_HTTP_PORT", srv.get("port", 8080), int)),
            server_host=str(g("EARTHSIM_HOST", srv.get("host", "127.0.0.1"), str)),
            ui_timezone=str(g("EARTHSIM_UI_TIMEZONE", "local", str)),
            storage_root=str(g("EARTHSIM_STORAGE_ROOT", sto.get("root", "/data"), str)),
            local_data_dir=str(g("EARTHSIM_LOCAL_DATA_DIR", ".local-data", str)),
            gfs_poll_seconds=int(g("EARTHSIM_GFS_POLL_SECONDS", ing.get("gfs_poll_seconds", 900), int)),
            gfs_lead_max_hours=int(g("EARTHSIM_GFS_MAX_LEAD_HOURS", ing.get("gfs_lead_max_hours", 36), int)),
            volume_lead_max_hours=int(g("EARTHSIM_VOLUME_MAX_LEAD_HOURS", ing.get("volume_lead_max_hours", 3), int)),
            wave_lead_max_hours=int(g("EARTHSIM_WAVE_MAX_LEAD_HOURS", ing.get("wave_lead_max_hours", 3), int)),
            gefs_lead_max_hours=int(g("EARTHSIM_GEFS_MAX_LEAD_HOURS", ing.get("gefs_lead_max_hours", 6), int)),
            gfs_stale_after_hours=int(g("EARTHSIM_GFS_STALE_AFTER_HOURS", ing.get("gfs_stale_after_hours", 13), int)),
            oisst_stale_after_hours=int(g("EARTHSIM_OISST_STALE_AFTER_HOURS", ing.get("oisst_stale_after_hours", 480), int)),
            cams_stale_after_hours=int(g("EARTHSIM_CAMS_STALE_AFTER_HOURS", ing.get("cams_stale_after_hours", 24), int)),
            firms_min_frp_mw=float(g("EARTHSIM_FIRMS_MIN_FRP_MW", ing.get("firms_min_frp_mw", 10.0), float)),
            lightning_window_minutes=int(g("EARTHSIM_LIGHTNING_WINDOW_MINUTES", ing.get("lightning_window_minutes", 20), int)),
            lightning_max_strikes=int(g("EARTHSIM_LIGHTNING_MAX_STRIKES", ing.get("lightning_max_strikes", 5000), int)),
            lightning_poll_seconds=int(g("EARTHSIM_LIGHTNING_POLL_SECONDS", ing.get("lightning_poll_seconds", 30), int)),
            lightning_timeout_seconds=float(g("EARTHSIM_LIGHTNING_TIMEOUT_SECONDS", ing.get("lightning_timeout_seconds", 8.0), float)),
            openaq_api_key=str(g("EARTHSIM_OPENAQ_API_KEY", ing.get("openaq_api_key", ""), str)),
            openaq_page_size=int(g("EARTHSIM_OPENAQ_PAGE_SIZE", ing.get("openaq_page_size", 100), int)),
            openaq_max_pages=int(g("EARTHSIM_OPENAQ_MAX_PAGES", ing.get("openaq_max_pages", 20), int)),
            openaq_stale_after_hours=int(g("EARTHSIM_OPENAQ_STALE_AFTER_HOURS", ing.get("openaq_stale_after_hours", 6), int)),
            tle_cache_ttl_seconds=int(g("EARTHSIM_TLE_CACHE_TTL_SECONDS", ing.get("tle_cache_ttl_seconds", 7200), int)),
            ndbc_stale_after_minutes=int(g("EARTHSIM_NDBC_STALE_AFTER_MINUTES", ing.get("ndbc_stale_after_minutes", 240), int)),
            satellite_poll_seconds=int(g("EARTHSIM_SATELLITE_POLL_SECONDS", ing.get("satellite_poll_seconds", 300), int)),
            satellite_stale_after_minutes=int(g("EARTHSIM_SATELLITE_STALE_AFTER_MINUTES", ing.get("satellite_stale_after_minutes", 45), int)),
            satellite_initial_frames=int(g("EARTHSIM_SATELLITE_INITIAL_FRAMES", ing.get("satellite_initial_frames", 6), int)),
            metar_poll_seconds=int(g("EARTHSIM_METAR_POLL_SECONDS", ing.get("metar_poll_seconds", 300), int)),
            realtime_poll_seconds=int(g("EARTHSIM_REALTIME_POLL_SECONDS", ing.get("realtime_poll_seconds", 180), int)),
            firms_map_key=str(g("EARTHSIM_FIRMS_MAP_KEY", ing.get("firms_map_key", ""), str)),
            metar_stale_after_minutes=int(g("EARTHSIM_METAR_STALE_AFTER_MINUTES", ing.get("metar_stale_after_minutes", 120), int)),
            keep_gfs_cycles=int(g("EARTHSIM_KEEP_GFS_CYCLES", ing.get("keep_gfs_cycles", 2), int)),
            derived_cache_budget_gib=int(g("EARTHSIM_DERIVED_CACHE_GIB", ing.get("derived_cache_budget_gib", 12), int)),
            min_free_disk_gib=int(g("EARTHSIM_MIN_FREE_DISK_GIB", ing.get("min_free_disk_gib", 8), int)),
            http_timeout_seconds=int(g("EARTHSIM_HTTP_TIMEOUT", ing.get("http_timeout_seconds", 30), int)),
            max_download_bytes=int(g("EARTHSIM_MAX_DOWNLOAD_BYTES", ing.get("max_download_bytes", 268435456), int)),
        )
        s.data_mode = s.data_mode.strip().lower()
        return s

    def resolve_data_root(self) -> Path:
        """Pick a usable storage root and create the standard sub-directories."""
        candidate = Path(self.storage_root)
        in_container = os.name == "posix" and Path("/data").exists()
        # On Windows a POSIX-looking path like '/data' is drive-relative; force
        # the repository-local data directory unless an explicit drive is given.
        posix_like = self.storage_root.startswith("/") or str(candidate).startswith("\\")
        if not in_container and posix_like:
            candidate = REPO_ROOT / self.local_data_dir
        candidate = candidate.expanduser().resolve()
        candidate.mkdir(parents=True, exist_ok=True)
        for sub in ("catalog", "raw", "derived", "fixtures", "tmp"):
            (candidate / sub).mkdir(parents=True, exist_ok=True)
        self.data_root = candidate
        return candidate

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_root"] = str(self.data_root)
        return d


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.load()
        _settings.resolve_data_root()
    return _settings


def set_settings(s: Settings) -> None:
    global _settings
    _settings = s
