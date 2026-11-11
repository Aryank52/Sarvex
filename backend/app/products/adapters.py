"""Raster, HDF5, and NISAR product adapters.

Metadata extraction is deliberately conservative. Values are only populated
from file tags, CRS transforms, filenames, or explicit HDF5 attributes/datasets.
No acquisition metadata is synthesized.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.geometry import sha256_file
from app.products.base import (
    ProductAdapter,
    base_metadata,
    infer_polarizations,
    infer_product_type,
)
from app.products.metadata import NormalizedProductMetadata, ValidationReport

SPEED_OF_LIGHT_M_S = 299_792_458.0

_RASTER_SUFFIXES = {".tif", ".tiff", ".cog", ".img", ".vrt"}
_HDF5_SUFFIXES = {".h5", ".hdf5", ".he5", ".nc"}


def _parse_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        f = float(value)
        if math.isfinite(f):
            return f
    except (TypeError, ValueError):
        pass
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        f = float(value)
        if math.isfinite(f):
            return int(f)
    except (TypeError, ValueError):
        pass
    return None


def _wavelength_from_frequency(frequency_hz: float | None) -> float | None:
    if frequency_hz and frequency_hz > 0:
        return SPEED_OF_LIGHT_M_S / frequency_hz
    return None


def _looks_like_lonlat(bbox: list[float]) -> bool:
    minx, miny, maxx, maxy = bbox
    return -180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90


class RasterProductAdapter(ProductAdapter):
    """Reads GeoTIFF/COG and compatible raster products with rasterio."""

    name = "raster"

    def validate(self, path: Path) -> ValidationReport:
        report = ValidationReport(valid=True)
        if not path.exists():
            report.valid = False
            report.errors.append("File does not exist")
            return report
        if path.stat().st_size == 0:
            report.valid = False
            report.errors.append("File is empty")
            return report
        try:
            import rasterio

            with rasterio.open(path) as ds:
                report.checks.update(
                    {
                        "driver": ds.driver,
                        "width": ds.width,
                        "height": ds.height,
                        "bands": ds.count,
                        "crs": ds.crs.to_string() if ds.crs else None,
                        "dtype": ds.dtypes[0] if ds.dtypes else None,
                    }
                )
                if ds.width < 2 or ds.height < 2:
                    report.errors.append("Raster is too small (<2x2 pixels)")
                if ds.count < 1:
                    report.errors.append("Raster has no bands")
                if ds.crs is None:
                    report.warnings.append("Raster has no declared CRS; georeferencing is unavailable")
                    report.checks["has_crs"] = False
                else:
                    report.checks["has_crs"] = True
                if ds.crs and ds.bounds and (
                    not all(math.isfinite(v) for v in (*ds.bounds, *ds.transform[:6]))
                ):
                    report.errors.append("Non-finite geotransform or bounds")
                if not ds.transform.is_rectilinear:
                    report.warnings.append("Geotransform includes rotation; downstream alignment required")
        except Exception as exc:  # noqa: BLE001
            report.valid = False
            report.errors.append(f"Unreadable raster: {exc}")
        report.valid = report.valid and not report.errors
        return report

    def extract(
        self,
        path: Path,
        *,
        provider: str,
        product_id: str | None = None,
        product_type: str | None = None,
        source_url: str | None = None,
    ) -> NormalizedProductMetadata:
        import numpy as np
        import rasterio
        from rasterio.warp import transform_bounds

        meta = base_metadata(
            path,
            provider=provider,
            product_id=product_id,
            product_type=product_type,
            source_url=source_url,
            file_format=path.suffix.lstrip(".").lower(),
        )
        with rasterio.open(path) as ds:
            tags = {str(k): str(v) for k, v in ds.tags().items()}
            band_tags = [ds.tags(i + 1) for i in range(ds.count)]
            descriptions = [ds.descriptions[i] or "" for i in range(ds.count)]
            meta.extra["raster"] = {
                "driver": ds.driver,
                "width": ds.width,
                "height": ds.height,
                "bands": ds.count,
                "dtypes": list(ds.dtypes),
                "nodata": ds.nodata,
                "band_descriptions": descriptions,
                "tags": tags,
            }
            meta.crs = tags.get("SARVEX_CRS") or (ds.crs.to_string() if ds.crs else None)
            if ds.crs:
                try:
                    bounds = (
                        transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
                        if ds.crs.to_string() != "EPSG:4326"
                        else tuple(ds.bounds)
                    )
                    bbox = [float(b) for b in bounds]
                    if _looks_like_lonlat(bbox):
                        meta.bbox = bbox
                        meta.geometry = {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [bbox[0], bbox[1]],
                                    [bbox[2], bbox[1]],
                                    [bbox[2], bbox[3]],
                                    [bbox[0], bbox[3]],
                                    [bbox[0], bbox[1]],
                                ]
                            ],
                        }
                except Exception:  # noqa: BLE001
                    meta.extraction_notes.append("Could not transform raster bounds to EPSG:4326")
            if ds.crs:
                res_x, res_y = abs(ds.res[0]), abs(ds.res[1])
                if ds.crs.is_geographic:
                    lat = (meta.bbox[1] + meta.bbox[3]) / 2 if meta.bbox else 0.0
                    meta.spatial_resolution_m = float(
                        max(res_x, res_y) * 111_320.0 * max(math.cos(math.radians(lat)), 0.05)
                    )
                else:
                    meta.spatial_resolution_m = float(max(res_x, res_y))
            meta.file_format = ds.driver
            meta.product_type = infer_product_type(
                path.name, product_type or tags.get("SARVEX_PRODUCT_TYPE")
            )
            meta.frequency_band = tags.get("SARVEX_FREQUENCY_BAND") or tags.get("FREQUENCY_BAND")
            meta.frequency_hz = _float_or_none(tags.get("SARVEX_FREQUENCY_HZ"))
            meta.polarization = infer_polarizations(descriptions, tags)
            if not meta.polarization:
                for bt in band_tags:
                    pol = infer_polarizations([], {k: v for k, v in bt.items()})
                    if pol:
                        meta.polarization = pol
                        break
            meta.wavelength_m = _float_or_none(tags.get("SARVEX_WAVELENGTH_M")) or _wavelength_from_frequency(
                meta.frequency_hz
            )
            meta.units = tags.get("SARVEX_UNITS") or tags.get("UNITS")
            meta.orbit = _int_or_none(tags.get("SARVEX_ORBIT") or tags.get("ORBIT_NUMBER"))
            meta.pass_direction = tags.get("SARVEX_PASS_DIRECTION") or tags.get("PASS_DIRECTION")
            meta.track = _int_or_none(tags.get("SARVEX_TRACK"))
            meta.frame = _int_or_none(tags.get("SARVEX_FRAME"))
            meta.processing_baseline = (
                tags.get("SARVEX_PROCESSING_BASELINE")
                or tags.get("PROCESSING_BASELINE")
                or tags.get("PROCESSING_VERSION")
            )
            meta.calibration_status = tags.get("SARVEX_CALIBRATION_STATUS") or tags.get(
                "CALIBRATION_STATUS"
            )
            meta.acquisition_start = _parse_iso(
                tags.get("SARVEX_ACQUISITION_START")
                or tags.get("ACQUISITION_START")
                or tags.get("TIFFTAG_DATETIME")
            )
            meta.acquisition_end = _parse_iso(
                tags.get("SARVEX_ACQUISITION_END") or tags.get("ACQUISITION_END")
            )
            meta.satellite = tags.get("SARVEX_SATELLITE") or tags.get("SATELLITE")
            meta.mission = tags.get("SARVEX_MISSION", "NISAR")
            # Quick valid-data fraction from a bounded sample (never loads the full raster).
            try:
                max_dim = max(ds.width, ds.height)
                step = max(1, max_dim // 256)
                sample = ds.read(1, out_shape=(min(ds.height, 256), min(ds.width, 256)), masked=True)
                meta.quality_indicators["sampled_valid_fraction"] = float(
                    np.ma.count(sample) / max(sample.size, 1)
                )
                valid = sample.compressed().astype("float64")
                if valid.size:
                    meta.quality_indicators["sampled_min"] = float(valid.min())
                    meta.quality_indicators["sampled_max"] = float(valid.max())
                    meta.quality_indicators["sampled_median"] = float(np.median(valid))
                meta.quality_indicators["sampling_step_px"] = step
            except Exception:  # noqa: BLE001
                meta.extraction_notes.append("Valid-data sampling failed")
            meta.checksum = sha256_file(path)
        return meta


class HDF5ProductAdapter(ProductAdapter):
    """Conservative HDF5 reader for NISAR products.

    Product specifications evolve; the adapter records which attributes and
    dataset paths it recognized. Any value not present stays ``None`` and is
    reported in ``extraction_notes`` so it is never mistaken for calibrated
    metadata.
    """

    name = "hdf5"
    supported_suffixes = _HDF5_SUFFIXES

    def validate(self, path: Path) -> ValidationReport:
        report = ValidationReport(valid=True)
        if not path.exists() or path.stat().st_size == 0:
            report.valid = False
            report.errors.append("File is missing or empty")
            return report
        try:
            import h5py

            with h5py.File(path, "r") as f:
                datasets = [0]
                f.visititems(lambda _n, _o: datasets.__setitem__(0, datasets[0] + 1))
                report.checks.update({"hdf5_version": h5py.version.hdf5_version, "objects": datasets[0]})
                if datasets[0] == 0:
                    report.errors.append("HDF5 file contains no objects")
        except Exception as exc:  # noqa: BLE001
            report.valid = False
            report.errors.append(f"Unreadable HDF5: {exc}")
        return report

    def _scan(self, f: Any) -> tuple[dict[str, Any], list[str]]:
        found: dict[str, Any] = {}
        notes: list[str] = []
        keys = {
            "producttype": "product_type",
            "productid": "product_id",
            "missionid": "mission",
            "mission": "mission",
            "satellite": "satellite",
            "platform": "satellite",
            "orbitnumber": "orbit",
            "absoluteorbitnumber": "orbit",
            "tracknumber": "track",
            "framenumber": "frame",
            "frequencyband": "frequency_band",
            "centerfrequency": "frequency_hz",
            "lookdirection": "pass_direction",
            "passdirection": "pass_direction",
            "polarization": "polarization",
            "processingversion": "processing_baseline",
            "processingbaseline": "processing_baseline",
            "calibrationstatus": "calibration_status",
            "zerodopplerstarttime": "acquisition_start",
            "zerodopplerendtime": "acquisition_end",
            "starttime": "acquisition_start",
            "endtime": "acquisition_end",
            "boundingbox": "bbox",
            "epsg": "crs",
            "projection": "crs",
            "units": "units",
        }
        counter = [0]

        def visitor(name: str, obj: Any) -> None:
            if counter[0] > 20_000:
                return
            counter[0] += 1
            base = name.rsplit("/", 1)[-1].replace("_", "").replace("-", "").lower()
            target = keys.get(base)
            if target and target not in found:
                try:
                    import numpy as np
                    import h5py

                    if isinstance(obj, h5py.Dataset):
                        if obj.size == 0 or obj.size > 16:
                            return
                        value = obj[()]
                        if isinstance(value, bytes):
                            value = value.decode("utf-8", "replace")
                        elif isinstance(value, np.ndarray):
                            value = value.tolist()
                        if isinstance(value, str):
                            value = value.strip().strip("\x00")
                        found[target] = value
                except Exception:  # noqa: BLE001
                    pass

        f.visititems(visitor)
        if "frequency_hz" in found:
            hz = _float_or_none(found["frequency_hz"])
            if hz is not None and hz < 1e6:  # likely GHz in metadata
                hz *= 1e9
            found["frequency_hz"] = hz
        if "driver" not in found:
            notes.append("Metadata extracted via heuristic HDF5 scan; map to official product spec before production use")
        return found, notes

    def extract(
        self,
        path: Path,
        *,
        provider: str,
        product_id: str | None = None,
        product_type: str | None = None,
        source_url: str | None = None,
    ) -> NormalizedProductMetadata:
        import h5py

        meta = base_metadata(
            path,
            provider=provider,
            product_id=product_id,
            product_type=product_type,
            source_url=source_url,
            file_format=path.suffix.lstrip(".").lower(),
        )
        meta.extraction_method = "hdf5_heuristic"
        with h5py.File(path, "r") as f:
            root_attrs = {str(k): _decode(v) for k, v in f.attrs.items()}
            found, notes = self._scan(f)
            meta.extraction_notes.extend(notes)
            meta.extra["root_attributes"] = {k: v for k, v in root_attrs.items() if _is_simple(v)}
            meta.extra["hdf5_fields"] = {k: v for k, v in found.items() if _is_simple(v)}
        if found.get("product_type"):
            meta.product_type = infer_product_type(path.name, str(found["product_type"]))
        if found.get("product_id"):
            meta.product_id = str(found["product_id"]).strip("\x00")
        meta.mission = str(found.get("mission") or meta.mission or "NISAR")
        meta.satellite = _str_or_none(found.get("satellite"))
        meta.orbit = _int_or_none(found.get("orbit"))
        meta.track = _int_or_none(found.get("track"))
        meta.frame = _int_or_none(found.get("frame"))
        meta.frequency_band = _str_or_none(found.get("frequency_band"))
        meta.frequency_hz = _float_or_none(found.get("frequency_hz"))
        meta.wavelength_m = _wavelength_from_frequency(meta.frequency_hz)
        meta.polarization = _str_or_none(found.get("polarization"))
        meta.pass_direction = _str_or_none(found.get("pass_direction"))
        meta.processing_baseline = _str_or_none(found.get("processing_baseline"))
        meta.calibration_status = _str_or_none(found.get("calibration_status"))
        meta.units = _str_or_none(found.get("units"))
        meta.crs = _str_or_none(found.get("crs"))
        meta.acquisition_start = _parse_iso(found.get("acquisition_start"))
        meta.acquisition_end = _parse_iso(found.get("acquisition_end"))
        bbox = found.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            try:
                flat = [float(x) for x in bbox[:4]]
                if _looks_like_lonlat(flat):
                    meta.bbox = flat
                    meta.geometry = {
                        "type": "Polygon",
                        "coordinates": [[
                            [flat[0], flat[1]], [flat[2], flat[1]],
                            [flat[2], flat[3]], [flat[0], flat[3]], [flat[0], flat[1]],
                        ]],
                    }
            except (TypeError, ValueError):
                pass
        meta.file_size = path.stat().st_size
        meta.checksum = sha256_file(path)
        return meta


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip().strip("\x00")
    return text or None


def _is_simple(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or (
        isinstance(value, (list, tuple)) and len(value) <= 16 and all(isinstance(v, (str, int, float)) for v in value)
    )


class RSLCAdapter(HDF5ProductAdapter):
    name = "nisar_rslc"
    supported_types = ("RSLC",)


class GSLCAdapter(RasterProductAdapter):
    name = "nisar_gslc"
    supported_types = ("GSLC",)


class GCOVAdapter(RasterProductAdapter):
    name = "nisar_gcov"
    supported_types = ("GCOV",)


class RIFGAdapter(HDF5ProductAdapter):
    name = "nisar_rifg"
    supported_types = ("RIFG",)


class RUNWAdapter(HDF5ProductAdapter):
    name = "nisar_runw"
    supported_types = ("RUNW",)


class GUNWAdapter(HDF5ProductAdapter):
    name = "nisar_gunw"
    supported_types = ("GUNW",)


class ROFFAdapter(HDF5ProductAdapter):
    name = "nisar_roff"
    supported_types = ("ROFF",)


class GOFFAdapter(RasterProductAdapter):
    name = "nisar_goff"
    supported_types = ("GOFF",)


class GenericRasterAdapter(RasterProductAdapter):
    name = "generic_raster"
    supported_types = ("UNKNOWN", "GCOV", "GSLC", "GOFF")


class GenericHDF5Adapter(HDF5ProductAdapter):
    name = "generic_hdf5"
    supported_types = ("UNKNOWN", "RSLC", "RIFG", "RUNW", "GUNW", "ROFF")
