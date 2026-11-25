"""Background ingest worker.

Polls each enabled source on its configured interval; each collector merges
in-flight refreshes and keeps the last published batch on failure.
"""
from __future__ import annotations

import logging
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .config import get_settings
from .catalog import repository as repo
from .ingest import cables, disasters, gefs, gfs, metar, ifs, ndbc, oisst, openaq, realtime, satellites, volume, wave

log = logging.getLogger("earthsim.worker")
_stop = False
# Shared pool so slow collectors never block the scheduling loop. Each job is
# submitted fire-and-forget; a single source never runs twice concurrently.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ingest")
_inflight: set[str] = set()


def _handle_stop(signum, frame):  # pragma: no cover
    global _stop
    _stop = True


def run_once(settings) -> None:
    for source, interval, fn in (
        ("noaa_gfs", settings.gfs_poll_seconds, gfs.refresh),
        ("awc_metar", settings.metar_poll_seconds, metar.refresh),
        ("ecmwf_ifs", settings.gfs_poll_seconds, ifs.refresh),
        ("gfs_volume", settings.gfs_poll_seconds, volume.refresh),
        ("noaa_wave", settings.gfs_poll_seconds, wave.refresh),
        ("noaa_oisst", settings.gfs_poll_seconds, oisst.refresh),
        ("noaa_gefs", settings.gfs_poll_seconds, gefs.refresh),
        ("noaa_ndbc", settings.realtime_poll_seconds, ndbc.refresh),
        ("openaq", settings.gfs_poll_seconds, openaq.refresh),
        ("celestrak", settings.gfs_poll_seconds, satellites.refresh),
        ("telegeography", settings.gfs_poll_seconds, cables.refresh),
        ("usgs_quake", settings.realtime_poll_seconds, realtime.refresh_quakes),
        ("opensky", settings.realtime_poll_seconds, realtime.refresh_flights),
        ("nhc_storm", settings.realtime_poll_seconds, realtime.refresh_storms),
        ("nasa_cme", settings.realtime_poll_seconds, realtime.refresh_cme),
        ("noaa_aurora", settings.realtime_poll_seconds, realtime.refresh_aurora),
        ("noaa_solar_wind", settings.realtime_poll_seconds, realtime.refresh_solar_wind),
        ("gdacs", settings.realtime_poll_seconds, disasters.refresh_gdacs),
        ("eonet", settings.realtime_poll_seconds, disasters.refresh_eonet),
        ("nasa_firms", settings.realtime_poll_seconds, disasters.refresh_firms),
    ):
        try:
            result = fn()
            log.info("%s: %s", source, result)
        except Exception as e:  # noqa: BLE001
            log.warning("%s 采集异常：%s", source, e)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    settings = get_settings()
    repo.ensure_migrated()
    log.info("worker 启动")
    intervals = [settings.gfs_poll_seconds, settings.satellite_poll_seconds, settings.metar_poll_seconds]
    next_run = [0.0, 0.0, 0.0]
    while not _stop:
        now = time.time()
        jobs = (
            ("noaa_gfs", gfs.refresh),
            ("awc_metar", metar.refresh),
            ("ecmwf_ifs", ifs.refresh),
            ("gfs_volume", volume.refresh),
            ("noaa_wave", wave.refresh),
            ("noaa_oisst", oisst.refresh),
            ("noaa_gefs", gefs.refresh),
            ("noaa_ndbc", ndbc.refresh),
            ("openaq", openaq.refresh),
            ("celestrak", satellites.refresh),
            ("telegeography", cables.refresh),
            ("usgs_quake", realtime.refresh_quakes),
            ("opensky", realtime.refresh_flights),
            ("nhc_storm", realtime.refresh_storms),
            ("nasa_cme", realtime.refresh_cme),
            ("noaa_aurora", realtime.refresh_aurora),
            ("noaa_solar_wind", realtime.refresh_solar_wind),
            ("gdacs", disasters.refresh_gdacs),
            ("eonet", disasters.refresh_eonet),
            ("nasa_firms", disasters.refresh_firms),
        )
        intervals = [settings.gfs_poll_seconds, settings.metar_poll_seconds,
                     settings.gfs_poll_seconds, settings.gfs_poll_seconds,
                     settings.gfs_poll_seconds, settings.gfs_poll_seconds,
                     settings.gfs_poll_seconds,
                     settings.realtime_poll_seconds,  # noaa_ndbc
                     settings.gfs_poll_seconds,       # openaq
                     settings.gfs_poll_seconds,       # celestrak
                     settings.gfs_poll_seconds,       # telegeography
                     ] + [settings.realtime_poll_seconds] * 9
        if len(intervals) != len(jobs):
            raise RuntimeError(f"worker intervals/jobs 不匹配：{len(intervals)} vs {len(jobs)}")
        next_run = next_run + [0.0] * (len(jobs) - len(next_run))
        # Run due sources concurrently and fire-and-forget: a slow collector
        # (e.g. IFS's 95 MB download) must not block the loop or starve fast
        # feeds like aurora/METAR. next_run is
        # advanced immediately on submission, never on completion.
        due = [(i, name, fn) for i, (name, fn) in enumerate(jobs) if now >= next_run[i]]

        def run_job(name, fn):
            try:
                log.info("采集 %s", name)
                fn()
            except Exception as e:  # noqa: BLE001
                log.warning("%s 失败：%s", name, e)
            finally:
                _inflight.discard(name)

        if due:
            for i, name, fn in due:
                if name not in _inflight:  # don't double-run an in-progress source
                    _inflight.add(name)
                    _POOL.submit(run_job, name, fn)
                next_run[i] = now + intervals[i]  # retry no sooner than the interval
        time.sleep(5)
    log.info("worker 已停止")


if __name__ == "__main__":
    main()
