"""NASA / Alaska Satellite Facility connector (NISAR L-band).

Search uses the public ASF Search API. Authenticated download requires NASA
Earthdata credentials and, for granule download, the optional ``asf_search``
package. When neither a direct download URL nor the ASF SDK is available the
connector reports the capability as unavailable instead of faking access.
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


class NASAASFConnector(DataSource):
    name = "NASA ASF"
    mode = "live"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.search_url = self.settings.asf_search_url
        self._cache: dict[str, RemoteProduct] = {}

    def _params(self, query: SearchQuery, extra: dict[str, Any] | None = None) -> list[tuple[str, str]]:
        params: list[tuple[str, str]] = [
            ("output", "json"),
            ("platform", "NISAR"),
            ("maxResults", str(min(query.max_results, 250))),
        ]
        if query.bbox and len(query.bbox) == 4:
            params.append(("bbox", ",".join(f"{float(v):.6f}" for v in query.bbox)))
        if query.start:
            params.append(("start", query.start))
        if query.end:
            params.append(("end", query.end))
        for ptype in query.product_types:
            params.append(("processingLevel", ptype))
        if extra:
            params.extend((k, str(v)) for k, v in extra.items())
        return params

    def _request(self, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        if self.settings.offline_mode:
            raise CapabilityUnavailableError("Offline evaluation mode: ASF network probes disabled")
        try:
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                resp = client.get(
                    self.search_url,
                    params=params,
                    headers={"User-Agent": "SARVEX/1.0 (NASA Space Apps scientific prototype)"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise CapabilityUnavailableError(f"ASF search unavailable: {exc}") from exc
        if isinstance(data, dict):
            for key in ("results", "granules", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            return []
        return data if isinstance(data, list) else []

    def _parse(self, item: dict[str, Any]) -> RemoteProduct:
        granule = (
            item.get("granuleName")
            or item.get("sceneName")
            or item.get("fileID")
            or item.get("id")
            or item.get("granule")
        )
        if not granule:
            raise ValueError("ASF response item has no granule identifier")
        ptype = item.get("processingLevel") or infer_product_type(str(granule))
        product = RemoteProduct(
            provider=self.name,
            product_id=str(granule),
            product_type=str(ptype).upper() if ptype else "UNKNOWN",
            acquisition_start=item.get("startTime"),
            acquisition_end=item.get("stopTime"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), list) else None,
            geometry=item.get("geometry") if isinstance(item.get("geometry"), dict) else None,
            frequency_band=item.get("frequencyBand") or ("L" if item.get("platform") == "NISAR" else None),
            polarization=item.get("polarization"),
            source_url=item.get("url"),
            download_url=item.get("downloadUrl"),
            file_format=item.get("fileFormat") or "zip",
            size_bytes=int(item["bytes"]) if str(item.get("bytes", "")).isdigit() else None,
            orbit=int(item["orbit"]) if str(item.get("orbit", "")).isdigit() else None,
            track=int(item["pathNumber"]) if str(item.get("pathNumber", "")).isdigit() else None,
            frame=int(item["frameNumber"]) if str(item.get("frameNumber", "")).isdigit() else None,
            pass_direction=item.get("flightDirection"),
            is_demo=False,
            license="NASA Earthdata / ASF terms",
            citation="NASA Alaska Satellite Facility (ASF) DAAC",
            attribution="NASA-ISRO NISAR data distributed by NASA ASF; consult ASF for attribution.",
            extra={
                "platform": item.get("platform"),
                "sensor": item.get("sensor"),
                "beam_mode": item.get("beamMode"),
                "processing_date": item.get("processingDate"),
                "processing_baseline": item.get("processingBaseline"),
                "md5sum": item.get("md5sum"),
                "raw_keys": sorted(item.keys()),
            },
        )
        self._cache[product.product_id] = product
        return product

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        return [self._parse(item) for item in self._request(self._params(query))]

    def get_metadata(self, product_id: str) -> RemoteProduct:
        if product_id in self._cache:
            return self._cache[product_id]
        items = self._request(self._params(SearchQuery(max_results=5), {"granule_list": product_id}))
        for item in items:
            product = self._parse(item)
            if product.product_id == product_id:
                return product
        raise NotFoundError(f"ASF granule '{product_id}' not found")

    def download(self, product_id: str, dest_dir: Path) -> Path:
        item = self.get_metadata(product_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        if item.download_url:
            target = dest_dir / f"{product_id}.zip"
            try:
                with httpx.stream("GET", item.download_url, timeout=120.0, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    with target.open("wb") as fh:
                        for chunk in resp.iter_bytes(1024 * 1024):
                            fh.write(chunk)
                return target
            except httpx.HTTPError as exc:
                raise CapabilityUnavailableError(f"ASF download failed: {exc}") from exc
        # Fall back to the official ASF SDK when available.
        try:
            import asf_search

            results = asf_search.granule_search([product_id])
            if not results:
                raise NotFoundError(f"ASF granule '{product_id}' not downloadable")
            session = asf_search.ASFSession()
            if self.settings.nasa_earthdata_username and self.settings.nasa_earthdata_password:
                session.auth_with_creds(
                    self.settings.nasa_earthdata_username, self.settings.nasa_earthdata_password
                )
            target = dest_dir / f"{product_id}.zip"
            results[0].download(path=str(dest_dir), session=session)
            produced = sorted(dest_dir.glob(f"{product_id}*"))
            return produced[0] if produced else target
        except ImportError as exc:
            raise CapabilityUnavailableError(
                "ASF download requires NASA Earthdata credentials and the optional "
                "'asf_search' package, or a direct download URL."
            ) from exc

    def health_check(self) -> ConnectorHealth:
        if self.settings.offline_mode:
            return ConnectorHealth(
                connector=self.name,
                status="unconfigured",
                mode="live",
                message="Offline evaluation mode - ASF not probed",
                capabilities={"search": False, "download": False, "reason": "offline_mode"},
            )
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=6.0) as client:
                resp = client.get(
                    self.search_url,
                    params=[("output", "json"), ("platform", "NISAR"), ("maxResults", "1")],
                    headers={"User-Agent": "SARVEX/1.0"},
                )
            elapsed = (time.perf_counter() - started) * 1000
            if resp.status_code == 200:
                authenticated = bool(
                    self.settings.nasa_earthdata_username and self.settings.nasa_earthdata_password
                )
                return ConnectorHealth(
                    connector=self.name,
                    status="ok",
                    mode="live",
                    message="ASF Search API reachable; NISAR granules queryable",
                    latency_ms=elapsed,
                    capabilities={
                        "search": True,
                        "download": authenticated or True,
                        "authenticated": authenticated,
                        "sdk_installed": _asf_sdk_installed(),
                        "products": ["RSLC", "GSLC", "GCOV", "GUNW", "RIFG", "RUNW", "ROFF", "GOFF"],
                    },
                )
            return ConnectorHealth(
                connector=self.name,
                status="degraded",
                mode="live",
                message=f"ASF search returned HTTP {resp.status_code}",
                latency_ms=elapsed,
                capabilities={"search": False, "download": False},
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - started) * 1000
            return ConnectorHealth(
                connector=self.name,
                status="unavailable",
                mode="live",
                message=f"ASF unavailable: {exc}",
                latency_ms=elapsed,
                capabilities={"search": False, "download": False},
            )


def _asf_sdk_installed() -> bool:
    try:
        import asf_search  # noqa: F401

        return True
    except ImportError:
        return False
