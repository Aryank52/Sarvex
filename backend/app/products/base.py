"""Product adapter base classes.

Adapters isolate all format-specific metadata logic. Everything downstream sees
only :class:`NormalizedProductMetadata`.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from app.products.metadata import NormalizedProductMetadata, ValidationReport

PRODUCT_TYPES = ("RSLC", "GSLC", "GCOV", "RIFG", "RUNW", "GUNW", "ROFF", "GOFF")

_POL_PATTERN = re.compile(r"(?<![A-Z0-9])(VV|VH|HH|HV)(?![A-Z0-9])", re.IGNORECASE)
_KNOWN_BANDS = ("L", "S", "C", "X", "P")


def infer_product_type(filename: str, hint: str | None = None) -> str:
    if hint and hint.upper() in PRODUCT_TYPES:
        return hint.upper()
    upper = filename.upper()
    for ptype in PRODUCT_TYPES:
        if re.search(rf"(^|[_\-.]){ptype}([_\-. ]|$)", upper):
            return ptype
    return "UNKNOWN"


def infer_polarizations(descriptions: list[str], tags: dict[str, str]) -> str | None:
    if tags.get("SARVEX_POLARIZATION"):
        return tags["SARVEX_POLARIZATION"]
    found: list[str] = []
    for desc in descriptions:
        for match in _POL_PATTERN.findall(desc or ""):
            pol = match.upper()
            if pol not in found:
                found.append(pol)
    return "+".join(found) if found else None


class ProductAdapter(ABC):
    name: str = "base"
    version: str = "1.0"
    supported_types: tuple[str, ...] = PRODUCT_TYPES

    def supports(self, product_type: str, file_format: str | None) -> bool:
        return product_type.upper() in self.supported_types

    @abstractmethod
    def validate(self, path: Path) -> ValidationReport:
        ...

    @abstractmethod
    def extract(
        self,
        path: Path,
        *,
        provider: str,
        product_id: str | None = None,
        product_type: str | None = None,
        source_url: str | None = None,
    ) -> NormalizedProductMetadata:
        ...


def base_metadata(
    path: Path,
    *,
    provider: str,
    product_id: str | None,
    product_type: str | None,
    source_url: str | None,
    file_format: str | None,
) -> NormalizedProductMetadata:
    return NormalizedProductMetadata(
        provider=provider,
        product_id=product_id or path.stem,
        product_type=infer_product_type(path.name, product_type),
        source_url=source_url,
        source_identifier=path.name,
        file_format=file_format or path.suffix.lstrip(".").lower(),
        file_size=path.stat().st_size if path.exists() else None,
    )
