"""Geospatial context and exposure engine.

Context layers must declare provider, license, source, version, CRS and date.
They are correlated with events; SAR measurements are never modified by context.
Exposure means *potential spatial proximity*, never damage.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.geometry import geojson_distance_m, geojson_intersects, overlap_ratio
from app.db.models import (
    ChangeEvent,
    EventContextLink,
    EventExposure,
    GeospatialContext,
    InfrastructureAsset,
)


def seed_demo_context(session: Session) -> tuple[int, int]:
    """Seed clearly-labelled synthetic context and assets for the demo AOI."""
    existing = session.scalar(
        select(GeospatialContext.id).where(GeospatialContext.is_demo.is_(True)).limit(1)
    )
    if existing:
        return (0, 0)
    contexts = [
        {
            "layer_type": "river",
            "name": "DEMO braided river corridor",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.62, 26.10], [91.89, 26.10], [91.89, 26.22], [91.62, 26.22], [91.62, 26.10]]],
            },
        },
        {
            "layer_type": "settlement",
            "name": "DEMO settlement cluster A",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.70, 26.23], [91.78, 26.23], [91.78, 26.29], [91.70, 26.29], [91.70, 26.23]]],
            },
        },
        {
            "layer_type": "agriculture",
            "name": "DEMO agricultural belt",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.82, 26.24], [91.94, 26.24], [91.94, 26.31], [91.82, 26.31], [91.82, 26.24]]],
            },
        },
        {
            "layer_type": "wetland",
            "name": "DEMO wetland margin",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.60, 26.20], [91.68, 26.20], [91.68, 26.26], [91.60, 26.26], [91.60, 26.20]]],
            },
        },
    ]
    for ctx in contexts:
        session.add(
            GeospatialContext(
                layer_type=ctx["layer_type"],
                name=ctx["name"],
                geometry=ctx["geometry"],
                provider="SARVEX demo fixtures",
                license="SARVEX synthetic fixture - not authoritative GIS data",
                source="Generated for offline demonstration; geometry is synthetic.",
                version="DEMO-1.0",
                crs="EPSG:4326",
                layer_date=datetime.now(timezone.utc),
                properties={"demo": True, "authoritative": False},
                is_demo=True,
            )
        )
    assets = [
        {
            "asset_type": "bridge",
            "name": "DEMO river crossing",
            "geometry": {"type": "Point", "coordinates": [91.742, 26.158]},
        },
        {
            "asset_type": "road",
            "name": "DEMO transport corridor",
            "geometry": {
                "type": "LineString",
                "coordinates": [[91.58, 26.12], [91.72, 26.18], [91.90, 26.18], [91.98, 26.24]],
            },
        },
        {
            "asset_type": "settlement",
            "name": "DEMO settlement footprint B",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[91.66, 26.24], [91.70, 26.24], [91.70, 26.28], [91.66, 26.28], [91.66, 26.24]]],
            },
        },
    ]
    for asset in assets:
        session.add(
            InfrastructureAsset(
                asset_type=asset["asset_type"],
                name=asset["name"],
                geometry=asset["geometry"],
                provider="SARVEX demo fixtures",
                license="SARVEX synthetic fixture - not authoritative infrastructure data",
                source="Generated for offline demonstration; geometry is synthetic.",
                properties={"demo": True, "authoritative": False},
                is_demo=True,
            )
        )
    session.commit()
    return (len(contexts), len(assets))


def correlate_event_context(session: Session, event: ChangeEvent, near_m: float = 3000.0) -> list[str]:
    """Link intersecting or nearby context layers to an event."""
    if not event.geometry:
        return []
    context_ids: list[str] = []
    existing = {link.context_id for link in event.context_links}
    for ctx in session.scalars(select(GeospatialContext)).all():
        if not ctx.geometry or ctx.id in existing:
            continue
        try:
            relation = None
            if geojson_intersects(event.geometry, ctx.geometry):
                relation = "intersects"
            elif geojson_distance_m(event.geometry, ctx.geometry) <= near_m:
                relation = "nearby"
            if relation:
                session.add(EventContextLink(event_id=event.id, context_id=ctx.id, relation=relation))
                context_ids.append(ctx.id)
        except Exception:  # noqa: BLE001 - one bad geometry must not break event creation
            continue
    return context_ids


def compute_exposures(
    session: Session,
    event: ChangeEvent,
    *,
    max_distance_m: float = 10_000.0,
) -> list[EventExposure]:
    if not event.geometry:
        return []
    existing = {e.asset_id for e in event.exposures}
    exposures: list[EventExposure] = []
    for asset in session.scalars(select(InfrastructureAsset)).all():
        if asset.id in existing:
            continue
        try:
            distance = geojson_distance_m(event.geometry, asset.geometry)
        except Exception:  # noqa: BLE001
            continue
        if distance > max_distance_m:
            continue
        overlap = overlap_ratio(event.geometry, asset.geometry)
        proximity = max(0.0, 1.0 - distance / max_distance_m)
        score = float(
            (event.confidence if event.confidence is not None else 0.5)
            * (event.severity if event.severity is not None else 0.5)
            * (0.6 * overlap + 0.4 * proximity)
        )
        rationale = (
            f"Asset lies {distance:.0f} m from the detected change region "
            f"({'overlapping' if overlap > 0 else 'no overlap'}, overlap ratio {overlap:.2f}). "
            "Exposure is potential proximity, not observed damage."
        )
        exposure = EventExposure(
            event_id=event.id,
            asset_id=asset.id,
            distance_m=distance,
            overlap_ratio=overlap,
            exposure_score=score,
            rationale=rationale,
        )
        session.add(exposure)
        exposures.append(exposure)
    return exposures


def context_metadata_for_event(session: Session, event: ChangeEvent) -> dict[str, Any]:
    layers = []
    for link in event.context_links:
        ctx = session.get(GeospatialContext, link.context_id)
        if ctx:
            layers.append(
                {
                    "id": ctx.id,
                    "name": ctx.name,
                    "layer_type": ctx.layer_type,
                    "relation": link.relation,
                    "provider": ctx.provider,
                    "license": ctx.license,
                    "is_demo": ctx.is_demo,
                }
            )
    return {"layers": layers, "n_layers": len(layers)}
