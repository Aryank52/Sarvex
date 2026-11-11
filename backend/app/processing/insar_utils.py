"""Interferometric product readers and physically explicit conversions."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.crs import CRS

from app.core.units import phase_to_displacement_mm
from app.processing.base import InputProduct, ProcessContext
from app.processing.raster import RasterData, read_raster

SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass
class InsarPair:
    phase_rad: np.ndarray
    coherence: np.ndarray
    grid: RasterData
    wavelength_m: float
    phase_band: str
    coherence_band: str
    notes: list[str]


def resolve_wavelength(product: InputProduct) -> float | None:
    if product.wavelength_m and product.wavelength_m > 0:
        return float(product.wavelength_m)
    if product.frequency_hz and product.frequency_hz > 0:
        return SPEED_OF_LIGHT_M_S / float(product.frequency_hz)
    return None


def read_insar_pair(ctx: ProcessContext, product: InputProduct) -> InsarPair:
    from app.core.errors import ValidationError
    from app.processing.raster import RasterReadError

    wavelength = resolve_wavelength(product)
    if wavelength is None:
        raise ValidationError(
            "Interferometric wavelength/frequency metadata is required for displacement conversion",
            detail={"product": product.product_id},
        )
    path = product.path
    if path.suffix.lower() in {".h5", ".hdf5", ".he5"}:
        phase, coherence, grid, notes = _read_hdf5_interferogram(ctx, product)
    else:
        try:
            raster = read_raster(path, geometry=ctx.aoi_geometry)
        except RasterReadError as exc:
            raise ValidationError(str(exc)) from exc
        phase_idx = raster.band_index_by_keyword("unwrapped", "phase")
        coherence_idx = raster.band_index_by_keyword("coherence")
        params = ctx.parameters
        if phase_idx is None and "phase_band" in params:
            phase_idx = int(params["phase_band"])
        if coherence_idx is None and "coherence_band" in params:
            coherence_idx = int(params["coherence_band"])
        if phase_idx is None or coherence_idx is None:
            raise ValidationError(
                "Could not identify phase and coherence bands. Provide band descriptions "
                "('unwrapped_phase_rad', 'coherence') or explicit phase_band/coherence_band parameters.",
                detail={"descriptions": raster.descriptions, "product": product.product_id},
            )
        phase = raster.band(phase_idx)
        coherence = np.clip(raster.band(coherence_idx), 0.0, 1.0)
        grid = RasterData(
            data=raster.data,
            transform=raster.transform,
            crs=raster.crs,
            descriptions=raster.descriptions,
            tags=raster.tags,
        )
        notes = [f"phase band: {raster.descriptions[phase_idx] or phase_idx}; coherence band: {raster.descriptions[coherence_idx] or coherence_idx}"]
    if not np.isfinite(phase).any():
        raise ValidationError("Interferometric phase contains no finite values")
    return InsarPair(
        phase_rad=np.asarray(phase, dtype="float32"),
        coherence=np.asarray(coherence, dtype="float32"),
        grid=grid,
        wavelength_m=float(wavelength),
        phase_band="unwrapped_phase_rad",
        coherence_band="coherence",
        notes=notes,
    )


def displacement_and_uncertainty(
    pair: InsarPair, *, coherence_threshold: float, looks: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return displacement [mm], per-pixel 1-sigma uncertainty [mm], coherence mask."""
    from app.core.units import coherence_phase_sigma

    phase = pair.phase_rad
    disp_mm = np.full(phase.shape, np.nan, dtype="float32")
    unc_mm = np.full(phase.shape, np.nan, dtype="float32")
    coh_mask = np.isfinite(phase) & np.isfinite(pair.coherence) & (pair.coherence >= coherence_threshold)
    valid = np.isfinite(phase)
    disp_mm[valid] = phase_to_displacement_mm(phase[valid], pair.wavelength_m)
    coh_safe = np.clip(pair.coherence[valid], 1e-3, 0.9999)
    sigma_rad = np.sqrt(np.maximum(1.0 - coh_safe**2, 0.0) / (2.0 * coh_safe**2 * max(looks, 1.0)))
    unc_mm[valid] = (pair.wavelength_m / (4.0 * np.pi)) * sigma_rad * 1000.0
    return disp_mm, np.where(coh_mask, unc_mm, np.nan).astype("float32"), coh_mask


def _read_hdf5_interferogram(
    ctx: ProcessContext, product: InputProduct
) -> tuple[np.ndarray, np.ndarray, RasterData, list[str]]:
    """Best-effort read of georeferenced phase/coherence from HDF5.

    The reader requires explicit coordinate arrays and an explicit CRS; without
    them it refuses to geocode rather than inventing a transform.
    """
    from app.core.errors import CapabilityUnavailableError, ValidationError
    from app.processing.raster import RasterReadError

    import h5py

    notes: list[str] = []
    with h5py.File(product.path, "r") as f:
        datasets: dict[str, tuple[np.ndarray, tuple[int, ...]]] = {}

        def visitor(name: str, obj) -> None:  # type: ignore[no-untyped-def]
            if isinstance(obj, h5py.Dataset) and obj.ndim == 2 and obj.size < 200_000_000:
                low = name.lower()
                if any(k in low for k in ("unwrapped", "phase", "coherence")):
                    try:
                        datasets[name] = (obj[()], obj.shape)
                    except Exception:  # noqa: BLE001
                        pass

        f.visititems(visitor)
        phase_items = [(k, v) for k, v in datasets.items() if "coherence" not in k.lower()]
        coherence_items = [(k, v) for k, v in datasets.items() if "coherence" in k.lower()]
        if not phase_items or not coherence_items:
            raise CapabilityUnavailableError(
                "HDF5 interferogram does not expose readable phase/coherence datasets",
                detail={"product": product.product_id},
            )
        # Prefer 'unwrappedphase', then shortest path.
        phase_items.sort(key=lambda kv: (0 if "unwrapped" in kv[0].lower() else 1, len(kv[0])))
        coherence_items.sort(key=lambda kv: len(kv[0]))
        phase = np.asarray(phase_items[0][1][0], dtype="float32")
        coherence = np.asarray(coherence_items[0][1][0], dtype="float32")
        notes.append(f"HDF5 phase dataset: {phase_items[0][0]}")
        notes.append(f"HDF5 coherence dataset: {coherence_items[0][0]}")

        x = _find_coordinate(f, ("xcoordinates", "x_coordinates", "lon", "longitude"))
        y = _find_coordinate(f, ("ycoordinates", "y_coordinates", "lat", "latitude"))
        crs_attr = _find_scalar(f, ("crs", "epsg", "projection", "spatialreference"))
        if x is None or y is None or crs_attr is None:
            raise CapabilityUnavailableError(
                "HDF5 interferogram lacks explicit x/y coordinates and CRS; geocoding requires "
                "the ISCE3 adapter or an official product-specific reader.",
                detail={"product": product.product_id, "notes": notes},
            )
        if phase.shape != coherence.shape:
            raise ValidationError("Phase and coherence datasets have different shapes")
        transform = _transform_from_coords(x, y, phase.shape)
        crs = _parse_crs(crs_attr)
        if crs is None:
            raise CapabilityUnavailableError(f"Unrecognized CRS metadata: {crs_attr}")
        grid = RasterData(
            data=np.stack([phase, coherence])[np.newaxis] if False else np.stack([phase, coherence]),
            transform=transform,
            crs=crs,
            descriptions=["unwrapped_phase_rad", "coherence"],
            tags={},
        )
        # Clip to AOI via rasterio window on an in-memory grid would add a copy;
        # for now the caller masks by AOI after reading (bounded dataset size check above).
        return phase, coherence, grid, notes


def _find_scalar(f, names: tuple[str, ...]):  # type: ignore[no-untyped-def]
    found = None

    def visitor(name: str, obj) -> None:  # type: ignore[no-untyped-def]
        nonlocal found
        if found is not None:
            return
        low = name.rsplit("/", 1)[-1].lower().replace("_", "")
        if any(n in low for n in names):
            try:
                import h5py

                if isinstance(obj, h5py.Dataset) and obj.size == 1:
                    value = obj[()]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "replace")
                    if isinstance(value, str):
                        value = value.strip().strip("\x00")
                    found = value
            except Exception:  # noqa: BLE001
                pass

    f.visititems(visitor)
    return found


def _find_coordinate(f, names: tuple[str, ...]):  # type: ignore[no-untyped-def]
    found = None

    def visitor(name: str, obj) -> None:  # type: ignore[no-untyped-def]
        nonlocal found
        if found is not None:
            return
        low = name.rsplit("/", 1)[-1].lower().replace("_", "")
        if any(n in low for n in names):
            try:
                import h5py

                if isinstance(obj, h5py.Dataset) and obj.ndim == 1 and obj.size > 1:
                    found = np.asarray(obj[()], dtype="float64")
            except Exception:  # noqa: BLE001
                pass

    f.visititems(visitor)
    return found


def _parse_crs(value) -> CRS | None:  # type: ignore[no-untyped-def]
    try:
        text = str(value).strip()
        if text.upper().startswith("EPSG:"):
            return CRS.from_string(text)
        if text.isdigit():
            return CRS.from_epsg(int(text))
        return CRS.from_user_input(text)
    except Exception:  # noqa: BLE001
        return None


def _transform_from_coords(x: np.ndarray, y: np.ndarray, shape: tuple[int, int]) -> Affine:
    if len(x) != shape[1] or len(y) != shape[0]:
        raise ValueError("Coordinate arrays do not match raster dimensions")
    dx = float(np.median(np.diff(x)))
    dy = float(np.median(np.diff(y)))
    return Affine(dx, 0.0, float(x[0]) - dx / 2.0, 0.0, dy, float(y[0]) - dy / 2.0)
