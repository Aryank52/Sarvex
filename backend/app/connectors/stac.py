"""Generic STAC catalog connector.

Supports future NASA Earthdata STAC, optical, DEM and contextual catalogs.
Collections are operator-configurable via extra search parameters.
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


class STACConnector(DataSource):
    name = "STAC"
    mode = "live"

    def __init__(self, urls: list[str] | None = None) -> None:
        self.settings = get_settings()
        self.urls = urls or self.settings.stac_url_list
        self._cache: dict[str, RemoteProduct] = {}

    def _endpoint(self, url: str) -> str:
        return url.rstrip("/") + ("" if url.rstrip("/").endswith("/search") else "/search")

    def _parse(self, item: dict[str, Any], catalog_url: str) -> RemoteProduct:
        properties = item.get("properties") or {}
        assets = item.get("assets") or {}
        pid = str(item.get("id") or item.get("collection") or "unknown")
        ptype = (
            properties.get("product_type")
            or properties.get("processingLevel")
            or infer_product_type(pid)
        )
        download_url = None
        file_format = None
        for asset in assets.values():
            href = asset.get("href")
            if not href:
                continue
            media = str(asset.get("type") or "")
            if any(token in media for token in ("geotiff", "hdf5", "octet-stream")):
                download_url = href
                file_format = "GTiff" if "geotiff" in media else "h5"
                break
        if download_url is None and assets:
            first = next(iter(assets.values()))
            download_url = first.get("href")
            file_format = "unknown"
        product = RemoteProduct(
            provider=properties.get("provider") or item.get("collection") or self.name,
            product_id=pid,
            product_type=str(ptype).upper() if ptype else "UNKNOWN",
            acquisition_start=properties.get("datetime") or properties.get("start_datetime"),
            acquisition_end=properties.get("end_datetime"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), list) else None,
            geometry=item.get("geometry") if isinstance(item.get("geometry"), dict) else None,
            frequency_band=properties.get("frequency_band"),
            polarization=properties.get("polarization"),
            source_url=item.get("links", [{}])[0].get("href") if item.get("links") else catalog_url,
            download_url=download_url,
            file_format=file_format,
            size_bytes=next(
                (
                    int(a["file:size"])
                    for a in assets.values()
                    if str(a.get("file:size", "")).isdigit()
                ),
                None,
            ),
            is_demo=False,
            license=item.get("license") or properties.get("license"),
            citation=properties.get("citation") or f"STAC catalog {catalog_url}",
            attribution=properties.get("attribution") or "STAC provider; consult item metadata.",
            extra={"collection": item.get("collection"), "catalog": catalog_url},
        )
        self._cache[product.product_id] = product
        return product

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        if not self.urls:
            raise CapabilityUnavailableError("No STAC search URLs configured")
        if self.settings.offline_mode:
            raise CapabilityUnavailableError("Offline evaluation mode: STAC network probes disabled")
        results: list[RemoteProduct] = []
        payload: dict[str, Any] = {"limit": min(query.max_results, 200)}
        if query.bbox:
            payload["bbox"] = query.bbox
        if query.start or query.end:
            payload["datetime"] = f"{query.start or '..'}/{query.end or '..'}"
        if query.extra.get("collections"):
            payload["collections"] = query.extra["collections"]
        for url in self.urls:
            try:
                with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                    resp = client.post(self._endpoint(url), json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                for feature in data.get("features", [])[: query.max_results]:
                    results.append(self._parse(feature, url))
            except Exception as exc:  # noqa: BLE001
                raise CapabilityUnavailableError(f"STAC search failed at {url}: {exc}") from exc
        return results[: query.max_results]

    def get_metadata(self, product_id: str) -> RemoteProduct:
        if product_id in self._cache:
            return self._cache[product_id]
        for item in self.search(SearchQuery(max_results=100)):
            if item.product_id == product_id:
                return item
        raise NotFoundError(f"STAC item '{product_id}' not found")

    def download(self, product_id: str, dest_dir: Path) -> Path:
        item = self.get_metadata(product_id)
        if not item.download_url:
            raise CapabilityUnavailableError("STAC item has no downloadable asset")
        dest_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(item.download_url.split("?")[0]).suffix or ".bin"
        target = dest_dir / f"{item.product_id}{suffix}"
        try:
            with httpx.stream("GET", item.download_url, timeout=180.0, follow_redirects=True) as resp:
                resp.raise_for_status()
                with target.open("wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 1024):
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            raise CapabilityUnavailableError(f"STAC asset download failed: {exc}") from exc
        return target

    def health_check(self) -> ConnectorHealth:
        if not self.urls:
            return ConnectorHealth(
                connector=self.name,
                status="unconfigured",
                mode="live",
                message="No STAC endpoints configured",
                capabilities={"search": False},
            )
        if self.settings.offline_mode:
            return ConnectorHealth(
                connector=self.name,
                status="unconfigured",
                mode="live",
                message="Offline evaluation mode - STAC not probed",
                capabilities={"search": False, "endpoints": self.urls},
            )
        started = time.perf_counter()
        ok_urls = 0
        for url in self.urls:
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(url)
                if resp.status_code < 500:
                    ok_urls += 1
            except Exception:  # noqa: BLE001
                pass
        elapsed = (time.perf_counter() - started) * 1000
        return ConnectorHealth(
            connector=self.name,
            status="ok" if ok_urls == len(self.urls) else ("degraded" if ok_urls else "unavailable"),
            mode="live",
            message=f"{ok_urls}/{len(self.urls)} STAC endpoints reachable",
            latency_ms=elapsed,
            capabilities={"search": ok_urls > 0, "endpoints": self.urls},
        )
