"""Regular lat/lon grid specification, binary encoding and point sampling.

Contract (mirrors the implementation guide, section 5.2):
  * EPSG:4326, lon west->east ascending, lat south->north ascending.
  * index((i,j),k) = (j * nx + i) * ncomponents + k
  * binary = float32 little-endian, NaN = missing.
  * sample_point cell reference: (lon0 + i*dx, lat0 + j*dy).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import numpy as np

from .timeutil import normalize_lat, normalize_lon

MISSING = float("nan")


@dataclass(frozen=True)
class GridSpec:
    crs: str
    nx: int
    ny: int
    lon0: float
    lat0: float
    dx: float
    dy: float
    wrap_longitude: bool = True
    cell_reference: str = "sample_point"

    def __post_init__(self) -> None:
        if self.nx < 2 or self.ny < 2:
            raise ValueError("grid must have at least 2x2 cells")
        if self.dx <= 0 or self.dy <= 0:
            raise ValueError("grid spacing must be positive")

    @classmethod
    def from_dict(cls, d: dict) -> "GridSpec":
        return cls(
            crs=d.get("crs", "EPSG:4326"),
            nx=int(d["nx"]), ny=int(d["ny"]),
            lon0=float(d["lon0"]), lat0=float(d["lat0"]),
            dx=float(d["dx"]), dy=float(d["dy"]),
            wrap_longitude=bool(d.get("wrap_longitude", True)),
            cell_reference=d.get("cell_reference", "sample_point"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def nbytes(self, ncomponents: int, dtype=np.float32) -> int:
        return self.nx * self.ny * ncomponents * np.dtype(dtype).itemsize

    def lons(self) -> np.ndarray:
        return self.lon0 + np.arange(self.nx, dtype=np.float64) * self.dx

    def lats(self) -> np.ndarray:
        return self.lat0 + np.arange(self.ny, dtype=np.float64) * self.dy

    def index(self, i: int, j: int) -> int:
        return j * self.nx + i

    def contains(self, lon: float, lat: float) -> bool:
        lon = normalize_lon(lon)
        lat = normalize_lat(lat)
        lon_ok = (self.lon0 <= lon <= self.lon0 + (self.nx - 1) * self.dx)
        if not lon_ok and self.wrap_longitude:
            lon_ok = True  # global grid wraps
        lat_ok = self.lat0 <= lat <= self.lat0 + (self.ny - 1) * self.dy
        return bool(lon_ok and lat_ok)


def read_grid_binary(path: Path | str, grid: GridSpec, ncomponents: int) -> np.ndarray:
    """Read and validate a grid asset. Returns shape (ny, nx, ncomponents)."""
    path = Path(path)
    expected = grid.nbytes(ncomponents, np.float32)
    raw = path.read_bytes()
    if len(raw) != expected:
        raise ValueError(f"grid asset {path.name}: expected {expected} bytes, got {len(raw)}")
    arr = np.frombuffer(raw, dtype="<f4").astype(np.float32)
    return arr.reshape((grid.ny, grid.nx, ncomponents))


def write_grid_binary(path: Path | str, arr: np.ndarray) -> None:
    """Write shape (ny,nx[,ncomp]) as validated little-endian float32."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    a = np.asarray(arr, dtype="<f4")
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3:
        raise ValueError("grid array must be 2D or 3D")
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(a.tobytes(order="C"))
    tmp.replace(path)


def _wrap_index(i: float, nx: int, wrap: bool) -> tuple[int, int] | None:
    i0 = int(math.floor(i))
    i1 = i0 + 1
    if wrap:
        return i0 % nx, i1 % nx
    if i0 < 0 or i1 >= nx:
        return None
    return i0, i1


def bilinear_sample(
    grid: GridSpec,
    values: np.ndarray,
    lon: float,
    lat: float,
    nearest_fallback: bool = True,
) -> tuple[list[float | None], str]:
    """Sample all components at (lon,lat) with bilinear interpolation.

    Returns (values, method) where method is one of
    ``bilinear`` / ``nearest`` / ``missing`` / ``out_of_bounds``.
    Missing neighbours are excluded; if fewer than 4 valid corners remain the
    fallback is ``nearest`` (when configured) or ``missing``.
    """
    lon = normalize_lon(lon)
    lat = normalize_lat(lat)
    if values.ndim == 2:
        values = values[:, :, None]
    ny, nx, ncomp = values.shape
    if (nx, ny) != (grid.nx, grid.ny):
        raise ValueError("values shape does not match grid spec")

    fi = (lon - grid.lon0) / grid.dx
    fj = (lat - grid.lat0) / grid.dy
    # Clamp latitude; wrap longitude for global grids.
    fj = max(0.0, min(float(ny - 1), fj))
    wrap = grid.wrap_longitude
    if wrap:
        fi = fi % nx
    else:
        if fi < 0 or fi > nx - 1:
            return ([None] * ncomp, "out_of_bounds")
    if not (0 <= fj <= ny - 1):
        return ([None] * ncomp, "out_of_bounds")

    cols = _wrap_index(fi, nx, wrap)
    if cols is None:
        return ([None] * ncomp, "out_of_bounds")
    i0, i1 = cols
    j0 = int(math.floor(fj))
    j1 = min(j0 + 1, ny - 1)
    tx = fi - math.floor(fi)
    ty = fj - j0
    if wrap and i1 < i0:  # should not happen with modulo, guarded anyway
        i1 = i0

    corners = [(j0, i0), (j0, i1), (j1, i0), (j1, i1)]
    weights = [(1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty]

    result: list[float | None] = []
    method = "bilinear"
    for k in range(ncomp):
        num = 0.0
        den = 0.0
        for (j, i), w in zip(corners, weights):
            v = float(values[j, i, k])
            if math.isnan(v):
                continue
            num += w * v
            den += w
        if den > 0:
            result.append(num / den)
            continue
        if nearest_fallback:
            jn, inn = min(corners, key=lambda ji: (abs(ji[0] - fj) + abs(_angular_i(ji[1], fi, nx, wrap)), 0))
            v = float(values[jn, inn, k])
            result.append(None if math.isnan(v) else v)
            method = "nearest" if method != "bilinear" or k == 0 else method
        else:
            result.append(None)
            method = "missing"
    if any(v is None for v in result) and method == "bilinear":
        method = "missing"
    return result, method


def _angular_i(i: int, fi: float, nx: int, wrap: bool) -> float:
    d = abs(i - fi)
    if wrap:
        d = min(d, nx - d)
    return d


def sample_many(
    grid: GridSpec, values: np.ndarray, points: Iterable[tuple[float, float]]
) -> list[tuple[list[float | None], str]]:
    return [bilinear_sample(grid, values, lon, lat) for lon, lat in points]


def describe_grid(grid: GridSpec) -> dict:
    """Return a JSON-serializable grid manifest with corner coordinates."""
    d = grid.to_dict()
    d["corners_lonlat"] = [
        [grid.lon0, grid.lat0],
        [grid.lon0 + (grid.nx - 1) * grid.dx, grid.lat0],
        [grid.lon0 + (grid.nx - 1) * grid.dx, grid.lat0 + (grid.ny - 1) * grid.dy],
        [grid.lon0, grid.lat0 + (grid.ny - 1) * grid.dy],
    ]
    return d
