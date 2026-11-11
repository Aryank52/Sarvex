"""Raster IO and geospatial alignment for SAR analysis.

Design constraints:
* windowed reads clipped to the AOI (never global rasters into RAM),
* explicit CRS/transform propagation,
* NaN for invalid pixels (no silent zero-filling),
* alignment of multi-temporal stacks onto one reference grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import transform_geom


class RasterReadError(ValueError):
    pass


@dataclass
class RasterData:
    data: np.ndarray  # (bands, rows, cols), float32, NaN = invalid
    transform: Affine
    crs: CRS
    descriptions: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    nodata: float | None = None
    path: Path | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return int(self.data.shape[1]), int(self.data.shape[2])

    @property
    def bands(self) -> int:
        return int(self.data.shape[0])

    def band(self, index: int = 0) -> np.ndarray:
        return self.data[index]

    def band_index_by_keyword(self, *keywords: str) -> int | None:
        for idx, desc in enumerate(self.descriptions):
            low = (desc or "").lower()
            if any(k in low for k in keywords):
                return idx
        return None

    def mask_for_geometry(self, geometry: dict[str, Any]) -> np.ndarray:
        geom = geometry
        if self.crs and self.crs.to_string() != "EPSG:4326":
            geom = transform_geom("EPSG:4326", self.crs, geometry)
        return geometry_mask([geom], out_shape=(self.shape[1], self.shape[0]), transform=self.transform, invert=True)

    def bbox_wgs84(self) -> list[float]:
        from rasterio.warp import transform_bounds

        left, bottom, right, top = (
            self.transform.c,
            self.transform.f,
            self.transform.c + self.transform.a * self.shape[0],
            self.transform.f + self.transform.e * self.shape[1],
        )
        if self.crs and self.crs.to_string() != "EPSG:4326":
            bounds = transform_bounds(self.crs, "EPSG:4326", left, bottom, right, top, densify_pts=21)
        else:
            bounds = (left, bottom, right, top)
        return [float(min(bounds[0], bounds[2])), float(min(bounds[1], bounds[3])),
                float(max(bounds[0], bounds[2])), float(max(bounds[1], bounds[3]))]

    def pixel_area_m2(self) -> float:
        """Approximate ground pixel area derived from the WGS84 bounds."""
        from pyproj import Geod

        bbox = self.bbox_wgs84()
        geod = Geod(ellps="WGS84")
        lon_span = bbox[2] - bbox[0]
        lat_span = bbox[3] - bbox[1]
        # Geodesic polygon area; the sign depends on ring orientation.
        area, _ = geod.polygon_area_perimeter(
            [bbox[0], bbox[2], bbox[2], bbox[0], bbox[0]],
            [bbox[1], bbox[1], bbox[3], bbox[3], bbox[1]],
        )
        return abs(float(area)) / max(self.shape[0] * self.shape[1], 1)


def _margin_window(bounds: tuple[float, float, float, float], transform: Affine, shape: tuple[int, int], margin: int = 2):
    from rasterio.windows import Window, from_bounds

    window = from_bounds(*bounds, transform=transform)
    col_off = max(int(math.floor(window.col_off)) - margin, 0)
    row_off = max(int(math.floor(window.row_off)) - margin, 0)
    width = int(math.ceil(window.width)) + 2 * margin
    height = int(math.ceil(window.height)) + 2 * margin
    width = min(width, shape[1] - col_off)
    height = min(height, shape[0] - row_off)
    if width <= 0 or height <= 0:
        raise RasterReadError("AOI does not overlap the raster")
    return Window(col_off, row_off, width, height)


def read_raster(
    path: Path,
    *,
    geometry: dict[str, Any] | None = None,
    band_index: int | None = None,
    max_pixels: int = 40_000_000,
) -> RasterData:
    """Read a raster (optionally clipped to an AOI) without loading the globe."""
    import rasterio

    try:
        with rasterio.open(path) as ds:
            if ds.crs is None:
                raise RasterReadError("Raster has no declared CRS; geospatial analysis cannot proceed")
            window = None
            if geometry is not None:
                geom_r = geometry
                if ds.crs.to_string() != "EPSG:4326":
                    geom_r = transform_geom("EPSG:4326", ds.crs, geometry)
                from rasterio.features import bounds as feature_bounds

                bounds = feature_bounds(geom_r)
                window = _margin_window(bounds, ds.transform, (ds.height, ds.width))
            if window is not None:
                width, height = int(window.width), int(window.height)
                transform = ds.window_transform(window)
            else:
                width, height = ds.width, ds.height
                transform = ds.transform
            if width * height > max_pixels:
                raise RasterReadError(
                    f"Raster window is too large ({width}x{height}); supply a smaller AOI or COG overviews"
                )
            indexes = [band_index + 1] if band_index is not None else list(range(1, ds.count + 1))
            arr = ds.read(indexes, window=window, masked=False).astype("float32")
            nodata = ds.nodata
            if nodata is not None:
                arr = np.where(arr == nodata, np.nan, arr)
            # Masked read catches alpha/internal masks even without nodata tags.
            try:
                masked = ds.read(indexes, window=window, masked=True)
                if np.ma.isMaskedArray(masked):
                    mask = np.ma.getmaskarray(masked)
                    if mask.any():
                        arr = np.where(mask, np.nan, arr)
            except Exception:  # noqa: BLE001
                pass
            descriptions = [
                (ds.descriptions[i - 1] or "") for i in indexes
            ]
            tags = {str(k): str(v) for k, v in ds.tags().items()}
            if ds.count > 1 and band_index is None:
                arr = arr.reshape(len(indexes), height, width)
            elif arr.ndim == 2:
                arr = arr[np.newaxis, :, :]
            return RasterData(
                data=arr.astype("float32"),
                transform=transform,
                crs=ds.crs,
                descriptions=descriptions,
                tags=tags,
                nodata=nodata,
                path=path,
            )
    except RasterReadError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RasterReadError(f"Failed to read raster {path.name}: {exc}") from exc


def align_to(reference: RasterData, source: RasterData, resampling: Resampling = Resampling.bilinear) -> RasterData:
    """Reproject/resample source onto the reference grid (NaN preserved)."""
    if (
        reference.shape == source.shape
        and reference.crs == source.crs
        and reference.transform.almost_equals(source.transform)
    ):
        return source
    import rasterio
    from rasterio.warp import reproject

    out = np.full((source.bands, reference.shape[1], reference.shape[0]), np.nan, dtype="float32")
    for b in range(source.bands):
        reproject(
            source=source.band(b),
            destination=out[b],
            src_transform=source.transform,
            src_crs=source.crs,
            dst_transform=reference.transform,
            dst_crs=reference.crs,
            src_nodata=np.nan,
            dst_nodata=np.nan,
            resampling=resampling,
        )
    return RasterData(
        data=out,
        transform=reference.transform,
        crs=reference.crs,
        descriptions=source.descriptions,
        tags=source.tags,
        nodata=np.nan,
        path=source.path,
    )


def write_geotiff(
    path: Path,
    array: np.ndarray,
    *,
    transform: Affine,
    crs: CRS,
    descriptions: list[str] | None = None,
    tags: dict[str, str] | None = None,
    nodata: float = float("nan"),
) -> Path:
    import rasterio

    arr = np.asarray(array, dtype="float32")
    if arr.ndim == 2:
        arr = arr[np.newaxis, :, :]
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=arr.shape[2],
        height=arr.shape[1],
        count=arr.shape[0],
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="deflate",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as ds:
        for i in range(arr.shape[0]):
            ds.write(arr[i], i + 1)
            if descriptions and i < len(descriptions):
                ds.set_band_description(i + 1, descriptions[i])
        ds.update_tags(**(tags or {}))
    return path
