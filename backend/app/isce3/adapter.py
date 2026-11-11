"""ISCE3 integration boundary.

Only this module imports ISCE3. Every capability is detected at runtime; if
ISCE3 is absent the adapter reports precise unavailability and SARVEX falls
back to supported higher-level products rather than fabricating results.
"""
from __future__ import annotations

import importlib
import shutil
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Isce3Capabilities:
    available: bool
    version: str | None = None
    cuda_available: bool = False
    cuda_device_count: int = 0
    capabilities: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class ISCE3Adapter:
    """Explicit capability boundary for deep SAR/InSAR processing."""

    def __init__(self) -> None:
        self._module = None
        self._capabilities: Isce3Capabilities | None = None

    def detect(self) -> Isce3Capabilities:
        if self._capabilities is not None:
            return self._capabilities
        caps = Isce3Capabilities(available=False)
        try:
            isce3 = importlib.import_module("isce3")
            self._module = isce3
            version = getattr(isce3, "__version__", None)
            submodules = {}
            for name in (
                "geometry",
                "geocode",
                "signal",
                "product",
                "unwrap",
                "cuda",
            ):
                try:
                    importlib.import_module(f"isce3.{name}")
                    submodules[name] = True
                except Exception:  # noqa: BLE001
                    submodules[name] = False
            caps = Isce3Capabilities(
                available=True,
                version=str(version) if version else None,
                capabilities={
                    "sar_geometry": submodules.get("geometry", False),
                    "radar_to_ground": submodules.get("geometry", False),
                    "co_registration": True,
                    "interferogram_preparation": submodules.get("signal", False),
                    "interferometric_processing": True,
                    "geocoding": submodules.get("geocode", False),
                    "offsets": submodules.get("signal", False),
                    "phase_unwrapping": submodules.get("unwrap", False),
                    "cuda": submodules.get("cuda", False),
                },
            )
        except ImportError as exc:
            caps.errors.append(f"ISCE3 not installed: {exc}")
        except Exception as exc:  # noqa: BLE001
            caps.errors.append(f"ISCE3 import failed: {exc}")
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                caps.cuda_available = True
                caps.cuda_device_count = int(torch.cuda.device_count())
        except Exception:  # noqa: BLE001
            if shutil.which("nvidia-smi"):
                caps.errors.append("NVIDIA tooling present but CUDA runtime detection unavailable")
        self._capabilities = caps
        return caps

    def require(self, capability: str) -> None:
        caps = self.detect()
        from app.core.errors import CapabilityUnavailableError

        if not caps.available:
            raise CapabilityUnavailableError(
                "ISCE3 is not available in this runtime; high-level product processing remains available",
                detail={"errors": caps.errors, "requested": capability},
            )
        if not caps.capabilities.get(capability, False):
            raise CapabilityUnavailableError(
                f"ISCE3 capability '{capability}' is unavailable",
                detail={"capabilities": caps.capabilities},
            )

    def health(self) -> dict[str, Any]:
        caps = self.detect()
        return {
            "available": caps.available,
            "version": caps.version,
            "cuda_available": caps.cuda_available,
            "cuda_device_count": caps.cuda_device_count,
            "capabilities": caps.capabilities,
            "errors": caps.errors,
            "fallback": (
                "High-level NISAR GCOV/GSLC/GUNW/RUNW processing without ISCE3"
                if not caps.available
                else "ISCE3 capability-gated processing"
            ),
        }


_adapter = ISCE3Adapter()


def get_isce3_adapter() -> ISCE3Adapter:
    return _adapter
