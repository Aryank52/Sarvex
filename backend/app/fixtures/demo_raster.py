"""Deterministic synthetic demo rasters.

These are SARVEX fixtures, not NASA/ISRO observations. Every file and every
catalog record is explicitly tagged DEMO. The scenes contain controlled
patterns (river/flood expansion, a localized deformation lobe, vegetation
structure change) so the full scientific pipeline can be exercised offline.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from app.config import BACKEND_DIR

DEMO_DIR = BACKEND_DIR / "data" / "demo_fixtures"

# A real-world AOI (Assam, India) is used for geographic context. All pixel
# values are synthetic and labelled as such.
AOI_BOUNDS = (91.55, 26.05, 91.95, 26.32)
WIDTH = HEIGHT = 180


def _write_geotiff(
    path: Path,
    bands: list[np.ndarray],
    *,
    descriptions: list[str],
    tags: dict[str, str],
) -> Path:
    import rasterio
    from rasterio.transform import from_bounds

    path.parent.mkdir(parents=True, exist_ok=True)
    transform = from_bounds(*AOI_BOUNDS, WIDTH, HEIGHT)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=WIDTH,
        height=HEIGHT,
        count=len(bands),
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
        compress="deflate",
    ) as ds:
        for idx, band in enumerate(bands, start=1):
            ds.write(band.astype("float32"), idx)
            ds.set_band_description(idx, descriptions[idx - 1])
        ds.update_tags(**tags)
    return path


def _river_mask(expansion: float = 0.0) -> np.ndarray:
    """Meandering river mask; expansion shifts the floodplain amplitude."""
    y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
    centerline = 70 + 24 * np.sin(x / 18.0) + 8 * np.sin(x / 6.3)
    width = 7.0 + 9.0 * expansion
    return np.abs(y - centerline) < width


def _base_land(rng: np.random.Generator) -> np.ndarray:
    texture = rng.normal(0, 0.8, (HEIGHT, WIDTH))
    fields = 2.5 * np.sin(np.mgrid[0:HEIGHT, 0:WIDTH][1] / 11.0) * np.sin(
        np.mgrid[0:HEIGHT, 0:WIDTH][0] / 15.0
    )
    return -11.0 + texture + fields


def _scene(seed: int, flood_expansion: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    land = _base_land(rng)
    water = np.where(_river_mask(flood_expansion), -22.0 + rng.normal(0, 0.7, land.shape), land)
    return water


def _tags(scene_id: str, acquired: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    tags = {
        "SARVEX_IS_DEMO": "TRUE",
        "SARVEX_PRODUCT_TYPE": "GCOV",
        "SARVEX_MISSION": "SARVEX-DEMO",
        "SARVEX_SATELLITE": "DEMO-SAR",
        "SARVEX_FREQUENCY_BAND": "L",
        "SARVEX_FREQUENCY_HZ": "1257000000",
        "SARVEX_WAVELENGTH_M": "0.2385",
        "SARVEX_POLARIZATION": "VV",
        "SARVEX_UNITS": "dB",
        "SARVEX_ORBIT": "1001",
        "SARVEX_PASS_DIRECTION": "ASCENDING",
        "SARVEX_TRACK": "42",
        "SARVEX_FRAME": "17",
        "SARVEX_ACQUISITION_START": acquired,
        "SARVEX_PROCESSING_BASELINE": "DEMO-B1.0",
        "SARVEX_CALIBRATION_STATUS": "DEMO_SYNTHETIC",
        "SARVEX_SCENE_ID": scene_id,
        "SARVEX_ATTRIBUTION": "SARVEX synthetic fixture. Not NASA or ISRO data.",
    }
    if extra:
        tags.update(extra)
    return tags


DEMO_SCENES = {
    "gcov_l_before": {
        "file": "DEMO_NISAR_L2_GCOV_BETA_V1_20260601_assam.tif",
        "tags": _tags("gcov_l_before", "2026-06-01T05:30:00+00:00"),
        "product_type": "GCOV",
        "polarization": "VV",
    },
    "gcov_l_mid": {
        "file": "DEMO_NISAR_L2_GCOV_BETA_V1_20260705_assam.tif",
        "tags": _tags("gcov_l_mid", "2026-07-05T05:30:00+00:00"),
        "product_type": "GCOV",
        "polarization": "VV",
    },
    "gcov_l_after": {
        "file": "DEMO_NISAR_L2_GCOV_BETA_V1_20260810_assam.tif",
        "tags": _tags("gcov_l_after", "2026-08-10T05:30:00+00:00"),
        "product_type": "GCOV",
        "polarization": "VV",
    },
    "gcov_s_mid": {
        "file": "DEMO_NISAR_S2_GCOV_BETA_V1_20260709_assam.tif",
        "tags": _tags(
            "gcov_s_mid",
            "2026-07-09T05:25:00+00:00",
            {
                "SARVEX_FREQUENCY_BAND": "S",
                "SARVEX_FREQUENCY_HZ": "3200000000",
                "SARVEX_WAVELENGTH_M": "0.0937",
            },
        ),
        "product_type": "GCOV",
        "polarization": "VV",
    },
    "gcov_s_after": {
        "file": "DEMO_NISAR_S2_GCOV_BETA_V1_20260813_assam.tif",
        "tags": _tags(
            "gcov_s_after",
            "2026-08-13T05:25:00+00:00",
            {
                "SARVEX_FREQUENCY_BAND": "S",
                "SARVEX_FREQUENCY_HZ": "3200000000",
                "SARVEX_WAVELENGTH_M": "0.0937",
            },
        ),
        "product_type": "GCOV",
        "polarization": "VV",
    },
    "pol_l_before": {
        "file": "DEMO_NISAR_L2_GCOV_POL_BETA_V1_20260601_assam.tif",
        "tags": _tags(
            "pol_l_before",
            "2026-06-01T05:30:00+00:00",
            {"SARVEX_POLARIZATION": "VV+VH"},
        ),
        "product_type": "GCOV",
        "polarization": "VV+VH",
    },
    "pol_l_after": {
        "file": "DEMO_NISAR_L2_GCOV_POL_BETA_V1_20260810_assam.tif",
        "tags": _tags(
            "pol_l_after",
            "2026-08-10T05:30:00+00:00",
            {"SARVEX_POLARIZATION": "VV+VH"},
        ),
        "product_type": "GCOV",
        "polarization": "VV+VH",
    },
    "gunw_l": {
        "file": "DEMO_NISAR_L2_GUNW_BETA_V1_20260810_assam.tif",
        "tags": _tags(
            "gunw_l",
            "2026-08-10T05:30:00+00:00",
            {
                "SARVEX_PRODUCT_TYPE": "GUNW",
                "SARVEX_CALIBRATION_STATUS": "DEMO_SYNTHETIC",
                "SARVEX_REFERENCE_DATE": "2026-07-05T05:30:00+00:00",
            },
        ),
        "product_type": "GUNW",
        "polarization": "VV",
    },
}


def _ensure_scene(scene_key: str) -> Path:
    spec = DEMO_SCENES[scene_key]
    path = DEMO_DIR / spec["file"]
    if path.exists():
        return path
    if scene_key in {"gcov_l_before", "gcov_l_mid", "gcov_l_after", "gcov_s_mid", "gcov_s_after"}:
        expansion = {"gcov_l_before": 0.0, "gcov_l_mid": 0.7, "gcov_l_after": 1.0, "gcov_s_mid": 0.5, "gcov_s_after": 0.9}[scene_key]
        seed = {"gcov_l_before": 11, "gcov_l_mid": 12, "gcov_l_after": 13, "gcov_s_mid": 21, "gcov_s_after": 22}[scene_key]
        scene = _scene(seed, expansion)
        return _write_geotiff(path, [scene], descriptions=["sigma0_VV_dB"], tags=spec["tags"])
    if scene_key in {"pol_l_before", "pol_l_after"}:
        rng = np.random.default_rng(31 if scene_key == "pol_l_before" else 32)
        vv = _scene(31, 0.0 if scene_key == "pol_l_before" else 1.0)
        vh = vv - (7.5 + rng.normal(0, 0.5, vv.shape))
        vegetation = (np.mgrid[0:HEIGHT, 0:WIDTH][1] > 120) & (np.mgrid[0:HEIGHT, 0:WIDTH][0] < 60)
        if scene_key == "pol_l_after":
            vh[vegetation] -= 3.0  # structure change in the demo vegetation patch
        return _write_geotiff(
            path,
            [vv, vh],
            descriptions=["sigma0_VV_dB", "sigma0_VH_dB"],
            tags=spec["tags"],
        )
    if scene_key == "gunw_l":
        rng = np.random.default_rng(41)
        y, x = np.mgrid[0:HEIGHT, 0:WIDTH]
        lobe = 2.4 * np.exp(-(((x - 105) ** 2) / (2 * 24.0**2) + ((y - 90) ** 2) / (2 * 18.0**2)))
        phase = lobe + rng.normal(0, 0.22, (HEIGHT, WIDTH))
        coherence = np.clip(0.78 - 0.35 * lobe + rng.normal(0, 0.05, (HEIGHT, WIDTH)), 0.05, 0.99)
        tags = dict(spec["tags"])
        tags["SARVEX_WAVELENGTH_M"] = "0.2385"
        return _write_geotiff(
            path,
            [phase.astype("float32"), coherence.astype("float32")],
            descriptions=["unwrapped_phase_rad", "coherence"],
            tags=tags,
        )
    raise KeyError(scene_key)


def ensure_demo_fixtures() -> dict[str, Path]:
    return {key: _ensure_scene(key) for key in DEMO_SCENES}
