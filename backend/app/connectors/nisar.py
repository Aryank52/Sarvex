"""NISAR provider abstraction and product adapters.

Wraps the existing ASF/Bhoonidhi/STAC/local/demo connectors behind a common
NISARDataProvider contract so the platform can treat NISAR as a first-class
source while remaining provider-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from app.connectors.base import ConnectorHealth, RemoteProduct, SearchQuery
from app.connectors.registry import ConnectorRegistry


@dataclass
class NISARProductMetadata:
    product_id: str
    mission: str = "NISAR"
    satellite: str | None = None
    provider: str = ""
    frequency: str | None = None
    polarization: str | None = None
    acquisition_time: str | None = None
    orbit: int | None = None
    pass_direction: str | None = None
    crs: str | None = None
    bbox: list[float] | None = None
    resolution_m: float | None = None
    units: str | None = None
    processing_baseline: str | None = None
    source: str | None = None
    quality: dict[str, Any] = None  # type: ignore[assignment]
    file_uri: str | None = None

    def __post_init__(self) -> None:
        if self.quality is None:
            self.quality = {}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProductAdapter(ABC):
    product_type: str = ""

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NISARProductMetadata:
        ...

    @staticmethod
    def _bbox(raw: dict[str, Any]) -> list[float] | None:
        return raw.get("bbox") or raw.get("bounding_box")


class RSLCAdapter(ProductAdapter):
    product_type = "RSLC"

    def normalize(self, raw: dict[str, Any]) -> NISARProductMetadata:
        return NISARProductMetadata(
            product_id=raw.get("product_id") or raw.get("id", ""),
            mission=raw.get("mission", "NISAR"),
            satellite=raw.get("satellite"),
            provider=raw.get("provider", ""),
            frequency=raw.get("frequency_band") or raw.get("frequency"),
            polarization=raw.get("polarization"),
            acquisition_time=raw.get("acquisition_start") or raw.get("acquisition_time"),
            orbit=raw.get("orbit"),
            pass_direction=raw.get("pass_direction"),
            crs=raw.get("crs"),
            bbox=self._bbox(raw),
            resolution_m=raw.get("spatial_resolution_m") or raw.get("resolution_m"),
            units=raw.get("units", "complex"),
            processing_baseline=raw.get("processing_baseline"),
            source=raw.get("source_url") or raw.get("source"),
            quality=raw.get("quality") or {},
            file_uri=raw.get("object_uri") or raw.get("file_uri"),
        )


class GSLCAdapter(RSLCAdapter):
    product_type = "GSLC"


class GCOVAdapter(ProductAdapter):
    product_type = "GCOV"

    def normalize(self, raw: dict[str, Any]) -> NISARProductMetadata:
        return RSLCAdapter().normalize({**raw, "units": raw.get("units", "gamma0")})


class RIFGAdapter(ProductAdapter):
    product_type = "RIFG"

    def normalize(self, raw: dict[str, Any]) -> NISARProductMetadata:
        return RSLCAdapter().normalize({**raw, "units": raw.get("units", "interferogram")})


class RUNWAdapter(RIFGAdapter):
    product_type = "RUNW"


class GUNWAdapter(RIFGAdapter):
    product_type = "GUNW"


class ROFFAdapter(ProductAdapter):
    product_type = "ROFF"

    def normalize(self, raw: dict[str, Any]) -> NISARProductMetadata:
        return RSLCAdapter().normalize({**raw, "units": raw.get("units", "offset")})


class GOFFAdapter(ROFFAdapter):
    product_type = "GOFF"


ADAPTERS: dict[str, ProductAdapter] = {
    "RSLC": RSLCAdapter(),
    "GSLC": GSLCAdapter(),
    "GCOV": GCOVAdapter(),
    "RIFG": RIFGAdapter(),
    "RUNW": RUNWAdapter(),
    "GUNW": GUNWAdapter(),
    "ROFF": ROFFAdapter(),
    "GOFF": GOFFAdapter(),
}


def get_adapter(product_type: str) -> ProductAdapter:
    return ADAPTERS.get(product_type.upper(), RSLCAdapter())


class NISARDataProvider(ABC):
    name: str = ""
    mode: str = "unknown"

    @abstractmethod
    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        ...

    @abstractmethod
    def get_metadata(self, product_ref: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    def download(self, product_ref: str, target_dir: str) -> str | None:
        ...

    @abstractmethod
    def validate(self, product_ref: str) -> bool:
        ...

    @abstractmethod
    def register(self, product: RemoteProduct) -> dict[str, Any]:
        ...

    @abstractmethod
    def health_check(self) -> ConnectorHealth:
        ...


class ASFProvider(NISARDataProvider):
    name = "asf"
    mode = "live"

    def __init__(self) -> None:
        self._reg = ConnectorRegistry()

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        return self._reg.asf.search(query)

    def get_metadata(self, product_ref: str) -> dict[str, Any] | None:
        return self._reg.asf.get_metadata(product_ref)

    def download(self, product_ref: str, target_dir: str) -> str | None:
        try:
            return self._reg.asf.download(product_ref, target_dir)
        except Exception:  # noqa: BLE001
            return None

    def validate(self, product_ref: str) -> bool:
        return self._reg.asf.validate(product_ref)

    def register(self, product: RemoteProduct) -> dict[str, Any]:
        return {"provider": self.name, "product_id": product.product_id}

    def health_check(self) -> ConnectorHealth:
        return self._reg.asf.health_check()


class BhoonidhiProvider(NISARDataProvider):
    name = "bhoonidhi"
    mode = "live"

    def __init__(self) -> None:
        self._reg = ConnectorRegistry()

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        return self._reg.bhoonidhi.search(query)

    def get_metadata(self, product_ref: str) -> dict[str, Any] | None:
        return self._reg.bhoonidhi.get_metadata(product_ref)

    def download(self, product_ref: str, target_dir: str) -> str | None:
        try:
            return self._reg.bhoonidhi.download(product_ref, target_dir)
        except Exception:  # noqa: BLE001
            return None

    def validate(self, product_ref: str) -> bool:
        return self._reg.bhoonidhi.validate(product_ref)

    def register(self, product: RemoteProduct) -> dict[str, Any]:
        return {"provider": self.name, "product_id": product.product_id}

    def health_check(self) -> ConnectorHealth:
        return self._reg.bhoonidhi.health_check()


class LocalNISARProvider(NISARDataProvider):
    name = "local"
    mode = "local"

    def __init__(self) -> None:
        self._reg = ConnectorRegistry()

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        return self._reg.local.search(query)

    def get_metadata(self, product_ref: str) -> dict[str, Any] | None:
        return self._reg.local.get_metadata(product_ref)

    def download(self, product_ref: str, target_dir: str) -> str | None:
        try:
            return self._reg.local.download(product_ref, target_dir)
        except Exception:  # noqa: BLE001
            return None

    def validate(self, product_ref: str) -> bool:
        return self._reg.local.validate(product_ref)

    def register(self, product: RemoteProduct) -> dict[str, Any]:
        return {"provider": self.name, "product_id": product.product_id}

    def health_check(self) -> ConnectorHealth:
        return self._reg.local.health_check()


class DemoNISARProvider(NISARDataProvider):
    name = "demo"
    mode = "demo"

    def __init__(self) -> None:
        self._reg = ConnectorRegistry()

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        return self._reg.demo.search(query)

    def get_metadata(self, product_ref: str) -> dict[str, Any] | None:
        return self._reg.demo.get_metadata(product_ref)

    def download(self, product_ref: str, target_dir: str) -> str | None:
        try:
            return self._reg.demo.download(product_ref, target_dir)
        except Exception:  # noqa: BLE001
            return None

    def validate(self, product_ref: str) -> bool:
        return self._reg.demo.validate(product_ref)

    def register(self, product: RemoteProduct) -> dict[str, Any]:
        return {"provider": self.name, "product_id": product.product_id, "is_demo": True}

    def health_check(self) -> ConnectorHealth:
        return self._reg.demo.health_check()


def get_nisar_providers() -> dict[str, NISARDataProvider]:
    return {
        "asf": ASFProvider(),
        "bhoonidhi": BhoonidhiProvider(),
        "local": LocalNISARProvider(),
        "demo": DemoNISARProvider(),
    }
