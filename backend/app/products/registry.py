"""Adapter registry: pick the correct adapter without format logic leaking out."""
from __future__ import annotations

from pathlib import Path

from app.core.errors import ValidationError
from app.products.adapters import (
    GCOVAdapter,
    GOFFAdapter,
    GSLCAdapter,
    GUNWAdapter,
    GenericHDF5Adapter,
    GenericRasterAdapter,
    RIFGAdapter,
    ROFFAdapter,
    RSLCAdapter,
    RUNWAdapter,
)
from app.products.base import ProductAdapter

_ADAPTERS: dict[str, ProductAdapter] = {
    "RSLC": RSLCAdapter(),
    "GSLC": GSLCAdapter(),
    "GCOV": GCOVAdapter(),
    "RIFG": RIFGAdapter(),
    "RUNW": RUNWAdapter(),
    "GUNW": GUNWAdapter(),
    "ROFF": ROFFAdapter(),
    "GOFF": GOFFAdapter(),
    "UNKNOWN_RASTER": GenericRasterAdapter(),
    "UNKNOWN_HDF5": GenericHDF5Adapter(),
}
_RASTER = {".tif", ".tiff", ".cog", ".img", ".vrt"}
_HDF5 = {".h5", ".hdf5", ".he5", ".nc"}


def get_adapter(path: Path, product_type: str | None = None) -> ProductAdapter:
    suffix = path.suffix.lower()
    ptype = (product_type or "UNKNOWN").upper()
    if suffix in _RASTER and ptype in _ADAPTERS and _ADAPTERS[ptype].name.startswith("nisar"):
        # GCOV/GSLC/GOFF adapters are raster based; others need HDF5.
        if ptype in {"GCOV", "GSLC", "GOFF"}:
            return _ADAPTERS[ptype]
    if suffix in _HDF5 and ptype in {"RSLC", "RIFG", "RUNW", "GUNW", "ROFF"}:
        return _ADAPTERS[ptype]
    if suffix in _RASTER:
        return _ADAPTERS["UNKNOWN_RASTER"]
    if suffix in _HDF5:
        return _ADAPTERS["UNKNOWN_HDF5"]
    raise ValidationError(
        f"Unsupported product format '{suffix}'",
        detail={"supported_raster": sorted(_RASTER), "supported_hdf5": sorted(_HDF5)},
    )


def adapter_catalog() -> list[dict[str, str]]:
    return [
        {"product_type": k.split("_")[0], "adapter": v.name, "version": v.version}
        for k, v in _ADAPTERS.items()
        if not k.startswith("UNKNOWN")
    ]
