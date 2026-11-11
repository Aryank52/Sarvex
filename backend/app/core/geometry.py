"""Geometry, checksum, and path-safety helpers."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pyproj import Geod
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

_GEOD = Geod(ellps="WGS84")


class GeometryValidationError(ValueError):
    pass


def validate_geojson_geometry(geometry: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a WGS84 GeoJSON geometry and return a normalized mapping."""
    if not isinstance(geometry, dict) or not geometry.get("type"):
        raise GeometryValidationError("A GeoJSON geometry object is required")
    try:
        geom = shape(geometry)
    except Exception as exc:  # noqa: BLE001
        raise GeometryValidationError(f"Invalid GeoJSON: {exc}") from exc
    if geom.is_empty or not geom.is_valid:
        raise GeometryValidationError("Geometry is empty or invalid")
    if geometry.get("type") == "GeometryCollection":
        raise GeometryValidationError("GeometryCollection is not supported for AOIs")
    minx, miny, maxx, maxy = geom.bounds
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise GeometryValidationError("Coordinates must be longitude/latitude in EPSG:4326")
    if minx == maxx or miny == maxy:
        raise GeometryValidationError("Geometry must have non-zero extent")
    return json.loads(json.dumps(geometry))


def geometry_area_m2(geometry: dict[str, Any]) -> float:
    """Geodesic area on the WGS84 ellipsoid."""
    geom = shape(geometry)
    area, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(float(area))


def geometry_bbox(geometry: dict[str, Any]) -> list[float]:
    return [float(v) for v in shape(geometry).bounds]


def geometry_centroid_lonlat(geometry: dict[str, Any]) -> tuple[float, float]:
    c = shape(geometry).centroid
    return float(c.x), float(c.y)


def geojson_intersects(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return bool(shape(a).intersects(shape(b)))


def geojson_distance_m(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Minimum geodesic-aware distance approximated via local azimuthal projection.

    For the exposure engine we need a defensible distance; using the geodesic
    calculator on nearest points after a Lambert Azimuthal Equal Area
    projection centred on the event keeps metre units without treating degrees
    as distances.
    """
    from pyproj import Transformer

    ga, gb = shape(a), shape(b)
    if ga.intersects(gb):
        return 0.0
    lon, lat = geometry_centroid_lonlat(a)
    proj = (
        f"+proj=laea +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )
    transformer = Transformer.from_crs("EPSG:4326", proj, always_xy=True)
    inv = Transformer.from_crs(proj, "EPSG:4326", always_xy=True)

    def project(g: BaseGeometry) -> BaseGeometry:
        from shapely.ops import transform

        return transform(transformer.transform, g)

    pa, pb = project(ga), project(gb)
    nearest = pa.exterior.interpolate(pa.exterior.project(pb.centroid)) if pa.geom_type == "Polygon" else pa.centroid
    nearest_b = pb.exterior.interpolate(pb.exterior.project(nearest)) if pb.geom_type == "Polygon" else pb.centroid
    lon1, lat1 = inv.transform(nearest.x, nearest.y)
    lon2, lat2 = inv.transform(nearest_b.x, nearest_b.y)
    _, _, distance = _GEOD.inv(lon1, lat1, lon2, lat2)
    return abs(float(distance))


def overlap_ratio(event_geometry: dict[str, Any], asset_geometry: dict[str, Any]) -> float:
    event = shape(event_geometry)
    asset = shape(asset_geometry)
    if event.is_empty or asset.is_empty or not event.intersects(asset):
        return 0.0
    inter = event.intersection(asset)
    # Intersections are evaluated approximately in WGS84; ratios are scale-free.
    if asset.area <= 0:
        return 0.0
    return float(min(inter.area / asset.area, 1.0))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_join(base: Path, relative: str) -> Path:
    """Resolve a relative path while preventing traversal outside ``base``."""
    base = base.resolve()
    target = (base / relative).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Path traversal attempt detected")
    return target


def sanitize_filename(name: str) -> str:
    candidate = Path(name).name.replace("\x00", "").strip()
    allowed = "".join(c if (c.isalnum() or c in "._- ") else "_" for c in candidate)
    allowed = allowed.strip(". ")
    if not allowed:
        raise ValueError("Invalid filename")
    return allowed[:200]


def finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
