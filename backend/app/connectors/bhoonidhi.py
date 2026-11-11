"""ISRO / Bhoonidhi connector.

Bhoonidhi API access is authorized and operator-specific. SARVEX therefore
requires an explicit search endpoint (``BHOONIDHI_SEARCH_URL``) and API key.
Without them this connector reports ``unconfigured`` and never fabricates
S-band observations.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.connectors.base import ConnectorHealth, DataSource, RemoteProduct, SearchQuery
from app.core.errors import CapabilityUnavailableError, NotFoundError
from app.products.base import infer_product_type


class BhoonidhiConnector(DataSource):
    name = "ISRO Bhoonidhi"
    mode = "live"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.search_url = self.settings.bhoonidhi_search_url
        self.api_key = self.settings.bhoonidhi_api_key
        self._cache: dict[str, RemoteProduct] = {}

    @property
    def configured(self) -> bool:
        return bool(self.search_url and self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise CapabilityUnavailableError("Bhoonidhi API key is not configured")
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def _parse(self, item: dict[str, Any]) -> RemoteProduct:
        pid = (
            item.get("product_id")
            or item.get("productId")
            or item.get("granuleId")
            or item.get("identifier")
            or item.get("id")
        )
        if not pid:
            raise ValueError("Bhoonidhi response item has no product identifier")
        ptype = item.get("product_type") or item.get("productType") or infer_product_type(str(pid))
        item_bbox = item.get("bbox") or item.get("boundingBox")
        product = RemoteProduct(
            provider=self.name,
            product_id=str(pid),
            product_type=str(ptype).upper() if ptype else "UNKNOWN",
            acquisition_start=item.get("acquisition_start") or item.get("startTime"),
            acquisition_end=item.get("acquisition_end") or item.get("endTime"),
            bbox=item_bbox if isinstance(item_bbox, list) else None,
            geometry=item.get("geometry") if isinstance(item.get("geometry"), dict) else None,
            frequency_band=item.get("frequency_band") or "S",
            polarization=item.get("polarization"),
            source_url=item.get("source_url") or item.get("url"),
            download_url=item.get("download_url") or item.get("downloadUrl"),
            file_format=item.get("file_format") or item.get("format") or "h5",
            size_bytes=int(item["size_bytes"]) if str(item.get("size_bytes", "")).isdigit() else None,
            is_demo=False,
            license="ISRO Bhoonidhi terms (authorized access)",
            citation="ISRO Bhoonidhi data portal",
            attribution="NISAR S-band products via ISRO Bhoonidhi; consult Bhoonidhi for attribution.",
            extra={"raw_keys": sorted(item.keys())},
        )
        self._cache[product.product_id] = product
        return product

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        if not self.configured:
            raise CapabilityUnavailableError(
                "Bhoonidhi is not configured. Set BHOONIDHI_SEARCH_URL and BHOONIDHI_API_KEY."
            )
        params: dict[str, Any] = {"limit": min(query.max_results, 200)}
        if query.bbox:
            params["bbox"] = ",".join(str(v) for v in query.bbox)
        if query.start:
            params["start"] = query.start
        if query.end:
            params["end"] = query.end
        if query.product_types:
            params["product_type"] = ",".join(query.product_types)
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(self.search_url, params=params, headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise CapabilityUnavailableError(f"Bhoonidhi search failed: {exc}") from exc
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("results", "data", "products", "features"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        return [self._parse(i) for i in items[: query.max_results]]

    def get_metadata(self, product_id: str) -> RemoteProduct:
        if product_id in self._cache:
            return self._cache[product_id]
        for item in self.search(SearchQuery(max_results=200)):
            if item.product_id == product_id:
                return item
        raise NotFoundError(f"Bhoonidhi product '{product_id}' not found")

    def download(self, product_id: str, dest_dir: Path) -> Path:
        if not self.configured:
            raise CapabilityUnavailableError("Bhoonidhi is not configured for downloads")
        item = self.get_metadata(product_id)
        if not item.download_url:
            raise CapabilityUnavailableError(
                "Bhoonidhi response did not provide an authorized download URL"
            )
        dest_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(item.download_url).suffix or ".h5"
        target = dest_dir / f"{product_id}{suffix}"
        try:
            with httpx.stream(
                "GET", item.download_url, headers=self._headers(), timeout=180.0, follow_redirects=True
            ) as resp:
                resp.raise_for_status()
                with target.open("wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 1024):
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            raise CapabilityUnavailableError(f"Bhoonidhi download failed: {exc}") from exc
        return target

    def health_check(self) -> ConnectorHealth:
        if not self.configured:
            return ConnectorHealth(
                connector=self.name,
                status="unconfigured",
                mode="live",
                message="Authorized search endpoint/API key not configured",
                capabilities={"search": False, "download": False, "frequency_bands": ["S"]},
            )
        if self.settings.offline_mode:
            return ConnectorHealth(
                connector=self.name,
                status="unconfigured",
                mode="live",
                message="Offline evaluation mode - Bhoonidhi not probed",
                capabilities={"search": False, "download": False},
            )
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(self.search_url, headers=self._headers())
            elapsed = (time.perf_counter() - started) * 1000
            ok = resp.status_code < 500
            return ConnectorHealth(
                connector=self.name,
                status="ok" if ok else "degraded",
                mode="live",
                message=f"Bhoonidhi endpoint HTTP {resp.status_code}" if ok else f"HTTP {resp.status_code}",
                latency_ms=elapsed,
                capabilities={"search": ok, "download": ok, "frequency_bands": ["S"]},
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(
                connector=self.name,
                status="unavailable",
                mode="live",
                message=f"Bhoonidhi unavailable: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000,
                capabilities={"search": False, "download": False},
            )
