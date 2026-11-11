"""Processing artifacts: COG-ready GeoTIFFs, map PNGs, legends and metadata.

Every map layer carries title, units, date range, source, product, method and
confidence so the frontend can render scientific transparency requirements
without guessing.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app.processing.raster import RasterData, write_geotiff
from app.storage.object_store import ObjectStore

COLOR_RAMPS: dict[str, list[tuple[float, str]]] = {
    "backscatter": [(0.0, "#08131f"), (0.35, "#0e4f6b"), (0.7, "#39a7a0"), (1.0, "#d8f5e3")],
    "difference": [(0.0, "#2b6cff"), (0.5, "#f4f1ec"), (1.0, "#ff5a36")],
    "displacement": [(0.0, "#7b2ff7"), (0.5, "#161022"), (0.5001, "#161022"), (1.0, "#ffb000")],
    "coherence": [(0.0, "#07131f"), (0.5, "#0f7f8a"), (1.0, "#d7fff9")],
    "confidence": [(0.0, "#08251c"), (0.5, "#1e9e6a"), (1.0, "#d4ff5e")],
    "uncertainty": [(0.0, "#120b22"), (0.5, "#8f3fb3"), (1.0, "#ffd3e0")],
    "ratio": [(0.0, "#4a2b12"), (0.5, "#c7a86a"), (1.0, "#2f8f5b")],
    "mask": [(0.0, "#ffb000"), (1.0, "#ffd166")],
}

LEGEND_TITLES = {
    "backscatter": "Backscatter",
    "difference": "Change",
    "displacement": "Line-of-sight displacement",
    "coherence": "Interferometric coherence",
    "confidence": "Detection confidence",
    "uncertainty": "Uncertainty",
    "ratio": "Polarimetric ratio",
    "mask": "Changed / detected",
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def colorize(array: np.ndarray, ramp: str, vmin: float, vmax: float, valid: np.ndarray) -> np.ndarray:
    stops = COLOR_RAMPS.get(ramp, COLOR_RAMPS["difference"])
    colors = [_hex_to_rgb(c) for _, c in stops]
    positions = [p for p, _ in stops]
    norm = np.clip((array - vmin) / max(vmax - vmin, 1e-12), 0, 1)
    out = np.zeros((*array.shape, 4), dtype=np.uint8)
    for channel in range(3):
        out[..., channel] = np.interp(norm, positions, [c[channel] for c in colors]).astype(np.uint8)
    out[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return out


def render_png(array: np.ndarray, ramp: str, vmin: float, vmax: float, valid: np.ndarray, max_size: int = 1024) -> bytes:
    from io import BytesIO

    from PIL import Image

    rgba = colorize(np.asarray(array, dtype="float32"), ramp, vmin, vmax, valid)
    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > max_size:
        scale = max_size / max(image.size)
        image = image.resize(
            (max(int(image.width * scale), 1), max(int(image.height * scale), 1)),
            resample=Image.Resampling.BILINEAR,
        )
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _range(array: np.ndarray, valid: np.ndarray, symmetric: bool) -> tuple[float, float]:
    vals = array[valid]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return (0.0, 1.0)
    if symmetric:
        p2, p98 = np.percentile(vals, [2, 98])
        limit = float(max(abs(p2), abs(p98), 1e-6))
        return (-limit, limit)
    p2, p98 = np.percentile(vals, [2, 98])
    if not np.isfinite(p2) or not np.isfinite(p98) or abs(p98 - p2) < 1e-9:
        p2, p98 = float(np.min(vals)), float(np.max(vals) + 1e-6)
    return (float(p2), float(p98))


def save_layer(
    store: ObjectStore,
    *,
    result_id: str,
    name: str,
    array: np.ndarray,
    grid: RasterData,
    title: str,
    units: str,
    method: str,
    source: str,
    ramp: str = "difference",
    symmetric: bool = False,
    mask: np.ndarray | None = None,
    product_ids: list[str] | None = None,
    dates: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    arr = np.asarray(array, dtype="float32")
    valid = np.isfinite(arr) if mask is None else (np.isfinite(arr) & mask)
    vmin, vmax = _range(arr, valid, symmetric)
    tmpdir = Path(tempfile.mkdtemp(prefix="sarvex-layer-"))
    tif_path = tmpdir / f"{name}.tif"
    write_geotiff(
        tif_path,
        arr,
        transform=grid.transform,
        crs=grid.crs,
        descriptions=[title],
        tags={
            "SARVEX_LAYER": name,
            "SARVEX_UNITS": units,
            "SARVEX_METHOD": method,
            "SARVEX_RESULT_ID": result_id,
            "SARVEX_SOURCE": source,
        },
    )
    tif_uri = store.put_file(f"results/{result_id}/layers/{name}.tif", tif_path, "image/tiff")
    png_bytes = render_png(arr, ramp, vmin, vmax, valid)
    png_uri = store.put_bytes(f"results/{result_id}/layers/{name}.png", png_bytes, "image/png")
    bbox = grid.bbox_wgs84()
    stops = COLOR_RAMPS.get(ramp, COLOR_RAMPS["difference"])
    legend = [
        {"value": round(vmin + (vmax - vmin) * p, 4), "color": color, "label": _fmt(vmin + (vmax - vmin) * p)}
        for p, color in stops
    ]
    metadata = {
        "layer": name,
        "title": title,
        "units": units,
        "method": method,
        "source": source,
        "product_ids": product_ids or [],
        "dates": dates or [],
        "ramp": ramp,
        "vmin": vmin,
        "vmax": vmax,
        "bbox": bbox,
        "crs": grid.crs.to_string() if grid.crs else None,
        "width": grid.shape[0],
        "height": grid.shape[1],
        "raster_uri": tif_uri,
        "png_uri": png_uri,
        "image_coordinates": [
            [bbox[0], bbox[3]],
            [bbox[2], bbox[3]],
            [bbox[2], bbox[1]],
            [bbox[0], bbox[1]],
        ],
        "legend": legend,
        "legend_title": LEGEND_TITLES.get(ramp, title),
        "valid_fraction": float(np.count_nonzero(valid) / valid.size) if valid.size else 0.0,
        "extra": extra or {},
    }
    return metadata


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def save_categorical_layer(
    store: ObjectStore,
    *,
    result_id: str,
    name: str,
    mask: np.ndarray,
    grid: RasterData,
    title: str,
    method: str,
    source: str,
    label: str = "changed",
    color: str = "#ffb000",
) -> dict[str, Any]:
    arr = mask.astype("float32")
    tmpdir = Path(tempfile.mkdtemp(prefix="sarvex-layer-"))
    tif_path = tmpdir / f"{name}.tif"
    write_geotiff(
        tif_path,
        arr,
        transform=grid.transform,
        crs=grid.crs,
        descriptions=[title],
        tags={"SARVEX_LAYER": name, "SARVEX_UNITS": "boolean", "SARVEX_METHOD": method},
    )
    tif_uri = store.put_file(f"results/{result_id}/layers/{name}.tif", tif_path, "image/tiff")
    rgba = np.zeros((*arr.shape, 4), dtype=np.uint8)
    rgb = _hex_to_rgb(color)
    rgba[mask, 0], rgba[mask, 1], rgba[mask, 2], rgba[mask, 3] = rgb[0], rgb[1], rgb[2], 210
    from io import BytesIO

    from PIL import Image

    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > 1024:
        scale = 1024 / max(image.size)
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.BILINEAR)
    buf = BytesIO()
    image.save(buf, format="PNG")
    png_uri = store.put_bytes(f"results/{result_id}/layers/{name}.png", buf.getvalue(), "image/png")
    bbox = grid.bbox_wgs84()
    return {
        "layer": name,
        "title": title,
        "units": "boolean",
        "method": method,
        "source": source,
        "bbox": bbox,
        "crs": grid.crs.to_string() if grid.crs else None,
        "raster_uri": tif_uri,
        "png_uri": png_uri,
        "image_coordinates": [[bbox[0], bbox[3]], [bbox[2], bbox[3]], [bbox[2], bbox[1]], [bbox[0], bbox[1]]],
        "legend": [{"value": 1, "color": color, "label": label}],
        "legend_title": title,
        "kind": "categorical",
    }
