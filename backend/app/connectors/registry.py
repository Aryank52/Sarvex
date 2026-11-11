"""Connector registry and demo-fallback policy.

Fallback is explicit: callers receive both the connector used and a
``demo_fallback`` flag. The API surfaces this flag; the UI shows DEMO MODE.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.connectors.asf import NASAASFConnector
from app.connectors.base import ConnectorHealth, DataSource, RemoteProduct, SearchQuery
from app.connectors.bhoonidhi import BhoonidhiConnector
from app.connectors.demo import DemoFixtureConnector
from app.connectors.local import LocalFileConnector
from app.connectors.stac import STACConnector


class ConnectorRegistry:
    def __init__(self) -> None:
        self.demo = DemoFixtureConnector()
        self.asf = NASAASFConnector()
        self.bhoonidhi = BhoonidhiConnector()
        self.stac = STACConnector()
        self.local = LocalFileConnector()

    def get(self, name: str) -> DataSource:
        mapping = {
            "demo": self.demo,
            "asf": self.asf,
            "nasa_asf": self.asf,
            "bhoonidhi": self.bhoonidhi,
            "stac": self.stac,
            "local": self.local,
        }
        try:
            return mapping[name.lower()]
        except KeyError as exc:
            raise ValueError(f"Unknown connector '{name}'") from exc

    def all(self) -> list[DataSource]:
        return [self.asf, self.bhoonidhi, self.stac, self.local, self.demo]

    def health_all(self) -> list[ConnectorHealth]:
        return [connector.health_check() for connector in self.all()]

    def live_connectors(self) -> list[DataSource]:
        return [self.asf, self.bhoonidhi, self.stac]

    def search_with_fallback(
        self, connector_name: str, query: SearchQuery
    ) -> tuple[list[RemoteProduct], str, bool, str | None]:
        """Search one connector, optionally falling back to demo fixtures.

        Returns ``(products, source_connector, demo_fallback, warning)``.
        The warning is always populated when synthetic data is returned.
        """
        settings = get_settings()
        connector = self.get(connector_name)
        if settings.demo_mode == "on" and connector_name != "demo":
            products = self.demo.search(query)
            return products, "demo", True, _demo_warning("Demo mode is forced on")

        try:
            products = connector.search(query)
            if products:
                return products, connector.name, connector.mode == "demo", None
            if connector_name != "demo" and settings.demo_mode == "auto":
                demo_products = self.demo.search(query)
                if demo_products:
                    return (
                        demo_products,
                        "demo",
                        True,
                        _demo_warning("Live search returned no matching products"),
                    )
            return [], connector.name, connector.mode == "demo", None
        except Exception as exc:  # noqa: BLE001
            if settings.demo_mode == "auto" and connector_name != "demo":
                return (
                    self.demo.search(query),
                    "demo",
                    True,
                    _demo_warning(f"Live connector unavailable: {exc}"),
                )
            raise

    def availability_summary(self) -> dict[str, Any]:
        health = self.health_all()
        live_ok = any(h.status == "ok" and h.mode == "live" for h in health)
        return {
            "demo_fixtures_available": True,
            "live_data_available": live_ok,
            "effective_data_mode": "LIVE" if live_ok else "DEMO",
            "connectors": [h.as_dict() for h in health],
        }


def _demo_warning(reason: str) -> str:
    return (
        f"{reason}. Results are SARVEX synthetic fixtures, not NASA/ISRO NISAR observations."
    )


@lru_cache(maxsize=1)
def get_connector_registry() -> ConnectorRegistry:
    return ConnectorRegistry()


def reset_connector_registry() -> None:
    get_connector_registry.cache_clear()
