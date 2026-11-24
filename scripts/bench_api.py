"""Local API latency smoke benchmark (no browser FPS measurement)."""
import sys
import time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from earthsim.api.app import app

c = TestClient(app)
lat = []
for i in range(120):
    lon = -170 + i * 2.8
    t = time.perf_counter()
    r = c.get("/api/v1/sample", params={"frame_id": "fixture-wind10-t03", "lon": lon, "lat": 10})
    lat.append((time.perf_counter() - t) * 1000)
    assert r.status_code == 200
lat.sort()
print("samples", len(lat))
print("median_ms", round(median(lat), 2))
print("p95_ms", round(lat[int(0.95 * len(lat)) - 1], 2))
